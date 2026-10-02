"""`TenantScope` — whose data a request may touch.

A plain value: two fields and a fail-closed invariant. Nothing here talks to an identity provider,
to host_app or to an HTTP framework, and that is the point — `query.py` and `entities.py` need only
this value to decide what a query may see, and importing it must never drag in a web stack. A
module's in-process test layer exercises the query core against a real database with no server
running, and `requirements-dev.txt` states the same boundary from the tooling side: SQLAlchemy,
SQLAlchemy-Continuum and pydantic, deliberately not FastAPI.

Each module's `auth` resolves one of these from its own answer to "who is asking".
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantScope:
    """Whose data a request may touch — and, separately, whose it may only look at.

    Two fields rather than one widened set, because reading across tenants and writing across
    tenants are different authorisations and only the first is grantable:

    - `tenant_ids` — the caller's own tenants. Never empty (see `__post_init__`) and never
      widened, so every WRITE is confined to it whatever else is true.
    - `read_all_tenants` — set only when the caller holds the module's cross-tenant read
      permission. Widens reads, and nothing else.
    """

    tenant_ids: frozenset[int]
    read_all_tenants: bool = False

    def __post_init__(self) -> None:
        # An empty scope must never exist as a value: a caller reading `scope.tenant_ids` cannot
        # tell "no tenants" from "all tenants" by looking at an empty set, and one of those two
        # readings is a breach.
        if not self.tenant_ids:
            raise ValueError('TenantScope requires at least one tenant id')
