# module_template Authentication & Authorization Specification

## 1. Purpose and Scope

This document mirrors `modules/host_app/SPECS/auth-specs.md` and defines the **mandatory** authentication and authorization contract for any remote module derived from module_template. Keeping this file in sync across host_app ⇄ module_template ⇄ downstream remotes ensures:

1. Auth rules are discoverable without digging into host_app internals.
2. Template sync tooling can propagate spec changes automatically.
3. The stricter `:menu_access` permission model stays consistent everywhere.

Whenever host_app’s `auth-specs.md` changes, **update this file in the same change set** and re-sync module_template derived repos.

---

## 2. Identity Provider & Session Model

- **Authentik** is the only identity provider and JWT issuer.
- The SPA and backend authenticate exclusively via **OIDC Authorization Code Flow + PKCE**.
- Access tokens are validated as Bearer JWTs against Authentik JWKS; local key stores or static secrets are forbidden.
- Reject missing, expired, malformed, unsigned, or signature-invalid tokens with `401`.
- Remote modules MUST NOT implement standalone login flows, password databases, or token minting helpers.
- The backend never accepts raw credentials—only Bearer tokens obtained from Authentik.

---

## 3. JWT Claim Contract

### 3.1 Namespaces

| Namespace | Purpose |
| --- | --- |
| `hostapp.permissions` | host_app-scoped permissions, including host_app menu visibility (`users:menu_access`, etc.). |
| `hostapp.tenant_ids` | Company scoping list. Entries use `TenantName(ID)` and MUST be honored for multi-tenant filtering. |
| `<module_slug>.permissions` | **All module permissions**, including `<resource>:menu_access` strings for menu visibility. |
| `<module_slug>.tenant_ids` | Optional module-specific tenant scoping (defaults to `hostapp.tenant_ids` when absent). |

### 3.2 Emission rules

1. Permissions and menu visibility share the same array; every entry is `<resource>:<action>`.
2. Menu visibility requires the **explicit** permission `<resource>:menu_access`. There is **no** `<module_slug>.menu_access` fallback array.
3. The `<resource>` prefix MUST match menu item codes referenced in `config/menu_definition.json` and host_app’s `modules_menu_mapping.json`.
4. Any additional custom claim namespaces MUST be namespaced (`<module_slug>.<custom>`), documented here, and declared in `config/authorization.yaml`.
5. Audit-trail visibility MUST use the explicit `audit_trail:view` permission inside `<module_slug>.permissions`; it is not a separate claim namespace.

### 3.3 Example payload fragment

```json
{
  "hostapp.permissions": [
    "profiles:menu_access",
    "profiles:view"
  ],
  "template.permissions": [
    "items:menu_access",
    "items:view",
    "items:edit"
  ],
  "hostapp.tenant_ids": ["Acme(42)"]
}
```

---

## 4. Authorization Configuration (`config/authorization.yaml`)

- Serves as the authoritative contract consumed by `bootstrap_authentik.py`.
- MUST declare every permission the module requires using `<resource>:<action>` names, including `<resource>:menu_access`.
- Role↔permission and profile↔role mappings are optional but MUST follow the host_app schema when present.
- When permissions, roles, or profiles change, redeploy the module so bootstrap regenerates Authentik entities and scope mappings.

---

### 5. Frontend Responsibilities

1. Flatten the JWT claim arrays into a single permission set exactly as the backend does: prepend each claim array's module prefix to every bare `<resource>:<action>` value, producing fully-qualified `<module_slug>.<resource>:<action>` strings. host_app reads this flattened set from `/me`; a remote SPA decodes its own token and flattens it identically. Resolve every visibility and action check by exact match against this fully-qualified set (e.g. check for `"template.items:menu_access"`).
2. `authorization_claim` entries in `menu_definition.json` remain bare `<resource>:menu_access` strings and MUST reference real permissions emitted in `<module_slug>.permissions`; the module context supplies the prefix at match time.
3. Hide or disable all UI actions (buttons, table actions, edit icons, routes) when the matching permission is absent.
4. Refresh the in-memory permission map whenever the SPA refreshes/rotates the token (profile change, `/me` refresh, silent renew).
5. Treat `<resource>:menu_access` as visibility only; never infer edit rights from it.
6. Treat `audit_trail:view` as the authority for audit-trail row actions and popup access.

---

## 6. Backend Responsibilities

1. Apply a central dependency (see module_template `backend/SOURCES/app/auth.py`) to parse JWTs and expose helpers like `require_permission("template.items:view")`.
2. Every protected endpoint MUST validate the bearer token; return `401` for missing/invalid tokens and `403` for authenticated-but-unauthorized callers.
3. CRUD routes MUST declare explicit permissions (e.g., `template.items:view` for `GET`, `template.items:edit` for `POST/PUT/DELETE`).
4. Never trust UI hints, query params, or local RBAC tables; only JWT claims are authoritative.
5. Enforce tenant scoping using `hostapp.tenant_ids` (or module-specific tenant claims) on every data access.
6. History endpoints for audit-trail access MUST require `<module_slug>.audit_trail:view` and MUST return `403` when that permission is missing.

### Permission string format

JWT claim arrays store bare `<resource>:<action>` strings (e.g. `"items:view"` inside `template.permissions`). The backend's `_get_permissions_from_claims` / `get_authorization_claim_names` prepends the claim array's module prefix when flattening, producing fully-qualified strings in the runtime set. All `require_permission()` calls MUST therefore pass the fully-qualified form `<module_slug>.<resource>:<action>`. Bare `<resource>:<action>` strings to `require_permission()` are never correct.

---

## 7. Menu Definition Alignment

- `config/menu_definition.json` and host_app’s `modules_menu_mapping.json` use bare `authorization_claim` strings that MUST equal `<resource>:menu_access` permissions; each `modules_menu_mapping.json` item also carries a `module` field.
- host_app qualifies each `authorization_claim` with its item's `module` prefix (`<module>.<resource>:menu_access`) and renders the entry only when that fully-qualified permission exists in the flattened set.
- Parent/section items that control collapsible groups require their own `<resource>:menu_access` entry.
- host_app will never render a menu entry unless the qualified permission is present; remote SPAs must mirror this logic against their own flattened token.

---

## 8. Bootstrap & Registry Expectations

- `bootstrap_authentik.py` reads every module’s `config/authorization.yaml`, merges permissions, and maintains the Authentik registry groups:
  - `app:available-permissions-registry`
  - `app:permissions-to-role-registry`
  - `app:roles-to-profile-registry`
- The **Ideable Permissions Claims** property mapping emits:
  - `<module_slug>.permissions` (includes `<resource>:menu_access`).
  - `hostapp.tenant_ids` and optional `<module_slug>.tenant_ids`.
- Remote modules MUST NOT modify these registries directly; only the bootstrap pipeline may write them.

---

## 9. Compliance Checklist

A remote module is compliant only if the answer to each question is “yes”:

1. Does the SPA/backend authenticate exclusively via Authentik OIDC Authorization Code + PKCE?
2. Does every API call rely solely on verified JWT claims for authorization (no local RBAC fallbacks)?
3. Are menu entries rendered only when the fully-qualified `<module_slug>.<resource>:menu_access` permission exists in the flattened permission set?
4. Are CRUD actions gated by explicit `<resource>:view|edit|delete|...` permissions defined in `config/authorization.yaml`?
5. Is bootstrap rerun (via redeploy) whenever permissions/roles/profiles change?
6. Is tenant scoping enforced from `hostapp.tenant_ids` (or documented module-specific equivalents)?
7. Are this file and host_app `SPECS/auth-specs.md` kept in sync across host_app, module_template, and downstream remotes?

Any “no” answer means the module is out of spec and must not ship.

---

## 10. Sync Policy

- `modules/module_template/SPECS/ideable-framework-specs/auth-specs.md` is part of the **shared spec set** and MUST be distributed to every derived module.
- Update `scripts/module_only/sync-template-updates.sh` and `scripts/master_only/push-updates-to-module_template-repo.sh` whenever new shared specs are added so that consumer repos automatically receive them.
- Derived modules MAY extend this document with stricter module-specific requirements, but they MUST keep the shared sections identical to the baseline to remain compatible with host_app expectations.


## 11. Changes in the authentication and authorization specifications

When during the development of a module changes are needed or suppoesed to be needed to the authentication and authorization specifications, the following steps MUST be taken:
1. Never modify modules/host_app/authentik/DIST/bootstrap_authentik.py file. It is a Framework managed file that should not be modified by any module.
2. Create a concise and complete description of the issue and the proposed solution.
3. Send a chage request to the Ideable Framework team, or ask for assistance to the Ideable Framework team.