"""The entity registry: one declaration describes what the framework needs to serve an entity.

`EntityDescriptor` is the unit of opt-in. It says both what the backend mounts (a generated router,
`router.py`) and what the frontend resolves (`GET <api>/entities/{key}`) — so the two cannot
disagree about whether an entity is standard.

Design constraints this module keeps:

- **The backend owns what is queryable; this says nothing about how it is presented.** Labels,
  column widths, formatters and cell renderers are a frontend concern, never a field here.
- **Registration happens at import, validated at import.** `register_entity()` validates the
  descriptor as part of registering it, which happens when the module declaring it is imported —
  so a broken descriptor fails at startup, not on the first request that reaches it.
- **The registry is frozen once declaring is done.** The consuming module calls
  `freeze_registry()`; a `register_entity()` afterwards raises rather than silently mutating a
  structure request handlers already read from. This is what makes "per-entity work happens once,
  at import" a checked property rather than a comment.
- **One registry per process, which is one registry per module.** A backend serves exactly one
  module, so a module's entities and a process's entities are the same set by construction.
- **No FastAPI import, anywhere but `router.py`.** The query core (`query.py`) and this registry
  must be importable — and exercisable against a real database — with no HTTP framework present:
  a module's in-process test layer does exactly that. `TenantScope` therefore comes from
  `.tenancy`, never from a module's `auth`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Any, Mapping, Optional, Type

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import query as crud
from .tenancy import TenantScope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntityDescriptor:
    """One declaration: what the backend mounts, and what the frontend resolves.

    Everything the generic CRUD core needs that is a property of the TABLE — whether it is
    tenant-scoped, which columns may be filtered or sorted — is read off `model` directly
    (`__tenant_scoped__`, `__filterable__`, `__sortable__`, already mandatory per
    `shared-backend-bug-avoider.md`) and is deliberately NOT duplicated here: a second copy of a
    whitelist is a whitelist that can disagree with the one `crud.py` actually enforces. What IS
    declared here is a property of *serving this entity through the registry* — which schemas
    shape a request/response, which permission resource a (sub-set 2) router checks against, and
    the eager-load plan a read must apply.

    The reuse hooks decided for this plan (`scope_query`, `before_create`, `after_update`,
    `after_delete`, and replacing a single generated endpoint) are sub-set 2's deliverable, not
    sub-set 1's: they are exercised by the router sub-set 2 generates, and adding the fields here
    before anything calls them would be a field with no test that can fail.
    """

    # URL segment / registry key — "items", not "template.items": the module's own slug is
    # applied wherever a permission or a route is actually built (sub-set 2), never baked in here.
    key: str
    model: Type[Any]
    create_schema: Type[BaseModel]
    update_schema: Type[BaseModel]
    read_schema: Type[BaseModel]
    page_schema: Type[BaseModel]
    # Bare resource name a permission is built from, e.g. f"{module_slug}.{permission_resource}:view"
    # (sub-set 2). Bare because `config/authorization.yaml` declares permissions bare too — see
    # `general_bug_avoider.md` on the fully-qualified form being assembled, never hand-written.
    permission_resource: str
    # Optional: an entity may opt out of the audit trail per `general_bug_avoider.md`'s carve-out,
    # even though every MAIN entity must have one by default.
    version_schema: Optional[Type[BaseModel]] = None
    #: The page envelope the history endpoint returns. Required whenever
    #: `version_schema` is set: a versioned entity serves `/history`, and an endpoint
    #: needs the shape of its page as much as the shape of its rows.
    version_page_schema: Optional[Type[BaseModel]] = None
    #: --- The reuse surface ------------------------------------------------------------------
    #:
    #: An escape hatch that costs the whole descriptor to use is not an escape hatch. These let a
    #: module keep the generated endpoints and change the one thing it needs to, instead of
    #: writing a router to alter a single step. Each is optional and defaults to doing nothing.
    #:
    #: The set is chosen from what entity-bound code already did by hand: narrowing what a caller
    #: may see (`scope_query`), deriving or validating fields at write time (`before_create`,
    #: `before_update`), and side effects that must observe the committed row (`after_create`,
    #: `after_update`, `after_delete`). A broader surface would be a plugin framework nobody asked
    #: for; a narrower one sends every real deviation to a hand-written router, which is the
    #: duplication this exists to remove.
    #:
    #: `scope_query(query, scope)` returns a narrowed query. It runs AFTER tenant scoping, never
    #: instead of it — a hook that could widen what a caller sees would make tenancy advisory.
    scope_query: Optional[Callable[[Any, Any], Any]] = None
    before_create: Optional[Callable[[Any, Any], None]] = None
    after_create: Optional[Callable[[Any, Any], None]] = None
    before_update: Optional[Callable[[Any, Any, Any], None]] = None
    after_update: Optional[Callable[[Any, Any], None]] = None
    #: `before_delete(existing, scope)` — the one point at which a rule can refuse a delete before it
    #: happens; `after_delete` sees a row that is already gone.
    before_delete: Optional[Callable[[Any, Any], None]] = None
    after_delete: Optional[Callable[[Any, Any], None]] = None
    # Loader options applied to every read this entity serves — `joinedload(Model.rel)`,
    # `selectinload(...)`, `load_only(...)` — never omittable for a model whose read schema
    # serializes a relationship. Enforcing that a relationship cannot be declared without one is
    # sub-set 4's N+1 guard; this field is the plan that guard reads. Empty is a legitimate answer
    # for an entity with no relationships (e.g. `items` today).
    eager_load: tuple[Any, ...] = ()
    #: True for an entity whose rows may never be created, updated or deleted through these
    #: endpoints — host_app's `permissions`, sourced only from each module's `authorization.yaml`
    #: catalog via the seed job. `build_entity_router` then mounts only the three read routes
    #: (list, get-one, describe); POST/PUT/DELETE are not mounted at all, rather than mounted and
    #: refusing — an entity that is read-only by DESIGN should not have a write route for a
    #: caller to find, whatever it would have answered. `create_schema`/`update_schema` are still
    #: required even when this is true: they cost nothing unused, and a descriptor should not grow
    #: a second shape (optional schemas) for what is already expressed by this one flag.
    read_only: bool = False
    #: --- Four declarations for what a module used to hand-write -------------------------------
    #:
    #: `tenant_from=(ParentModel, 'parent_fk')` — a tenant-scoped child's tenant is its parent's. On
    #: create the parent named by the payload's `parent_fk` is read inside the caller's own scope and
    #: its `tenant_id` is the child's. See `create_entity_row`.
    tenant_from: Optional[tuple[Any, str]] = None
    #: `{query parameter: predicate(query, value) -> query}` — list filters that are not columns. Run
    #: after tenant scoping and `scope_query`; they can only narrow. See `list_entity`.
    derived_filters: Mapping[str, Callable[[Any, str], Any]] = field(default_factory=dict)
    #: Bare resource names that, IN ADDITION to `permission_resource`, open the reads (list, get-one,
    #: describe). Writes keep `permission_resource` alone.
    read_permission_resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_descriptor(self)


#: The generated list endpoint's own QUERY parameters (`router.build_entity_router`). A filterable
#: column is spliced into the same signature under its own name, so a column named like one of these
#: would be two parameters with one name — refused here, by name, when the descriptor is declared,
#: rather than surfacing as `ValueError: duplicate parameter name` from `inspect` when the app mounts.
#: The handler's DEPENDENCIES are underscored (`_db`, `_tenant_scope`) so no column can meet them:
#: host_app's `roles`/`profiles` declare a filterable `scope`, which is how the collision was found.
LIST_QUERY_PARAMETERS = ('skip', 'limit', 'id', 'sort_by', 'sort_order', 'after_id', 'include_total')


def _validate_descriptor(descriptor: EntityDescriptor) -> None:
    """Everything about `descriptor` that is checkable with no database connection.

    Raises `ValueError` naming the field, so a broken descriptor fails the import statement that
    declares it, with a message that says what to fix — not a `KeyError` three calls into a
    request that reached a router sub-set 2 generated from it.
    """
    if not descriptor.key or descriptor.key != descriptor.key.lower() or not descriptor.key.replace('_', '').isalnum():
        raise ValueError(
            f"EntityDescriptor.key {descriptor.key!r} must be a lowercase snake_case URL segment"
        )
    if not descriptor.permission_resource or not descriptor.permission_resource.strip():
        raise ValueError(f"EntityDescriptor({descriptor.key!r}).permission_resource must not be blank")
    if not hasattr(descriptor.model, '__tablename__'):
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}).model ({descriptor.model!r}) is not a mapped "
            f"SQLAlchemy model"
        )
    if not hasattr(descriptor.model, '__tenant_scoped__'):
        # Belt over `scripts/dev/common/check_tenancy_markers.py`: that gate runs at BUILD time
        # over the source file; this one runs at IMPORT time over the actual object, so a
        # descriptor cannot be registered for a model that gate somehow missed.
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}).model {descriptor.model.__name__!r} declares no "
            f"__tenant_scoped__ — every model must (shared-backend-bug-avoider.md)"
        )
    for field_name, schema in (
        ('create_schema', descriptor.create_schema),
        ('update_schema', descriptor.update_schema),
        ('read_schema', descriptor.read_schema),
        ('page_schema', descriptor.page_schema),
    ):
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            raise ValueError(
                f"EntityDescriptor({descriptor.key!r}).{field_name} must be a pydantic BaseModel "
                f"subclass, got {schema!r}"
            )
    if (descriptor.version_schema is None) != (descriptor.version_page_schema is None):
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}) declares one of version_schema / "
            f"version_page_schema and not the other. A versioned entity serves /history and needs "
            f"both; an unversioned one serves neither and needs neither."
        )
    if descriptor.version_page_schema is not None and not (
        isinstance(descriptor.version_page_schema, type)
        and issubclass(descriptor.version_page_schema, BaseModel)
    ):
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}).version_page_schema must be a pydantic "
            f"BaseModel subclass, got {descriptor.version_page_schema!r}"
        )
    if descriptor.version_schema is not None and not (
        isinstance(descriptor.version_schema, type) and issubclass(descriptor.version_schema, BaseModel)
    ):
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}).version_schema must be a pydantic BaseModel "
            f"subclass, got {descriptor.version_schema!r}"
        )
    _validate_declarations(descriptor)
    clash = sorted(set(getattr(descriptor.model, '__filterable__', ())) & set(LIST_QUERY_PARAMETERS))
    if clash:
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}).model declares __filterable__ {clash}, which the "
            f"generated list endpoint already uses as query parameters {LIST_QUERY_PARAMETERS}"
        )


_DERIVED_FILTER_NAME = re.compile(r'^[a-z][a-z0-9_]*$')


def _validate_declarations(descriptor: EntityDescriptor) -> None:
    """The checks for `tenant_from`, `derived_filters` and `read_permission_resources`, by name."""
    key = descriptor.key
    if descriptor.tenant_from is not None:
        try:
            parent_model, parent_fk = descriptor.tenant_from
        except (TypeError, ValueError):
            raise ValueError(
                f"EntityDescriptor({key!r}).tenant_from must be (ParentModel, 'parent_fk')") from None
        if not getattr(descriptor.model, '__tenant_scoped__', False):
            raise ValueError(
                f"EntityDescriptor({key!r}).tenant_from is declared on an entity that is not "
                f"tenant-scoped: a global row has no tenant to derive")
        if not hasattr(parent_model, '__tablename__') or not getattr(parent_model, '__tenant_scoped__', False):
            raise ValueError(
                f"EntityDescriptor({key!r}).tenant_from parent {parent_model!r} must be a mapped, "
                f"tenant-scoped model")
        if not isinstance(parent_fk, str) or parent_fk not in descriptor.create_schema.model_fields:
            raise ValueError(
                f"EntityDescriptor({key!r}).tenant_from names {parent_fk!r}, which is not a field of "
                f"its create_schema: the parent is read from the payload")
    filterable = set(getattr(descriptor.model, '__filterable__', ()))
    for name, predicate in descriptor.derived_filters.items():
        if not _DERIVED_FILTER_NAME.match(name):
            raise ValueError(
                f"EntityDescriptor({key!r}).derived_filters name {name!r} must be a lowercase "
                f"identifier not beginning with an underscore — it becomes a query parameter")
        if name in LIST_QUERY_PARAMETERS or name in filterable:
            raise ValueError(
                f"EntityDescriptor({key!r}).derived_filters name {name!r} is already a list "
                f"parameter or a __filterable__ column: two parameters cannot share one name")
        if not callable(predicate):
            raise ValueError(
                f"EntityDescriptor({key!r}).derived_filters[{name!r}] must be callable, got {predicate!r}")
    names = descriptor.read_permission_resources
    if any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError(f"EntityDescriptor({key!r}).read_permission_resources must hold non-blank names")
    if len(set(names)) != len(names):
        raise ValueError(f"EntityDescriptor({key!r}).read_permission_resources repeats a name: {names}")
    if descriptor.permission_resource in names:
        raise ValueError(
            f"EntityDescriptor({key!r}).read_permission_resources names permission_resource "
            f"{descriptor.permission_resource!r}, which already opens reads")


# ---------------------------------------------------------------------------
# The registry: a module-level dict, written only by `register_entity()`, read by everything else.
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, EntityDescriptor] = {}
_FROZEN = False


def register_entity(descriptor: EntityDescriptor) -> EntityDescriptor:
    """Add `descriptor` to the registry. Called at import time by the module that declares it.

    Returns the descriptor unchanged, so a declaring module can write
    `ITEMS = register_entity(EntityDescriptor(...))` and keep a module-level name for its own use
    (tests, sub-set 2's router generator) without a second registry lookup.

    Checked in this order — a colliding KEY before a frozen REGISTRY — so the two failures stay
    distinguishable after startup too: re-registering an existing key always reports the collision
    (the more specific, more actionable fact), and only a genuinely NEW key reaching this function
    after freeze reports that the registry is closed.
    """
    if descriptor.key in _REGISTRY:
        raise ValueError(f"entity {descriptor.key!r} is already registered")
    if _FROZEN:
        raise RuntimeError(
            f"cannot register {descriptor.key!r}: the entity registry is frozen. Entities are "
            f"registered at import time, before this package finishes importing — see "
            f"freeze_registry()."
        )
    _REGISTRY[descriptor.key] = descriptor
    logger.debug('Entity registered: %s -> %s', descriptor.key, descriptor.model.__name__)
    return descriptor


def freeze_registry() -> None:
    """Close the registry to further writes.

    Called exactly once, below, after every descriptor submodule of this package has been
    imported — never per request, and never by a reader (a router, a test) that only wants to
    consult the registry. A second call raises, on the same reasoning `register_entity` raises
    after freezing: freezing is a one-way transition, not a flag to be waved twice.
    """
    global _FROZEN
    if _FROZEN:
        raise RuntimeError('entity registry is already frozen')
    _FROZEN = True
    logger.info(
        'Entity registry frozen with %d entit%s: %s',
        len(_REGISTRY), 'y' if len(_REGISTRY) == 1 else 'ies', sorted(_REGISTRY),
    )


def is_registry_frozen() -> bool:
    return _FROZEN


def get_entity_descriptor(key: str) -> EntityDescriptor:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(f"no entity registered under {key!r}; registered: {sorted(_REGISTRY)}") from None


def all_entity_descriptors() -> MappingProxyType:
    """A read-only view over the registry. Callers must not mutate what this returns."""
    return MappingProxyType(_REGISTRY)


# ---------------------------------------------------------------------------
# Descriptor-driven query core: the same generic functions `crud.py` already exposes for ANY
# model, closed over ONE descriptor instead of a bare model — so the eager-load plan applies
# uniformly regardless of who calls them (a test today; sub-set 2's generated router next).
# ---------------------------------------------------------------------------

def list_entity(db: Session, descriptor: EntityDescriptor, scope: Optional[TenantScope],
                derived: Optional[Mapping[str, str]] = None, **kwargs: Any):
    """`crud.list_entities` for `descriptor.model`, with its eager-load plan enforced.

    Enforced, not offered: there is no parameter here that skips `descriptor.eager_load` — a
    caller that forgot it is exactly the N+1 sub-set 4 guards against.

    `scope_query` narrows further, and only further: it is handed the query AFTER tenant scoping
    has been applied, so a hook cannot widen what a caller may see. A hook that could would make
    tenancy advisory, which is the one property here that may not be optional.
    """
    narrow = descriptor.scope_query
    if derived:
        unknown = sorted(set(derived) - set(descriptor.derived_filters))
        if unknown:
            raise ValueError(f'unknown derived filter(s) for {descriptor.key}: {unknown}')
        applied = [(descriptor.derived_filters[name], value) for name, value in derived.items()]
        scope_query = descriptor.scope_query

        def combined(query, caller_scope):
            """`scope_query` first, then each derived filter: all after the tenant predicate."""
            if scope_query is not None:
                query = scope_query(query, caller_scope)
            for predicate, value in applied:
                query = predicate(query, value)
            return query

        narrow = combined

    return crud.list_entities(
        db, descriptor.model, scope, options=descriptor.eager_load, narrow=narrow, **kwargs,
    )


def get_entity_row(
    db: Session, descriptor: EntityDescriptor, entity_id: int, scope: Optional[TenantScope],
    *, for_write: bool = False,
):
    """`crud.get_entity` for `descriptor.model`, with its eager-load plan enforced."""
    return crud.get_entity(
        db, descriptor.model, entity_id, scope, narrow=descriptor.scope_query,
        for_write=for_write, options=descriptor.eager_load,
    )


def create_entity_row(db: Session, descriptor: EntityDescriptor, payload: BaseModel,
                      scope: Optional[TenantScope]):
    """`crud.create_entity` for `descriptor.model`, with the create hooks around the insert.

    Takes the schema instance itself (not a dict): `crud.create_entity` calls
    `payload.model_dump(exclude_unset=True)` internally, exactly as the hand-written `create_item`
    did.

    `before_create(payload, scope)` sees the payload BEFORE the insert — the point at which a
    derived or validated field must be set, and the only one where a rule can refuse the write
    before it happens. `after_create(row, scope)` sees the row once it EXISTS, which is what a side
    effect needing the id the insert assigned requires: host_app's `users` creates the Authentik
    identity beside the row, and with no `after_create` the only way to say so was a hand-written
    route — the duplication the descriptor exists to remove.

    Both were declared on the descriptor and left uncalled, so the two-part shape `update_entity_row`
    already had was missing from the create path. The registry suite
    (`backend/TESTS/test_entity_registry.py`) pins the order and what each hook is handed.
    """
    if descriptor.before_create is not None:
        descriptor.before_create(payload, scope)
    row = crud.create_entity(
        db, descriptor.model, payload, scope, options=descriptor.eager_load,
        tenant_id=_tenant_from_parent(db, descriptor, payload, scope),
    )
    if descriptor.after_create is not None:
        descriptor.after_create(row, scope)
    return row


def _tenant_from_parent(db: Session, descriptor: EntityDescriptor, payload: BaseModel,
                        scope: Optional[TenantScope]) -> Optional[int]:
    """The tenant `descriptor.tenant_from` derives for this payload, or `None` when not declared.

    The parent is read INSIDE the caller's own scope — the write GUC, so row-level security hides
    every row outside the caller's tenants — and never by bare id: otherwise a caller could file a
    child under another tenant's parent by naming its id. Every failure is the tenant-scope error the
    write path already answers `403` to: a missing `parent_fk`, a parent that does not exist or is not
    visible (the two are deliberately indistinguishable), and, in `crud.create_entity`, a payload
    tenant that disagrees. The derived tenant must still be one of the caller's own.
    """
    if descriptor.tenant_from is None:
        return None
    parent_model, parent_fk = descriptor.tenant_from
    parent_id = getattr(payload, parent_fk, None)
    if parent_id is None:
        raise crud.TenantScopeError(f'{parent_fk} is required to derive the tenant')
    crud.apply_tenant_guc(db, scope, for_write=True)
    parent = db.query(parent_model).filter(parent_model.id == parent_id).first()
    if parent is None:
        raise crud.TenantScopeError(f'{parent_fk} does not name a row within the caller\'s scope')
    return int(parent.tenant_id)


def update_entity_row(db: Session, descriptor: EntityDescriptor, existing: Any, payload: BaseModel,
                      scope: Optional[TenantScope]):
    """`crud.update_entity` against an already-loaded row.

    `before_update(existing, payload, scope)` sees the row as it stands and the change about to be
    applied — the only point at which both are available, which is what a rule like "status may not
    go backwards" needs.
    """
    if descriptor.before_update is not None:
        descriptor.before_update(existing, payload, scope)
    row = crud.update_entity(db, existing, payload, scope, options=descriptor.eager_load)
    if descriptor.after_update is not None:
        descriptor.after_update(row, scope)
    return row


#: PostgreSQL's SQLSTATE for a foreign-key violation.
_FOREIGN_KEY_VIOLATION = '23503'


class StillReferenced(Exception):
    """A delete the datamodel restricts: another row still points at this one.

    A plain exception, NOT an `HTTPException`: only the router imports fastapi (the core must stay
    importable — and testable — without it), so the generated `DELETE` turns this into `409 Conflict`
    and a module's hand-written caller does the same. `str(error)` is the message for the caller; it
    names the referencing table and nothing else of the database — not the constraint, the key or the
    SQL.
    """

    def __init__(self, key: str, blocker: str | None):
        self.key = key
        self.blocker = blocker
        super().__init__(
            f'{key} is still referenced by {blocker} and cannot be deleted' if blocker
            else f'{key} is still referenced by other rows and cannot be deleted'
        )


def foreign_key_blocker(error: IntegrityError) -> tuple[bool, str | None]:
    """`(is_a_foreign_key_violation, the_referencing_table_if_known)` for a database error.

    Only SQLSTATE 23503 is a refusal the caller can act on; a NOT NULL or CHECK failure is not, and
    stays the server error it was. PostgreSQL reports the REFERENCING table as `diag.table_name`
    (measured: deleting an item that has sub_items names `sub_items`), and the same table in the
    detail line, which is the fallback when a driver does not fill `diag`.
    """
    original = getattr(error, 'orig', None)
    if getattr(original, 'pgcode', None) != _FOREIGN_KEY_VIOLATION:
        return False, None
    diag = getattr(original, 'diag', None)
    table = getattr(diag, 'table_name', None)
    if not table:
        found = re.search(r'referenced from table "([^"]+)"', getattr(diag, 'message_detail', None) or str(original))
        table = found.group(1) if found else None
    return True, table


def delete_entity_row(db: Session, descriptor: EntityDescriptor, existing: Any,
                      scope: TenantScope | None = None) -> None:
    """`crud.delete_entity` against an already-loaded row.

    `after_delete(row, scope)` receives the row as it was — read anything needed from it before
    calling, since the row is gone once this returns.

    A row another row still points at is not deleted: the transaction is rolled back and the caller
    gets `StillReferenced`, which the router answers as 409. Any other database failure propagates
    unchanged.
    """
    if descriptor.before_delete is not None:
        descriptor.before_delete(existing, scope)
    try:
        crud.delete_entity(db, existing)
    except IntegrityError as error:
        db.rollback()
        is_foreign_key, blocker = foreign_key_blocker(error)
        if not is_foreign_key:
            raise
        raise StillReferenced(descriptor.key, blocker) from None
    if descriptor.after_delete is not None:
        descriptor.after_delete(existing, scope)


# ---------------------------------------------------------------------------
# Declaring is the module's job, not the framework's
# ---------------------------------------------------------------------------
# A module's descriptor submodules register themselves as a side effect of being imported — this
# is what "validated at import" means in practice. The module imports each one and then calls
# `freeze_registry()`; nothing is frozen here, because this package does not know when a module has
# finished declaring. One registry exists per PROCESS, and a backend is one module's process, so
# "this module's registry" and "this process's registry" are the same object by construction.


__all__ = [
    'EntityDescriptor',
    'register_entity',
    'freeze_registry',
    'is_registry_frozen',
    'get_entity_descriptor',
    'all_entity_descriptors',
    'list_entity',
    'get_entity_row',
    'create_entity_row',
    'update_entity_row',
    'delete_entity_row',
    'StillReferenced',
    'foreign_key_blocker',
    'mount_entity_routers',
]


def mount_entity_routers(app, platform, prefix: str = '/api') -> list[str]:
    """Mount a generated router for EVERY registered entity and association. Returns the keys mounted.

    Unconditional by contract: there is no mode on a descriptor and nothing to opt into, so a
    module that declares an entity or an association has its endpoints without asking. What a
    maintainer chooses is whether to call them.

    Associations are mounted here rather than by a second call because they are the same act — one
    module declares what it serves, and the app mounts all of it — and because a module that
    declared an association but forgot to mount it would have a registry entry nothing served.

    `platform` is the module's `Platform` (see `platform.py`): how THIS backend opens a session,
    checks a permission and resolves a tenant scope. The framework generates the endpoints; it does
    not know how any particular module authenticates.

    Imported here rather than at module top so this package stays importable without FastAPI —
    the in-process test layer depends on that, and so does anything that wants the registry without
    the web stack. `associations` is imported here for the same reason, and because it imports this
    module: a top-level import would be a cycle.
    """
    from .associations import all_association_descriptors
    from .router import build_association_router, build_descriptor_router, build_entity_router

    app.include_router(build_descriptor_router(platform), prefix=prefix)
    mounted = []
    for key, descriptor in all_entity_descriptors().items():
        app.include_router(build_entity_router(descriptor, platform), prefix=prefix)
        mounted.append(key)
    for key, descriptor in all_association_descriptors().items():
        app.include_router(build_association_router(descriptor, platform), prefix=prefix)
        mounted.append(key)
    return mounted
