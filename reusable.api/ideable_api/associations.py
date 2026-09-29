"""Associations: the link tables a module declares, and the query side that serves them.

An **association** is a row of a link table addressed by the rows it links — a role's permission, a
profile's role, a user's grant. It is not an entity: it has no id of its own in the API (the
synthetic `<left>__<right>` id is what makes it addressable without giving the link table's primary
key meaning), its text comes from the rows it joins, and its permission is its own. A module
declares one with an `AssociationDescriptor` and `ideable_api.router` generates its endpoints, on
the same terms as an entity: validated at construction, registered at import, frozen with the entity
registry, mounted by `mount_entity_routers`.

The contract is stated in `modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md`
§ *Associations are declared, not written*; this module is its implementation.

Three properties this module keeps, each for a reason:

- **No FastAPI, and no import of a module's `app` package.** The query side is exercisable against a
  real database with no web stack present — a module's in-process test layer does exactly that — and
  the framework runs in EVERY backend, so it cannot name one. A rule a module has over its own link
  tables goes in a hook on its descriptor, never here. Its own refusals are `AssociationError`,
  which the generated router answers as an HTTP error, exactly as `query.TenantScopeError` is.
- **The link table's own primary key is never exposed.** The synthetic id is the row's API address,
  and its arity follows the descriptor's key count: `<left>__<right>`, or
  `<left>__<right>__<scope>` for a spec with a third key.
- **The text is joined server-side, under two names.** `text_fields` publishes the DOTTED names a
  caller filters and sorts by (`permission.name`), because a caller has to say which side of the join
  it means; `response_fields` publishes the CLEAN names a row carries (`permission`), because a
  response is per row and a table column wants `permission`, not `permission.name`. The two cannot be
  derived from one another, so the map is explicit.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel

from . import entities as registry

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DELIMITER = "__"

#: The refusals the framework itself raises, each carrying the status the generated router answers
#: with. A module's hooks raise whatever they like — host_app's raise `HTTPException` — and the
#: router lets those through untouched; this type exists so the query side needs no web stack.
NOT_FOUND = 404
CONFLICT = 409
UNPROCESSABLE = 422


class AssociationError(Exception):
    """A refusal from the association query side, to be answered as `status_code` + `detail`."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# The synthetic id: how an association row is addressed
# ---------------------------------------------------------------------------

def synthetic_id(*keys: int) -> str:
    """`<left>__<right>`, or `<left>__<right>__<scope>` for a spec with a third key."""
    return DELIMITER.join(str(k) for k in keys)


def parse_synthetic_id(association_id: str, arity: int = 2) -> tuple[int, ...]:
    parts = association_id.split(DELIMITER)
    if len(parts) != arity:
        raise ValueError("Invalid association id")
    return tuple(int(p) for p in parts)


def _keys_or_404(spec: "AssociationDescriptor", association_id: str) -> tuple[int, ...]:
    """Parse the id, answering 404 rather than 400 when it is not one.

    An id that cannot be parsed names an association that cannot exist, so "not found" is both true
    and the answer clients already handle. A 400 here would be a contract change dressed up as
    stricter validation. A two-part id sent to a three-key association is one of those: it names no
    grant.
    """
    try:
        return parse_synthetic_id(association_id, len(spec.key_cols))
    except ValueError:
        raise AssociationError(NOT_FOUND, "Association not found") from None


# ---------------------------------------------------------------------------
# The descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssociationDescriptor:
    """One declaration: what the framework needs to serve an association's endpoints.

    Everything that differs between two association endpoints is here and nothing else. The key
    columns, the models they point at and the text the rows carry are the shape; the hooks are where
    a module's own rules go, because a rule that spans the link table and the rows it links is the
    module's and the framework knows nothing of any module's authorization model.
    """

    #: URL segment / registry key — `as_user_profile`, not `hostapp.as_user_profile`.
    key: str
    #: The link table. Must be mapped and must declare `__tenant_scoped__ = False`.
    model: Any
    left_col: str
    right_col: str
    left_model: Any
    right_model: Any
    #: searchable/sortable API field name -> value from (left_row, right_row). Dotted names.
    text_fields: Dict[str, Callable[[Any, Any], str]]
    #: RESPONSE field name -> a key of `text_fields` (or `scope_text_fields`), for the joined text
    #: the client renders. Explicit because it cannot be derived: `permission.name` and `role.role`
    #: would both want `name`.
    response_fields: Dict[str, str] = field(default_factory=dict)
    left_label: str = "left"        # used in the 404 that names a missing endpoint
    right_label: str = "right"
    #: An optional THIRD key — the tenant a grant applies in (`user_profiles.tenant_fk`). A
    #: descriptor that declares it is addressed by `<left>__<right>__<scope>`; one that does not
    #: keeps the two-part id.
    scope_col: Optional[str] = None
    scope_model: Any = None
    scope_label: str = "scope"
    #: searchable/sortable field -> value from the scope row, beside `text_fields`.
    scope_text_fields: Dict[str, Callable[[Any], str]] = field(default_factory=dict)
    #: The schemas this association is served with — the module's, like an entity's.
    create_schema: Any = None
    update_schema: Any = None
    read_schema: Any = None
    page_schema: Any = None
    #: Bare resource name a permission is built from, e.g. `profile_to_user_assignments`; the
    #: module's slug is added by the router.
    permission_resource: str = ""
    #: --- The hooks ---------------------------------------------------------------------------
    #:
    #: `narrow(db)` returns a row predicate or None — the caller's administration scope. It is
    #: resolved once per request inside `list_page`/`get_one`, so no call path can skip a declared
    #: one, and it NARROWS only: it is a predicate over rows the query already produced.
    narrow: Optional[Callable[[Any], Optional[Callable[[Dict[str, Any]], bool]]]] = None
    #: `validate(db, keys)` before a create or a move lands, after the endpoint rows are found. It
    #: raises the error that names a broken rule.
    validate: Optional[Callable[[Any, Dict[str, int]], None]] = None
    before_create: Optional[Callable[[Any, Dict[str, int]], None]] = None
    before_update: Optional[Callable[[Any, Dict[str, int], Dict[str, int]], None]] = None
    before_delete: Optional[Callable[[Any, Dict[str, int]], None]] = None
    after_create: Optional[Callable[[Any, Any], None]] = None
    after_update: Optional[Callable[[Any, Any], None]] = None
    after_delete: Optional[Callable[[Any, Dict[str, int]], None]] = None

    def __post_init__(self) -> None:
        _validate_descriptor(self)

    @property
    def key_cols(self) -> tuple[str, ...]:
        return (self.left_col, self.right_col) + ((self.scope_col,) if self.scope_col else ())

    @property
    def key_models(self) -> tuple[Any, ...]:
        return (self.left_model, self.right_model) + ((self.scope_model,) if self.scope_col else ())

    @property
    def key_labels(self) -> tuple[str, ...]:
        return (self.left_label, self.right_label) + ((self.scope_label,) if self.scope_col else ())

    @property
    def text_names(self) -> tuple[str, ...]:
        return tuple(self.text_fields) + tuple(self.scope_text_fields)


def _validate_descriptor(descriptor: AssociationDescriptor) -> None:
    """Everything about `descriptor` that is checkable with no database connection.

    Raises `ValueError` naming the field, so a broken descriptor fails the import statement that
    declares it rather than the request that reaches it — the same property `EntityDescriptor` has,
    for the same reason.
    """
    if (not descriptor.key or descriptor.key != descriptor.key.lower()
            or not descriptor.key.replace('_', '').isalnum()):
        raise ValueError(
            f"AssociationDescriptor.key {descriptor.key!r} must be a lowercase snake_case URL segment"
        )
    if not descriptor.permission_resource or not descriptor.permission_resource.strip():
        raise ValueError(
            f"AssociationDescriptor({descriptor.key!r}).permission_resource must not be blank"
        )
    if '.' in descriptor.permission_resource:
        raise ValueError(
            f"AssociationDescriptor({descriptor.key!r}).permission_resource "
            f"({descriptor.permission_resource!r}) must be bare: the module slug is added by the router"
        )
    for label, model in (('model', descriptor.model), ('left_model', descriptor.left_model),
                         ('right_model', descriptor.right_model)):
        if not hasattr(model, '__tablename__'):
            raise ValueError(
                f"AssociationDescriptor({descriptor.key!r}).{label} ({model!r}) is not a mapped "
                f"SQLAlchemy model"
            )
    if not hasattr(descriptor.model, '__tenant_scoped__'):
        raise ValueError(
            f"AssociationDescriptor({descriptor.key!r}).model {descriptor.model.__name__!r} declares "
            f"no __tenant_scoped__ — every model must (shared-backend-bug-avoider.md)"
        )
    if getattr(descriptor.model, '__tenant_scoped__'):
        # Fail closed: the association query side applies no tenant predicate, so a declaration the
        # framework would serve unscoped must fail the line that builds it rather than the tenant it
        # leaks. Serving a tenant-scoped link table is a framework change of its own.
        raise ValueError(
            f"AssociationDescriptor({descriptor.key!r}).model {descriptor.model.__name__!r} declares "
            f"__tenant_scoped__ = True, which the association query side does not apply — narrow the "
            f"rows with a `narrow` hook, or serve it as an entity"
        )
    if not descriptor.scope_col and (descriptor.scope_model is not None
                                     or descriptor.scope_text_fields):
        raise ValueError(
            f"AssociationDescriptor({descriptor.key!r}) declares scope_model/scope_text_fields "
            f"with no scope_col: a third key is declared all together or not at all"
        )
    for column in descriptor.key_cols:
        # The key columns are the LINK table's: the endpoint models are what they point at, and are
        # joined by their own `id`, which is what the row builder reads.
        if not hasattr(descriptor.model, column):
            raise ValueError(
                f"AssociationDescriptor({descriptor.key!r}): {descriptor.model.__name__!r} has no "
                f"key column {column!r}"
            )
    for model in descriptor.key_models:
        if not hasattr(model, 'id'):
            raise ValueError(
                f"AssociationDescriptor({descriptor.key!r}): {model.__name__!r} has no `id`, which "
                f"is how a link row's keys are joined to the text they name"
            )
    clash = sorted(set(descriptor.key_cols) & set(registry.LIST_QUERY_PARAMETERS))
    if clash:
        raise ValueError(
            f"AssociationDescriptor({descriptor.key!r}) declares key columns {clash}, which the "
            f"generated list endpoint already uses as query parameters "
            f"{registry.LIST_QUERY_PARAMETERS}"
        )
    for name in descriptor.text_fields:
        if '.' not in name:
            raise ValueError(
                f"AssociationDescriptor({descriptor.key!r}).text_fields names {name!r} without a "
                f"dotted side (e.g. 'role.role'): a caller filtering has to say which side it means"
            )
    for response_name, source in descriptor.response_fields.items():
        if source not in descriptor.text_names:
            raise ValueError(
                f"AssociationDescriptor({descriptor.key!r}).response_fields maps {response_name!r} to "
                f"{source!r}, which no text_field or scope_text_field produces"
            )
    for field_name, schema in (('create_schema', descriptor.create_schema),
                               ('update_schema', descriptor.update_schema),
                               ('read_schema', descriptor.read_schema),
                               ('page_schema', descriptor.page_schema)):
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                f"AssociationDescriptor({descriptor.key!r}).{field_name} must be a pydantic "
                f"BaseModel subclass, got {schema!r}"
            )


# ---------------------------------------------------------------------------
# The registry: written only by `register_association()`, frozen with the entity registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, AssociationDescriptor] = {}


def register_association(descriptor: AssociationDescriptor) -> AssociationDescriptor:
    """Add `descriptor` to the registry. Called at import time by the module that declares it.

    Returns the descriptor unchanged, so a declaring module can write
    `AS_USER_PROFILE = register_association(AssociationDescriptor(...))` and keep a module-level name
    for its own use (tests) without a second registry lookup.

    Checked in the same order `register_entity` checks — a colliding KEY before a frozen registry —
    so the two failures stay distinguishable after startup too. **Frozen with the ENTITY registry**:
    one `freeze_registry()` closes both, because a module declares its entities and its associations
    together, before the app serves anything.
    """
    if descriptor.key in _REGISTRY:
        raise ValueError(f"association {descriptor.key!r} is already registered")
    if registry.is_registry_frozen():
        raise RuntimeError(
            f"cannot register {descriptor.key!r}: the entity registry is frozen, and associations "
            f"are frozen with it. Declarations happen at import time, before freeze_registry() — "
            f"see app/entities/__init__.py."
        )
    _REGISTRY[descriptor.key] = descriptor
    logger.debug('Association registered: %s -> %s', descriptor.key, descriptor.model.__name__)
    return descriptor


def get_association_descriptor(key: str) -> AssociationDescriptor:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"no association registered under {key!r}; registered: {sorted(_REGISTRY)}"
        ) from None


def all_association_descriptors() -> MappingProxyType:
    """A read-only view over the registry. Callers must not mutate what this returns."""
    return MappingProxyType(_REGISTRY)


# ---------------------------------------------------------------------------
# The query side: the shared helpers, then the rows they are applied to
# ---------------------------------------------------------------------------

def parse_filters_param(raw_filters: Optional[str]) -> Dict[str, str]:
    """The `filters` JSON query parameter as `{dotted name: needle}`, dropping what it cannot use."""
    if not raw_filters:
        return {}
    try:
        parsed = json.loads(raw_filters)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid filters payload: %s", raw_filters)
        return {}
    if not isinstance(parsed, dict):
        return {}
    clean: Dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped:
            clean[key] = stripped
    return clean


def _extract_filter_value(item: dict, key: str, accessor: Optional[Callable[[dict], Any]]) -> str:
    value: Any = accessor(item) if accessor else item.get(key)
    if value is None:
        return ""
    return str(value).lower()


def apply_text_filters(
    items: list[dict],
    filters: Dict[str, str],
    accessors: Optional[Dict[str, Callable[[dict], Any]]] = None,
) -> list[dict]:
    """Keep the rows whose text contains every needle. A key with no accessor matches nothing."""
    if not filters:
        return items
    result = items
    accessors = accessors or {}
    for key, needle in filters.items():
        accessor = accessors.get(key)
        normalized = needle.lower()
        result = [item for item in result if normalized in _extract_filter_value(item, key, accessor)]
    return result


def sort_items(
    items: list[dict],
    sort_by: Optional[str],
    sort_order: Optional[str],
    accessors: Optional[Dict[str, Callable[[dict], Any]]] = None,
) -> list[dict]:
    """Sort by a published name; an unpublished one reorders nothing (every row compares equal)."""
    if not sort_by:
        return items
    reverse = (sort_order or "").lower() == "desc"
    accessors = accessors or {}
    accessor = accessors.get(sort_by)

    def _key(item: dict):
        value = accessor(item) if accessor else item.get(sort_by)
        return value if value is not None else ""

    return sorted(items, key=_key, reverse=reverse)


def _rows(db: "Session", spec: AssociationDescriptor) -> List[dict]:
    """Every row of the link table, joined to the text of the rows it links.

    In memory rather than as one SQL join, because an association's text is a function of two or
    three rows the descriptor names — not a column — and because these tables are the size of an
    authorization catalogue. The accessors are keyed on the DOTTED names, which is what a caller
    filters and sorts by; `response_fields` repeats the same values under the names a row carries.
    """
    by_id = [{r.id: r for r in db.query(model).all()} for model in spec.key_models]
    out: List[dict] = []
    for assoc in db.query(spec.model).all():
        keys = tuple(getattr(assoc, col) for col in spec.key_cols)
        rows = [table.get(key) for table, key in zip(by_id, keys)]
        if any(row is None for row in rows):
            # A link row whose endpoint is gone is a referential-integrity violation the FKs make
            # impossible; skipping silently would hide it if it ever happened.
            continue
        item: Dict[str, Any] = {"id": synthetic_id(*keys), **dict(zip(spec.key_cols, keys))}
        for name, fn in spec.text_fields.items():
            item[f"_{name}"] = fn(rows[0], rows[1])
        for name, scope_fn in spec.scope_text_fields.items():
            item[f"_{name}"] = scope_fn(rows[2])
        for response_name, source in spec.response_fields.items():
            item[response_name] = item.get(f"_{source}", "")
        out.append(item)
    return out


def _accessors(spec: AssociationDescriptor) -> Dict[str, Callable[[Dict[str, Any]], str]]:
    def accessor(field: str) -> Callable[[Dict[str, Any]], str]:
        # A named factory rather than `lambda item, f=field:`: the default-argument binding works at
        # runtime but types as a two-argument callable, which is not what the helpers take.
        return lambda item: item.get(f"_{field}", "")

    return {field: accessor(field) for field in spec.text_names}


def _narrowed(spec: AssociationDescriptor, db: "Session", items: List[dict]) -> List[dict]:
    """The caller's administration scope, as a row predicate — resolved here, never by a caller.

    Resolved inside the two read paths rather than handed in, so a route cannot forget it: a row the
    scope rejects is in no page and not in the total, and is a 404 by id.
    """
    if spec.narrow is None:
        return items
    keep = spec.narrow(db)
    return items if keep is None else [item for item in items if keep(item)]


def list_page(
    db: "Session",
    spec: AssociationDescriptor,
    *,
    skip: int,
    limit: int,
    id: Optional[str] = None,
    left_fk: Optional[int] = None,
    right_fk: Optional[int] = None,
    scope_fk: Optional[int] = None,
    filters: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> dict:
    """One page of an association, in the envelope the `@ideable/ui` association view reads."""
    items = _narrowed(spec, db, _rows(db, spec))
    if left_fk is not None:
        items = [i for i in items if i[spec.left_col] == left_fk]
    if right_fk is not None:
        items = [i for i in items if i[spec.right_col] == right_fk]
    if scope_fk is not None and spec.scope_col:
        items = [i for i in items if i[spec.scope_col] == scope_fk]
    if id is not None:
        items = [i for i in items if i["id"] == id]

    accessors = _accessors(spec)
    items = apply_text_filters(items, parse_filters_param(filters), accessors)
    total = len(items)
    items = sort_items(items, sort_by, sort_order, accessors)
    return {
        "items": items[skip : skip + limit],
        "total": total,
        "page": (skip // limit) + 1 if limit > 0 else 1,
        "size": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1,
    }


def get_one(db: "Session", spec: AssociationDescriptor, association_id: str) -> dict:
    keys = _keys_or_404(spec, association_id)
    for item in _narrowed(spec, db, _rows(db, spec)):
        if tuple(item[col] for col in spec.key_cols) == keys:
            return item
    raise AssociationError(NOT_FOUND, "Association not found")


def find(db: "Session", spec: AssociationDescriptor, keys: tuple[int, ...]):
    """The link row itself (not the joined text), or None."""
    query = db.query(spec.model)
    for col, key in zip(spec.key_cols, keys):
        query = query.filter(getattr(spec.model, col) == key)
    return query.first()


def _require_endpoints(db: "Session", spec: AssociationDescriptor, keys: tuple[int, ...]) -> None:
    for model, label, key in zip(spec.key_models, spec.key_labels, keys):
        if db.query(model).filter(model.id == key).first() is None:
            raise AssociationError(NOT_FOUND, f"{label} not found")


def _validated(db: "Session", spec: AssociationDescriptor, keys: tuple[int, ...]) -> None:
    _require_endpoints(db, spec, keys)
    if spec.validate is not None:
        spec.validate(db, dict(zip(spec.key_cols, keys)))


def _as_dict(spec: AssociationDescriptor, keys: tuple[int, ...]) -> dict:
    """The response a write returns: the id and the keys, and no joined text.

    A write answers with the row it wrote, and the joined text is a READ's convenience: the pages
    re-read the list after a write, so joining the text here would be work nobody reads. Kept as it
    was, because it is part of the wire contract the frontend services already speak.
    """
    return {"id": synthetic_id(*keys), **dict(zip(spec.key_cols, keys))}


def create_association(db: "Session", spec: AssociationDescriptor, left_id: int, right_id: int,
                       scope_id: Optional[int] = None) -> dict:
    """Insert one association, running the descriptor's create hooks around the insert.

    `before_create(db, keys)` runs first — it is where a rule refuses a write the caller may not
    make — then the endpoint rows are checked to exist and `validate` runs, then the insert, the
    flush and `after_create(db, row)`. The caller commits.
    """
    keys: tuple[int, ...] = (left_id, right_id)
    if spec.scope_col:
        if scope_id is None:
            raise AssociationError(UNPROCESSABLE, f"{spec.scope_col} is required")
        keys += (scope_id,)
    if spec.before_create is not None:
        spec.before_create(db, dict(zip(spec.key_cols, keys)))
    _validated(db, spec, keys)
    if find(db, spec, keys) is not None:
        raise AssociationError(CONFLICT, "Association already exists")
    db.add(spec.model(**dict(zip(spec.key_cols, keys))))
    db.flush()
    if spec.after_create is not None:
        # The row is FLUSHED, not committed: an `after_*` hook that needs the row's id has it, and a
        # hook that raises leaves nothing committed. The commit is the last step, as it was when the
        # routers owned this code.
        spec.after_create(db, find(db, spec, keys))
    db.commit()
    return _as_dict(spec, keys)


def update_association(
    db: "Session",
    spec: AssociationDescriptor,
    association_id: str,
    new_left: Optional[int],
    new_right: Optional[int],
    new_scope: Optional[int] = None,
) -> dict:
    """Move one association: the keys not sent keep their value, and the target is validated.

    A move is a removal and a create, so both halves run: `before_update(db, existing_keys,
    target_keys)` sees them, and `validate` runs on the target. An unchanged target is a no-op.
    """
    keys = _keys_or_404(spec, association_id)
    row = find(db, spec, keys)
    if row is None:
        raise AssociationError(NOT_FOUND, "Association not found")

    wanted = (new_left, new_right) + ((new_scope,) if spec.scope_col else ())
    target: tuple[int, ...] = tuple(new if new is not None else old for old, new in zip(keys, wanted))
    if target == keys:
        return _as_dict(spec, keys)

    if spec.before_update is not None:
        spec.before_update(db, dict(zip(spec.key_cols, keys)), dict(zip(spec.key_cols, target)))
    _validated(db, spec, target)
    if find(db, spec, target) is not None:
        raise AssociationError(CONFLICT, "Association already exists")

    for col, key in zip(spec.key_cols, target):
        setattr(row, col, key)
    db.add(row)
    db.flush()
    if spec.after_update is not None:
        spec.after_update(db, row)
    db.commit()
    return _as_dict(spec, target)


def delete_association(db: "Session", spec: AssociationDescriptor, association_id: str) -> None:
    """Remove one association: `before_delete(db, keys)` may still refuse it, `after_delete` sees
    the keys of a row that is already gone."""
    keys = _keys_or_404(spec, association_id)
    row = find(db, spec, keys)
    if row is None:
        raise AssociationError(NOT_FOUND, "Association not found")
    if spec.before_delete is not None:
        spec.before_delete(db, dict(zip(spec.key_cols, keys)))
    db.delete(row)
    db.flush()
    if spec.after_delete is not None:
        spec.after_delete(db, dict(zip(spec.key_cols, keys)))
    db.commit()


__all__ = [
    'AssociationDescriptor',
    'AssociationError',
    'all_association_descriptors',
    'apply_text_filters',
    'create_association',
    'delete_association',
    'find',
    'get_association_descriptor',
    'get_one',
    'list_page',
    'parse_filters_param',
    'parse_synthetic_id',
    'register_association',
    'sort_items',
    'synthetic_id',
    'update_association',
]
