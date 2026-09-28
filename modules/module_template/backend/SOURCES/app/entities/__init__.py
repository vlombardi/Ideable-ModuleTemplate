"""This module's entity registry: what module_template declares, and the platform it declares it on.

The framework's implementation — `EntityDescriptor`, its validation, the query core and the router
generator — is `ideable_api` (`reusable.api/README.md`), shared by every module's backend. What
lives here is this module's own: which entities exist, and how THIS backend opens a session, checks
a permission, resolves a tenant scope and reads its audit trail.

Every name the framework defines is re-exported, so `app.entities.get_entity_descriptor(...)` and
`app.entities.list_entity(...)` read exactly as before — this package is the module's face onto the
framework, not a second implementation of it.
"""
import os

from ideable_api.entities import (  # noqa: F401
    EntityDescriptor,
    all_entity_descriptors,
    create_entity_row,
    delete_entity_row,
    freeze_registry,
    get_entity_descriptor,
    get_entity_row,
    is_registry_frozen,
    list_entity,
    register_entity,
    update_entity_row,
)
from ideable_api.entities import mount_entity_routers as _mount_entity_routers

# Importing a descriptor submodule registers it — this is what "validated at import" means in
# practice. Add an entity by adding its submodule here; a broken descriptor then fails at startup
# rather than on the first request that reaches it.
from . import items as _items  # noqa: E402,F401 — imported for its registration side effect
from . import sub_items as _sub_items  # noqa: E402,F401 — imported for its registration side effect
from . import sub_item_notes as _sub_item_notes  # noqa: E402,F401 — the chain's third level

# No descriptor may be added after this point: request handlers read the registry, and a structure
# they read must not change under them.
freeze_registry()

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
    'platform',
]


def platform():
    """This module's `Platform` — how the generated endpoints reach THIS backend.

    Built on call rather than at import so that importing the registry still needs no FastAPI: the
    in-process test layer (`backend/TESTS/README.md`) exercises descriptors and the query core with
    no web stack present, and `app.auth`/`app.database` both import one.
    """
    from ideable_api.platform import AuditBinding, Platform

    from .. import audit, auth, database

    return Platform(
        get_db=database.get_db,
        require_permission=auth.require_permission,
        require_tenant_scope=auth.require_tenant_scope,
        # The permission namespace this deployment's authorization.yaml is written in. A property
        # of the deployment, not of an entity, which is why it is resolved here once.
        module_slug=os.getenv('MODULE_SLUG', 'template'),
        audit=AuditBinding(
            system_actor_username=audit.SYSTEM_ACTOR_USERNAME,
            unavailable_error=audit.AuditUnavailableError,
            ensure_utc=audit.ensure_utc,
            get_system_startup_at=audit.get_system_startup_at,
            make_synthetic_creation_row=audit.make_synthetic_creation_row,
        ),
    )


def mount_entity_routers(app, prefix: str = '/api') -> list[str]:
    """Mount every declared entity's generated router onto `app`. Returns the keys mounted."""
    return _mount_entity_routers(app, platform(), prefix=prefix)
