"""What the framework needs from the module hosting it.

The generated endpoints (`router.py`) are framework code and the same for every module. Four things
they depend on are not: how this backend opens a database session, how it decides a caller holds a
permission, how it resolves a caller's tenants, and how it reads its audit trail. Those are a
module's own — they know its settings, its engine and its identity provider — so they are passed in
rather than imported.

That is the whole reason this file exists. An earlier shape had the framework do `from ..auth
import require_permission`, which made the framework code a member of one module's package and is
exactly why it could not be shared.

A module builds one of these once, at startup, and hands it to `mount_entity_routers`.
"""
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Platform:
    """One module's answers to what the generated endpoints need.

    Every field is a callable the module supplies, not a value: a FastAPI dependency is resolved
    per request, and freezing one at mount time would resolve it once for the life of the process.
    """

    #: `Depends(get_db)` — a session per request, closed when it ends.
    get_db: Callable[[], Any]

    #: `require_permission(name) -> dependency` — raises 403 when the caller lacks `name`.
    require_permission: Callable[[str], Any]

    #: The permission namespace this deployment's `authorization.yaml` is written in: a permission
    #: reads `<module_slug>.<resource>:<action>`. A property of the deployment, not of an entity,
    #: which is why it is here and not on a descriptor.
    module_slug: str

    #: `require_tenant_scope() -> dependency` — resolves the caller's `TenantScope`, or raises.
    #: Absent (None) for a module with no tenant-scoped entity: `TenantScope` requires at least one
    #: tenant by its own invariant, so a module whose data is not partitioned by tenant — today,
    #: host_app's — has no answer to give and none is asked of it. What decides whether a GIVEN
    #: entity needs one is its own `__tenant_scoped__`, not this field: a module may declare some
    #: entities tenant-scoped and others global, and only the former requires this to be set.
    #: `build_entity_router` refuses at mount time if a tenant-scoped entity is declared while this
    #: is None — the mismatch shows up at startup, never as a request silently unscoped.
    require_tenant_scope: Optional[Callable[[], Any]] = None

    #: The module's audit trail, as the five names the history endpoint uses. Absent (None) for a
    #: module with no audit trail: history routes are then not generated at all, for any entity,
    #: whatever a descriptor's `versioned` says.
    audit: Any = None


@dataclass(frozen=True)
class AuditBinding:
    """The audit-trail surface a history endpoint calls.

    Separate from `Platform` because it is optional as a unit: a module either has an audit trail
    or has none, and half of one is not a state worth representing.
    """

    system_actor_username: str
    unavailable_error: type
    ensure_utc: Callable[[Any], Any]
    get_system_startup_at: Callable[[], Any]
    make_synthetic_creation_row: Callable[..., Any]
