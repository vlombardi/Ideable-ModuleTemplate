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
        au_creation_timestamp=startup_at,
        au_last_update_timestamp=startup_at,
        au_created_by_user=SYSTEM_ACTOR_USERNAME,
        au_last_updated_by_user=SYSTEM_ACTOR_USERNAME,
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

def extract_username_from_token(token: str) -> str:
    ...  # decode JWT and return the username claim

# app/main.py
from fastapi import FastAPI, Depends, Header
from typing import Optional
from .auth import extract_username_from_token
from .audit import set_current_user, clear_current_user

def _audit_actor_dependency(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1)
        try:
            username = extract_username_from_token(token)
            set_current_user(username)
        except Exception:
            pass
    yield
    clear_current_user()

app = FastAPI(
    ...,
    dependencies=[Depends(_audit_actor_dependency)],
)
```

**Rule**: Every module backend must register a global generator dependency that extracts the username from the incoming request, calls `set_current_user(username)`, and calls `clear_current_user()` after `yield`.  The stored actor MUST be the authenticated username, not a display name or user ID.  Per-route `set_current_user()` calls are not allowed; the global dependency is the sole mechanism.

---

## Audit Trail: No inline `au_*` columns on business tables

**Rule**: Business tables in `datamodel.sql` must NOT contain `au_creation_timestamp`, `au_last_update_timestamp`, `au_created_by_user`, or `au_last_updated_by_user`.  Audit metadata is the sole responsibility of SQLAlchemy-Continuum.

SQLAlchemy-Continuum stores creation timestamp, update timestamp, and actor in its generated `<table>_version` and `transaction` tables.  Inline audit columns on the base table would require manual population in every CRUD path, introduce drift risk when code paths forget to set them (e.g. bulk operations, raw SQL, or background tasks), and duplicate metadata that Continuum already captures reliably.  The base tables contain only business fields and foreign keys; `__versioned__ = {}` on the ORM model is sufficient.  History endpoints read from Continuum version classes via `version_class(Model)`.
