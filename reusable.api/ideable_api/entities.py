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
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Any, Optional, Type

from pydantic import BaseModel
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
    clash = sorted(set(getattr(descriptor.model, '__filterable__', ())) & set(LIST_QUERY_PARAMETERS))
    if clash:
        raise ValueError(
            f"EntityDescriptor({descriptor.key!r}).model declares __filterable__ {clash}, which the "
            f"generated list endpoint already uses as query parameters {LIST_QUERY_PARAMETERS}"
        )


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
                **kwargs: Any):
    """`crud.list_entities` for `descriptor.model`, with its eager-load plan enforced.

    Enforced, not offered: there is no parameter here that skips `descriptor.eager_load` — a
    caller that forgot it is exactly the N+1 sub-set 4 guards against.

    `scope_query` narrows further, and only further: it is handed the query AFTER tenant scoping
    has been applied, so a hook cannot widen what a caller may see. A hook that could would make
    tenancy advisory, which is the one property here that may not be optional.
    """
    return crud.list_entities(
        db, descriptor.model, scope, options=descriptor.eager_load,
        narrow=descriptor.scope_query, **kwargs,
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
    row = crud.create_entity(db, descriptor.model, payload, scope, options=descriptor.eager_load)
    if descriptor.after_create is not None:
        descriptor.after_create(row, scope)
    return row


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


def delete_entity_row(db: Session, descriptor: EntityDescriptor, existing: Any,
                      scope: TenantScope | None = None) -> None:
    """`crud.delete_entity` against an already-loaded row.

    `after_delete(row, scope)` receives the row as it was — read anything needed from it before
    calling, since the row is gone once this returns.
    """
    if descriptor.before_delete is not None:
        descriptor.before_delete(existing, scope)
    crud.delete_entity(db, existing)
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
