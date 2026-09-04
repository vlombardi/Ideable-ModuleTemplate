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

## Backup and recovery (mandatory)

**Recovery targets: RPO 24 hours, RTO 4 hours.** At most one day of data may be lost, and service
must be restorable within four hours. These are the documented baseline for a single-host
deployment; a deployer with stricter needs tightens them (see `docs/RUNBOOK.md` § *Tightening the
targets*) — they are not a limit of the tooling.

Consequences of those targets, which every module inherits:

- **Nightly logical dump, no WAL archiving.** `scripts/runtime/config/backup.sh` runs `pg_dump -Fc`
  against every database — host_app's, Authentik's, and each enabled module's — plus the artefacts
  a restored database needs to become a running system (`.env.config`, `traefik/acme.json`,
  Authentik blueprints, each module's `config/`). Point-in-time recovery is deliberately **not**
  implemented at a 24-hour RPO: it needs archive storage, `archive_mode=on` and a space budget on
  every database, and buys nothing against this target.
- **A module's database must be discoverable, not hardcoded.** `backup.sh` finds module databases
  from the running `${APP_SLUG}.<slug>.database` containers and reads `<SLUG>_ENTITIES_DB_NAME` /
  `<SLUG>_ENTITIES_DB_USER`. A module that renames those variables silently drops out of the
  backup — keep them, or the backup script must be updated in the same change.
- **`.env.secrets` is never backed up.** Credentials belong in a secret store; a plaintext copy in
  the backup directory is a larger risk than restoring them by hand. Any module adding a secret
  must add it there too, or a host-loss recovery cannot complete.
- **Partial backups fail loudly.** `backup.sh` exits non-zero if any database or artefact fails
  and prunes old runs only after a fully successful one; every run is checksummed
  (`MANIFEST.sha256`), and `restore.sh` refuses a backup that fails verification or has no
  manifest.
- **An untested backup is not a backup.** `verify-backup.sh` restores the latest backup into a
  throwaway container and asserts each database came back with tables; it is safe to run from
  cron. `check-backup-freshness.sh` alarms when the newest backup is stale, missing, or has no
  manifest (an interrupted run) — a backup job that stops silently otherwise looks exactly like
  one that works.

Operator procedures — container loss, volume loss, host loss, Authentik bootstrap corruption, ACME
failure, secret rotation — live in `docs/RUNBOOK.md`, each with an expected duration.

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
- That file is the single source of truth for the module-specific permissions and any optional menu-visibility permissions needed by the module.
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

- Module permissions are namespaced `<module_slug>.<resource>:<action>`, and reach a caller through `/api/me` — never as a token claim.
- Tenant scoping must use the `tenant_ids` returned by host_app's `/api/me` for tenant filtering.
- If a remote module defines additional claims, they must follow the same namespaced pattern and must be documented in that module’s `config/authorization.yaml`.
- Permission values must be declarative strings such as `items:view` and `items:edit`, declared bare in `authorization.yaml` and qualified with the module slug when resolved.
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

- The frontend must treat the permission set from `GET /api/me` as the only source of truth for visibility and enabled state; it must never decode the token for authorization.
- Menu definitions must be hidden entirely when the required `<resource>:menu_access` permission is missing from `*.permissions`.
- Primary action buttons, row actions, and edit-mode icons must be hidden or disabled when the required permission is absent from the set `/api/me` returned.
- The UI must re-read claims after token refresh or profile switch.
- The UI must not cache authorization decisions independently of the current token.
- A stale token must never be allowed to keep showing actions that the refreshed token no longer grants.

### 7. Backend API rules

- Every protected endpoint must use a permission dependency that resolves the caller's permissions from host_app (`require_permission()` → `GET /api/me`), never from token claims.
- CRUD endpoints must declare the exact permission required for each HTTP action.
- Read-only operations must use a `:view` permission or an equivalent explicitly declared permission.
- Mutating operations must use a `:edit` permission or an equivalent explicitly declared permission.
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
- Does it derive action availability from the `/api/me` permission set (and not from the token)?
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
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose `/api/me` permission set contains the exact required permission can see the menu item and its entire sub-tree. The field name is historical — the value is a permission, never read from the token
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
- Backend authorizes requests from host_app: `require_permission()` calls `GET /api/me` with the caller's bearer token and caches the answer per token for at most the 60 s revocation SLO.
- Protected endpoints enforce permissions in the `items:*` namespace, resolved as `template.items:*` from host_app.
- Swagger UI must expose an `Authorize` button via OAuth2 Authorization Code + PKCE.
- The OAuth2 callback used by Swagger UI must be `/module/template/api/docs/oauth2-redirect` in the deployed host_app domain and must be registered in Authentik as a strict redirect URI.
- Remote modules derived from this baseline must keep the same pattern, substituting their own module slug in the Swagger redirect URI path.
- JWT validation must fail closed.
- Permission helpers must operate on the permission set host_app resolved for the caller, never on decoded-but-untrusted user data from the request body.
- If the module defines a helper such as `require_permission(...)`, that helper must throw `403` when the caller does not hold the required permission and `401` when the token itself is absent or invalid.
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
- The scope mapping must emit **nothing** into the access token: its expression is `return {}`. Permissions and tenant scope are served by `/api/me` (`auth-specs.md` §3).
- The generated artifacts must remain aligned with the deployed `config/authorization.yaml` files and must be regenerated whenever those files change.
- A remote module is not compliant if it requires manual Authentik editing after deployment to function correctly.

## Database Schema

- Includes a single example entity table: `<entity>` holding only business fields (`id`, `name`, `description`).
- Carries no inline `au_*` audit columns: creation/update timestamps and actor are captured by the SQLAlchemy-Continuum version tables (see `audit-trail-specs.md` §2.2bis).
- The authoritative schema source is `modules/<module_slug>/backend/SOURCES/app/models.py`: the
  model is the schema, and only Alembic writes it.
- Migrations under `backend/SOURCES/alembic/versions/` apply it; `database/SPECS/schema.sql` is a
  generated rendering of the result, for reading and review.
- The full procedure is `database/SPECS/ideable-framework-specs/schema-workflow.md`.

## Database Targets (Entities vs Authorization)

- The baseline remote module uses a single entities DB target configured via env vars:
  - Entities DB target (`<SLUG>_ENTITIES_DB_*`) for module entities and backend runtime.
- Authorization is not stored in a host_app-managed RBAC database; it is supplied by Authentik JWT claims.
- The entities DB target holds the module's own entities; migrations run against it.
- Module bootstrap seeds **data** only (`seed.sql`); it creates no tables.

## Adding an entity (mandatory checklist)

Nine files, and they are listed because there was no list. A second entity was implemented from
these specs in a generated project, and every step below had to be recovered by reading the existing
entity's source — which is not a spec, and drifts the moment someone edits it.

Work in this order; each step depends on the one before.

**Database**

1. **`backend/SOURCES/app/models.py`** — add the model. It must declare:
   - `__versioned__: dict = {}` (audit trail is on by default; opt out only with a reason);
   - `__tenant_scoped__` — **mandatory**, and `scripts/common/check_tenancy_markers.py` fails the
     build without it, because the alternative is a table that silently holds every customer's rows;
   - `tenant_id` **leading** every composite index, or a query touches every tenant's rows and
     filters afterwards;
   - a **trigram GIN index** on any column exposed as a substring filter — `ILIKE '%term%'` has a
     leading wildcard, which no B-tree can serve.
2. **The migration** (`scripts/dev/schema.sh migration <module> -m "…"`). Autogenerate proposes; read
   it before committing. A **versioned, tenant-scoped** entity needs all of this, and autogenerate
   writes only the first item:
   - the table;
   - the Continuum `_version` twin, carrying a denormalised `issued_at` filled by a **column
     default** — Continuum writes those rows inside its own flush without naming the column;
   - primary keys that **contain the partition column**: `(id, transaction_id, issued_at)` on the
     version table, `(id, issued_at)` on `transaction`;
   - `create_hypertable` on the version table;
   - `ENABLE` **and** `FORCE ROW LEVEL SECURITY`;
   - the `tenant_isolation` and `tenant_cross_read` policies;
   - the indexes from step 1.
3. **Regenerate the rendering**: `scripts/dev/schema.sh schema-sql <module>` updates
   `database/SPECS/schema.sql`, which the FK-ordering helper and the schema contract test both read.

**Backend**

4. **`app/schemas.py`** — `…Base` / `…Create` / `…Update` / `…Read`, and a page model carrying
   `total`, `total_is_exact` and `next_after_id` (`backend/SPECS/ideable-framework-specs/base-specs.md`
   § *List endpoints*).
5. **`app/crud.py`** — list/get/create/update/delete. Reuse the tenant helpers (`apply_tenant_guc`,
   `_resolve_write_tenant`, `_refresh_within_scope`); cap `limit` at `MAX_PAGE_SIZE`, and switch to
   the planner's estimate above `EXACT_COUNT_THRESHOLD`.
6. **`app/routers/<entity>.py`** — permissions are **fully qualified**:
   `require_permission('<slug>.<entity>:view')`. A bare `'<entity>:view'` matches nothing at runtime
   and 403s every request.
7. **`app/main.py`** — import the router and `include_router(..., prefix='/api')`.

**Frontend and configuration**

8. **`config/authorization.yaml`** — declare `<entity>:view` / `:edit` / `:menu_access` (**bare** here;
   the seed qualifies them) and attach them to the module's roles.
9. **`frontend/SOURCES/src/`** — the service (`services/<entity>.ts`), the page
   (`pages/<Entity>.tsx`), an entry in `moduleManifest.ts` (`menuItems`, `routes`, `permissions`),
   and the i18n keys in **every** locale bundle. The page and service must satisfy
   `shared-ui-widgets-specs.md` § *Entity List Page Requirements* — including `onFilterChange`,
   `onSortChange`, and the empty-sort guard.

**Then**: one CRUD E2E suite for the entity (`rules/testing-guidelines.md` § *CRUD E2E tests*), and
record anything module-specific in the relevant `<sub-module>/SPECS/module-specs.md`.

## Audit Trail (mandatory for every entity)

Every main entity the module declares **must** implement an audit trail.
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

- Main entities are derived from the module's models (rendered in `database/SPECS/schema.sql`).
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
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose `/api/me` permission set contains the exact required permission can see the menu item and its entire sub-tree, while users without it will not see the item (it is not added to the UI). The field name is historical — the value is a permission, never read from the token
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
- Build Docker image: `docker build --no-cache -t <slug>.frontend:${IMAGE_TAG} --build-arg VITE_<SLUG>_API_URL=${VITE_<SLUG>_API_URL} ./frontend/SOURCES/`
- the build step is local-only and produces the image consumed by `deployment_root/docker-compose.yml`
- if you want to publish the built image to a registry, set `MODULE_DOCKER_REGISTRY_PREFIX` in the module `.env` (e.g. `MODULE_DOCKER_REGISTRY_PREFIX=ghcr.io/OWNER`) and run `scripts/common/push_module_images_to_registry.py` after the build step
- the push script is the only step that tags and pushes images; it never rebuilds them
- Produces Docker image only; no DIST folder.

### backend
- Build Docker image: `docker build --no-cache -t <slug>.backend:${IMAGE_TAG} ./backend/SOURCES/`
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

Registry prefix and `enabled.md` mode: during deployment the script reads `MODULE_DOCKER_REGISTRY_PREFIX` from each module's own `.env.config` and resolves it directly into the deployed `docker-compose.yml` image references. For modules declared as `local` (build from local SOURCES) the prefix is replaced with an empty string so compose uses locally built images (e.g. `<slug>.backend:${IMAGE_TAG}`). For modules declared as `remote` the full prefix is baked in so compose pulls pre-built images from the declared registry. The variable itself is unconditionally stripped from all deployed `.env.config` and `.env.secrets` files (merged and per-module) to prevent cross-module leakage.

## Deployment Paths

- Database init scripts: `database/DIST/initdb/` → `deployment_root/modules/<module_slug>/database/initdb/`
- Docker compose: `docker-compose.yml` → `deployment_root/modules/<module_slug>/docker-compose.yml`
- Environment variables: `modules/<module_slug>/.env.config` is merged into `deployment_root/.env.config` and `modules/<module_slug>/.env.secrets` is merged into `deployment_root/.env.secrets` by `scripts/common/build_and_deploy.py`
- Secret templates: `modules/<module_slug>/.env.secrets.example` is copied into `deployment_root/modules/<module_slug>/.env.secrets.example` and merged into `deployment_root/.env.secrets.example` by `deployment_root/scripts/create-merged-configuration.sh` (run by `redeploy.sh` after the build step)
