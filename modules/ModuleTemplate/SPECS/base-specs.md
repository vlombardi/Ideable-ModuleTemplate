# IMPORTANT: Read This First

**This file (`base-specs.md`) is the MANDATORY starting point for any coding agent action on this module and is the baseline contract for all remote modules unless explicitly overridden.**

Before implementing, modifying, or troubleshooting any backend component, you MUST:
1. Read `rules/general-guidelines.md`, then
2. Read this entire file, then
3. Read `module-specs.md`, then
4. any other further referenced specs files
5. Read the relevant sub-module `base-specs` file fully.
6. Follow the related `general_bug_avoider.md` files for the touched sub-modules.

## General Deployment Rules Reference

This module follows the deployment rules defined in `rules/general-guidelines.md`. Critical requirements:

- **No `build:` sections in docker-compose**: All Docker images must be pre-built before deployment.
- **No `SOURCES/` references in docker-compose volume mounts**: Only deployment paths are allowed.
- **No `Dockerfile` in deployment**: Dockerfiles stay in `SOURCES/` only.

See `rules/general-guidelines.md` lines 98-115 for complete deployment constraints.

## Internationalization

- All UI text (menu items, tooltips, popup messages, labels, etc.) must be defined in per-language JSON files (e.g., `en.json`, `it.json`).
- There must be one file per managed language.
- The module UI must render text in the language defined by the current value of the HostApp `language` property.
- The module must not define or manage the active language itself; it must only consume the `language` value exposed by HostApp.
- realize and keep always aligned the two language files `en.json` and `it.json`.


## Build-time SPECS JSON artifact rule

- Any `.json` file located in `SPECS/` that is required at deployment/runtime must be materialized into the related sub-module `DIST/` during the build step.
- These JSON files must not be read directly from `SPECS/` by runtime containers.
- If a sub-module needs non-standard copy logic for these files, define it in that sub-module `SPECS/build.sh` so `scripts/common/build_and_deploy.py` can execute it during build.

# Remote Module Base Specs

This file is the baseline remote-module specification for Ideable modules and serves as a starter reference implementation.

## Distribution and ownership contract

- The baseline remote module in this repository is the source-distributed blueprint for third-party module developers.
- HostApp source code is maintainer-internal and is distributed externally only as ready-to-run Docker images.
- In the maintainer repository, HostApp and the baseline remote module may coexist in-tree, but the remote-module baseline must remain independently exportable.
- Official export mechanism for public sharing is `git subtree split --prefix modules/<module_slug>`.

Maintainer export flow:
- Use the maintainer export flow script in `scripts/master_only/` to create and push the curated remote-module snapshot to the standalone template repository.

## Purpose

- Demonstrate the expected structure of a remote module.
- Provide a minimal but complete reference implementation.
- Ensure compatibility with HostApp host-module integration patterns.
- Unless a section explicitly says otherwise, any `template` value in this file is an example baseline slug and must be replaced with the derived module's real slug when a remote module is initialized from this baseline.

## Authorization config

- The authoritative authorization config for the baseline remote module lives at `modules/<module_slug>/config/authorization.yaml`.
- That file is the single source of truth for the module-specific permission claims and any optional menu visibility claims needed by the module.
- The module bootstrap process must consume that config file directly and must never depend on HostApp database tables or ad hoc local RBAC state.
- The config is intentionally module-scoped; HostApp owns the initial app-wide authorization bootstrap in `modules/HostApp/config/authorization.yaml`.
- Remote modules derived from this baseline must preserve the same config shape and replace the module slug, routes, menu item codes, and permission names with their own values.

## Remote module authentication and authorization config

This file must remain understandable even without reading HostApp files. The remote-module config is explicitly defined here and is mandatory for compliance.

### 1. Identity provider and token model

- Authentik is the only identity provider.
- The module must authenticate users with OIDC Authorization Code Flow with PKCE.
- The module must validate access tokens as Bearer JWTs using Authentik JWKS.
- The module must reject missing, expired, malformed, unsigned, or invalid-signature tokens.
- The module must not implement a local login system, local password database, or local session authority.
- The module must not exchange credentials directly with its backend as an authentication mechanism.

### 2. Required claim namespaces

- Module claims must use `<module_slug>.permissions` and `<module_slug>.menu_access`.
- Company scoping must use `hostapp.company_ids` for HostApp-managed tenant filtering.
- If a remote module defines additional claims, they must follow the same namespaced pattern and must be documented in that module’s `config/authorization.yaml`.
- Permission values must be declarative claim strings such as `<permission_name>.items:view` and `<permission_name>.items:edit`.
- Menu visibility values must be declarative claim strings such as `<permission_name>.items` emitted through the `*.menu_access` claim.

### 3. Authorization semantics

- `*.permissions` controls whether the user can perform an action.
- `*.menu_access` controls whether the user can see the menu entry and its UI subtree.
- The frontend must hide or disable action buttons, table action icons, routes, and menu entries when the matching claim is absent.
- The backend must return `401` for missing/invalid credentials and `403` for authenticated users who lack the required permission.
- Authorization decisions must be derived only from verified JWT claims.
- The module must not query HostApp to decide whether a user is allowed to view or edit a resource.
- The module must not depend on local RBAC tables as the authoritative source of runtime authorization.

### 4. YAML contract requirements

- Every remote module must keep a `config/authorization.yaml` file.
- That file must declare the module-specific permissions required by the module.
- If the module exposes frontend pages or routes, that file must also declare the corresponding `menu_access` permissions used for menu visibility.
- Permission entries must use the `<resource>:<action>` format.
- `menu_access` permissions must use the `menu_access` action and represent visibility only.
- Additional authorization entities such as users, profiles, roles, and mapping tables are allowed, but they are not mandatory under this baseline contract.

### 5. Bootstrap and deployment rules

- The bootstrap pipeline must be idempotent.
- Redeploying the same config must not duplicate users, profiles, roles, permissions, registries, or scope mappings.
- Running `./redeploy.sh` or the equivalent build-and-deploy flow must regenerate the authorization plan at deployment time from the deployed `config/authorization.yaml` files and refresh the deployed Authentik artifacts.
- The generated authorization plan must be materialized into `deployment_root/modules/HostApp/authentik/blueprints/` and must be the file shipped to runtime containers.
- Runtime containers must read from the deployed authorization config and generated deployment blueprint, not from source-tree `SOURCES/` or `DIST/` blueprint artifacts.
- If a claim, permission, role, or mapping changes in any `config/authorization.yaml`, the module must be redeployed before the change is considered effective.

### 6. Runtime UI rules

- The frontend must interpret token-derived claims as the only source of truth for visibility and enabled state.
- Menu definitions must be hidden entirely when the required `*.menu_access` claim is missing.
- Primary action buttons, row actions, and edit-mode icons must be hidden or disabled when the required `*.permissions` claim is missing.
- The UI must re-read claims after token refresh or profile switch.
- The UI must not cache authorization decisions independently of the current token.
- A stale token must never be allowed to keep showing actions that the refreshed token no longer grants.

### 7. Backend API rules

- Every protected endpoint must use a permission dependency that checks token claims.
- CRUD endpoints must declare the exact permission required for each HTTP action.
- Read-only operations must use a `:view` permission or equivalent explicitly declared claim.
- Mutating operations must use a `:edit` permission or equivalent explicitly declared claim.
- Any endpoint that exposes module data to the browser must be protected if the data is not public by design.
- Swagger UI must expose an `Authorize` button and must use the same OIDC flow as the SPA.

### 8. HostApp interoperability rules

- HostApp is responsible for seeding the initial application-wide contract and for forwarding the authenticated identity to the module through JWT claims.
- The remote module must consume the same OIDC issuer and JWKS used by HostApp.
- The remote module must not invent a separate issuer, separate login page, or separate persistence model for authorization.
- The remote module must remain operable when embedded in HostApp and when deployed as the canonical baseline-derived remote.

### 9. Compliance checklist

To be conformant, a remote module must be able to answer “yes” to all of the following:

- Does it validate Authentik JWTs against JWKS?
- Does it reject unauthenticated and unauthorized requests correctly?
- Does it derive menu visibility from `*.menu_access` claims?
- Does it derive action availability from `*.permissions` claims?
- Does it define all of its permissions in `config/authorization.yaml`?
- Does it regenerate and ship the resulting Authentik artifacts at deployment time?
- Does it avoid HostApp database lookups for authorization decisions?
- Does it re-evaluate claims after refresh or profile change?

If any answer is “no”, the module is not compliant.

## Self-contained minimum integration contract

The minimum contract is explicitly defined here:

- Remote frontend exposes `./moduleManifest` with fields:
  - `name`, `slug`, `menuItems[]`, `routes[]`, optional `permissions[]`
- `menuItems[]` entries include: `name`, `href`, `icon`, optional `order`
- `routes[]` entries include: `path`, lazy `component`
- Remote `config/menu_definition.json` exposes `menu_definition[]`; each node includes:
  - `menu_item_code`, `menu_item_name`, `icon`, `sub_items[]`, optional `routing`
  - optional `is_collapsible` (boolean, default `false`): when `true`, the menu item is collapsible, hiding all its sub-menu items; when `false` or absent, the item is not collapsible and all sub-items are always visible
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose validated Authentik JWT includes the required claim can see the menu item and its entire sub-tree
- Host-side compatibility requirement (for host mapping file):
  - `menu_mapping[]` items include `module`, `module_menu_item_code_path`, `sub_items[]`
  - optional: `menu_item_code`, `menu_item_name`, `icon`

## API Scope

- External API base path (through Traefik): `/module/template/api`.
- Internal backend API base path: `/api`.
- Example protected routes:
  - `GET /module/template/api/items` (`template.items:view`)
  - `POST /module/template/api/items` (`template.items:edit`)
  - `PUT /module/template/api/items/{item_id}` (`template.items:edit`)
  - `DELETE /module/template/api/items/{item_id}` (`template.items:edit`)
- Swagger docs endpoint: `GET /module/template/api/docs`
- Swagger OAuth2 callback: `GET /module/template/api/docs/oauth2-redirect`
- Remote module APIs expose Swagger UI with OAuth2 Authorization Code + PKCE.
- The module-specific oauth2 redirect callback must be registered in Authentik.
- The redirect URI must use the module slug in the path for derived remotes.
- The backend must not expose unprotected mutation routes by default.
- Public endpoints, if any, must be explicitly documented in the module’s own SPECS.

## L&F source-of-truth rule

- Baseline remote-module frontend L&F definitions (tokens, shared table/control patterns, class structure conventions) are authoritative for reusable remote-module UX.
- HostApp maintainers must align HostApp shared component behavior to the baseline remote-module L&F contracts for common reusable patterns.
- Any divergence between HostApp reusable patterns and this baseline remote-module contract must be explicitly documented in both HostApp and the corresponding module SPECS before release.

Mandatory parity validation:
- automated parity contract tests in `modules/<module_slug>/frontend/TESTS/test_lf_parity_contract.py`
- visual snapshot parity checks in `modules/<module_slug>/frontend/TESTS/playwright/`
- orchestrated runner provided in `scripts/` for the module-template parity workflow

Verification URLs (deployed environment):
- `https://<host>/module-registry.json`
  - Must contain a `template` entry with `entry: "/remotes/template/mf-manifest.json"`.
- `https://<host>/remotes/template/mf-manifest.json`
  - Must be reachable and include exposed module `./moduleManifest`.

## Backend Authentication and Authorization

- FastAPI backend validates JWT tokens against Authentik JWKS.
- Backend authorizes requests directly from JWT claims emitted by Authentik.
- Protected endpoints enforce permissions in `template.items:*` namespace using claim-based checks.
- Swagger UI must expose an `Authorize` button via OAuth2 Authorization Code + PKCE.
- The OAuth2 callback used by Swagger UI must be `/module/template/api/docs/oauth2-redirect` in the deployed HostApp domain and must be registered in Authentik as a strict redirect URI.
- Remote modules derived from this baseline must keep the same pattern, substituting their own module slug in the Swagger redirect URI path.
- JWT validation must fail closed.
- Permission helpers must operate on the validated claims object, not on decoded-but-untrusted user data from the request body.
- If the module defines a helper such as `require_permission(...)`, that helper must throw `403` when the required claim is absent and `401` when the token itself is absent or invalid.
- Claim extraction must support the claim suffix conventions used by HostApp and this baseline remote module, including `.permissions`, `.menu_access`, and `.company_ids`.
- Backend authorization logic must not rely on UI state, query parameters, or local user profile caches.

## Frontend authentication and authorization behavior

- The SPA must acquire tokens through Authentik OIDC Authorization Code + PKCE.
- The SPA must attach `Authorization: Bearer <token>` to API requests.
- The SPA must hide menu entries, page actions, and table row action icons when the current token lacks the needed claim.
- The SPA must refresh its understanding of claims after token renewal and after profile changes.
- The SPA must never show an action that the current token does not authorize, even momentarily after refresh.
- The SPA must treat `*.menu_access` as visibility only and must not infer edit rights from it.
- The SPA must treat `*.permissions` as action authority and must not infer menu visibility from it alone.

## Bootstrap and claim-generation responsibilities

- The Authentik bootstrap must read the deployed module contracts, build the authorization plan, and publish the plan into the generated deployment artifacts.
- The generated plan must include users, profiles, roles, permissions, role_permissions, profile_roles, and any metadata needed for claim generation.
- The scope mapping must emit the permission and menu claims into the access token.
- The generated artifacts must remain aligned with the deployed `config/authorization.yaml` files and must be regenerated whenever those files change.
- A remote module is not compliant if it requires manual Authentik editing after deployment to function correctly.

## Database Schema

- Includes a single example entity table: `template_items`.
- Uses standard audit columns (`au_creation_timestamp`, `au_last_update_timestamp`, `au_created_by_user`, `au_last_updated_by_user`).
- The authoritative schema source is `modules/<module_slug>/database/SPECS/datamodel.sql`.
- `datamodel.sql` is initially authored in `SPECS/` during the specifications step.
- During `/Specs2Sources`, schema SQL is materialized to `modules/<module_slug>/database/SOURCES/initdb/datamodel.sql` for runtime initialization.

## Database Targets (Entities vs Authorization)

- The baseline remote module uses a single entities DB target configured via env vars:
  - Entities DB target (`TEMPLATE_ENTITIES_DB_*`) for module entities and backend runtime.
- Authorization is not stored in a HostApp-managed RBAC database; it is supplied by Authentik JWT claims.
- `datamodel.sql` is for entities schema lifecycle only.
- `datamodel.sql` is executed during module bootstrap for entity schema initialization only.

## Entity-to-menu consistency rules

- Main entities are derived from `modules/<module_slug>/database/SPECS/datamodel.sql`.
- For each main entity, frontend manifest must expose:
  - one `menuItems[]` entry (`name`, `href`, `icon`, optional `order`)
  - one corresponding `routes[]` entry (`path`, lazy `component`)
- Path convention must follow HostApp integration contract:
  - `menuItems[].href` is HostApp absolute path with module base path (example `/template/items`)
  - `routes[].path` is module-local and must not duplicate base path (example `/items`)

## Standalone menu definition (mandatory)

- The module `config/` folder must contain a file named `menu_definition.json`.
- This file defines the module menu hierarchy used when the module runs as a standalone app (not integrated in HostApp).
- `menu_definition.json` must expose a top-level `menu_definition` array.
- Each item in `menu_definition` must contain:
  - `menu_item_code` (internal reference, for example `SECOND_BUILDING`, `FIRST_FLOOR`, `THIRD_ROOM`)
  - `menu_item_name`
  - `icon`
  - optional `routing` (reference to the related content page; omitted for pure container items)
  - optional `is_collapsible` (boolean, default `false`): when `true`, the menu item is collapsible, hiding all its sub-menu items; when `false` or absent, the item is not collapsible and all sub-items are always visible
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose validated Authentik JWT includes the required claim can see the menu item and its entire sub-tree, while users without that claim will not see the item (it is not added to the UI)
  - `sub_items` array with the same recursive structure

Example (`config/menu_definition.json`):

```json
{
  "menu_definition": [
    {
      "menu_item_code": "SECOND_BUILDING",
      "menu_item_name": "Second Building",
      "icon": "Building2",
      "sub_items": [
        {
          "menu_item_code": "FIRST_FLOOR",
          "menu_item_name": "First Floor",
          "icon": "Layers",
          "is_collapsible": true,
          "authorization_claim": "BuildingFirstFloorMenu",
          "sub_items": [
            {
              "menu_item_code": "THIRD_ROOM",
              "menu_item_name": "Third Room",
              "icon": "DoorOpen",
              "routing": "/rooms/third",
              "sub_items": []
            }
          ]
        }
      ]
    }
  ]
}
```

# Build
(from SOURCES to Docker images + DIST)

## Sub-module Build Process

Each sub-module has specific build requirements:

### frontend
- Build Docker image: `docker build --no-cache -t template/frontend:latest --build-arg VITE_TEMPLATE_API_URL=${VITE_TEMPLATE_API_URL} ./frontend/SOURCES/`
- the build step is local-only and produces the image consumed by `deployment_root/docker-compose.yml`
- if you want to publish the built image to a registry, run `scripts/common/push_module_images_to_registry.sh` after the build step and choose the tag you want to publish
- the push script is the only step that tags and pushes images; it never rebuilds them
- Produces Docker image only; no DIST folder.

### backend
- Build Docker image: `docker build --no-cache -t template/backend:latest ./backend/SOURCES/`
- the build step is local-only and produces the image consumed by `deployment_root/docker-compose.yml`
- if you want to publish the built image to a registry, run `scripts/common/push_module_images_to_registry.sh` after the build step and choose the tag you want to publish
- the push script is the only step that tags and pushes images; it never rebuilds them
- Produces Docker image only; no DIST folder.
- Endpoint convention:
  - internal backend endpoints remain module-local (for example `/docs`, `/openapi.json`, `/health`)
  - external routed endpoints are namespaced by Traefik under `/module/template/*`

### database
- No Docker image produced; uses standard `postgres:16-alpine` image.
- Copy `database/SOURCES/initdb/*` to `database/DIST/initdb/` during build step.
- See `database/SPECS/build.sh` for deterministic build script.

# Deployment
(from Docker images + DIST to DEPLOYMENT_ROOT)

## Docker Compose Rules

Per `rules/general-guidelines.md`:
- **No `build:` sections** in `docker-compose.yml`
- All services reference pre-built images via `image:` key
- Build the images first, then optionally publish selected images with `scripts/common/push_module_images_to_registry.sh` using the tag you want.
- Volume mounts reference deployment paths only (e.g., `./modules/<module_slug>/database/initdb` not `./database/SOURCES/initdb`)
- Deployed compose uses `env_file: - ../../.env` (pointing to the merged `deployment_root/.env`)
- No hardcoded values where an env var is available

## Deployment Paths

- Database init scripts: `database/DIST/initdb/` → `deployment_root/modules/<module_slug>/database/initdb/`
- Docker compose: `docker-compose.yml` → `deployment_root/modules/<module_slug>/docker-compose.yml`
- Environment variables: `modules/<module_slug>/.env` is merged into `deployment_root/.env` by `scripts/common/build_and_deploy.py`
