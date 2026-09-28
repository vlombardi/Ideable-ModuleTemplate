"""The generic query core, re-exported from the framework.

Every function here is `ideable_api.query`'s: the list/read/write contract is entity-agnostic and
identical in every module, so it lives once (`reusable.api/README.md`). This module is the name
this backend calls it by — `crud.list_entities(...)` reads the same as it always did, and a module
that needs a query of its own adds it HERE, beside these, rather than in the framework.
"""
from ideable_api.query import (  # noqa: F401
    EXACT_COUNT_THRESHOLD,
    MAX_PAGE_SIZE,
    TenantScopeError,
    apply_tenant_guc,
    create_entity,
    delete_entity,
    get_entity,
    list_entities,
    list_item_history,
    scoped_to_readable_tenants,
    update_entity,
)

__all__ = [
    'EXACT_COUNT_THRESHOLD',
    'MAX_PAGE_SIZE',
    'TenantScopeError',
    'apply_tenant_guc',
    'create_entity',
    'delete_entity',
    'get_entity',
    'list_entities',
    'list_item_history',
    'scoped_to_readable_tenants',
    'update_entity',
]
