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

Deployment constraints (no `build:` sections, no `SOURCES/` mounts, Dockerfile placement, `env_file` paths) are fully defined in `rules/general-guidelines.md` §docker-compose.yml rules — they apply here without exception.

## Internationalization

- All UI text (menu items, tooltips, popup messages, labels, etc.) must be defined in per-language JSON files (e.g., `en.json`, `it.json`).
- There must be one file per managed language.
- The module UI must render text in the language defined by the current value of the host_app `language` property.
- The module must not define or manage the active language itself; it must only consume the `language` value exposed by host_app.
- realize and keep always aligned the two language files `en.json` and `it.json`.


## Build-time SPECS JSON artifact rule

- This rule applies only when a `.json` file under `SPECS/` must be available to deployment/runtime containers and cannot be consumed directly from `SPECS/`.
- In that case, the file must be materialized into the related sub-module `DIST/` during the build step.
- If a sub-module needs non-standard copy logic for such files, define it in that sub-module `SPECS/build.sh` so `scripts/common/build_and_deploy.py` can execute it during build.

## Infrastructure file manifest

- `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md` is the canonical manifest of infrastructure files and folders maintained by the module_template export/sync scripts.
- Whenever `scripts/module_only/sync-template-updates.sh` or `scripts/master_only/push-updates-to-module_template-repo.sh` changes the infrastructure set, matching file patterns, or sync/export coverage, this manifest MUST be updated in the same change set.
- Any infrastructure file added to or removed from the script-maintained set MUST be reflected here before the sync/export logic is considered complete.

## Infrastructure files — modification warning

Any file listed in `infrastructure-file-list.md` (including but not limited to `scripts/common/build_and_deploy.py`, `redeploy.sh`, `start.sh`, `stop.sh`, `status.sh`, `update_backend.sh`, `update_frontend.sh`, and all documents under `SPECS/ideable-framework-specs/`) is maintained centrally by the Ideable dev team.

- **Do NOT modify these files directly in a remote module repository.**
- If a bug is found or a change is needed in an infrastructure file, open an issue / signal the requirement to the Ideable dev team.
- Wait for the fix to be published and then pull the updated files via `scripts/module_only/sync-template-updates.sh` (or via the push/sync mechanism provided by the maintainer).

Direct local modifications will be overwritten during the next sync and will block clean future updates.

# Remote Module Base Specs

This file is the baseline remote-module specification for Ideable modules and serves as a starter reference implementation.

## Distribution and ownership contract

- The baseline remote module in this repository is the source-distributed blueprint for third-party module developers.
- host_app source code is maintainer-internal and is distributed externally only as ready-to-run Docker images.
- In the maintainer repository, host_app and the baseline remote module may coexist in-tree, but the remote-module baseline must remain independently exportable.
- Official export mechanism for public sharing is `git subtree split --prefix modules/<module_slug>`.

Maintainer export flow:
- Use the maintainer export flow script in `scripts/master_only/` to create and push the curated remote-module snapshot to the standalone template repository.

## Purpose

- Demonstrate the expected structure of a remote module.
- Provide a minimal but complete reference implementation.
- Ensure compatibility with host_app host-module integration patterns.
- Unless a section explicitly says otherwise, any `template` value in this file is an example baseline slug and must be replaced with the derived module's real slug when a remote module is initialized from this baseline.

## Authorization config

- The authoritative authorization config for the baseline remote module lives at `modules/<module_slug>/config/authorization.yaml`.
- That file is the single source of truth for the module-specific permission claims and any optional menu visibility claims needed by the module.
- The module bootstrap process must consume that config file directly and must never depend on host_app database tables or ad hoc local RBAC state.
- The config is intentionally module-scoped; host_app owns the initial app-wide authorization bootstrap in `modules/host_app/config/authorization.yaml`.
- Remote modules derived from this baseline must preserve the same config shape and replace the module slug, routes, menu item codes, and permission names with their own values.

## Remote module authentication and authorization config

This file must remain understandable even without reading host_app files. The remote-module config is explicitly defined here and is mandatory for compliance.

### 1. Identity provider and token model

- Authentik is the only identity provider.
- The module must authenticate users with OIDC Authorization Code Flow with PKCE.
- The module must validate access tokens as Bearer JWTs using Authentik JWKS.
- The module must reject missing, expired, malformed, unsigned, or invalid-signature tokens.
- The module must not implement a local login system, local password database, or local session authority.
- The module must not exchange credentials directly with its backend as an authentication mechanism.

### 2. Required claim namespaces

- Module claims must use `<module_slug>.permissions`.
- Tenant scoping must use `hostapp.tenant_ids` for host_app-managed tenant filtering.
- If a remote module defines additional claims, they must follow the same namespaced pattern and must be documented in that module’s `config/authorization.yaml`.
- Permission values must be declarative claim strings such as `<permission_name>.items:view` and `<permission_name>.items:edit`.
- Menu visibility values must be declarative claim strings such as `<resource>:menu_access` emitted into `*.permissions`.

### 3. Authorization semantics

- `*.permissions` controls whether the user can perform an action.
- `<resource>:menu_access` entries inside `*.permissions` control whether the user can see the menu entry and its UI subtree.
- The frontend must hide or disable action buttons, table action icons, routes, and menu entries when the matching claim is absent.
- The backend must return `401` for missing/invalid credentials and `403` for authenticated users who lack the required permission.
- Authorization decisions must be derived only from verified JWT claims.
- The module must not query host_app to decide whether a user is allowed to view or edit a resource.
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
- The generated authorization plan must be materialized into `deployment_root/modules/host_app/authentik/blueprints/` and must be the file shipped to runtime containers.
- Runtime containers must read from the deployed authorization config and generated deployment blueprint, not from source-tree `SOURCES/` or `DIST/` blueprint artifacts.
- If a claim, permission, role, or mapping changes in any `config/authorization.yaml`, the module must be redeployed before the change is considered effective.

### 6. Runtime UI rules

- The frontend must interpret token-derived claims as the only source of truth for visibility and enabled state.
- Menu definitions must be hidden entirely when the required `<resource>:menu_access` permission is missing from `*.permissions`.
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

### 8. host_app interoperability rules

- host_app is responsible for seeding the initial application-wide contract and for forwarding the authenticated identity to the module through JWT claims.
- The remote module must consume the same OIDC issuer and JWKS used by host_app.
- The remote module must not invent a separate issuer, separate login page, or separate persistence model for authorization.
- The remote module must remain operable when embedded in host_app and when deployed as the canonical baseline-derived remote.

### 9. Compliance checklist

To be conformant, a remote module must be able to answer “yes” to all of the following:

- Does it validate Authentik JWTs against JWKS?
- Does it reject unauthenticated and unauthorized requests correctly?
- Does it derive menu visibility from `<resource>:menu_access` permissions inside `*.permissions`?
- Does it derive action availability from `*.permissions` claims?
- Does it define all of its permissions in `config/authorization.yaml`?
- Does it regenerate and ship the resulting Authentik artifacts at deployment time?
- Does it avoid host_app database lookups for authorization decisions?
- Does it re-evaluate claims after refresh or profile change?

If any answer is “no”, the module is not compliant.

## Self-contained minimum integration contract

> **Standard MF 2.0 vs Ideable Framework:** Exposing `./moduleManifest` with a defined shape is an Ideable Framework contract built on top of standard Module Federation 2.0 module exposure. The `menu_definition.json` format and `menu_mapping[]` contract are Ideable Framework conventions.

The minimum contract is explicitly defined here:

- Remote frontend exposes `./moduleManifest` with fields:
  - `name`, `slug`, `menuItems[]`, `routes[]`, optional `permissions[]`
- `menuItems[]` entries include: `name`, `href`, `icon`, optional `order`
- `routes[]` entries include: `path`, lazy `component`
- Remote `config/menu_definition.json` exposes `menu_definition[]`; each node includes:
  - `menu_item_code`, `menu_item_name`, `icon`, `sub_items[]`, optional `routing`
  - optional `is_collapsible` (boolean, default `false`): when `true`, the menu item is collapsible, hiding all its sub-menu items; when `false` or absent, the item is not collapsible and all sub-items are always visible
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose validated Authentik JWT includes the exact required permission in `*.permissions` can see the menu item and its entire sub-tree
- Host-side compatibility requirement (for host mapping file):
  - `menu_mapping[]` items include `module`, `module_menu_item_code_path`, `sub_items[]`
  - optional: `menu_item_code`, `menu_item_name`, `icon`

## API Scope

- External API base path (through Traefik): `/module/template/api`.
- Internal backend API base path: `/api`.
- Example protected routes:
  - `GET /module/template/api/items` (`items:view`)
  - `POST /module/template/api/items` (`items:edit`)
  - `PUT /module/template/api/items/{item_id}` (`items:edit`)
  - `DELETE /module/template/api/items/{item_id}` (`items:edit`)
- Swagger docs endpoint: `GET /module/template/api/docs`
- Swagger OAuth2 callback: `GET /module/template/api/docs/oauth2-redirect`
- Remote module APIs expose Swagger UI with OAuth2 Authorization Code + PKCE.
- The module-specific oauth2 redirect callback must be registered in Authentik.
- The redirect URI must use the module slug in the path for derived remotes.
- The backend must not expose unprotected mutation routes by default.
- Public endpoints, if any, must be explicitly documented in the module’s own SPECS.

## L&F source-of-truth rule

- Baseline remote-module frontend L&F definitions (tokens, shared table/control patterns, class structure conventions) are authoritative for reusable remote-module UX.
- host_app maintainers must align host_app shared component behavior to the baseline remote-module L&F contracts for common reusable patterns.
- Any divergence between host_app reusable patterns and this baseline remote-module contract must be explicitly documented in both host_app and the corresponding module SPECS before release.

Mandatory parity validation:
- automated parity contract tests in `modules/<module_slug>/frontend/TESTS/test_lf_parity_contract.py`
- visual snapshot parity checks in `modules/<module_slug>/frontend/TESTS/playwright/`
- orchestrated runner provided in `scripts/` for the module-template parity workflow

Verification URLs (deployed environment):
- `https://<host>/module-registry.json`
  - Must contain a `template` entry with `entry: "/remotes/template/mf-manifest.json"` and `remoteEntry: "/remotes/template/remoteEntry.js"`.
- `https://<host>/remotes/template/mf-manifest.json`
  - Must be reachable and include exposed module `./moduleManifest`.

## Backend Authentication and Authorization

- FastAPI backend validates JWT tokens against Authentik JWKS.
- Backend authorizes requests directly from JWT claims emitted by Authentik.
- Protected endpoints enforce permissions in `items:*` namespace (flat names inside `template.permissions`) using claim-based checks.
- Swagger UI must expose an `Authorize` button via OAuth2 Authorization Code + PKCE.
- The OAuth2 callback used by Swagger UI must be `/module/template/api/docs/oauth2-redirect` in the deployed host_app domain and must be registered in Authentik as a strict redirect URI.
- Remote modules derived from this baseline must keep the same pattern, substituting their own module slug in the Swagger redirect URI path.
- JWT validation must fail closed.
- Permission helpers must operate on the validated claims object, not on decoded-but-untrusted user data from the request body.
- If the module defines a helper such as `require_permission(...)`, that helper must throw `403` when the required claim is absent and `401` when the token itself is absent or invalid.
- Claim extraction must support the claim suffix conventions used by host_app and this baseline remote module, including `.permissions` and `.tenant_ids`.
- Backend authorization logic must not rely on UI state, query parameters, or local user profile caches.

## Frontend authentication and authorization behavior

- The SPA must acquire tokens through Authentik OIDC Authorization Code + PKCE.
- The SPA must attach `Authorization: Bearer <token>` to API requests.
- The SPA must hide menu entries, page actions, and table row action icons when the current token lacks the needed claim.
- The SPA must refresh its understanding of claims after token renewal and after profile changes.
- The SPA must never show an action that the current token does not authorize, even momentarily after refresh.
- The SPA must treat `<resource>:menu_access` permissions as visibility only and must not infer edit rights from them.
- The SPA must treat other `*.permissions` entries as action authority.

## Bootstrap and claim-generation responsibilities

- The Authentik bootstrap must read the deployed module contracts, build the authorization plan, and publish the plan into the generated deployment artifacts.
- The generated plan must include users, profiles, roles, permissions, role_permissions, profile_roles, and any metadata needed for claim generation.
- The scope mapping must emit the permission and menu claims into the access token.
- The generated artifacts must remain aligned with the deployed `config/authorization.yaml` files and must be regenerated whenever those files change.
- A remote module is not compliant if it requires manual Authentik editing after deployment to function correctly.

## Database Schema

- Includes a single example entity table: `template_items` holding only business fields (`id`, `name`, `description`).
- Carries no inline `au_*` audit columns: creation/update timestamps and actor are captured by the SQLAlchemy-Continuum version tables (see `audit-trail-specs.md` §2.2bis).
- The authoritative schema source is `modules/<module_slug>/database/SPECS/datamodel.sql`.
- `datamodel.sql` is initially authored in `SPECS/` during the specifications step.
- During `/Specs2Sources`, schema SQL is materialized to `modules/<module_slug>/database/SOURCES/initdb/datamodel.sql` for runtime initialization.

## Database Targets (Entities vs Authorization)

- The baseline remote module uses a single entities DB target configured via env vars:
  - Entities DB target (`TEMPLATE_ENTITIES_DB_*`) for module entities and backend runtime.
- Authorization is not stored in a host_app-managed RBAC database; it is supplied by Authentik JWT claims.
- `datamodel.sql` is for entities schema lifecycle only.
- `datamodel.sql` is executed during module bootstrap for entity schema initialization only.

## Audit Trail (mandatory for every entity)

Every main entity defined in `datamodel.sql` **must** implement an audit trail.
The authoritative contract is `SPECS/ideable-framework-specs/audit-trail-specs.md`.
Remote modules must read that file in full before implementing audit trail.

### 1. Backend requirements

- Every entity model that is backed by a local database table must enable SQLAlchemy-Continuum versioning with `__versioned__ = {}`.
- Every entity must expose a `GET /{entity_id}/history` endpoint that returns the full version history.
- The history endpoint must be protected by `require_permission('<module_slug>.audit_trail:view')`.
- The response schema must inherit from `BaseVersion` (see `app/schemas.py`) so that audit metadata and association-change fields have a uniform shape across all modules.
- The `app/audit.py` module must contain the reusable history factories (`build_transaction_map`, `make_synthetic_creation_row`, `version_row_to_schema`, `merge_and_sort_history`) and must never be trimmed or simplified.

### 2. Permission requirements

- `config/authorization.yaml` must declare an `audit_trail:view` permission.
- At least one role defined by the module must grant `audit_trail:view` so that users can view entity history.

### 3. Frontend requirements

- Every entity list or detail view that exposes mutable data must offer an audit-trail action icon (History) when the user holds `audit_trail:view`.
- The audit trail popup must render the history rows returned by the backend `/{entity_id}/history` endpoint.
- The popup must visually distinguish INSERT, UPDATE, DELETE, ASSOCIATE, and DISASSOCIATE operations.

## Entity-to-menu consistency rules

> **Ideable Framework:** The entity-to-menu mapping rules, path conventions, and `basePath` requirements are Ideable Framework conventions.

- Main entities are derived from `modules/<module_slug>/database/SPECS/datamodel.sql`.
- For each main entity, frontend manifest must expose:
  - one `menuItems[]` entry (`name`, `href`, `icon`, optional `order`)
  - one corresponding `routes[]` entry (`path`, lazy `component`)
- Path convention must follow host_app integration contract:
  - `menuItems[].href` is host_app absolute path with module base path (example `/template/items`)
  - `routes[].path` is module-local and must not duplicate base path (example `/items`)

## Standalone menu definition (mandatory)

> **Ideable Framework:** The `menu_definition.json` file format, collapsible behavior, and `authorization_claim` gating are Ideable Framework conventions.

- The module `config/` folder must contain a file named `menu_definition.json`.
- This file defines the module menu hierarchy used when the module runs as a standalone app (not integrated in host_app).
- `menu_definition.json` must expose a top-level `menu_definition` array.
- Each item in `menu_definition` must contain:
  - `menu_item_code` (internal reference, for example `SECOND_BUILDING`, `FIRST_FLOOR`, `THIRD_ROOM`)
  - `menu_item_name`
  - `icon`
  - optional `routing` (reference to the related content page; omitted for pure container items)
  - optional `is_collapsible` (boolean, default `false`): when `true`, the menu item is collapsible, hiding all its sub-menu items; when `false` or absent, the item is not collapsible and all sub-items are always visible
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose validated Authentik JWT includes the exact required permission in `*.permissions` can see the menu item and its entire sub-tree, while users without that claim will not see the item (it is not added to the UI)
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
- Build Docker image: `docker build --no-cache -t template.frontend:latest --build-arg VITE_TEMPLATE_API_URL=${VITE_TEMPLATE_API_URL} ./frontend/SOURCES/`
- the build step is local-only and produces the image consumed by `deployment_root/docker-compose.yml`
- if you want to publish the built image to a registry, set `MODULE_DOCKER_REGISTRY_PREFIX` in the module `.env` (e.g. `MODULE_DOCKER_REGISTRY_PREFIX=ghcr.io/OWNER`) and run `scripts/common/push_module_images_to_registry.py` after the build step
- the push script is the only step that tags and pushes images; it never rebuilds them
- Produces Docker image only; no DIST folder.

### backend
- Build Docker image: `docker build --no-cache -t template.backend:latest ./backend/SOURCES/`
- the build step is local-only and produces the image consumed by `deployment_root/docker-compose.yml`
- if you want to publish the built image to a registry, set `MODULE_DOCKER_REGISTRY_PREFIX` in the module `.env` (e.g. `MODULE_DOCKER_REGISTRY_PREFIX=ghcr.io/OWNER`) and run `scripts/common/push_module_images_to_registry.py` after the build step
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

All constraints are defined in `rules/general-guidelines.md` §docker-compose.yml rules.

Module-specific note: after building images you may optionally publish them with `scripts/common/push_module_images_to_registry.py` using the tag you want. The push script reads `MODULE_DOCKER_REGISTRY_PREFIX` from each module's `.env.config` to know which registry to push to. Compose services should reference it via `${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.<submodule>:latest`; when empty, local image names are used. The value should NOT include a trailing slash; compose files include the separator slash. It is the module maintainer's responsibility to keep `.env.config`, `.env.config.example`, `.env.secrets`, `.env.secrets.example`, and `docker-compose.yml` consistent. Build and deploy scripts must never automatically prepend a registry prefix.

Registry prefix and `enabled.md` mode: during deployment the script reads `MODULE_DOCKER_REGISTRY_PREFIX` from each module's own `.env.config` and resolves it directly into the deployed `docker-compose.yml` image references. For modules declared as `local` (build from local SOURCES) the prefix is replaced with an empty string so compose uses locally built images (e.g. `template.backend:latest`). For modules declared as `remote` the full prefix is baked in so compose pulls pre-built images from the declared registry. The variable itself is unconditionally stripped from all deployed `.env.config` and `.env.secrets` files (merged and per-module) to prevent cross-module leakage.

## Deployment Paths

- Database init scripts: `database/DIST/initdb/` → `deployment_root/modules/<module_slug>/database/initdb/`
- Docker compose: `docker-compose.yml` → `deployment_root/modules/<module_slug>/docker-compose.yml`
- Environment variables: `modules/<module_slug>/.env.config` is merged into `deployment_root/.env.config` and `modules/<module_slug>/.env.secrets` is merged into `deployment_root/.env.secrets` by `scripts/common/build_and_deploy.py`
- Secret templates: `modules/<module_slug>/.env.secrets.example` is copied into `deployment_root/modules/<module_slug>/.env.secrets.example` and merged into `deployment_root/.env.secrets.example` by `deployment_root/scripts/create-merged-configuration.sh` (run by `redeploy.sh` after the build step)
