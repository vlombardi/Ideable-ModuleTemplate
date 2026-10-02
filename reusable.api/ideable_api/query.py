"""The generic query core: the list/read/write contract for ANY entity.

Framework code (`reusable.api/README.md`), consumed by every module's backend as
`ideable_api.query`. It knows about models, tenancy and SQLAlchemy, and deliberately nothing
about FastAPI or about any particular entity — the in-process test layer exercises it against
a real database with no server running.
"""
import logging
import json
import os
import re

from typing import Any, Callable, Optional, Sequence
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import Boolean, Integer, Numeric
from .tenancy import TenantScope

logger = logging.getLogger(__name__)


def _is_exact_match_column(column: Any) -> bool:
    """True for a column compared with `= value` rather than `ILIKE '%value%'`.

    A foreign key or another integer asks "which one"; a BOOLEAN asks "true or false"; a numeric
    column asks "which value". None of the three has an `ILIKE`, and Postgres refuses one against a
    non-text column outright — so deciding from `Integer` alone sent `ILIKE` at a boolean and the
    request FAILED rather than returning rows. Measured 2026-09-22 on `users.is_active`: `Boolean`
    is not an `Integer` subclass, so a declared boolean filter could not run at all.

    Decided from the mapped SQL type rather than from the value: a text column that happens to hold
    digits (a code, a slug) still means "contains".
    """
    try:
        return isinstance(column.type, (Integer, Boolean, Numeric))
    except AttributeError:
        return False


def _coerce_filter_value(column: Any, value: str) -> Any:
    """The value an exact-match column compares against, from the string a client sent.

    `int(value)` is deliberately uncaught for an integer column: a non-numeric value is a caller
    error, and `ValueError` is exactly what the router turns into a 400. A boolean column takes the
    spellings a client actually sends — `true`/`false`, `1`/`0`, Postgres' own `t`/`f` — and
    anything else is the same caller error. A numeric column takes a float.
    """
    if isinstance(column.type, Boolean):
        lowered = str(value).strip().lower()
        if lowered in ('true', 't', '1', 'yes'):
            return True
        if lowered in ('false', 'f', '0', 'no'):
            return False
        raise ValueError(f'Invalid boolean filter value: {value}')
    if isinstance(column.type, Integer):
        return int(value)
    return float(value)


# A client must not be able to ask for the whole table: one unbounded request costs the server
# memory proportional to the table and the network the same, and it is trivial to send by
# accident. Requests above this are rejected (422) rather than silently clamped, so a caller
# learns its page size was wrong instead of quietly receiving less than it asked for.
MAX_PAGE_SIZE = int(os.getenv('MAX_PAGE_SIZE', '200'))

# Above this many matching rows an exact COUNT(*) stops being worth its cost, and the planner's
# estimate is used instead. An exact count is a second full pass over the same rows as the page
# query — on the most frequently hit endpoint in the product.
EXACT_COUNT_THRESHOLD = int(os.getenv('EXACT_COUNT_THRESHOLD', '50000'))


def _estimated_total(db: Session, query) -> int:
    """Row estimate for `query`, from the planner rather than by counting.

    `EXPLAIN` costs a plan, not a scan, so this is constant-time where COUNT(*) is linear. The
    number is an estimate and the response says so — a total that is approximately right and
    instant is more useful on a list view than one that is exact and doubles the query cost.
    """
    sql = query.statement.compile(db.bind, compile_kwargs={'literal_binds': True})
    plan = db.execute(text(f'EXPLAIN (FORMAT JSON) {sql}')).scalar()
    if isinstance(plan, str):
        plan = json.loads(plan)
    # `.scalar()` returns None when EXPLAIN yields no row, and the plan's shape is the planner's,
    # not ours. Indexing it blind would raise on a list view -- and an *estimate* is a
    # nice-to-have, so it must degrade rather than fail the request. mypy found this:
    # `Value of type "Any | None" is not indexable`.
    #
    # Narrowed with an explicit check rather than wrapped in `try`: a `try` satisfies the runtime
    # but not the reader or the type checker, and "is this a list of dicts?" is the actual question.
    if not isinstance(plan, list) or not plan:
        logger.warning('query plan was empty or not a list; reporting an unknown row estimate')
        return 0
    try:
        return int(plan[0]['Plan']['Plan Rows'])
    except (TypeError, KeyError, IndexError, ValueError):
        logger.warning('query plan had an unexpected shape; reporting an unknown row estimate')
        return 0


def scoped_to_readable_tenants(query, model, scope: TenantScope):
    """Confine a read to the tenants `scope` may READ — for any model.

    Generic on purpose, and it says something the entity-bound version could not. Every model
    declares `__tenant_scoped__` (mandatory, and `scripts/dev/common/check_tenancy_markers.py` fails the
    build without it), and when that is True the same gate guarantees `tenant_id` exists. So this
    can be trusted to find the column when it needs it — and, unlike the old helper, it can express
    `__tenant_scoped__ = False`: a table that is deliberately global is not filtered at all, rather
    than having no representation.

    The predicate is dropped only for a scope carrying the cross-tenant READ permission, and
    `apply_tenant_guc` widens the row-level policy in the same breath so the two layers state the
    same thing. Every other caller keeps the `IN` — including a cross-tenant reader's writes, which
    go through `scope.tenant_ids` and never come here.
    """
    if not getattr(model, '__tenant_scoped__', False):
        return query
    if scope.read_all_tenants:
        return query
    return query.filter(model.tenant_id.in_(scope.tenant_ids))


def list_entities(
    db: Session,
    model,
    scope: Optional[TenantScope],
    *,
    skip: int = 0,
    limit: int = 100,
    id: Optional[int] = None,
    filters: Optional[dict] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    after_id: Optional[int] = None,
    include_total: bool = True,
    options: Optional[Sequence[Any]] = None,
    narrow: Optional[Callable[[Any, TenantScope], Any]] = None,
):
    """The list contract for ANY entity: (rows, total, total_is_exact).

    Model-parameterised rather than copied per entity, the way `audit.py`'s history factories
    already are. Three properties are the reason this is worth centralising — each was a measured
    defect once, and each would otherwise have to be re-implemented correctly in every entity:

    - **Tenant scoping is applied FIRST**, before any other filter.
    - **`COUNT(*)` is skipped above a threshold** in favour of the planner's estimate, and the caller
      is told which it got. An exact count is a second full pass over the rows the page already
      selected.
    - **A cursor seeks instead of skipping.** `OFFSET` makes Postgres read and discard `skip` rows;
      measured on 1,000,000 rows, offset 900000 took 89 ms and the cursor 0.115 ms.

    Going through `getattr` costs nothing: `Model.name` and `getattr(Model, 'name')` produce the
    same SQLAlchemy expression, so the emitted SQL is identical (measured: 0.4 us difference in
    query CONSTRUCTION, against a query that takes milliseconds).

    What the entity declares, and this does not guess: `__filterable__` and `__sortable__`. Inferring
    them from the columns would put a sequential scan behind any field without a trigram index.

    `options` is the entity's eager-load plan (the entity-registry's `EntityDescriptor.eager_load`,
    a tuple of `sqlalchemy.orm` loader options such as `joinedload(...)`/`selectinload(...)`),
    applied to every row this returns. It is a parameter here — not a decision this function makes
    — because the plan is a property of what a read SCHEMA serializes, which only the descriptor
    knows; this function's job is to apply whatever plan it is given, uniformly, every time.
    """
    if limit > MAX_PAGE_SIZE:
        raise ValueError(f'limit must not exceed {MAX_PAGE_SIZE}')

    filterable = set(getattr(model, '__filterable__', ()))
    sortable = set(getattr(model, '__sortable__', ('id',)))

    # apply_tenant_guc because crud is called directly by jobs and tests that do not pass through
    # the dependency. Skipped for a GLOBAL entity (`__tenant_scoped__ = False`): no RLS policy on
    # such a table reads the GUC, so publishing it would only force every caller of a global
    # entity to hold a TenantScope that entity has no use for. `scoped_to_readable_tenants` already
    # makes the matching decision on its own — this mirrors it rather than duplicating a second
    # switch that could disagree with the first.
    tenant_scoped = getattr(model, '__tenant_scoped__', False)
    if tenant_scoped:
        apply_tenant_guc(db, scope)
    query = scoped_to_readable_tenants(db.query(model), model, scope)
    if narrow is not None:
        # AFTER the tenant predicate and never instead of it: an entity may narrow what its own
        # caller sees, and may not widen it. Applied here rather than left to the caller so there
        # is no call path on which a declared narrowing is silently skipped.
        query = narrow(query, scope)
    if options:
        query = query.options(*options)

    if id is not None:
        query = query.filter(model.id == id)

    for field, value in (filters or {}).items():
        if not value:
            continue
        if field not in filterable:
            raise ValueError(f'Invalid filter field: {field}')
        column = getattr(model, field)
        if _is_exact_match_column(column):
            # A foreign key, an integer, a boolean or a numeric column asks "which one", not "which
            # contain this text" — different questions with different operators. ILIKE against any
            # of them also fails outright in Postgres (no cast), so this is not an alternative
            # reading of the same filter, it is the only one that can run at all.
            query = query.filter(column == _coerce_filter_value(column, value))
        else:
            query = query.filter(column.ilike(f'%{value}%'))

    keyset = after_id is not None
    if sort_by:
        if sort_by not in sortable:
            raise ValueError(f'Invalid sort_by: {sort_by}')
        if sort_order not in {'asc', 'desc'}:
            raise ValueError(f'Invalid sort_order: {sort_order}')
        # A cursor is only meaningful against a stable, unique ordering. Any other column is
        # neither, so a cursor combined with another sort is refused rather than silently returning
        # the wrong window — a paginator that skips rows is worse than one that errors.
        if keyset and sort_by != 'id':
            raise ValueError('after_id requires ordering by id')
        column = getattr(model, sort_by)
        query = query.order_by(column.asc() if sort_order == 'asc' else column.desc())
    else:
        query = query.order_by(model.id.asc())

    total, total_is_exact = 0, True
    if include_total:
        estimate = _estimated_total(db, query)
        if estimate > EXACT_COUNT_THRESHOLD:
            total, total_is_exact = estimate, False
        else:
            total = query.count()

    if keyset:
        # Seek, not skip: the index is positioned once and the server reads only this page.
        rows = query.filter(model.id > after_id).limit(limit).all()
    else:
        rows = query.offset(skip).limit(limit).all()
    return rows, total, total_is_exact


def get_entity(
    db: Session, model, entity_id: int, scope: Optional[TenantScope], *,
    for_write: bool = False, options: Optional[Sequence[Any]] = None,
    narrow: Optional[Callable[[Any, TenantScope], Any]] = None,
):
    """One row, within the caller's tenants — and `for_write` is a security property, not a flag.

    Returns None — which the router turns into 404 — for another tenant's row, rather than 403. A
    403 would confirm the id exists somewhere, which is an enumeration side channel.

    **`for_write=True` ignores the cross-tenant READ widening.** It is how PUT and DELETE load their
    target: a caller holding `read_all_tenants` may SEE every tenant's rows and must still write
    only to its own, so the write path filters on `scope.tenant_ids` and never on the widened set.
    Collapsing the two would let one customer's administrator edit another's data — and this
    parameter is easy to lose in a refactor, which is precisely how it nearly was.

    `options` is the entity's eager-load plan — see `list_entities`'s docstring for why this
    function takes it rather than deciding it.
    """
    tenant_scoped = getattr(model, '__tenant_scoped__', False)
    if tenant_scoped:
        apply_tenant_guc(db, scope, for_write=for_write)
    query = db.query(model).filter(model.id == entity_id)
    if for_write and tenant_scoped:
        query = query.filter(model.tenant_id.in_(scope.tenant_ids))
    else:
        query = scoped_to_readable_tenants(query, model, scope)
    if narrow is not None:
        # The entity's own narrowing, on the by-id path as on the list: a row the list hides must be
        # a 404 here too, or narrowing is a filter on a table and not on the data.
        query = narrow(query, scope)
    if options:
        query = query.options(*options)
    return query.first()


def create_entity(db: Session, model, payload, scope: Optional[TenantScope], *,
                  options: Optional[Sequence[Any]] = None, tenant_id: Optional[int] = None):
    """Create within the caller's OWN tenants — never the widened read set.

    The row-level policy checks an INSERT against `app.tenant_ids` too, so the GUC has to be
    published before the flush, as a write. Without it the INSERT is refused outright: a write path
    that never set the GUC did not merely skip a layer, it could not write at all.

    `options` is the entity's eager-load plan, applied on the post-commit refresh — see
    `_refresh_within_scope`'s docstring for why a write needs the same plan a read does.

    `tenant_id` is a tenant the CALLER OF THIS FUNCTION derived (a descriptor's `tenant_from`: the
    tenant of the parent row). It replaces the payload's, never widens it: it is validated against the
    caller's own tenants exactly as a payload's is, and a payload that names a different one is
    refused rather than overridden.
    """
    tenant_scoped = getattr(model, '__tenant_scoped__', False)
    data = payload.model_dump(exclude_unset=True)
    if tenant_scoped:
        # `tenant_id` is the framework's to assign on a tenant-scoped row: the caller may name one of
        # its OWN tenants, never another. On a GLOBAL row it is an ordinary column and is written as
        # sent — popping it there silently dropped host_app's `roles.tenant_id`/`profiles.tenant_id`
        # (their owner), and the table's CHECK then refused the row as a 500.
        payload_tenant_id = data.pop('tenant_id', None)
        if tenant_id is not None and payload_tenant_id is not None and int(payload_tenant_id) != tenant_id:
            raise TenantScopeError('tenant_id does not match the parent row\'s tenant')
        resolved_tenant_id = _resolve_write_tenant(
            tenant_id if tenant_id is not None else payload_tenant_id, scope)
        apply_tenant_guc(db, scope, for_write=True)
        row = model(**data, tenant_id=resolved_tenant_id)
    else:
        row = model(**data)
    db.add(row)
    db.commit()
    _refresh_within_scope(db, model, row, scope, tenant_scoped=tenant_scoped, options=options)
    return row


def update_entity(db: Session, existing, payload, scope: Optional[TenantScope], *,
                  options: Optional[Sequence[Any]] = None):
    """Apply a partial update to a row the caller already loaded for writing.

    `exclude_unset=True` is what makes it a PATCH-shaped update: a field the client did not send is
    left alone, rather than written as None. The caller loaded `existing` through
    `get_entity(..., for_write=True)`, which published the write GUC.

    `options` — see `create_entity`.
    """
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(existing, field, value)
    db.commit()
    _refresh_within_scope(db, type(existing), existing, scope, tenant_scoped=getattr(
        type(existing), '__tenant_scoped__', False), options=options)
    return existing


def delete_entity(db: Session, existing) -> None:
    db.delete(existing)
    db.commit()


def apply_tenant_guc(db: Session, scope: TenantScope, *, for_write: bool = False) -> None:
    """Publish the caller's tenants to Postgres for Row-Level Security.

    RLS is the layer that survives a mistake: if a future query forgets its tenant filter, the
    database still refuses the rows. That only works if every transaction says who is asking, so
    this is called by each crud entry point rather than left to the caller to remember.

    Two settings, mirroring the two authorisations in `TenantScope`:

    - `app.tenant_ids` — always the caller's OWN tenants, never widened. Every policy that governs
      a write reads only this, so no permission can widen a write at the database layer.
    - `app.cross_tenant_read` — `on` only for a widened read. The policy that reads it is
      `FOR SELECT`, so this cannot authorise an UPDATE or a DELETE even if it is set. It is written
      as `off` rather than left unset when not widened, so the transaction states its answer
      instead of inheriting one.

    Both use `set_config(..., true)` — transaction-local, so nothing leaks to the next request that
    borrows this pooled connection.
    """
    if not scope.tenant_ids:
        raise TenantScopeError('tenant scope is required')
    db.execute(
        text("SELECT set_config('app.tenant_ids', :ids, true)"),
        {'ids': ','.join(str(int(t)) for t in sorted(scope.tenant_ids))},
    )
    db.execute(
        text("SELECT set_config('app.cross_tenant_read', :on, true)"),
        {'on': 'on' if (scope.read_all_tenants and not for_write) else 'off'},
    )


class TenantScopeError(ValueError):
    """Raised when a write targets a tenant the caller is not authorised for."""


def _resolve_write_tenant(payload_tenant_id, scope: TenantScope) -> int:
    """The tenant a write belongs to, validated against the caller's OWN tenants.

    `scope.tenant_ids`, never the widened read set: the cross-tenant permission is
    `items:read_all_tenants`, and a caller that can see every tenant's items still writes only to
    its own. Widening a write would let one customer's administrator file data under another's.

    With one authorised tenant the payload may omit it — the common case, and requiring clients
    to echo back their own tenant invites them to send the wrong one. With several, the payload
    must say which, because guessing would silently file data under the wrong customer.
    """
    tenant_ids = scope.tenant_ids
    if not tenant_ids:
        raise TenantScopeError('tenant scope is required')
    if payload_tenant_id is None:
        if len(tenant_ids) == 1:
            return next(iter(tenant_ids))
        raise TenantScopeError('tenant_id is required when the token authorises several tenants')
    if int(payload_tenant_id) not in tenant_ids:
        # 403 at the router: unlike a read, this is not an enumeration channel — the caller named
        # a tenant explicitly and is being told they may not write there.
        raise TenantScopeError('tenant_id is not within the caller\'s scope')
    return int(payload_tenant_id)


def _refresh_within_scope(db: Session, model, instance, scope: Optional[TenantScope], *,
                          tenant_scoped: bool, options: Optional[Sequence[Any]] = None) -> None:
    """Re-read a just-committed row, in a transaction that says who is asking.

    `db.commit()` ends the transaction the GUC was scoped to, and `Session.refresh` then issues its
    SELECT in a *new* one. Under FORCEd RLS a transaction that has not published `app.tenant_ids`
    matches no rows, so the refresh raises rather than returning the row that was just written.
    Re-publishing is the price of the setting being transaction-local — which is the property that
    stops it leaking to the next request on a pooled connection, so it is the right trade.

    `tenant_scoped` is the entity's, not derived here: a GLOBAL entity has no RLS policy reading
    `app.tenant_ids`, so a caller with no tenant scope at all (host_app's actors, today) can still
    create and refresh a global row.

    `options` is the SAME eager-load plan `list_entities`/`get_entity` apply, and a write needs it
    for the identical reason: `db.refresh` reloads COLUMNS only, never a relationship — and an
    entity that declares one `lazy='raise'` (the N+1 guard's enforcement, `SubItem.item` is the
    worked example) turns a create/update response into a 500 the moment its read schema
    serializes a field derived from that relationship. Measured: `POST /sub_items` failed this way
    before `create_row`/`update_row` (`router.py`) started passing the descriptor's plan through.
    A second, targeted query rather than passing `options` to `db.refresh` itself — `Session.
    refresh()` has no loader-options parameter — landing on the SAME identity-mapped row, so
    `instance`'s relationship attributes end up populated as a side effect and the caller's
    reference is the one left holding them.
    """
    if tenant_scoped:
        apply_tenant_guc(db, scope, for_write=True)
    db.refresh(instance)
    if options:
        db.query(model).options(*options).filter(model.id == instance.id).one()


# ---------------------------------------------------------------------------
# Audit history, paginated by the database
# ---------------------------------------------------------------------------
# The endpoint used to load every version of a record, build two more maps with
# `IN (all transaction_ids)`, convert every row to Pydantic, sort in Python and only then slice.
# `skip` and `limit` reduced nothing: memory and CPU grew with the record's entire lifetime, so a
# heavily edited item was a latency time bomb — and on a shared backend one such request degrades
# every other user.
#
# Everything below is one statement the database can plan: join, filter, order, count, limit.

_OPERATION_LABELS_SQL = "(CASE v.operation_type WHEN 0 THEN 'insert' WHEN 1 THEN 'update' " \
                        "WHEN 2 THEN 'delete' WHEN 3 THEN 'associate' " \
                        "WHEN 4 THEN 'disassociate' ELSE '' END)"

# `normalize_actor_username` trims and falls back to the system actor; this is the same rule in
# SQL, so filtering matches what the response shows rather than the raw meta value.
_ACTOR_SQL = "COALESCE(NULLIF(BTRIM(m.value), ''), :system_actor)"

# Python renders the timestamp with `datetime.isoformat()`, which omits the fractional part when
# microseconds are zero. Reproduced exactly so a substring filter behaves identically to the
# in-memory version it replaces.
_TIMESTAMP_ISO_SQL = (
    "(CASE WHEN date_part('microseconds', COALESCE(t.issued_at, :startup_at)) = 0 "
    "THEN to_char(COALESCE(t.issued_at, :startup_at) AT TIME ZONE 'UTC', "
    "'YYYY-MM-DD\"T\"HH24:MI:SS') "
    "ELSE to_char(COALESCE(t.issued_at, :startup_at) AT TIME ZONE 'UTC', "
    "'YYYY-MM-DD\"T\"HH24:MI:SS.US') END || '+00:00')"
)

# Chronological order is expressed as `transaction_id`, not `issued_at`. Continuum assigns both
# from the same transaction as it is created, so they order identically — but `issued_at` lives on
# the joined table behind a COALESCE, which no index can serve: ordering by it made the database
# sort all 50,000 rows before applying LIMIT (44 ms). `transaction_id` is the leading edge of the
# version table's primary key (id, transaction_id), so the same page comes back in 0.174 ms with
# an index scan that stops after LIMIT rows.
#
# `actor` and `operation_type` are not indexed, so sorting by them still costs a sort of the
# record's history. That is a deliberate trade: they are rare, and indexing every sortable column
# of an audit table costs every write.
_HISTORY_SORTS = {
    'operation_type': 'v.operation_type',
    'actor': _ACTOR_SQL,
    'timestamp': 'v.transaction_id',
}

# A tracked column name, before it is interpolated into `list_item_history`'s SELECT list. Not a
# defence against a hostile caller — `tracked_columns` comes from a descriptor's own
# `__filterable__`, declared by the module, never from a request — but from a typo in that
# declaration turning into a column-name-shaped SQL injection instead of a clear error.
_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _history_where(actor, operation_type, timestamp, scope: TenantScope):
    """WHERE fragments mirroring apply_history_filters: case-insensitive substring matches."""
    # Continuum mirrors the entity's columns onto the version table, so `tenant_id` is there for
    # free — and filtering on it means a forgotten check upstream cannot expose another tenant's
    # history even though the caller already had to pass get_item().
    #
    # History is a READ, so it follows the same readable set as the list: dropping the clause for a
    # cross-tenant reader keeps the two consistent. Leaving it in would have been worse than
    # inconsistent — a cross-tenant reader could open another tenant's item, get zero version rows,
    # and be shown the synthetic "created" row the empty case renders. A record with a real history
    # would look like one that had never been touched.
    clauses, params = ['v.id = :item_id'], {}
    if not scope.read_all_tenants:
        clauses.append('v.tenant_id = ANY(:tenant_ids)')
    if (actor or '').strip():
        clauses.append(f"LOWER({_ACTOR_SQL}) LIKE :actor")
        params['actor'] = f"%{actor.strip().lower()}%"
    if (timestamp or '').strip():
        clauses.append(f"LOWER({_TIMESTAMP_ISO_SQL}) LIKE :timestamp")
        params['timestamp'] = f"%{timestamp.strip().lower()}%"
    if (operation_type or '').strip():
        # The in-memory filter matched the label OR the exact numeric code; both are kept.
        clauses.append(f"({_OPERATION_LABELS_SQL} LIKE :op_label OR v.operation_type::text = :op_exact)")
        params['op_label'] = f"%{operation_type.strip().lower()}%"
        params['op_exact'] = operation_type.strip()
    return ' AND '.join(clauses), params


def list_item_history(
    db: Session,
    version_table: str,
    item_id: int,
    scope: TenantScope,
    startup_at,
    system_actor: str,
    tracked_columns: Sequence[str] = ('name', 'description'),
    skip: int = 0,
    limit: int = 50,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    actor: Optional[str] = None,
    operation_type: Optional[str] = None,
    timestamp: Optional[str] = None,
    before_transaction_id: Optional[int] = None,
) -> tuple[list, int]:
    """Return (page_rows, total) for one item's history, paginated by the database.

    `version_table` is passed in rather than derived here so a derived module can reuse this for
    its own entity; it is interpolated into SQL, so it must come from the ORM (Continuum's version
    class) and never from a request.

    `tracked_columns` is what the version schema actually carries beyond the base audit fields —
    `ideable_api.router.history_tracked_columns` reads it off the descriptor's `version_schema`.
    Defaulted to `('name', 'description')` for source compatibility with a caller that predates this
    parameter; a module with a different shape must pass its own. Each name is
    validated against `_SAFE_IDENTIFIER` before being interpolated — like `version_table`, it must
    come from the ORM's own declaration and never from a request, but a column list is a list, not
    a single trusted string, so it gets its own check rather than inheriting one meant for `version_table`.
    """
    if limit > MAX_PAGE_SIZE:
        raise ValueError(f'limit must not exceed {MAX_PAGE_SIZE}')
    for column in tracked_columns:
        if not _SAFE_IDENTIFIER.match(column):
            raise ValueError(f'unsafe tracked column name: {column!r}')

    apply_tenant_guc(db, scope)
    order_sql = _HISTORY_SORTS.get(sort_by or 'timestamp', _HISTORY_SORTS['timestamp'])
    direction = 'ASC' if (sort_order or 'desc').lower() == 'asc' else 'DESC'
    where_sql, params = _history_where(actor, operation_type, timestamp, scope)
    params |= {
        'item_id': item_id, 'startup_at': startup_at, 'system_actor': system_actor,
        'tenant_ids': sorted(int(x) for x in scope.tenant_ids),
    }

    # Cursor: seek to the position instead of walking to it. History is newest-first, so the
    # cursor is the oldest transaction_id already shown. Only valid for the default chronological
    # ordering — against an `actor` or `operation_type` sort a cursor would skip rows.
    cursor_sql = ''
    if before_transaction_id is not None and (sort_by or 'timestamp') == 'timestamp':
        cursor_sql = ' AND v.transaction_id < :before_transaction_id'
        params['before_transaction_id'] = before_transaction_id

    joins = (
        f'FROM {version_table} v '
        'LEFT JOIN transaction t ON t.id = v.transaction_id '
        # Only the actor row of the metadata, so the join stays 1:1 and cannot fan out.
        "LEFT JOIN transaction_meta m ON m.transaction_id = v.transaction_id AND m.key = 'actor' "
        f'WHERE {where_sql}'
    )
    # `total` counts the WHOLE history — the cursor narrows the page, not the total, or the client
    # could never know how many rows remain. `paged_joins` is therefore used only by the row query.
    paged_joins = joins + cursor_sql

    total = db.execute(text(f'SELECT count(*) {joins}'), params).scalar() or 0

    tracked_sql = ''.join(f'v.{column}, ' for column in tracked_columns)
    rows = db.execute(text(
        f'SELECT v.transaction_id, v.operation_type, v.end_transaction_id, v.id, '
        f'{tracked_sql}COALESCE(t.issued_at, :startup_at) AS ts, '
        f'{_ACTOR_SQL} AS actor {paged_joins} '
        # transaction_id breaks ties so paging is deterministic: without it, rows sharing a
        # timestamp can reappear on the next page or be skipped entirely.
        f'ORDER BY {order_sql} {direction}, v.transaction_id {direction} '
        'LIMIT :limit OFFSET :skip'
    ), params | {'limit': limit, 'skip': 0 if cursor_sql else skip}).mappings().all()

    return list(rows), int(total)
