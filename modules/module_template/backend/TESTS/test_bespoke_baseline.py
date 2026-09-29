"""The frozen bespoke baseline (`benchmark/bespoke_baseline.py`) still behaves correctly.

In-process layer (`TESTS/README.md`). This is NOT the benchmark — `test_parametric_path_performance.py`
does the timing. What belongs here is narrower and just as necessary: a baseline that silently
bit-rotted (a schema change it was never updated for, a Postgres upgrade that changed `EXPLAIN`'s
JSON shape) would let the benchmark "measure" the new path against a broken one and call the result
a win. So this proves the frozen copy still does what it says — tenant scoping, the filter and sort
behaviour, and the keyset cursor — against the live schema, today.
"""
import pytest


@pytest.fixture(scope="module")
def bespoke(app_module):
    """Import the frozen baseline — `app.models`/`app.tenancy` are already on `sys.path` via
    `app_module`; the baseline module itself lives beside this file, under `benchmark/`."""
    from benchmark import bespoke_baseline
    return bespoke_baseline


def test_tenant_scoping_is_applied(app_module, db_session, bespoke, tenant_scope_factory):
    mine = tenant_scope_factory()
    other = tenant_scope_factory()
    marker = f"baseline-{mine.tenant_ids}"
    payload = app_module.entities.get_entity_descriptor('items').create_schema(name=marker, description='x')
    row = app_module.entities.create_entity_row(
        db_session, app_module.entities.get_entity_descriptor('items'), payload, mine,
    )
    row_id = row.id
    try:
        mine_items, mine_total, _ = bespoke.bespoke_list_items(db_session, mine, name=marker)
        assert mine_total == 1 and mine_items[0].id == row_id

        other_items, other_total, _ = bespoke.bespoke_list_items(db_session, other, name=marker)
        assert other_total == 0 and other_items == []

        assert bespoke.bespoke_get_item(db_session, row_id, other) is None
        found = bespoke.bespoke_get_item(db_session, row_id, mine)
        assert found is not None and found.id == row_id
    finally:
        items = app_module.entities.get_entity_descriptor('items')
        fresh = app_module.entities.get_entity_row(db_session, items, row_id, mine, for_write=True)
        if fresh is not None:
            app_module.entities.delete_entity_row(db_session, items, fresh)


def test_max_page_size_is_enforced(bespoke, db_session, tenant_scope_factory):
    scope = tenant_scope_factory()
    with pytest.raises(ValueError, match='must not exceed'):
        bespoke.bespoke_list_items(db_session, scope, limit=bespoke.BESPOKE_MAX_PAGE_SIZE + 1)


def test_a_cursor_combined_with_a_non_id_sort_is_rejected(bespoke, db_session, tenant_scope_factory):
    scope = tenant_scope_factory()
    with pytest.raises(ValueError, match='after_id requires ordering by id'):
        bespoke.bespoke_list_items(db_session, scope, sort_by='name', sort_order='asc', after_id=0)


def test_keyset_pagination_seeks_forward(app_module, db_session, bespoke, tenant_scope_factory):
    scope = tenant_scope_factory()
    marker = f"baseline-keyset-{scope.tenant_ids}"
    items = app_module.entities.get_entity_descriptor('items')
    created_ids = []
    for i in range(3):
        payload = items.create_schema(name=marker, description=str(i))
        created_ids.append(app_module.entities.create_entity_row(db_session, items, payload, scope).id)
    try:
        first_page, total, exact = bespoke.bespoke_list_items(
            db_session, scope, name=marker, sort_by='id', sort_order='asc', limit=2,
        )
        assert total == 3 and exact is True
        assert [r.id for r in first_page] == sorted(created_ids)[:2]

        second_page, _, _ = bespoke.bespoke_list_items(
            db_session, scope, name=marker, sort_by='id', sort_order='asc',
            limit=2, after_id=first_page[-1].id,
        )
        assert {r.id for r in second_page} == {sorted(created_ids)[-1]}
    finally:
        for row_id in created_ids:
            fresh = app_module.entities.get_entity_row(db_session, items, row_id, scope, for_write=True)
            if fresh is not None:
                app_module.entities.delete_entity_row(db_session, items, fresh)
