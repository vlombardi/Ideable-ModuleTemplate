# Backend Bug Avoider

This file tracks bugs found during testing/execution and the corresponding rules added to prevent them from recurring.

> **Framework-level backend rules** (Continuum `version_class`, synthetic creation entry, NULL-integer normalization, actor before commit) are defined in:
> `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md`
> Read that file before this one. Only module-specific rules are listed here.

---

## 2026-06 — Permission checks: use the fully-qualified `<module_slug>.<resource>:<action>` form

**Bug**: Bare `<resource>:<action>` strings (e.g. `require_permission('items:edit')`) were used,
assuming they match the JWT claim values directly. They never matched the runtime permission set,
so every permission-gated endpoint returned `403`.

**Fix**: Always use the fully-qualified form:
```python
require_permission('template.items:edit')      # correct
require_permission('template.audit_trail:view') # correct
```

**Rule**: `config/authorization.yaml` declares permissions in the **bare** `<resource>:<action>`
form (e.g. `items:edit`), and host_app qualifies each one with its declaring module before serving
it. So the set a caller receives from `GET /api/me` always contains `"template.items:edit"` — never
the bare form — and both `require_permission()` (backend) and `hasPermission()` (frontend) must be
given the fully-qualified `<module_slug>.<resource>:<action>` string.

The qualification happens **server-side, in host_app**, not by flattening token claims: the token
carries no permissions at all. This mirrors the framework contract in
`ideable-framework-specs/shared-backend-bug-avoider.md` § *Authorization* (canonical).

---

## 2026-09-17 — The generic query core (`crud.py`, `app/entities/`) must import no HTTP framework

**Bug (caught before it shipped)**: `crud.py` did `from .auth import TenantScope`. `TenantScope`
itself is a plain dataclass, but `auth.py` — the module that line actually imports — pulls in
`fastapi` at the top of the file. So importing `app.crud` (and therefore `app.database`,
`app.models`, and the entity registry built on them in sub-set 1) transitively required FastAPI to
be installed, even though none of those modules call anything from it.

**Why this matters here specifically**: `backend/TESTS`' in-process layer (`TESTS/README.md`, layer
2) imports `app.crud` / `app.entities` directly to exercise the generic query core against a real
database with no HTTP server running — that is the whole point of the layer. `requirements-dev.txt`
installs SQLAlchemy, SQLAlchemy-Continuum and pydantic for exactly this but **deliberately does
not install FastAPI**. With the coupling above, every in-process test would have failed at import
with `ModuleNotFoundError: No module named 'fastapi'`, in the one environment that exists
specifically to run this layer without it.

**Fix**: `TenantScope` lives in the shared framework package, `ideable_api.tenancy`, which imports
nothing but `dataclasses`. `app/tenancy.py` re-exports it under the name this backend calls it by,
and `app/auth.py` re-exports it too, so every existing `from .auth import TenantScope` keeps
working.

**Rule**: any value type the generic query core needs (`TenantScope` today; anything added later
that the query core or the registry must accept as a parameter) is declared in a module with no
FastAPI import — `ideable_api.tenancy`, or a sibling module of the same shape — never pulled in via
`app/auth.py`. Before adding a new import to `crud.py` or `app/entities/`, check that the imported
module's own top-level imports contain no `fastapi` — a transitive import is exactly how this one
was missed the first time.

---

