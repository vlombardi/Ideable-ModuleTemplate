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

# Diagnostic probes are exempt: JWT validation on a 10s health check is pure waste.
PROBE_PATHS = frozenset({'/health', '/ready', '/startup'})

async def _audit_actor_dependency(request: Request):
    """Must be an async generator so FastAPI runs it in the same asyncio
    task as the route handler; sync generators execute in a thread pool and
    the ContextVar set there does not propagate to the handler."""
    if request.url.path in PROBE_PATHS:
        yield
        return
    username = _get_current_username_optional(request.headers.get('authorization'), None)
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

**Probe exemption (mandatory shape)**: the username MUST be resolved **inside** the dependency body from `request.headers`, not declared as a `Depends(_get_current_username_optional)` parameter. FastAPI resolves sub-dependencies *before* the body runs, so a declared sub-dependency would validate a JWT on every request — including the diagnostic probes (`/health`, `/ready`, `/startup`), which are unauthenticated and hit every 10 seconds by Docker. Registering the dependency on the app stays mandatory (it is still the single choke point); the probe paths are skipped by an early `yield`/`return` inside it. See `base-specs.md` § *Diagnostic probes*.

---

## Authorization: `require_permission()` always receives a fully-qualified string

**Rule**: Every `require_permission()` call must pass the fully-qualified `<module_slug>.<resource>:<action>` form (e.g. `require_permission('<slug>.<entity>:view')`). Bare `<resource>:<action>` strings (e.g. `'items:view'`) are never correct.

**Why**: JWT claim arrays store bare strings inside a module-prefixed array (e.g. `template.permissions: ["items:view"]`). The backend's permission-flattening function (`_get_permissions_from_claims` / `get_authorization_claim_names`) prepends the claim array's module prefix to every value before building the runtime set, so the set always contains `"<slug>.<entity>:view"` — not `"items:view"`. A bare string passed to `require_permission()` will never match and will always 403.

---

## Audit Trail: Business tables contain only business fields and foreign keys

**Rule**: Business tables contain only business fields and foreign keys. Add `__versioned__ = {}` to the ORM model to enable audit tracking. History endpoints read audit metadata from Continuum version classes via `version_class(Model)` — the version and transaction tables generated by Continuum are the sole source of audit metadata.

---

## Audit Trail: Never shadow the `actor` history-filter query param with a loop-local

**Rule**: In a history endpoint that accepts the audit-table filter params (`actor` / `operation_type` / `timestamp`) and passes them to `paginate_history(..., actor=actor, ...)`, the row-building loops must **not** assign to a local variable also named `actor` (or `operation_type` / `timestamp`). Give the per-row value a distinct name (e.g. `row_actor`, `entry_actor`) and use that when constructing the version schema: `SomeVersion(..., actor=row_actor, ...)`.

**Why**: Python function parameters and locals share one namespace. When a loop does `actor = normalize_actor_username(entry.actor)`, it overwrites the `actor` **query parameter** for the rest of the function. By the time `paginate_history(..., actor=actor, ...)` runs, `actor` holds the *last row's* actor instead of the caller's filter value — so the audit-table **"who" column filter silently does nothing** (or filters by the wrong value), while `operation_type`/`timestamp` filters, which have no such shadow, work fine. The mismatch (only "who" broken) is the tell-tale symptom. This bit `host_app`'s `get_user_history`, whose association/password/field loops all reassigned `actor`.

---

## Tenant scoping: parse the canonical `TenantName(ID)` claim, not just integers

**Rule**: A tenant-claim reader (`auth.get_tenant_ids()`) must accept the canonical wire format
`TenantName(ID)` — e.g. `DEFAULT_TENANT(1)`, or whatever the installation calls its tenants — as
well as bare integers and numeric strings. Match on the id in parentheses; ignore the name.

**Why**: `TenantName(ID)` is what host_app writes into the `hostapp.tenant_ids` attribute
(auth-specs.md §3), so it is what every real token carries. A reader that tried `int(value)` dropped
every id as non-numeric, `require_tenant_scope()` then found an empty set, and **every data endpoint
returned 403 for every user in the installation**. Fail-closed behaviour hid it completely: a 403 is
indistinguishable between "the claim is missing" and "the claim is unreadable". Ignore the *name*
for a second reason — names are editable labels, and matching one would follow a rename into the
wrong tenant.

---

## Tenant scoping: RLS governs writes too, and the GUC is transaction-local

**Rule**: Publish the tenant scope (`set_config('app.tenant_ids', …, true)`) **before the flush of a
write**, and publish it **again after `commit()`** if anything is read back (`Session.refresh`).

**Why**: two distinct failures, both invisible until the path is actually exercised.

1. The policy governs INSERT as well as SELECT. A create path that never set the GUC did not merely
   skip the defence-in-depth layer — the insert was refused outright (`new row violates row-level
   security policy for table …`). A write path with no GUC cannot write at all.
2. `set_config(…, true)` is scoped to the **transaction**. `db.commit()` ends it, and
   `Session.refresh` issues its SELECT in a new transaction where nothing has said who is asking —
   so under FORCEd RLS the row that was just written is invisible and the refresh raises. Re-publish
   before reading back.

Transaction-local is the property that stops the setting leaking to the next request that borrows a
pooled connection, so it is the right trade — but it has to be paid explicitly at every commit
boundary.

---

## Tenant scoping: a cross-tenant permission widens READS only, and never by an early return

**Rule**: Cross-tenant visibility is a **named permission** declared in `config/authorization.yaml`
(e.g. `items:read_all_tenants`). Carry it as a separate field on the scope value
(`TenantScope.read_all_tenants`) alongside the caller's own `tenant_ids`; resolve every **write**
against `tenant_ids` only, and load a PUT/DELETE target with `get_item(..., for_write=True)`. At the
database, express the widening as a **separate `FOR SELECT` policy**, never by loosening the main
one. Never write `if is_superadmin: return` — the fail-closed gate must run first, so a caller with
the permission and no tenant of its own is still denied.

**Why**: an implicit "administrators see everything" is invisible in the code path, in the token and
in the authorization contract, and it cannot be granted to one person without granting it to every
future holder of the same role. Splitting read from write is what keeps it honest at both layers:
because the database-side policy is `FOR SELECT` and permissive policies are OR-ed per command, a
cross-tenant reader gets `UPDATE 0`, `DELETE 0` and a refused INSERT even if the application forgets
the distinction. Granting visibility must not grant authority. Loading a write target with the
*widened* set instead would surface as a 500 from the policy where the honest answer is a 404.

---

## Tenant scoping: every model must declare `__tenant_scoped__`

**Rule**: Every SQLAlchemy model sets `__tenant_scoped__ = True` or `= False`. `True` requires a
`tenant_id` column. `scripts/common/validate_modules.sh` fails the build when a model declares
neither (`scripts/common/check_tenancy_markers.py`).

**Why**: the other tenancy rules protect the tables someone remembered. A model added later without
`tenant_id` raises nothing, logs nothing and fails no test — it just holds every customer's rows
while the queries over it look correct. So the declaration is mandatory and binary: silence is
indistinguishable from an oversight, and one of the two readings is a data leak. `False` is a
legitimate answer for reference data, a framework ledger or a control-plane table — state it, with
the reason, next to the model.

---

## Runtime: the backend image has no shell, no package manager and a read-only root filesystem

**Bug**: code written against a normal container quietly assumed things the runtime no longer offers. The backends run on `gcr.io/distroless/python3-debian12` as **uid 65532** with `read_only: true` and a `tmpfs` at `/tmp` (the non-root image work). There is no `sh`, no `bash`, no `pip`, no `ls`, and nothing outside `/tmp` is writable.

**Fix**: write to `/tmp` and nowhere else; never shell out.

```python
# WRONG — no shell in the image; also /app is read-only
subprocess.run("ls -la /app", shell=True)
open("/app/cache.json", "w")

# RIGHT
import tempfile, pathlib
pathlib.Path(tempfile.gettempdir(), "cache.json").write_text(payload)
```

**Rule**: no `shell=True`, no `subprocess` call to a shell utility, and no write outside `/tmp`. A healthcheck or `command:` in compose must be **exec form** — there is no shell to expand a string form. To debug a running backend use `docker exec <c> python -c …`; the recipes are in `docs/RUNBOOK.md` § *Debugging a container that has no shell*.

---

## Runtime: distroless prepends `python` to every command

**Bug**: `gcr.io/distroless/python3-debian12` sets `ENTRYPOINT ["/usr/bin/python3.11"]`, so a `CMD` or a compose `command:` becomes *arguments to python*, not a command. `command: ["python", "-m", "alembic", …]` ran as `python python -m alembic …` and died with `can't open file '/app/python'`.

**Fix**: reset it explicitly in the Dockerfile.
```dockerfile
ENTRYPOINT []
CMD ["python", "-m", "app"]
```

**Rule**: any Dockerfile using a distroless Python base must set `ENTRYPOINT []`, so every command in the Dockerfile and in compose reads as the thing it actually runs.

---

## Config: a required variable set to the EMPTY STRING must fail like a missing one

**Bug**: `DATABASE_URL=` (set, empty) passed pydantic validation — an empty string is a valid `str` — and died deeper in SQLAlchemy with `Could not parse SQLAlchemy URL from string ''`, naming neither the variable nor the file to fix. Only an *unset* variable produced a good diagnostic.

Empty is the case that actually happens: **docker compose substitutes an empty string for any variable it cannot resolve** and says so — *"The X variable is not set. Defaulting to a blank string"*.

**Fix**: reject blank values in `Settings`, naming the field and where to set it.
```python
@field_validator("DATABASE_URL", "AUTHENTIK_JWKS_URL")
@classmethod
def _must_not_be_blank(cls, value: str, info) -> str:
    if not value or not value.strip():
        raise ValueError(f"{info.field_name} is set but empty. Set a real value in the module's .env.config …")
    return value
```

**Rule**: every required field in a module's `config.py` must be covered by a blank check. Adding a new `Field(...)` without adding it to the validator reopens the gap for that one field — `test_process_model.py` fails if you do.

---

## Migrations: `alembic.ini` must be pure ASCII

**Bug**: one em dash in a comment in `alembic.ini` made the migrations job die with `UnicodeDecodeError`. Alembic opens that file with `encoding="locale"`, and `locale.getencoding()` **deliberately ignores Python's UTF-8 mode** (PEP 686). Measured inside the image: neither `PYTHONUTF8=1` nor `LANG=C.UTF-8` changes it, because distroless carries no locale data. Every backend waits on that job, so the whole stack stalls.

**Rule**: `alembic.ini` is **ASCII only** — including comments. The file carries a banner saying so, and `test_ascii_only_config.py` enforces it. Put prose that needs punctuation in `alembic/env.py`, which is read as UTF-8 like any Python source.

---

## Build context: `.dockerignore` patterns are NOT recursive unless `**/`-prefixed

**Bug**: a bare `__pycache__/` or `*.key` matches only at the **context root**. Measured with a probe image: `sub/__pycache__/nested.pyc` and `sub/secrets/leaked.key` were both copied into the image while the root-level equivalents were correctly excluded. Two consequences — 42 stale `.pyc` from a developer's tree were baked into every backend image, and the `*.pem`/`*.key`/`*.crt` lines written to stop a credential reaching an image were protecting only the one directory a credential is least likely to be in.

**Rule**: every pattern in every `.dockerignore` is `**/`-prefixed. `test_image_provenance.py` fails otherwise. Note separately that `PYTHONDONTWRITEBYTECODE` governs the **runtime** only — pip byte-compiles what it installs regardless, so `pip install` needs `--no-compile`.
