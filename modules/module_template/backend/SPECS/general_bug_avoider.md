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

