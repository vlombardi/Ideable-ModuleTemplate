# Shared Backend Bug Avoider — Framework-Level Rules

These rules apply to every module's backend. Module-specific `general_bug_avoider.md` files reference this file; do not duplicate these entries there.

---

## Audit Trail: Never access `__versioned__['class']` directly

**Bug**: History endpoints used `Model.__versioned__['class']` to retrieve the SQLAlchemy-Continuum version class. After `configure_mappers()`, the version class is registered differently, causing `KeyError: 'class'` and a `500 Internal Server Error` when accessing history.

**Fix**: Use `version_class(Model)` from `sqlalchemy_continuum` instead:
```python
from sqlalchemy_continuum import version_class
VersionClass = version_class(YourModel)
```

**Rule**: Always use `version_class(Model)` to get the Continuum version class. Never access `__versioned__['class']` directly — the internal structure is not stable after mapper configuration.

---

## Audit Trail: Synthetic creation entry when no version history exists

**Bug**: When a versioned entity had no Continuum versions (e.g., created before versioning was enabled), the history endpoint returned an empty list. The frontend showed "No results" with no evidence the entity exists.

**Fix**: After querying versions, if the list is empty, synthesize a creation entry using the current entity state and the system startup timestamp:
```python
if not versions:
    startup_at = get_system_startup_at()
    return [schemas.YourModelVersion(
        transaction_id=entity.id,
        operation_type=0,
        id=entity.id,
        # ... remaining fields from entity ...
        timestamp=startup_at,
        actor=SYSTEM_ACTOR_USERNAME,
        actor_id=None,
    )]
```

**Rule**: Every history endpoint must guarantee at least one audit row representing the entity's creation. If the audit source has no creation record, synthesize one using `get_system_startup_at()` and `SYSTEM_ACTOR_USERNAME` (value: `"system"`).

---

## Audit Trail: Continuum version tables may store `NULL` integers as `0`

**Bug**: When a nullable integer foreign key was set to `None`, the SQLAlchemy-Continuum version table stored `0` instead of SQL `NULL`. Association detection logic that checked `value is not None` incorrectly treated `0` as a valid association, generating phantom `ASSOCIATE(0)` rows instead of `DISASSOCIATE`.

**Fix**: Normalize `0` to `None` whenever reading nullable integer foreign keys from Continuum version rows:
```python
current_fk = v.some_fk if v.some_fk != 0 else None
```

**Rule**: Any nullable integer foreign key read from a Continuum version table must be normalized (`value if value != 0 else None`) before association/disassociation detection logic. Primary-key columns in PostgreSQL start at `1`, so `0` is never a valid entity ID and is safe to normalize to `None`.

---

## Audit Trail: Actor must be set before every mutating commit

**Bug**: SQLAlchemy-Continuum recorded `actor = None` in `TransactionMeta` because `set_current_user()` was not called before the DB session commit. Audit trail rows showed an empty "Who" column.

**Fix**: Attach a **global generator dependency** to the FastAPI app so the actor is set automatically for every authenticated request and always cleared afterward.  Generator dependencies run in the route handler's execution context, so they work correctly for both sync and async endpoints.

```python
# app/auth.py
@lru_cache(maxsize=1)
def _get_jwks() -> dict:
    ...  # cached JWKS fetch

def _get_current_username_optional(token: str | None = ...) -> str | None:
    ...  # decode JWT and return the username, or None for missing/invalid tokens

# app/main.py
from fastapi import FastAPI, Depends
from typing import Optional
from .auth import _get_current_username_optional
from .audit import set_current_user, clear_current_user

async def _audit_actor_dependency(
    username: str | None = Depends(_get_current_username_optional),
):
    """Must be an async generator so FastAPI runs it in the same asyncio
    task as the route handler; sync generators execute in a thread pool and
    the ContextVar set there does not propagate to the handler."""
    if username:
        set_current_user(username)
    yield
    clear_current_user()

app = FastAPI(
    ...,
    dependencies=[Depends(_audit_actor_dependency)],
)
```

**Rule**: Every module backend must register a **global async generator dependency** that extracts the username from the incoming request (via `_get_current_username_optional`), calls `set_current_user(username)`, and calls `clear_current_user()` after `yield`. The dependency **must be `async def`** — sync generators execute in a thread pool and the `ContextVar` set there does not propagate to the route handler, causing the actor to be recorded as `None`. The stored actor MUST be the authenticated username, not a display name or user ID. Per-route `set_current_user()` calls are not allowed; the global async dependency is the sole mechanism.

---

## Authorization: `require_permission()` always receives a fully-qualified string

**Rule**: Every `require_permission()` call must pass the fully-qualified `<module_slug>.<resource>:<action>` form (e.g. `require_permission('template.items:view')`). Bare `<resource>:<action>` strings (e.g. `'items:view'`) are never correct.

**Why**: JWT claim arrays store bare strings inside a module-prefixed array (e.g. `template.permissions: ["items:view"]`). The backend's permission-flattening function (`_get_permissions_from_claims` / `get_authorization_claim_names`) prepends the claim array's module prefix to every value before building the runtime set, so the set always contains `"template.items:view"` — not `"items:view"`. A bare string passed to `require_permission()` will never match and will always 403.

---

## Audit Trail: Business tables contain only business fields and foreign keys

**Rule**: Business tables in `datamodel.sql` contain only business fields and foreign keys. Add `__versioned__ = {}` to the ORM model to enable audit tracking. History endpoints read audit metadata from Continuum version classes via `version_class(Model)` — the version and transaction tables generated by Continuum are the sole source of audit metadata.
