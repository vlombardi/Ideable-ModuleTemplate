# Backend Bug Avoider

This file tracks bugs found during testing/execution and the corresponding rules added to prevent them from recurring.

> **Framework-level backend rules** (Continuum `version_class`, synthetic creation entry, NULL-integer normalization, actor before commit) are defined in:
> `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md`
> Read that file before this one. Only module-specific rules are listed here.

---

## 2026-06 — Permission checks: use flat permission names matching the JWT claim values

**Bug**: Developers assumed `require_permission('template.items:edit')` would work, but the JWT emits bare `<resource>:<action>` strings inside the per-module claim (e.g. `"items:edit"` inside `template.permissions`). The `require_permission()` helper checks the raw claim values directly, so the prefixed name never matched and all permission-gated endpoints returned `403`.

**Fix**: Always use the flat form exactly as it appears in the JWT claim:
```python
require_permission('items:edit')     # correct
require_permission('audit_trail:view') # correct
```

**Rule**: Each module's permissions are emitted as bare `<resource>:<action>` strings inside the per-module JWT claim (`<module_slug>.permissions`). Both frontend and backend check these raw claim values directly without any prefixing. `require_permission()` and frontend `hasPermission()` must receive the exact bare `<resource>:<action>` string that appears in the token. **Never** prepend the module slug to the permission string.

---

