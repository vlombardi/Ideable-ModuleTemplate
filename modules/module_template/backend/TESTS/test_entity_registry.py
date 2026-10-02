"""The registry contract: validated at import, frozen after startup — for every entity AND every
association a module declares.

An association is not an entity (it has no id of its own in the API, its text comes from the rows it
links, its permission is its own), but it is DECLARED on the same terms and frozen by the same
`freeze_registry()`: one act, at import. So it is held to the same contract here — the entity
registry's half by asking the module what it declares, the association half by the same probes with
stand-in models, since a module with no link table of its own must still be able to run this file.

GENERALISED ON PURPOSE. This suite names no entity. It asks the registry which entities this
module declares (`all_entity_descriptors()`) and holds the contract against each of them, so a
module with eight entities is covered by the same file as one with a single entity and nothing has
to be edited when an entity is added. That is what lets it be a framework test rather than a
module-tailored one: a suite that named `items` could only ever be force-synced into modules that
happen to have an `items` entity.

What stays out of it, deliberately: anything true of module_template's OWN entity in particular —
that its model is `TemplateItem`, that its create schema is called `TemplateItemCreate`. Those are
the module maintainer's to assert about their own entities; the framework's business is the
contract every descriptor must satisfy whatever it describes.

In-process layer (see `TESTS/README.md`) — no HTTP server involved, but a real database
connection is opened by the `app_module` fixture because importing `app.entities` also imports
`app.database`, which builds a real `Engine`. No query runs here: everything below is about the
registry's own behaviour (what a descriptor must look like, and what happens once it exists),
which the sub-set 1 design fixes as import-time properties rather than request-time ones — see
`app/entities/__init__.py`'s module docstring, "where the genericity is allowed to live" rule 1.
"""
import pytest


@pytest.fixture(scope="module")
def entities(app_module):
    return app_module.entities


@pytest.fixture(scope="module")
def declared(entities):
    """Every entity this module declares, as {key: descriptor}.

    The registry rather than `schema.sql`: the descriptor IS the declaration the framework mounts
    from, so a table with no descriptor is deliberately not an entity here, and a test reading the
    schema would disagree with the thing under test.
    """
    found = dict(entities.all_entity_descriptors())
    assert found, (
        "this module declares no entities, so nothing below can be checked. A module with a "
        "datamodel must register a descriptor per entity in app/entities/."
    )
    return found


@pytest.fixture(scope="module")
def a_descriptor(declared):
    """Any registered descriptor, to borrow valid field values from when building a probe.

    Which one is irrelevant — the probes below are about the VALIDATION, and every descriptor is by
    definition a set of values that passes it. Named this way so no reader mistakes it for a test
    about that particular entity.
    """
    return next(iter(declared.values()))


class TestTheRegistryIsFrozenAfterImport:
    """`app/entities/__init__.py` imports every descriptor submodule and freezes — once, at the
    bottom of the file. By the time any test (or a future router) can observe the registry, that
    has already happened, and it can never happen again in this process.
    """

    def test_the_registry_reports_itself_frozen(self, entities):
        assert entities.is_registry_frozen() is True

    def test_a_new_key_cannot_be_registered_after_freeze(self, entities, a_descriptor):
        """The property the plan's design note calls out by name: per-entity work happens once,
        at import — never per request, and never after the app has finished starting."""
        bogus = entities.EntityDescriptor(
            key='freeze_probe',
            model=a_descriptor.model,
            create_schema=a_descriptor.create_schema,
            update_schema=a_descriptor.update_schema,
            read_schema=a_descriptor.read_schema,
            page_schema=a_descriptor.page_schema,
            permission_resource=a_descriptor.permission_resource,
        )
        with pytest.raises(RuntimeError, match='frozen'):
            entities.register_entity(bogus)

    def test_a_colliding_key_is_reported_as_a_collision_not_a_frozen_registry(self, entities, a_descriptor):
        """Re-registering an EXISTING key must name the collision, even after freeze — the more
        specific, more actionable failure — and not be swallowed by the frozen-registry message.
        """
        with pytest.raises(ValueError, match='already registered'):
            entities.register_entity(a_descriptor)

    def test_freezing_twice_is_refused(self, entities):
        with pytest.raises(RuntimeError, match='already frozen'):
            entities.freeze_registry()


class TestEveryDeclaredEntityHoldsTheContract:
    """The framework's business: what must be true of EVERY descriptor, whatever it describes.

    Each test loops the declared entities and names the offending one in its message, so a module
    with eight entities gets eight verdicts out of one file and a failure says which entity broke
    the contract rather than that "the registry" did.
    """

    def test_each_entity_is_registered_under_its_own_key(self, declared):
        for key, descriptor in declared.items():
            assert descriptor.key == key, (
                f"entity {key!r} is registered under a key its descriptor does not carry "
                f"({descriptor.key!r}) — the registry and the descriptor disagree about its name"
            )

    def test_each_key_is_snake_case(self, declared):
        for key in declared:
            assert key == key.lower() and ' ' not in key, (
                f"entity key {key!r} is not snake_case; the key reaches a URL and a permission"
            )

    def test_each_model_is_a_real_mapping(self, declared):
        for key, descriptor in declared.items():
            assert hasattr(descriptor.model, '__table__'), (
                f"entity {key!r} points at {descriptor.model!r}, which is not a mapped SQLAlchemy "
                f"class — every test of this entity would validate against a stub"
            )

    def test_each_model_declares_its_tenancy(self, declared):
        """`scripts/dev/common/check_tenancy_markers.py` checks the files at build time; this
        checks the objects the app actually serves, which is what a request meets."""
        for key, descriptor in declared.items():
            assert hasattr(descriptor.model, '__tenant_scoped__'), (
                f"entity {key!r}'s model declares no __tenant_scoped__ — the generic query layer "
                f"cannot know whether to confine reads to the caller's tenants"
            )

    def test_each_permission_resource_is_bare_not_qualified(self, declared):
        """Bare exactly as `config/authorization.yaml` declares it; qualifying it with the module
        slug is a router's job, never the descriptor's own."""
        for key, descriptor in declared.items():
            assert descriptor.permission_resource.strip(), (
                f"entity {key!r} declares a blank permission_resource"
            )
            assert '.' not in descriptor.permission_resource, (
                f"entity {key!r} qualifies its permission_resource "
                f"({descriptor.permission_resource!r}); the slug is added by the router"
            )

    def test_each_entity_declares_its_eager_load_plan_explicitly(self, declared):
        """An entity with a relationship in its read schema and no plan is the N+1 the design note
        names. The field must exist and be a sequence — empty is an honest answer, absent is not."""
        for key, descriptor in declared.items():
            assert isinstance(descriptor.eager_load, (tuple, list)), (
                f"entity {key!r} does not declare an eager_load plan; an omitted plan is how a "
                f"generic serializer falls into N+1"
            )

    def test_each_entity_is_reachable_by_its_key(self, declared, entities):
        for key, descriptor in declared.items():
            assert entities.get_entity_descriptor(key) is descriptor

    def test_an_unknown_key_raises_and_names_what_is_registered(self, entities, declared):
        """The error is the only place a caller learns what IS registered, so it must list them."""
        with pytest.raises(KeyError) as raised:
            entities.get_entity_descriptor('does-not-exist')
        message = str(raised.value)
        for key in declared:
            assert key in message, (
                f"the unknown-key error does not mention {key!r}, so a caller cannot see what is "
                f"available"
            )

    def test_the_registry_view_is_read_only(self, entities, declared):
        view = entities.all_entity_descriptors()
        assert dict(view) == declared
        with pytest.raises(TypeError):
            view[next(iter(declared))] = None  # type: ignore[index]


class TestDescriptorValidationRunsAtConstruction:
    """Every one of these fails the `EntityDescriptor(...)` call itself — before `register_entity`
    ever runs — because a broken descriptor should fail the line that builds it, with a message
    naming the field, not a request three calls downstream."""

    @pytest.fixture
    def valid_kwargs(self, a_descriptor):
        return dict(
            model=a_descriptor.model, create_schema=a_descriptor.create_schema,
            update_schema=a_descriptor.update_schema, read_schema=a_descriptor.read_schema,
            page_schema=a_descriptor.page_schema,
            permission_resource=a_descriptor.permission_resource,
        )

    def test_uppercase_key_is_rejected(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match='snake_case'):
            entities.EntityDescriptor(key='Items', **valid_kwargs)

    def test_key_with_a_space_is_rejected(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match='snake_case'):
            entities.EntityDescriptor(key='two words', **valid_kwargs)

    def test_blank_permission_resource_is_rejected(self, entities, valid_kwargs):
        valid_kwargs['permission_resource'] = '   '
        with pytest.raises(ValueError, match='permission_resource'):
            entities.EntityDescriptor(key='probe', **valid_kwargs)

    def test_a_plain_class_is_not_a_valid_model(self, entities, valid_kwargs):
        valid_kwargs['model'] = object
        with pytest.raises(ValueError, match='mapped SQLAlchemy model'):
            entities.EntityDescriptor(key='probe', **valid_kwargs)

    def test_a_model_declaring_no_tenant_scoped_flag_is_rejected(self, entities, valid_kwargs):
        """Belt over `scripts/dev/common/check_tenancy_markers.py` (a build-time file check): this
        one runs at import time over the actual object, and needs nothing SQLAlchemy-mapped to do
        it — `_validate_descriptor` only checks attribute presence, so a plain stand-in with a
        `__tablename__` and no `__tenant_scoped__` exercises exactly the same branch a real,
        forgotten model would."""

        class _NoTenancyFlag:
            __tablename__ = 'entity_registry_probe_no_tenancy_flag'

        valid_kwargs['model'] = _NoTenancyFlag
        with pytest.raises(ValueError, match='__tenant_scoped__'):
            entities.EntityDescriptor(key='probe', **valid_kwargs)

    @pytest.mark.parametrize('field', ['create_schema', 'update_schema', 'read_schema', 'page_schema'])
    def test_a_non_basemodel_schema_is_rejected(self, entities, valid_kwargs, field):
        valid_kwargs[field] = dict  # a plain type, not a pydantic BaseModel subclass
        with pytest.raises(ValueError, match=field):
            entities.EntityDescriptor(key='probe', **valid_kwargs)

    def test_a_non_basemodel_version_schema_is_rejected(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match='version_schema'):
            entities.EntityDescriptor(key='probe', version_schema=dict, **valid_kwargs)


class TestTheCreateHooksAreCalled:
    """The create path calls `before_create` then `after_create`, around the insert.

    WHY THIS EXISTS. Both were declared on the descriptor and never called, so no descriptor could
    express a create-time side effect at all: `host_app`'s `users` must create the Authentik
    identity beside the row, and with no `after_create` the only way to say so was a hand-written
    route — the duplication the descriptor exists to remove. The update/delete hooks were wired and
    these two were not, which is the kind of half that reads as "done" until an entity needs it.

    The insert is STUBBED, not run: what is under test is the wiring — which hook, handed what, in
    which order — and `crud.create_entity` has its own suite.
    """

    def test_both_hooks_run_around_the_insert(self, entities, a_descriptor, monkeypatch):
        import dataclasses

        import ideable_api.query as crud

        calls: list[tuple] = []
        the_row = object()

        def fake_create(db, model, payload, scope, **kwargs):
            calls.append(("insert", payload))
            return the_row

        monkeypatch.setattr(crud, "create_entity", fake_create)
        payload = object()
        descriptor = dataclasses.replace(
            a_descriptor,
            before_create=lambda seen, scope: calls.append(("before", seen)),
            after_create=lambda row, scope: calls.append(("after", row)),
        )

        result = entities.create_entity_row(object(), descriptor, payload, None)

        assert [name for name, _ in calls] == ["before", "insert", "after"], (
            f"the create hooks did not bracket the insert: {[name for name, _ in calls]}"
        )
        assert calls[0][1] is payload, "`before_create` must see the payload it will insert"
        assert calls[2][1] is the_row, (
            "`after_create` must see the ROW the insert produced — a side effect needing the id the "
            "insert assigned has nothing else to read it from"
        )
        assert result is the_row

    def test_a_descriptor_with_no_create_hooks_still_creates(self, entities, a_descriptor,
                                                             monkeypatch):
        import ideable_api.query as crud

        monkeypatch.setattr(crud, "create_entity", lambda db, model, payload, scope, **kw: "row")
        assert entities.create_entity_row(object(), a_descriptor, "payload", None) == "row"


def test_every_declared_model_is_a_real_declarative_mapping(declared):
    """Sanity on the fixture itself: if this failed, every test above would be validating against
    a stub instead of the entities the app actually serves."""
    for key, descriptor in declared.items():
        model = descriptor.model
        assert hasattr(model, '__table__'), f"entity {key!r} is not a mapped SQLAlchemy class"
        assert getattr(model, '__tablename__', None), f"entity {key!r} maps to no table"



class TestAFilterableColumnCannotCollideWithTheListEndpoint:
    """A filterable column is spliced into the generated list endpoint's signature under its name.

    host_app's `roles` and `profiles` declare a filterable `scope` (their owner), which collided with
    the handler's tenant-scope dependency and stopped the backend at import with `ValueError:
    duplicate parameter name: 'scope'`. The handler's dependencies are now underscored, and a column
    named like one of the endpoint's real QUERY parameters is refused by name when the descriptor is
    built. Plain stand-ins, like the tenancy-flag probe above: validation reads attributes only.
    """

    @pytest.fixture
    def valid_kwargs(self, a_descriptor):
        return dict(
            create_schema=a_descriptor.create_schema, update_schema=a_descriptor.update_schema,
            read_schema=a_descriptor.read_schema, page_schema=a_descriptor.page_schema,
            permission_resource=a_descriptor.permission_resource,
        )

    @staticmethod
    def _model(*filterable):
        return type('Probe', (), {'__tablename__': 'entity_registry_probe_filters',
                                  '__tenant_scoped__': False, '__filterable__': filterable})

    def test_a_column_named_like_a_dependency_is_accepted(self, entities, valid_kwargs):
        entities.EntityDescriptor(key='probe', model=self._model('scope', 'db'), **valid_kwargs)

    @pytest.mark.parametrize('column', ['limit', 'id', 'sort_by'])
    def test_a_column_named_like_a_query_parameter_is_refused_by_name(self, entities, valid_kwargs,
                                                                        column):
        with pytest.raises(ValueError, match=f"'probe'.*{column}"):
            entities.EntityDescriptor(key='probe', model=self._model(column), **valid_kwargs)

    def test_the_list_handler_names_no_dependency_a_column_could_take(self):
        """Source-level on purpose: the router imports FastAPI, which this layer does not install."""
        from pathlib import Path

        router = (Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api' / 'router.py').read_text()
        handler = router.split('def list_rows(')[1].split('):')[0]
        assert '_db: Session' in handler and '_tenant_scope:' in handler
        assert '\n        scope:' not in handler and '\n        db:' not in handler


class TestTheFourDeclarationsAreValidatedAtConstruction:
    """`tenant_from`, `derived_filters` and `read_permission_resources` are refused by name when the
    descriptor is built, never at the first request. Plain stand-ins, like the probes above:
    validation reads attributes only."""

    @pytest.fixture
    def valid_kwargs(self, a_descriptor):
        return dict(
            create_schema=a_descriptor.create_schema, update_schema=a_descriptor.update_schema,
            read_schema=a_descriptor.read_schema, page_schema=a_descriptor.page_schema,
            permission_resource='probe_resource',
        )

    @staticmethod
    def _model(name='probe', *, tenant_scoped=True, filterable=()):
        return type(name, (), {'__tablename__': f'registry_{name}', '__tenant_scoped__': tenant_scoped,
                               '__filterable__': filterable})

    def _build(self, entities, valid_kwargs, **declared):
        model = declared.pop('model', None) or self._model()
        return entities.EntityDescriptor(key='probe', model=model, **{**valid_kwargs, **declared})

    # -- tenant_from
    def test_a_tenant_scoped_child_may_take_its_parents_tenant(self, entities, valid_kwargs, a_descriptor):
        field = next(iter(a_descriptor.create_schema.model_fields))
        self._build(entities, valid_kwargs, tenant_from=(self._model('parent'), field))

    def test_tenant_from_on_a_global_entity_is_refused(self, entities, valid_kwargs, a_descriptor):
        field = next(iter(a_descriptor.create_schema.model_fields))
        with pytest.raises(ValueError, match="'probe'.*tenant_from.*not tenant-scoped"):
            self._build(entities, valid_kwargs, model=self._model(tenant_scoped=False),
                        tenant_from=(self._model('parent'), field))

    def test_a_global_parent_is_refused(self, entities, valid_kwargs, a_descriptor):
        field = next(iter(a_descriptor.create_schema.model_fields))
        with pytest.raises(ValueError, match="tenant_from parent.*tenant-scoped"):
            self._build(entities, valid_kwargs,
                        tenant_from=(self._model('parent', tenant_scoped=False), field))

    def test_a_parent_key_outside_the_create_schema_is_refused_by_name(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match="names 'not_a_field'.*create_schema"):
            self._build(entities, valid_kwargs, tenant_from=(self._model('parent'), 'not_a_field'))

    def test_a_malformed_tenant_from_is_refused(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match="tenant_from must be"):
            self._build(entities, valid_kwargs, tenant_from='parent')

    # -- derived_filters
    def test_a_derived_filter_is_accepted(self, entities, valid_kwargs):
        self._build(entities, valid_kwargs, derived_filters={'risk_aspect': lambda query, value: query})

    @pytest.mark.parametrize('name', ['Risk', '_hidden', '1st', 'risk-aspect', ''])
    def test_a_name_that_is_not_a_lowercase_identifier_is_refused(self, entities, valid_kwargs, name):
        with pytest.raises(ValueError, match="derived_filters name"):
            self._build(entities, valid_kwargs, derived_filters={name: lambda query, value: query})

    @pytest.mark.parametrize('name', ['limit', 'sort_by', 'include_total'])
    def test_a_name_the_list_endpoint_already_uses_is_refused(self, entities, valid_kwargs, name):
        with pytest.raises(ValueError, match=f"derived_filters name '{name}'"):
            self._build(entities, valid_kwargs, derived_filters={name: lambda query, value: query})

    def test_a_name_that_is_also_a_filterable_column_is_refused(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match="derived_filters name 'status'"):
            self._build(entities, valid_kwargs, model=self._model(filterable=('status',)),
                        derived_filters={'status': lambda query, value: query})

    def test_a_predicate_that_is_not_callable_is_refused(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match=r"derived_filters\['risk'\] must be callable"):
            self._build(entities, valid_kwargs, derived_filters={'risk': 'not callable'})

    # -- read_permission_resources
    def test_alternative_read_resources_are_accepted(self, entities, valid_kwargs):
        self._build(entities, valid_kwargs, read_permission_resources=('assessment', 'review'))

    def test_a_blank_name_is_refused(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match="read_permission_resources must hold non-blank"):
            self._build(entities, valid_kwargs, read_permission_resources=('assessment', ' '))

    def test_a_repeated_name_is_refused(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match="repeats a name"):
            self._build(entities, valid_kwargs, read_permission_resources=('assessment', 'assessment'))

    def test_naming_the_entitys_own_resource_is_refused(self, entities, valid_kwargs):
        with pytest.raises(ValueError, match="names permission_resource 'probe_resource'"):
            self._build(entities, valid_kwargs, read_permission_resources=('probe_resource',))

    def test_a_descriptor_declaring_none_of_them_is_unchanged(self, entities, valid_kwargs):
        descriptor = self._build(entities, valid_kwargs)
        assert descriptor.tenant_from is None
        assert dict(descriptor.derived_filters) == {}
        assert descriptor.read_permission_resources == ()


class TestTheGeneratedRouterCarriesTheDeclarations:
    """Source-level on purpose, like the list-handler check above: the router imports FastAPI, which
    this layer does not install. What is pinned is what a regression would silently remove."""

    @pytest.fixture
    def router(self):
        from pathlib import Path

        return (Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api' / 'router.py').read_text()

    def test_history_tracks_the_version_schemas_columns_not_the_filter_whitelist(self, router):
        history = router.split('def _add_history_route(')[1].split('\ndef ')[0]
        assert 'history_tracked_columns(descriptor)' in history
        assert 'tracked_columns=tracked' in history
        assert 'for column in filterable' not in history, 'history rows must not be built from __filterable__'

    def test_the_tracked_set_is_the_schemas_model_columns_beyond_the_base_audit_fields(self, router):
        tracked = router.split('def history_tracked_columns(')[1].split('\ndef ')[0]
        for base in ('transaction_id', 'operation_type', 'end_transaction_id', 'timestamp', 'actor_id'):
            assert base in router.split('HISTORY_BASE_FIELDS = ')[1].split(')')[0]
        assert 'name not in HISTORY_BASE_FIELDS and name in columns' in tracked
        assert 'raise' not in tracked, 'a schema field that is not a column is skipped, never refused'

    def test_a_derived_filter_is_spliced_into_the_list_signature_and_separated_from_the_columns(self, router):
        assert 'base + _filter_parameters(descriptor) + _derived_parameters(descriptor)' in router
        assert 'derived={k: v for k, v in filters.items()' in router

    def test_reads_but_not_writes_take_the_any_of_dependency(self, router):
        build = router.split('def build_entity_router(')[1]
        assert "view = Depends(any_permission_dependency(platform, [" in build
        assert "edit = Depends(platform.require_permission(permission_for(platform, descriptor, 'edit')))" in build

    def test_only_a_403_is_swallowed_by_an_alternative(self, router):
        any_of = router.split('def any_permission_dependency(')[1].split('\ndef ')[0]
        assert any_of.count('if exc.status_code != status.HTTP_403_FORBIDDEN:') == 2
        assert 'raise outcomes[-1]' in any_of
        assert 'inspect.signature(dependency)' in any_of, 'the original dependency must keep its parameters'


class TestTheGeneratedWritesRunTheDescriptorHooks:
    """The generated POST/PUT/DELETE called the query core directly, so `before_create`,
    `before_update` and the `after_*` hooks — the reuse surface a descriptor promises — were
    declarations nothing ran. host_app's `roles`/`profiles` found it: their `before_update` refuses
    an owner change that would break an existing grant, and the generated PUT accepted it.
    Source-level: the router imports FastAPI, which this layer does not install."""

    @pytest.fixture
    def router_source(self):
        from pathlib import Path

        return (Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api' / 'router.py').read_text()

    @pytest.mark.parametrize('handler,wrapper', [('create_row', 'create_entity_row'),
                                                 ('update_row', 'update_entity_row'),
                                                 ('delete_row', 'delete_entity_row')])
    def test_each_write_goes_through_its_hook_running_wrapper(self, router_source, handler, wrapper):
        body = router_source.split(f'def {handler}(')[1].split('\n    def ')[0].split('router.add_api_route')[0]
        assert f'{wrapper}(' in body, f'{handler} must call entities.{wrapper}, which runs the hooks'
        assert 'crud.create_entity(' not in body and 'crud.update_entity(' not in body \
            and 'crud.delete_entity(' not in body


class TestAGlobalRowKeepsItsTenantIdColumn:
    """`tenant_id` is the framework's to assign on a TENANT-SCOPED row. On a global row it is an
    ordinary column: the create path popped it regardless, so host_app's `roles.tenant_id` (the
    owner) was dropped and the table's CHECK refused the row as a 500."""

    def test_the_create_path_pops_tenant_id_only_for_a_tenant_scoped_model(self):
        from pathlib import Path

        query = (Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api' / 'query.py').read_text()
        body = query.split('def create_entity(')[1].split('\ndef ')[0]
        scoped_branch = body.split('if tenant_scoped:')[1].split('else:')[0]
        assert "data.pop('tenant_id'" in scoped_branch
        assert "data.pop('tenant_id'" not in body.split('if tenant_scoped:')[0]



class TestTheEntitysNarrowingAppliesOnEveryPath:
    """`scope_query` ran on no generated route: the list called the query core directly, and the
    by-id paths had no narrowing at all — so a row the list hid was readable, updatable and
    deletable by id. Found by host_app's tenant administration, the first `scope_query` declared.
    Source-level: the router imports FastAPI, which this layer does not install."""

    @pytest.fixture
    def router_source(self):
        from pathlib import Path

        return (Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api' / 'router.py').read_text()

    def test_the_router_never_calls_the_query_core_for_a_read(self, router_source):
        assert 'crud.list_entities(' not in router_source and 'crud.get_entity(' not in router_source, (
            'a generated read that calls the query core directly skips the entity\'s scope_query'
        )

    def test_the_by_id_read_carries_the_narrowing(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api'
        entities = (root / 'entities.py').read_text().split('def get_entity_row(')[1].split('\ndef ')[0]
        assert 'narrow=descriptor.scope_query' in entities
        query = (root / 'query.py').read_text().split('def get_entity(')[1].split('\ndef ')[0]
        assert 'narrow(query, scope)' in query

    def test_a_delete_can_be_refused_before_it_happens(self):
        from pathlib import Path

        entities = (Path(__file__).resolve().parents[4] / 'reusable.api' / 'ideable_api' / 'entities.py').read_text()
        body = entities.split('def delete_entity_row(')[1].split('\ndef ')[0]
        assert body.index('descriptor.before_delete(') < body.index('crud.delete_entity(')


# ---------------------------------------------------------------------------
# Associations: declared on the same terms, frozen with the same registry
# ---------------------------------------------------------------------------

def _probe_endpoint(name: str):
    """A stand-in endpoint model: mapped, and joined by its own `id`."""
    return type(name, (), {'__tablename__': name.lower(), 'id': None})


def _probe_link(**columns):
    """A stand-in link table: mapped, global, with the key columns the probe declares.

    The class attributes are what the descriptor VALIDATES (a key column must be there); the
    `__init__` is what the core needs to build a row, `model(**keys)` as it does for any model.
    """
    base = {'__tablename__': 'association_probe', '__tenant_scoped__': False,
            '__init__': lambda self, **kwargs: self.__dict__.update(kwargs)}
    base.update(columns)
    return type('ProbeLink', (), base)


@pytest.fixture
def association_kwargs(a_descriptor):
    """Valid values for an `AssociationDescriptor`, over stand-in models.

    The schemas are borrowed from the module's own entity descriptor: an association's four schemas
    are the module's, and this suite is not about their content — only that they are pydantic
    models — so inventing a second set here would assert nothing extra.
    """
    return dict(
        model=_probe_link(user_fk=None, profile_fk=None, tenant_fk=None),
        left_col='user_fk', right_col='profile_fk',
        left_model=_probe_endpoint('ProbeUser'), right_model=_probe_endpoint('ProbeProfile'),
        text_fields={'user.username': lambda user, profile: user.username or ''},
        create_schema=a_descriptor.create_schema, update_schema=a_descriptor.update_schema,
        read_schema=a_descriptor.read_schema, page_schema=a_descriptor.page_schema,
        permission_resource='probe_assignments',
    )


class TestTheAssociationDescriptorContract:
    """What must be true of EVERY association descriptor, whatever link table it describes.

    Stand-ins, like the descriptor probes above: this file names no link table and no module, so it
    is force-synced into a module that declares no association at all without going red.
    """

    def test_a_two_key_association_is_accepted(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        descriptor = AssociationDescriptor(key='as_probe_pair', **association_kwargs)
        assert descriptor.key_cols == ('user_fk', 'profile_fk')

    def test_a_three_key_association_is_accepted_and_gets_a_three_part_id(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor, synthetic_id

        descriptor = AssociationDescriptor(
            key='as_probe_grant', scope_col='tenant_fk',
            scope_model=_probe_endpoint('ProbeTenant'), scope_label='Tenant',
            scope_text_fields={'tenant.name': lambda tenant: tenant.name or ''},
            response_fields={'username': 'user.username', 'tenant': 'tenant.name'},
            **association_kwargs)
        assert descriptor.key_cols == ('user_fk', 'profile_fk', 'tenant_fk')
        assert synthetic_id(*range(1, 4)) == '1__2__3'

    def test_a_tenant_scoped_link_table_is_refused(self, association_kwargs):
        """Fail closed: the association query side applies no tenant predicate, so a declaration it
        would serve unscoped must fail the line that builds it rather than the tenant it leaks."""
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['model'] = _probe_link(
            __tenant_scoped__=True, user_fk=None, profile_fk=None, tenant_fk=None)
        with pytest.raises(ValueError, match='__tenant_scoped__'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_a_scope_model_without_a_scope_col_is_refused(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['scope_model'] = _probe_endpoint('ProbeTenant')
        with pytest.raises(ValueError, match='all together or not at all'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_a_key_column_the_link_table_does_not_have_is_refused(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['right_col'] = 'profile_id'
        with pytest.raises(ValueError, match='profile_id'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_an_endpoint_without_an_id_is_refused(self, association_kwargs):
        """The row builder joins a link row's keys to its endpoints by `id`."""
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['right_model'] = type('ProbeNoId', (), {'__tablename__': 'probe_no_id'})
        with pytest.raises(ValueError, match='`id`'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_a_response_field_with_no_text_behind_it_is_refused(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['response_fields'] = {'username': 'user.email'}
        with pytest.raises(ValueError, match='user.email'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_an_undotted_text_field_is_refused(self, association_kwargs):
        """A caller filtering has to say which side of the join it means."""
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['text_fields'] = {'username': lambda user, profile: user.username or ''}
        with pytest.raises(ValueError, match='dotted'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_a_key_column_named_like_a_list_query_parameter_is_refused(self, association_kwargs):
        """The key columns are spliced into the list handler's signature under their own names."""
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['model'] = _probe_link(user_fk=None, limit=None)
        association_kwargs['right_col'] = 'limit'
        with pytest.raises(ValueError, match="'limit'"):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_an_uppercase_key_is_refused(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        with pytest.raises(ValueError, match='snake_case'):
            AssociationDescriptor(key='AsProbePair', **association_kwargs)

    def test_a_qualified_permission_resource_is_refused(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['permission_resource'] = 'hostapp.probe_assignments'
        with pytest.raises(ValueError, match='bare'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)

    def test_a_non_basemodel_schema_is_refused(self, association_kwargs):
        from ideable_api.associations import AssociationDescriptor

        association_kwargs['read_schema'] = dict
        with pytest.raises(ValueError, match='read_schema'):
            AssociationDescriptor(key='as_probe_pair', **association_kwargs)


class TestTheAssociationRegistryIsFrozenWithTheEntityRegistry:
    """One `freeze_registry()` closes both: a module declares what it serves in one act, at import."""

    def test_registering_after_freeze_is_refused(self, entities, association_kwargs):
        import ideable_api.associations as associations

        assert entities.is_registry_frozen() is True
        probe = associations.AssociationDescriptor(key='freeze_probe', **association_kwargs)
        with pytest.raises(RuntimeError, match='frozen'):
            associations.register_association(probe)

    def test_a_colliding_key_is_reported_as_a_collision_not_a_frozen_registry(
            self, association_kwargs, monkeypatch):
        """Re-registering an EXISTING key names the collision even after freeze — the more
        specific, more actionable failure."""
        import ideable_api.associations as associations

        probe = associations.AssociationDescriptor(key='as_probe_pair', **association_kwargs)
        monkeypatch.setitem(associations._REGISTRY, 'as_probe_pair', probe)
        with pytest.raises(ValueError, match='already registered'):
            associations.register_association(probe)

    def test_an_unknown_key_raises_and_names_what_is_registered(self, monkeypatch):
        import ideable_api.associations as associations

        monkeypatch.setitem(associations._REGISTRY, 'as_probe_pair', object())
        with pytest.raises(KeyError) as raised:
            associations.get_association_descriptor('does-not-exist')
        assert 'as_probe_pair' in str(raised.value)


class _FakeQuery:
    """`Session.query(...)`'s two methods the query side uses. The criteria are ignored: the rows
    the fake was built with ARE the answer, which is what makes the probe's expectations explicit."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def filter(self, *_criteria):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Enough of a Session to exercise the query side's behaviour with no database.

    `add` appends to the same list `query` reads, so a `find` after a write sees the row the write
    added — the property the `after_*` hooks depend on. `calls` records the write path's steps, in
    order, which is how the hook order is asserted rather than assumed.
    """

    def __init__(self, rows_by_model, visible_tenant=None):
        self.rows_by_model = rows_by_model
        self.visible_tenant = visible_tenant
        self.calls: list[str] = []

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))

    def add(self, row):
        self.calls.append('add')
        self.rows_by_model.setdefault(type(row), []).append(row)

    def flush(self):
        self.calls.append('flush')

    def commit(self):
        self.calls.append('commit')

    def delete(self, row):
        self.calls.append('delete')


@pytest.fixture
def probe(a_descriptor):
    """A grant-shaped association over stand-in models, with the rows to serve it.

    Three keys, joined text on both sides, and a `narrow` that keeps only the caller's tenant — the
    shape host_app's `as_user_profile` has, which is the one with a third key and an isolation rule.
    """
    from types import SimpleNamespace

    from ideable_api.associations import AssociationDescriptor

    link = _probe_link(user_fk=None, profile_fk=None, tenant_fk=None)
    users = _probe_endpoint('ProbeUser')
    profiles = _probe_endpoint('ProbeProfile')
    tenants = _probe_endpoint('ProbeTenant')
    descriptor = AssociationDescriptor(
        key='as_probe_grant',
        model=link, left_col='user_fk', right_col='profile_fk',
        left_model=users, right_model=profiles, left_label='User', right_label='Profile',
        scope_col='tenant_fk', scope_model=tenants, scope_label='Tenant',
        scope_text_fields={'tenant.name': lambda tenant: tenant.name or ''},
        text_fields={'user.username': lambda user, profile: user.username or ''},
        response_fields={'username': 'user.username', 'tenant': 'tenant.name'},
        create_schema=a_descriptor.create_schema, update_schema=a_descriptor.update_schema,
        read_schema=a_descriptor.read_schema, page_schema=a_descriptor.page_schema,
        permission_resource='probe_assignments',
        narrow=lambda db: (lambda item: item['tenant_fk'] == db.visible_tenant),
    )
    rows = {
        users: [SimpleNamespace(id=1, username='ada'), SimpleNamespace(id=2, username='bob')],
        profiles: [SimpleNamespace(id=10, name='admin')],
        tenants: [SimpleNamespace(id=100, name='T1'), SimpleNamespace(id=200, name='T2')],
        link: [SimpleNamespace(user_fk=1, profile_fk=10, tenant_fk=100),
               SimpleNamespace(user_fk=2, profile_fk=10, tenant_fk=200)],
    }
    return descriptor, _FakeSession(rows, visible_tenant=100)


class TestTheAssociationQuerySide:
    """`narrow`, the joined text, the key filter and the hook order — the behaviour the generated
    router leans on, over a stand-in session rather than a live one."""

    def test_the_list_keeps_only_the_rows_the_narrowing_keeps(self, probe):
        from ideable_api.associations import list_page

        descriptor, db = probe
        page = list_page(db, descriptor, skip=0, limit=10)

        assert [item['id'] for item in page['items']] == ['1__10__100'], (
            "a row the caller's scope rejects must be in no page — and in no total"
        )
        assert page['total'] == 1

    def test_the_joined_text_is_on_the_row_under_both_names(self, probe):
        """The dotted name is what a caller filters and sorts by; the clean one is what a row
        carries. Both are on the row, because a filter and a cell read different names."""
        from ideable_api.associations import list_page

        descriptor, db = probe
        row = list_page(db, descriptor, skip=0, limit=10)['items'][0]

        assert row['username'] == 'ada' and row['_user.username'] == 'ada'
        assert row['tenant'] == 'T1' and row['_tenant.name'] == 'T1'

    def test_a_key_filter_selects_one_row(self, probe):
        from ideable_api.associations import list_page

        descriptor, db = probe
        db.visible_tenant = 200
        assert [i['id'] for i in list_page(db, descriptor, skip=0, limit=10, left_fk=2)['items']] \
            == ['2__10__200']
        assert list_page(db, descriptor, skip=0, limit=10, scope_fk=100)['items'] == []

    def test_get_one_hides_a_row_outside_the_narrowing(self, probe):
        """A row the list hides must be a 404 by id, not a row a caller can read by guessing."""
        from ideable_api.associations import AssociationError, get_one

        descriptor, db = probe
        with pytest.raises(AssociationError) as raised:
            get_one(db, descriptor, '2__10__200')
        assert raised.value.status_code == 404

    def test_get_one_answers_a_row_inside_the_narrowing(self, probe):
        from ideable_api.associations import get_one

        descriptor, db = probe
        assert get_one(db, descriptor, '1__10__100')['username'] == 'ada'

    def test_an_id_of_the_wrong_arity_names_no_row(self, probe):
        from ideable_api.associations import AssociationError, get_one

        descriptor, db = probe
        with pytest.raises(AssociationError) as raised:
            get_one(db, descriptor, '1__10')
        assert raised.value.status_code == 404

    def test_the_write_path_runs_the_hooks_around_the_insert(self, probe):
        """before → insert → flush → after → commit. A hook that raises leaves nothing committed,
        and an `after_*` hook that needs the row's id has it: the flush is what gives it one."""
        import dataclasses

        from ideable_api.associations import create_association

        descriptor, db = probe
        db.rows_by_model[descriptor.model] = []
        hooks: list[tuple] = []
        descriptor = dataclasses.replace(
            descriptor,
            before_create=lambda db, keys: hooks.append(('before_create', dict(keys))),
            validate=lambda db, keys: hooks.append(('validate', dict(keys))),
            after_create=lambda db, row: hooks.append(('after_create', row)),
        )

        result = create_association(db, descriptor, 1, 10, 100)

        assert [name for name, _ in hooks] == ['before_create', 'validate', 'after_create'], (
            "the endpoint rows are checked and the rule validated before the insert, and the "
            "after hook runs once the row exists"
        )
        assert hooks[0][1] == {'user_fk': 1, 'profile_fk': 10, 'tenant_fk': 100}
        assert hooks[2][1] is not None, "`after_create` must see the row, not None"
        assert db.calls == ['add', 'flush', 'commit'], (
            f"the write's own steps, in order: {db.calls}"
        )
        assert result['id'] == '1__10__100'

    def test_an_existing_row_is_a_conflict(self, probe):
        from ideable_api.associations import AssociationError, create_association

        descriptor, db = probe
        with pytest.raises(AssociationError) as raised:
            create_association(db, descriptor, 1, 10, 100)
        assert raised.value.status_code == 409

    def test_a_three_key_create_without_its_third_key_is_unprocessable(self, probe):
        from ideable_api.associations import AssociationError, create_association

        descriptor, db = probe
        with pytest.raises(AssociationError) as raised:
            create_association(db, descriptor, 1, 10)
        assert raised.value.status_code == 422

    def test_both_read_paths_go_through_the_narrowing(self):
        """Source-level, and the point of the hook: `narrow` is resolved INSIDE the two read paths,
        so a route cannot forget it — a row the list hides is a 404 by id."""
        import framework_sources

        source = framework_sources.read(framework_sources.ASSOCIATIONS)
        for function in ('def list_page(', 'def get_one('):
            body = source.split(function)[1].split('\ndef ')[0]
            assert '_narrowed(' in body, f"{function.strip()} does not apply the descriptor's narrow"
