"""The generic query core, exercised against EVERY declared entity directly — with no router.

GENERALISED ON PURPOSE. This suite names no entity and no column. It asks the registry what this
module declares and, per entity, discovers the columns it needs from that entity's own create
schema — so a module with eight entities gets eight verdicts from one file, and adding an entity
needs no edit here. That is what separates a framework test from a module-tailored one: a suite
naming `items`, `name` and `description` could only be force-synced into modules that happen to
have all three.

In-process layer (`TESTS/README.md`): a real SQLAlchemy session against the deployed database, the
restricted `<SLUG>_APP_DB_USER` role, real Row-Level Security, real migrations. Only the HTTP layer
is absent. This file is ADDITIVE — mechanics an API test cannot observe (the SQL actually emitted,
the eager-load plan honoured, a keyset seek past a page) — and is not a substitute for the
API-level tests in `test_items.py`.

A test here owns the rows it creates and deletes them, namespaced per test
(`rules/testing-guidelines.md` § "A test owns the data it needs"): `tenant_scope_factory` hands out
a fresh random tenant id per call, so two runs never collide and a leftover row can never be
mistaken for another tenant's real data.

WHY A LOOP AND NOT PARAMETRISATION. The entity set is known only once `app_module` has imported the
app, which happens at fixture time — after pytest has finished collecting. So each test loops and
names the entity in its assertion messages instead; a failure says which entity broke the contract
rather than that "the query core" did.
"""
from typing import NamedTuple

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import load_only


class EntityUnderTest(NamedTuple):
    """One entity, plus the two columns this suite needs to drive it.

    `marker` is written with a unique value and then filtered and sorted on. `deferrable` is a
    second settable column, used only where a test needs a column that must NOT be touched or must
    NOT be fetched — a partial update leaving it alone, an eager-load plan excluding it. It is
    `None` for an entity with a single settable text column, and those tests then skip that entity
    rather than assert against nothing.
    """
    key: str
    descriptor: object
    marker: str
    deferrable: str | None


def _settable_text_columns(descriptor) -> list[str]:
    """Settable text columns, in declaration order, read off the CREATE schema.

    The create schema rather than the model, because a column that cannot be set at creation is no
    use to a test that needs to write a known value into it — and read-only, generated and
    server-default columns drop out for free rather than having to be excluded by name.
    """
    return [name for name, field in descriptor.create_schema.model_fields.items()
            if field.annotation is str]


@pytest.fixture
def entities_under_test(app_module) -> list[EntityUnderTest]:
    """Every declared entity this suite can drive, as `EntityUnderTest` records.

    An empty result is a FAILURE, not a skip: a module whose entities are all undrivable here means
    the generic query core is going unmeasured, which is the state this suite exists to prevent.
    The message names what was seen, so the gap is actionable rather than mysterious.
    """
    usable, undrivable = [], []
    for key, descriptor in app_module.entities.all_entity_descriptors().items():
        columns = _settable_text_columns(descriptor)
        if columns:
            usable.append(EntityUnderTest(
                key=key, descriptor=descriptor, marker=columns[0],
                deferrable=columns[1] if len(columns) > 1 else None,
            ))
        else:
            undrivable.append(key)
    assert usable, (
        "no declared entity exposes a settable text column, so the generic query core cannot be "
        f"exercised here. Entities seen: {sorted(undrivable)}. Give one a text field, or cover the "
        "query core another way — but do not leave it unmeasured."
    )
    return usable


def _resolve_dependency_id(app_module, db_session, model, field_name: str, scope, dependencies) -> int | None:
    """If `field_name` is a foreign key to another DECLARED entity's table, create one row of it
    in `scope` and return its id — generalised the same way `entities_under_test` is: read off
    the model's own `ForeignKey`, never a named entity. `None` for a plain column.

    THE DEPENDENCY'S OWN REQUIRED FIELDS ARE SATISFIED THE SAME WAY, recursively, because the
    sample datamodel is a chain rather than a pair: `sub_item_notes` points at `sub_items`, which
    points at `template_items`. Filling only the one text marker built a `sub_items` payload with no
    `item_fk`, which the schema refuses — so the builder has to walk as deep as the chain goes, not
    one level.

    Every row created here (this one and, recursively, anything it in turn depended on) is appended
    to `dependencies` as `(descriptor, id)`, deepest-created first — `rules/testing-guidelines.md`
    § "A test owns the data it needs": a dependency row is still a row this test caused to exist,
    and must not outlive the test, `tenant_scope_factory`'s randomised tenant notwithstanding.
    """
    column = sa.inspect(model).columns.get(field_name)
    if column is None or not column.foreign_keys:
        return None
    target_table = next(iter(column.foreign_keys)).column.table.name
    for descriptor in app_module.entities.all_entity_descriptors().values():
        if descriptor.model.__tablename__ != target_table:
            continue
        dep_columns = _settable_text_columns(descriptor)
        dep_fields = {dep_columns[0]: f'mech-dep-{field_name}'} if dep_columns else {}
        for dep_name, dep_field in descriptor.create_schema.model_fields.items():
            if dep_name in dep_fields or dep_name == 'tenant_id' or not dep_field.is_required():
                continue
            resolved = _resolve_dependency_id(
                app_module, db_session, descriptor.model, dep_name, scope, dependencies)
            if resolved is not None:
                dep_fields[dep_name] = resolved
        dep_payload = descriptor.create_schema(**dep_fields)
        dep_row = app_module.entities.create_entity_row(db_session, descriptor, dep_payload, scope)
        dependencies.append((descriptor, dep_row.id))
        return dep_row.id
    return None


def _create(app_module, db_session, entity: EntityUnderTest, scope, dependencies, **fields):
    """Build and create `entity`'s row, filling in any OTHER required field generically.

    A create schema may require more than the one text marker this suite drives — `sub_item`'s
    `item_fk` is the worked example. Rather than special-case it by name, every required field the
    caller did not supply is checked against the MODEL's own foreign keys, and a dependency row is
    created to satisfy it. `dependencies` is the caller's list (typically started as `[]` right
    before this call) that every such row is appended to, so the caller can delete them alongside
    the entity under test — see `_delete_dependencies`.
    """
    payload_fields = dict(fields)
    for name, field in entity.descriptor.create_schema.model_fields.items():
        if name in payload_fields or name == 'tenant_id' or not field.is_required():
            continue
        dependency_id = _resolve_dependency_id(
            app_module, db_session, entity.descriptor.model, name, scope, dependencies)
        if dependency_id is not None:
            payload_fields[name] = dependency_id
    payload = entity.descriptor.create_schema(**payload_fields)
    return app_module.entities.create_entity_row(db_session, entity.descriptor, payload, scope)


def _delete_row(app_module, db_session, descriptor, scope, row_id):
    """Delete one row by descriptor, owned by `scope`, re-fetching it immediately before.

    Takes a bare id, never an ORM row object, and that is the point. `SessionLocal` commits with
    the default `expire_on_commit=True`, so ANY intervening commit — the create itself, a
    `list_entity` call, another delete in the same loop — expires every tracked object's
    attributes, including its `id`. Touching `row.id` on such an object forces SQLAlchemy to reload
    it, in whatever transaction happens to be open; `crud.delete_entity` does not publish the
    tenant GUC itself (it is the caller's job, exactly as a router's `for_write=True` load does in
    the same request), so that reload can land in a transaction with no GUC published — or the
    wrong tenant's, if the last read was a deliberate cross-tenant check — and Row-Level Security
    then makes a perfectly real row look deleted. Re-fetching with `for_write=True` (which
    republishes the GUC) right before the delete avoids both failure modes: nothing here ever reads
    an attribute off a possibly-expired instance.
    """
    fresh = app_module.entities.get_entity_row(db_session, descriptor, row_id, scope, for_write=True)
    if fresh is not None:
        app_module.entities.delete_entity_row(db_session, descriptor, fresh)


def _delete_all(app_module, db_session, entity: EntityUnderTest, scope, row_ids):
    """Delete every id in `row_ids`, owned by `scope`. See `_delete_row` for the re-fetch-before-
    delete reasoning."""
    for row_id in row_ids:
        _delete_row(app_module, db_session, entity.descriptor, scope, row_id)


def _delete_dependencies(app_module, db_session, scope, dependencies):
    """Delete every row `_resolve_dependency_id` created, in the REVERSE of creation order.

    `dependencies` is deepest-created-first (a `sub_items` dependency's own `template_items`
    dependency is created, and appended, before the `sub_items` row that references it) — deleting
    in reverse deletes each row before the row it depends on, so a foreign key never blocks it.
    """
    for descriptor, row_id in reversed(dependencies):
        _delete_row(app_module, db_session, descriptor, scope, row_id)


def _in_a_fresh_session(app_module, work):
    """Run `work(session)` on a new session and close it, whatever happens.

    SQLAlchemy's identity map can hand back a previously-fully-loaded object for the same primary
    key regardless of the new query's loader options, which would make the eager-load tests below
    pass for the wrong reason.
    """
    session = app_module.database.SessionLocal()
    try:
        return work(session)
    finally:
        session.close()


class TestGenericListQuery:
    """`list_entity` driven through the descriptor — the whitelist, the page ceiling, the cursor,
    tenant scoping and keyset paging. Sub-set 1's row "Generic list query: whitelisted filter/sort,
    offset + keyset, MAX_PAGE_SIZE, estimated count"."""

    def test_an_unwhitelisted_filter_field_is_rejected(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            with pytest.raises(ValueError, match='Invalid filter field'):
                app_module.entities.list_entity(
                    db_session, entity.descriptor, scope, filters={'no_such_field': 'x'})

    def test_an_unwhitelisted_sort_field_is_rejected(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            with pytest.raises(ValueError, match='Invalid sort_by'):
                app_module.entities.list_entity(
                    db_session, entity.descriptor, scope,
                    sort_by='no_such_field', sort_order='asc')

    def test_a_page_larger_than_max_page_size_is_rejected(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            too_big = app_module.crud.MAX_PAGE_SIZE + 1
            with pytest.raises(ValueError, match='must not exceed'):
                app_module.entities.list_entity(
                    db_session, entity.descriptor, scope, limit=too_big)

    def test_a_cursor_combined_with_a_non_id_sort_is_rejected(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        """A cursor is only meaningful against a stable, unique ordering — the framework contract
        in `backend/SPECS/ideable-framework-specs/base-specs.md` § *List endpoints*."""
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            with pytest.raises(ValueError, match='after_id requires ordering by id'):
                app_module.entities.list_entity(
                    db_session, entity.descriptor, scope,
                    sort_by=entity.marker, sort_order='asc', after_id=0,
                )

    def test_tenant_scoping_is_applied_before_any_filter(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            mine = tenant_scope_factory()
            other = tenant_scope_factory()
            marker = f"mech-{mine.tenant_ids}"
            deps: list = []
            created_id = _create(
                app_module, db_session, entity, mine, deps, **{entity.marker: marker}).id
            try:
                rows, total, _ = app_module.entities.list_entity(
                    db_session, entity.descriptor, mine, filters={entity.marker: marker})
                assert total == 1, f"{entity.key}: the owning tenant cannot see its own row"
                assert getattr(rows[0], entity.marker) == marker, (
                    f"{entity.key}: the filter returned the wrong row"
                )

                other_rows, other_total, _ = app_module.entities.list_entity(
                    db_session, entity.descriptor, other, filters={entity.marker: marker})
                assert other_total == 0 and other_rows == [], (
                    f"{entity.key}: another tenant can see this row — tenant scoping is not applied "
                    f"before the filter"
                )
            finally:
                _delete_all(app_module, db_session, entity, mine, [created_id])
                _delete_dependencies(app_module, db_session, mine, deps)

    def test_keyset_pagination_seeks_forward_with_no_gaps_or_repeats(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            marker = f"mech-keyset-{scope.tenant_ids}"
            deps: list = []
            created_ids = [
                _create(app_module, db_session, entity, scope, deps, **{entity.marker: marker}).id
                for _ in range(5)
            ]
            try:
                first_page, total, exact = app_module.entities.list_entity(
                    db_session, entity.descriptor, scope, filters={entity.marker: marker},
                    sort_by='id', sort_order='asc', limit=2,
                )
                assert total == 5 and exact is True, (
                    f"{entity.key}: five rows were created, the count says {total}"
                )
                assert [r.id for r in first_page] == sorted(created_ids)[:2], (
                    f"{entity.key}: the first page is not the lowest two ids, ascending"
                )

                second_page, _, _ = app_module.entities.list_entity(
                    db_session, entity.descriptor, scope, filters={entity.marker: marker},
                    sort_by='id', sort_order='asc', limit=2, after_id=first_page[-1].id,
                )
                first_ids = {r.id for r in first_page}
                second_ids = {r.id for r in second_page}
                assert not (first_ids & second_ids), (
                    f"{entity.key}: the cursor repeated a row the first page already returned"
                )
                assert second_ids, (
                    f"{entity.key}: the cursor returned nothing, so it skipped past real rows"
                )
            finally:
                _delete_all(app_module, db_session, entity, scope, created_ids)
                _delete_dependencies(app_module, db_session, scope, deps)

    def test_include_total_false_skips_the_count(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            rows, total, exact = app_module.entities.list_entity(
                db_session, entity.descriptor, scope, include_total=False)
            assert rows == [] and total == 0 and exact is True, (
                f"{entity.key}: a brand-new tenant sees rows, or a skipped count reported one"
            )


class TestGenericGetCreateUpdateDelete:
    """Sub-set 1's row "Generic get/create/update/delete with tenant scope and actor-before-commit"
    — the actor half is the app-level `_audit_actor_dependency` in `main.py`, which this layer does
    not exercise (there is no request); what belongs here is the tenant-scope half."""

    def test_create_then_get_round_trips_within_the_same_tenant(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            deps: list = []
            row_id = _create(
                app_module, db_session, entity, scope, deps, **{entity.marker: 'mech-roundtrip'}).id
            try:
                got = app_module.entities.get_entity_row(
                    db_session, entity.descriptor, row_id, scope)
                assert got is not None, f"{entity.key}: a row just created cannot be read back"
                assert got.id == row_id
                assert got.tenant_id == next(iter(scope.tenant_ids)), (
                    f"{entity.key}: the row was written under the wrong tenant"
                )
            finally:
                _delete_all(app_module, db_session, entity, scope, [row_id])
                _delete_dependencies(app_module, db_session, scope, deps)

    def test_get_returns_none_for_another_tenants_row(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            owner = tenant_scope_factory()
            stranger = tenant_scope_factory()
            deps: list = []
            row_id = _create(
                app_module, db_session, entity, owner, deps, **{entity.marker: 'mech-isolated'}).id
            try:
                assert app_module.entities.get_entity_row(
                    db_session, entity.descriptor, row_id, stranger) is None, (
                    f"{entity.key}: another tenant can read this row by id"
                )
            finally:
                # `owner`, not `stranger`: the read above left the session's published tenant GUC
                # set to the STRANGER's tenant, and cleanup must delete as the row's actual owner —
                # `_delete_all` re-fetches `for_write=True` under `owner` before deleting, which is
                # what re-publishes the right GUC in the transaction that does the deleting.
                _delete_all(app_module, db_session, entity, owner, [row_id])
                _delete_dependencies(app_module, db_session, owner, deps)

    def test_update_changes_only_the_fields_sent(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        """A partial update must leave every column it did not name alone.

        Needs a second settable column to watch: asserting "only the field sent changed" against an
        entity with one field is a test that cannot fail, so such entities are passed over and the
        whole test skips if none qualifies.
        """
        exercised = 0
        for entity in entities_under_test:
            if entity.deferrable is None:
                continue
            exercised += 1
            scope = tenant_scope_factory()
            deps: list = []
            row = _create(app_module, db_session, entity, scope, deps,
                          **{entity.marker: 'mech-before', entity.deferrable: 'keep-me'})
            row_id = row.id
            try:
                updated = app_module.entities.update_entity_row(
                    db_session, entity.descriptor, row,
                    entity.descriptor.update_schema(**{entity.marker: 'mech-after'}), scope,
                )
                assert getattr(updated, entity.marker) == 'mech-after', (
                    f"{entity.key}: the field that was sent did not change"
                )
                assert getattr(updated, entity.deferrable) == 'keep-me', (
                    f"{entity.key}: a partial update overwrote {entity.deferrable!r}, which it was "
                    f"not asked to change"
                )
            finally:
                _delete_all(app_module, db_session, entity, scope, [row_id])
                _delete_dependencies(app_module, db_session, scope, deps)
        if not exercised:
            pytest.skip("no declared entity has two settable text columns to compare")

    def test_delete_removes_the_row(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        for entity in entities_under_test:
            scope = tenant_scope_factory()
            deps: list = []
            row = _create(app_module, db_session, entity, scope, deps,
                          **{entity.marker: 'mech-delete'})
            row_id = row.id
            try:
                app_module.entities.delete_entity_row(db_session, entity.descriptor, row)
                assert app_module.entities.get_entity_row(
                    db_session, entity.descriptor, row_id, scope) is None, (
                    f"{entity.key}: the row is still readable after being deleted"
                )
            finally:
                _delete_dependencies(app_module, db_session, scope, deps)


class TestEagerLoadPlanIsEnforcedOnRead:
    """Sub-set 1's row "Eager-load plan declared per descriptor and enforced on read".

    What this proves is that a descriptor's `eager_load` tuple genuinely reaches the compiled
    query, using `load_only` as a plan any model can carry whether or not it has relationships. The
    N+1 guard lives in `test_parametric_path_performance.py`, which fails any entity exposing a
    relationship in its read schema with no eager-load plan covering it.

    Needs a second settable column — the one that must NOT be fetched — so an entity with only one
    is passed over rather than asserted against nothing.
    """

    def _narrowed(self, app_module, entity: EntityUnderTest):
        """The same entity with a plan that loads the id and the marker, and nothing else."""
        d = entity.descriptor
        return app_module.entities.EntityDescriptor(
            key='eager_probe', model=d.model, create_schema=d.create_schema,
            update_schema=d.update_schema, read_schema=d.read_schema,
            page_schema=d.page_schema, permission_resource=d.permission_resource,
            eager_load=(load_only(d.model.id, getattr(d.model, entity.marker)),),
        )

    def _cleanup(self, app_module, entity: EntityUnderTest, row_id, scope, dependencies=()):
        def work(session):
            leftover = app_module.entities.get_entity_row(
                session, entity.descriptor, row_id, scope)
            if leftover is not None:
                app_module.entities.delete_entity_row(session, entity.descriptor, leftover)
            _delete_dependencies(app_module, session, scope, list(dependencies))
        _in_a_fresh_session(app_module, work)

    def test_get_entity_row_applies_the_descriptors_loader_options(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        exercised = 0
        for entity in entities_under_test:
            if entity.deferrable is None:
                continue
            exercised += 1
            scope = tenant_scope_factory()
            deps: list = []
            row_id = _create(app_module, db_session, entity, scope, deps, **{
                entity.marker: 'mech-eager', entity.deferrable: 'deferred-me'}).id
            db_session.close()
            try:
                narrowed = self._narrowed(app_module, entity)
                got = _in_a_fresh_session(app_module, lambda s: (
                    app_module.entities.get_entity_row(s, narrowed, row_id, scope).__dict__.copy()
                ))
                assert entity.marker in got, (
                    f"{entity.key}: load_only(id, {entity.marker}) did not load it eagerly"
                )
                assert entity.deferrable not in got, (
                    f"{entity.key}: eager_load was not applied to the compiled query — "
                    f"{entity.deferrable} should have been deferred, not fetched"
                )

                plain = _in_a_fresh_session(app_module, lambda s: (
                    app_module.entities.get_entity_row(
                        s, entity.descriptor, row_id, scope).__dict__.copy()
                ))
                assert entity.deferrable in plain, (
                    f"{entity.key}: the default (empty) eager_load plan should fetch every column"
                )
            finally:
                self._cleanup(app_module, entity, row_id, scope, deps)
        if not exercised:
            pytest.skip("no declared entity has a second settable column to defer")

    def test_list_entity_applies_the_descriptors_loader_options(
        self, app_module, db_session, entities_under_test, tenant_scope_factory,
    ):
        exercised = 0
        for entity in entities_under_test:
            if entity.deferrable is None:
                continue
            exercised += 1
            scope = tenant_scope_factory()
            marker = f"mech-eager-list-{scope.tenant_ids}"
            deps: list = []
            row_id = _create(app_module, db_session, entity, scope, deps, **{
                entity.marker: marker, entity.deferrable: 'deferred-me'}).id
            db_session.close()
            try:
                narrowed = self._narrowed(app_module, entity)
                listed = _in_a_fresh_session(app_module, lambda s: [
                    row.__dict__.copy() for row in app_module.entities.list_entity(
                        s, narrowed, scope, filters={entity.marker: marker})[0]
                ])
                assert len(listed) == 1, f"{entity.key}: the marked row was not listed"
                assert entity.deferrable not in listed[0], (
                    f"{entity.key}: eager_load was not applied to the list query — "
                    f"{entity.deferrable} should have been deferred"
                )
            finally:
                self._cleanup(app_module, entity, row_id, scope, deps)
        if not exercised:
            pytest.skip("no declared entity has a second settable column to defer")
