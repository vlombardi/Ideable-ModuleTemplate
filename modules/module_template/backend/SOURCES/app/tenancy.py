"""`TenantScope`, re-exported from the framework.

The type itself is `ideable_api.tenancy` — it is framework code, identical in every module, and
lives once (`reusable.api/README.md`). This module stays because `from .tenancy import TenantScope`
is written across this backend and reads better than reaching into the package from everywhere.
"""
from ideable_api.tenancy import TenantScope

__all__ = ['TenantScope']
