"""The bespoke `items` list/get query, frozen here as sub-set 4's comparison baseline.

This is `app/crud.py`'s `list_items` / `get_item` / their private helpers, as they read at commit
`4ec30aab` — the LAST commit before `d1331a96` ("refactor(backend): model-parameterised CRUD, so a
second entity inherits it") generalised them into today's `list_entities` / `get_entity`. That is
the genuinely bespoke, hand-written-per-entity implementation this plan's sub-set 4 needs to
measure the parametric path against; today's `crud.list_items` already calls the shared generic
core, so benchmarking it against `app.entities.list_entity` would compare a function to itself.

Decided in the plan's "Decisions and answers" chapter (2026-09-17 15:12): captured in sub-set 1,
**before** sub-set 2 removes `routers/items.py` and the entity-bound half of `crud.py` — a
benchmark against a path that no longer exists would be a benchmark against a remembered number.

Self-contained on purpose: no import from `app.crud`, so a future edit or removal there can never
silently change what this baseline measures. It DOES import `app.models.TemplateItem` and
`app.tenancy.TenantScope` — the table and the scope value are not the thing being compared, the
QUERY CONSTRUCTION is, and pointing this at a renamed table would defeat the baseline rather than
freeze it.

This file is exercised in TWO ways, expected to keep growing apart:
- **Now (sub-set 1):** `TESTS/test_bespoke_baseline.py` proves the frozen copy still behaves
  correctly against the live schema — a baseline that silently bit-rotted would compare the new
  path against a broken one and call the result a win.
- **Later (sub-set 4):** the benchmark suite imports this module BY NAME to run the same queries
  under load, timing them against `app.entities.list_entity` / `get_entity_row`.
"""
import json
import logging
import os
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models
from app.tenancy import TenantScope

logger = logging.getLogger(__name__)

# Frozen at the values `crud.py` carried on 2026-09-17: a baseline whose thresholds silently track
# a later tuning of the live constants would no longer be measuring the same query shape.
BESPOKE_MAX_PAGE_SIZE = int(os.getenv('MAX_PAGE_SIZE', '200'))
BESPOKE_EXACT_COUNT_THRESHOLD = int(os.getenv('EXACT_COUNT_THRESHOLD', '50000'))


def _bespoke_estimated_total(db: Session, query) -> int:
    """Row estimate for `query`, from the planner rather than by counting. Verbatim from the
    pre-refactor `crud._estimated_total`."""
    sql = query.statement.compile(db.bind, compile_kwargs={'literal_binds': True})
    plan = db.execute(text(f'EXPLAIN (FORMAT JSON) {sql}')).scalar()
    if isinstance(plan, str):
        plan = json.loads(plan)
    if not isinstance(plan, list) or not plan:
        logger.warning('query plan was empty or not a list; reporting an unknown row estimate')
        return 0
    try:
        return int(plan[0]['Plan']['Plan Rows'])
    except (TypeError, KeyError, IndexError, ValueError):
        logger.warning('query plan had an unexpected shape; reporting an unknown row estimate')
        return 0


def bespoke_apply_tenant_guc(db: Session, scope: TenantScope, *, for_write: bool = False) -> None:
    """Publish the caller's tenants to Postgres for Row-Level Security. Verbatim from the
    pre-refactor `crud.apply_tenant_guc`."""
    if not scope.tenant_ids:
        raise BespokeTenantScopeError('tenant scope is required')
    db.execute(
        text("SELECT set_config('app.tenant_ids', :ids, true)"),
        {'ids': ','.join(str(int(t)) for t in sorted(scope.tenant_ids))},
    )
    db.execute(
        text("SELECT set_config('app.cross_tenant_read', :on, true)"),
        {'on': 'on' if (scope.read_all_tenants and not for_write) else 'off'},
    )


class BespokeTenantScopeError(ValueError):
    """Raised when a write targets a tenant the caller is not authorised for."""


def _bespoke_scoped_to_readable_tenants(query, scope: TenantScope):
    """Confine a read to the tenants `scope` may READ. Verbatim from the pre-refactor
    `crud._scoped_to_readable_tenants`, hardcoded to `TemplateItem` — the property that makes this
    the BESPOKE path rather than the generic one."""
    if scope.read_all_tenants:
        return query
    return query.filter(models.TemplateItem.tenant_id.in_(scope.tenant_ids))


def bespoke_list_items(
    db: Session,
    scope: TenantScope,
    skip: int = 0,
    limit: int = 100,
    id: Optional[int] = None,  # kept identical to the frozen signature, shadowed builtin and all
    name: Optional[str] = None,
    description: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    after_id: Optional[int] = None,
    include_total: bool = True,
) -> tuple[list, int, bool]:
    """Return (items, total, total_is_exact). Verbatim from the pre-refactor `crud.list_items`,
    hand-written for `TemplateItem` with no model parameter and no `__filterable__` /
    `__sortable__` lookup — everything the generic `list_entities` now does once, this repeats."""
    if limit > BESPOKE_MAX_PAGE_SIZE:
        raise ValueError(f'limit must not exceed {BESPOKE_MAX_PAGE_SIZE}')

    query = db.query(models.TemplateItem)

    bespoke_apply_tenant_guc(db, scope)
    query = _bespoke_scoped_to_readable_tenants(query, scope)

    if id is not None:
        query = query.filter(models.TemplateItem.id == id)

    if name:
        query = query.filter(models.TemplateItem.name.ilike(f"%{name}%"))

    if description:
        query = query.filter(models.TemplateItem.description.ilike(f"%{description}%"))

    allowed_sort_fields = {"id", "name", "description"}
    keyset = after_id is not None
    if sort_by:
        if sort_by not in allowed_sort_fields:
            raise ValueError(f"Invalid sort_by: {sort_by}")
        if sort_order not in {"asc", "desc"}:
            raise ValueError(f"Invalid sort_order: {sort_order}")
        if keyset and sort_by != "id":
            raise ValueError("after_id requires ordering by id")
        column = getattr(models.TemplateItem, sort_by)
        query = query.order_by(column.asc() if sort_order == "asc" else column.desc())
    else:
        query = query.order_by(models.TemplateItem.id.asc())

    total, total_is_exact = 0, True
    if include_total:
        estimate = _bespoke_estimated_total(db, query)
        if estimate > BESPOKE_EXACT_COUNT_THRESHOLD:
            total, total_is_exact = estimate, False
        else:
            total = query.count()

    if keyset:
        items = query.filter(models.TemplateItem.id > after_id).limit(limit).all()
    else:
        items = query.offset(skip).limit(limit).all()
    return items, total, total_is_exact


def bespoke_get_item(
    db: Session, item_id: int, scope: TenantScope, *, for_write: bool = False
):
    """Return the item only if it belongs to a tenant `scope` may see. Verbatim from the
    pre-refactor `crud.get_item`."""
    bespoke_apply_tenant_guc(db, scope, for_write=for_write)
    query = db.query(models.TemplateItem).filter(models.TemplateItem.id == item_id)
    if for_write:
        query = query.filter(models.TemplateItem.tenant_id.in_(scope.tenant_ids))
    else:
        query = _bespoke_scoped_to_readable_tenants(query, scope)
    return query.first()
