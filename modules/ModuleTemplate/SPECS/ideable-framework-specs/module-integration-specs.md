# ModuleTemplate Module Integration Specs

This document is the canonical integration contract for remote modules in Ideable.
HostApp and downstream remote module repositories should treat this file as the primary reference for Module Federation integration, menu mapping, permission-based visibility, runtime composition, and deployment validation.

## 1) Architecture Overview

> **Standard MF 2.0 vs Ideable Framework:** HostApp acting as an MF host runtime, remote modules exposing manifests, and HostApp dynamically loading those manifests are standard Module Federation 2.0 capabilities. The integration with Authentik for identity/authorization and the specific route/menu mounting behavior are Ideable Framework conventions.

- HostApp is the MF host runtime.
- Remote modules expose their manifest through Module Federation.
- HostApp dynamically loads remote manifests and mounts routes/menu items.
- Authentik is the central identity and authorization provider.
- HostApp is the UI/admin/control surface.
- Remote modules consume claims issued by Authentik and authorize directly from validated JWTs.

Distribution model:
- HostApp is distributed externally as pre-built Docker images (no source-code distribution contract).
- ModuleTemplate is the source-distributed blueprint for module developers.
- In maintainer repos where HostApp and ModuleTemplate coexist, ModuleTemplate must remain independently exportable with:
  - `git subtree split --prefix modules/ModuleTemplate`
  - curated maintainer export flow: `scripts/master_only/push-updates-to-ModuleTemplate-repo.sh`

Validation model:
- The canonical validation entry point is `scripts/common/validate_modules.sh`.
- `validate_modules.sh` must accept no arguments to validate all enabled modules from `modules/enabled.md`.
- `validate_modules.sh` must accept a module list as positional arguments to validate only those modules.
- The validation scope is limited to each module's `.env`, `docker-compose.yml`, and every file in `config/`.
- The build and deploy flow must run validation immediately before the deploy step.

## 2) Remote Module Contract

> **Standard MF 2.0 vs Ideable Framework:** Exposing a named module (e.g., `./moduleManifest`) from a remote build is standard Module Federation 2.0. The required contract shape (`name`, `slug`, `menuItems[]`, `routes[]`, `permissions[]`), the standalone `menu_definition.json` format, and the validation rules are Ideable Framework conventions.

Remote frontend modules must expose `./moduleManifest` that matches HostApp contract expectations.

Each remote module `config/` folder must include a `menu_definition.json` file representing the menu hierarchy used when the module runs as a standalone app.

Minimum contract fields:
- `name`
- `slug`
- `menuItems[]`
- `routes[]`
- `permissions[]` (optional but recommended)

`menuItems[]` entries must provide:
- `name`
- `href`
- `icon`
- optional `order`

`routes[]` entries must provide:
- `path`
- lazy `component` loader

Path convention:
- HostApp owns URL namespacing via `basePath` from module registry.
- Remote `routes[].path` values must be module-local paths and must not duplicate `basePath`.
- Example for `basePath: "/template"`: use `"/dashboard"`, not `"/template/dashboard"`.

Validation rules for remote module root files:
- Each enabled module must include a module-root `.env` file.
- Each enabled module must include a module-root `docker-compose.yml` file.
- Each enabled module must include a `config/` folder containing the runtime configuration files used by the module.
- The validator must fail when any required file is missing.
- The validator must fail when `docker-compose.yml` is not syntactically valid.
- The validator must fail when `.env` contains malformed key/value entries.
- The validator must fail when files in `config/` are missing, unreadable, or malformed according to the file type they represent.

Standalone menu definition contract (`menu_definition.json`):
- Top-level key: `menu_definition` (array)
- Each item in `menu_definition` must contain:
  - `menu_item_code` (internal reference, for example `SECOND_BUILDING`, `FIRST_FLOOR`, `THIRD_ROOM`)
  - `menu_item_name`
  - `icon`
  - optional `routing` (reference to related content page; omitted for container-only nodes)
  - optional `is_collapsible` (boolean, default `false`): when `true`, the menu item is collapsible, hiding all its sub-menu items; when `false` or absent, the item is not collapsible and all sub-items are always visible
  - optional `authorization_claim` (string): when absent, the menu item is visible by all users; when defined, only users whose validated Authentik JWT includes the exact permission string in `<module_slug>.permissions` can see the menu item and its entire sub-tree. For menu visibility, the permission must use the `<resource>:menu_access` format (e.g. `BuildingFirstFloor:menu_access`). Users without that exact permission will not see the item (it is not added to the UI).
  - `sub_items` array with the same recursive item structure

Example (`modules/<ModuleName>/config/menu_definition.json`):

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
          "authorization_claim": "BuildingFirstFloor:menu_access",
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

## 3) Module Registry Format

> **Ideable Framework:** The `module-registry.json` format, registry endpoint, and verification URLs are Ideable Framework conventions; Module Federation 2.0 does not prescribe a registry file format.

HostApp uses `public/module-registry.json` with this structure:

```json
{
  "modules": [
    {
      "name": "template",
      "entry": "/remotes/template/mf-manifest.json",
      "displayName": "Module Template",
      "basePath": "/template"
    }
  ]
}
```

Rules:
- One entry per enabled remote module.
- `entry` must point to that module's MF manifest endpoint.
- `basePath` must match the module routing prefix.

Verification URLs for remote exposition (example: `template`):
- `https://<host>/module-registry.json`
  - Must contain module entry `name: "template"` with `entry: "/remotes/template/mf-manifest.json"`.
- `https://<host>/remotes/template/mf-manifest.json`
  - Must be reachable through Traefik and must include exposed module `./moduleManifest`.

Generic pattern for any module slug `<slug>`:
- Registry endpoint: `https://<host>/module-registry.json`
- Remote MF manifest endpoint: `https://<host>/remotes/<slug>/mf-manifest.json`

## 3.1) HostApp Modules Menu Mapping Contract

> **Ideable Framework:** The `modules_menu_mapping.json` contract, nesting rules, and rendering depth are Ideable Framework conventions.

The canonical HostApp menu mapping file lives at `deployment_root/modules/HostApp/config/modules_menu_mapping.json` and is mounted by the HostApp runtime.

There are two ways this file is produced at deployment time:

1. **Explicit HostApp mapping** — If `modules/HostApp/config/modules_menu_mapping.json` exists, it is used directly and copied into `deployment_root/modules/HostApp/config/`.
2. **Auto-merged from modules** — If the HostApp file does not exist, the deployment process (`create-merged-configuration.sh`) merges all enabled modules' `config/modules_menu_mapping.json` files into a single `modules_menu_mapping.json` placed in `deployment_root/modules/HostApp/config/`.

Each remote module may optionally provide `config/modules_menu_mapping.json` to propose its own menu placement in the HostApp sidebar. When auto-merging, the deployment script concatenates the `menu_mapping` arrays from every enabled module (excluding HostApp) that provides this file.

`modules_menu_mapping.json` must contain a top-level `menu_mapping` array.

Each `menu_mapping` item must contain:
- optional `menu_item_code` (HostApp internal reference; if omitted, use module `menu_item_code`)
- optional `menu_item_name` (HostApp display label; if omitted, use module `menu_item_name`)
- optional `icon` (if omitted, use module item icon)
- `module` (module name, for example `template`)
- `module_menu_item_code_path` (dot-separated path in remote `menu_definition`)
- `sub_items` array with the same recursive `menu_mapping` structure

Nesting under an existing HostApp menu item is expressed by making the first path segment match that HostApp menu code.

Examples:
- `TEMPLATE.ITEMS` renders the module item `ITEMS` under the module branch `TEMPLATE`
- `ADMIN.MYMENU` renders the module item `MYMENU` under the existing HostApp `Admin` menu branch

When a mapping path starts with a HostApp menu code such as `ADMIN`, HostApp treats that first segment as the parent branch and renders the mapped module subtree beneath it.

Mapped menu trees are rendered up to four levels deep total.

Example (`modules/HostApp/config/modules_menu_mapping.json`):

```json
{
  "menu_mapping": [
    {
      "menu_item_code": "MYMENU",
      "menu_item_name": "My Menu",
      "icon": "Shield",
      "module": "template",
      "module_menu_item_code_path": "ADMIN.MYMENU",
      "sub_items": [
        {
          "menu_item_code": "SUBITEM",
          "menu_item_name": "Sub Item",
          "icon": "List",
          "module": "template",
          "module_menu_item_code_path": "ADMIN.MYMENU.SUBITEM",
          "sub_items": []
        }
      ]
    }
  ]
}
```

## 3.2) Container Naming Contract

> **Ideable Framework:** The dotted container naming pattern and deployment-time slug resolution are Ideable Framework deployment conventions.

All HostApp and remote module compose files must use the dotted runtime naming pattern:

- `${APP_SLUG}.${MODULE_SLUG}.<container_name>`

Examples:
- `${APP_SLUG}.${MODULE_SLUG}.database`
- `${APP_SLUG}.${MODULE_SLUG}.backend`
- `${APP_SLUG}.${MODULE_SLUG}.frontend`
- `${APP_SLUG}.${MODULE_SLUG}.authentik-server`

Rules:
- `APP_SLUG` is the project-wide prefix defined in repo-root `project.env.config`.
- `MODULE_SLUG` is the module-local suffix defined in each module's `.env.config`.
- During deployment, `scripts/common/build_and_deploy.py` resolves the module slug for each deployed compose file before generating the merged compose output so the final runtime container names stay unique even though all module env files are merged into `deployment_root/.env.config` and `.env.secrets`.

## 4) Creating a New Remote Module

> **Standard MF 2.0 vs Ideable Framework:** Using Rsbuild with `@module-federation/rsbuild-plugin` and exposing a module from the remote are standard Module Federation 2.0 patterns (the specific build tool choice is Ideable-specific). The `./moduleManifest` contract, Authentik JWT validation, `config/authorization.yaml`, audit trail, and compose/registry wiring are Ideable Framework conventions.

1. Create module folder under `modules/<ModuleName>/` with `module.json`.
2. Set module metadata (`slug`, `displayName`, `role: remote`, `cssPrefix`).
3. Implement frontend remote with Rsbuild + `@module-federation/rsbuild-plugin`.
4. Expose `./moduleManifest` from remote frontend.
5. Implement backend API with JWT validation via Authentik JWKS.
6. Enforce permissions directly from Authentik JWT claims.
6a. Define module-specific authorization data in `modules/<ModuleName>/config/authorization.yaml` (e.g. entity roles, permissions, claim mappings). HostApp already owns the initial app-wide authorization bootstrap.
6b. Include `audit_trail:view` in `authorization.yaml` and assign it to at least one role.
7. Implement audit trail for every main entity (see `audit-trail-specs.md` and §11 below).
9. Add module compose file (`docker-compose.yml` or supported naming variant).
10. Enable module in `modules/enabled.md`.
11. Re-run build/deploy to regenerate module registry and merged compose.

## 5) Shared Dependency Requirements

> **Standard MF 2.0 vs Ideable Framework:** Configuring shared dependencies as singletons is a standard Module Federation 2.0 requirement. The specific shared library list (`react-oidc-context`, `oidc-client-ts`, `@tanstack/react-query`) is an Ideable Framework choice.

MF shared dependencies must be configured as singletons for compatibility:
- `react`
- `react-dom`
- `react-router-dom`
- `react-oidc-context`
- `oidc-client-ts`
- `@tanstack/react-query`

## 6) CSS Prefix Convention

> **Ideable Framework:** The Tailwind prefix convention and modifier ordering are Ideable Framework isolation rules.

Each module must use a dedicated Tailwind prefix equal to its slug:
- HostApp: `hostapp-`
- ModuleTemplate: `template-`

Modifier ordering must preserve Tailwind syntax:
- `hover:hostapp-bg-accent`
- `md:template-grid-cols-2`

## 6.1) Canonical Reference Module

> **Ideable Framework:** The canonical reference module pattern and parity gate requirements are Ideable Framework conventions.

- `modules/ModuleTemplate/` is the canonical, always-updated reference implementation for HostApp-compatible remote modules.
- When HostApp integration contracts change (routing, auth, widget behavior, or visual token usage), ModuleTemplate specs and implementation must be updated in the same change cycle.
- New module developers should treat ModuleTemplate as the first implementation reference before creating custom patterns.

## 6.2) Validation Discoverability Contract

> **Ideable Framework:** The validation discoverability contract, parity gates, and L&F compatibility model are Ideable Framework conventions.

Because HostApp and remote modules can live in separate codebases, validation compatibility must be discoverable through versioned artifacts instead of implicit knowledge.

Mandatory discoverability artifacts:
- HostApp module integration and validation contract in this file (`module-integration-specs.md`).
- ModuleTemplate frontend specs as executable baseline reference (`modules/ModuleTemplate/frontend/SPECS/shared-ui-specs.md`, `shared-ui-widgets-specs.md`, and `module-ui-specs.md`).
- ModuleTemplate frontend implementation (`modules/ModuleTemplate/frontend/SOURCES/`) as copy-ready compatibility baseline.

Validation runner requirements:
- `scripts/common/validate_modules.sh` is the authoritative runner used by build/deploy orchestration.
- The runner must validate all enabled modules when called without arguments.
- The runner must validate only the listed modules when module names are passed positionally.
- The runner must be safe to call before deployment and must not mutate module source files.

L&F compatibility model for remotes:
- Default mode: inherit HostApp visual tokens and interaction patterns.
- Override mode: apply module-specific visual overrides only inside module scope, without mutating HostApp global CSS.

Mandatory parity gates before release:
- automated parity contract tests:
  - `modules/ModuleTemplate/frontend/TESTS/test_template_items_table_contract.py`
  - `modules/ModuleTemplate/frontend/TESTS/test_lf_parity_contract.py`
- visual snapshot parity tests:
  - `modules/ModuleTemplate/frontend/TESTS/playwright/tests/lf-parity.spec.ts`
- runner:
  - `scripts/check_moduletemplate_lf_parity.sh`

## 7) Docker Compose Composition

> **Ideable Framework:** The two-level execution model, merge strategy, and per-module `.env`/compose rules are Ideable Framework deployment conventions (see `rules/general-guidelines.md`).

See `rules/general-guidelines.md` for complete deployment architecture specification:
- Two-level execution model (standalone vs composed)
- Path resolution in merged compose
- Environment variable strategy
- Per-module vs ecosystem-wide `.env` and `docker-compose.yml` files

### 7.1) Env Var Interpolation Rules

> **Ideable Framework:** The `--no-interpolate` merge rules and validation step ordering are Ideable Framework deployment pipeline conventions.

The build and deploy pipeline uses `docker compose config --no-interpolate` when merging compose files. Because `--no-interpolate` disables all variable expansion during merge-time validation, env var placeholders **must not appear in YAML dictionary keys** — they are only allowed in YAML values.

**Allowed in values (string fields):**
- `container_name: ${APP_SLUG}.${MODULE_SLUG}.backend`
- `image: ${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.backend:latest`
- `ports: - "${BACKEND_PORT:-8001}:8001"`
- environment variable values, labels, commands, healthcheck tests

**Forbidden in keys (structural identifiers):**
- Service names under `services:` — must be static strings
- `depends_on:` keys — must reference actual service names
- Top-level `networks:` keys — must be static network names
- Top-level `volumes:` keys — must be static volume names

Example of correct usage:
```yaml
services:
  backend:
    image: ${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.backend:latest
    container_name: ${APP_SLUG}.${MODULE_SLUG}.backend
    networks:
      - ideable_network
    depends_on:
      database:
        condition: service_healthy

networks:
  ideable_network:
    driver: bridge
```

Example of incorrect usage (will fail validation):
```yaml
services:
  ${APP_SLUG}.backend:         # WRONG: env var in service name key
    image: backend:latest
    depends_on:
      ${APP_SLUG}.database:    # WRONG: env var in depends_on key
        condition: service_healthy

networks:
  ${APP_SLUG}.network:          # WRONG: env var in networks key
    driver: bridge
```

Deployment validation step:
- `scripts/common/build_and_deploy.py` must invoke `scripts/common/validate_modules.sh` after build succeeds and immediately before any deployment copy or compose-generation step.
- Validation must run before any deployment-side file is written so invalid module files stop the pipeline early.

### 7.2) Sync-managed compose sections

> **Ideable Framework:** The sync-managed section markers and ownership model are Ideable Framework conventions.

`modules/ModuleTemplate/docker-compose.yml` uses explicit sync-managed sections to define which compose areas are owned by the framework. The current ownership model is:

- `# SYNC-MANAGED-BEGIN: bootstrap-service` / `# SYNC-MANAGED-END: bootstrap-service`
- `# SYNC-MANAGED-BEGIN: database-service` / `# SYNC-MANAGED-END: database-service`
- `# SYNC-MANAGED-BEGIN: backend-service` / `# SYNC-MANAGED-END: backend-service`
- `# SYNC-MANAGED-BEGIN: frontend-service` / `# SYNC-MANAGED-END: frontend-service`
- `# SYNC-MANAGED-BEGIN: top-level-networks` / `# SYNC-MANAGED-END: top-level-networks`
- `# SYNC-MANAGED-BEGIN: top-level-volumes` / `# SYNC-MANAGED-END: top-level-volumes`

The sync script replaces only those marked sections in downstream remote modules. Remote module developers own any compose content outside the managed blocks, including remote-specific labels, service overrides, or additional services.

Volumes are framework-managed when they are part of the marked top-level volumes section, but their runtime paths remain configurable through env vars such as `DATA_FOLDER`-style settings, so deployers can still redirect persistent storage without editing the managed compose block.

When a remote module predates this marker layout, migrate it by adding the same markers around the framework-owned sections and then re-running the sync script. After migration, future syncs update only the marked sections and preserve remote-specific compose customizations outside them.

## 7.1) MF 2.0 Runtime Configuration via Volume Mounts

> **Standard MF 2.0 vs Ideable Framework:** Runtime module composition without rebuilding is enabled by Module Federation 2.0 dynamic remote loading. The specific volume-mount configuration (`modules/HostApp/config/`), `module-registry.json`, and `modules_menu_mapping.json` runtime update mechanism are Ideable Framework conventions.

To enable runtime module composition changes without rebuilding containers, the deployed HostApp stack must mount the full `modules/HostApp/config/` folder from `deployment_root/` into the frontend container.

- `.env` (used by compose services via `env_file`)
- `modules/HostApp/config/` as a read-only volume mounted at `/usr/share/nginx/html/config`

The frontend must fetch runtime assets from `/config/` inside the container.

Because browsers may heuristically cache JSON responses (especially when no explicit `Cache-Control` header is present), every `fetch()` call for runtime JSON assets must append a cache-busting query parameter (e.g. `?t=${Date.now()}`) so that updated config files are never served from a stale browser cache across deployments.

The mounted `modules/HostApp/config/` folder contains the canonical runtime assets for HostApp, including:

- `modules_menu_mapping.json`
- `module-registry.json`
- `home.html`
- favicon file pointed to by `AUTHENTIK_LOGIN_FAVICON_FILE`
- `login_bg.png`

`.env` is mandatory runtime configuration and must be wired from `deployment_root/.env` through compose `env_file` entries.

**Deployment-root mount pattern (reference):**
```yaml
services:
  frontend:
    env_file:
      - .env
    volumes:
      - ./modules/HostApp/config:/usr/share/nginx/html/config:ro

  template-frontend:
    env_file:
      - .env
    volumes:
      - ./modules/ModuleTemplate/config/menu_definition.json:/usr/share/nginx/html/menu_definition.json:ro
```

**Key Principle**: These files are configuration that may change between deployments or require runtime adjustments. Mounting them as volumes allows operators to:
- Enable/disable modules by updating `modules_menu_mapping.json`
- Customize branding without rebuilding images
- Update menu structures without redeployment

All volume mounts use `:ro` (read-only) flag as these are configuration files, not runtime state.

## 8) Traefik Routing

> **Ideable Framework:** The `/remotes/<slug>/*` and `/module/<slug>/*` routing prefixes and Traefik strip-prefix behavior are Ideable Framework deployment conventions.

Remote module routing pattern:
- Frontend static assets/manifests: `/remotes/<slug>/*`
- Backend surface: `/module/<slug>/*`

HostApp routing pattern:
- HostApp business APIs: `/api/*`
- HostApp docs/OpenAPI: `/api/docs`, `/api/openapi.json`
- HostApp health check: `/health`

Remote module operational/docs pattern:
- External (through Traefik):
  - API root: `/module/<slug>/api`
  - API docs: `/module/<slug>/api/docs`
  - OpenAPI: `/module/<slug>/api/openapi.json`
  - Health: `/module/<slug>/health`
- Internal remote backend service remains module-local and routed behind strip-prefix:
  - API root: `/api`
  - API docs: `/api/docs`
  - OpenAPI: `/api/openapi.json`
  - Health: `/health`

HostApp Traefik config must keep host and remote routes isolated.

## 11) Environment Variable Ownership

> **Ideable Framework:** The `VITE_APP_TITLE` ownership rule and module-scoped build-arg restrictions are Ideable Framework conventions.

- `VITE_APP_TITLE` is owned by HostApp frontend configuration.
- Remote module `.env` files must not define `VITE_APP_TITLE`.
- Remote module frontend build args must include only module-scoped variables (for example `VITE_TEMPLATE_API_URL`).

## 9) Authorization Integration

> **Ideable Framework:** While JWT validation and Bearer token usage are standard patterns, the claim namespace convention (`<module_slug>.permissions`), permission naming (`<resource>:<action>`), and menu visibility model are Ideable Framework conventions.

Remote modules must use the same access token received by the SPA:

1. Validate token signature using Authentik JWKS.
2. Read authorization claims from the token payload.
3. Enforce permission checks in module backend.

Permission naming convention:
- Bare `<resource>:<action>` strings are emitted inside the per-module JWT claim `<module_slug>.permissions`.
- Both frontend and backend check these raw claim values directly without prefixing.

Examples (as they appear inside `template.permissions`):
- `items:view`
- `items:edit`

Modules may define custom claims for:
- menu visibility
- route authorization
- tenant/company scoping
- feature flags

## 10) Kubernetes Readiness Notes

Remote modules must remain Kubernetes-ready:
- Use service DNS names in internal URLs.
- Avoid host-path assumptions.
- Keep module boundaries explicit (frontend, backend, database).
- Expose health endpoints for orchestrator probes.

## 12) Audit Trail Implementation

> **Ideable Framework:** Audit trail implementation (SQLAlchemy-Continuum versioning, history endpoints, `audit_trail:view` permission, and frontend popup) is an Ideable Framework requirement with no Module Federation 2.0 standard equivalent.

Every remote module must implement audit trail for every main entity as defined in
`audit-trail-specs.md`. The following checklist maps the spec requirements to concrete
ModuleTemplate files.

### 12.1 Backend checklist

1. **Entity model versioning** — every main entity must set `__versioned__ = {}`:
   - Example: `modules/ModuleTemplate/backend/SOURCES/app/models.py`

2. **`app/audit.py` must not be simplified** — it must contain all reusable factories:
   - `set_current_user()`, `get_current_user()`, `clear_current_user()`
   - `set_system_startup_at()`, `get_system_startup_at()`
   - `ensure_utc()`, `normalize_actor_username()`
   - `build_transaction_map(db, version_rows)`
   - `make_synthetic_creation_row(schema_cls, entity, ...)`
   - `version_row_to_schema(version_row, schema_cls, tx_map, ...)`
   - `merge_and_sort_history(field_versions, association_rows, ...)`
   - `register_audit_listener(engine)` (legacy fallback)
   - `ActorPlugin` — a `sqlalchemy_continuum.plugins.Plugin` subclass whose `before_flush`
     sets `uow.current_transaction.meta['actor']` from the context-var set by `set_current_user()`.
     Must be passed to `make_versioned(plugins=[TransactionMetaPlugin(), ActorPlugin()])`.

3. **History endpoint** for each entity:
   - Route: `GET /<entity>/{entity_id}/history`
   - Guard: `require_permission('<module_slug>.audit_trail:view')`
   - Must use `build_transaction_map`, `version_row_to_schema`, and `merge_and_sort_history`
   - Must synthesise a creation row via `make_synthetic_creation_row` when no versions exist

4. **Response schema** for each entity:
   - Must inherit from `BaseVersion` (defined in `app/schemas.py`)
   - Only add business fields (e.g. `name`, `description`) to the subclass
   - Example: `class TemplateItemVersion(BaseVersion): ...`

5. **Actor injection** — every mutating endpoint must call `set_current_user(username)` before
the DB commit. The username must come from the validated JWT, never from a display name or email.
   The `ActorPlugin` (registered in `make_versioned`) copies the context-var actor into each
   Continuum transaction during `before_flush`, so the audit trail reports the correct user.

### 12.2 Frontend checklist

1. **Audit trail action icon** — every entity table or detail page must show a `History` icon
(from lucide-react) in the action column, gated by `audit_trail:view` in the JWT permissions.

2. **AuditTrailPopup** — clicking the icon opens the popup component that fetches and renders
`GET /<entity>/{entity_id}/history`. The popup must visually distinguish the five operation types
(`0`/`1`/`2`/`3`/`4`).

3. **No legacy toggle** — the old per-page "Show audit data" toggle is not allowed; visibility
is controlled exclusively by the permission-gated action icon.

### 12.3 Authorization checklist

1. **`config/authorization.yaml`** must declare `audit_trail:view` as a permission.
2. At least one role must grant `audit_trail:view` so users can view history.
3. The permission string passed to `require_permission()` must be the fully-qualified form
`<module_slug>.audit_trail:view`.

## 13) Logging and Observability

> **Ideable Framework:** The automatic `<SLUG>_LOG_LEVEL` derivation from `modules/enabled.md` mode and the backend startup logging contract are Ideable Framework conventions.

### 13.1 Automatic Log Level

The deploy script (`scripts/common/build_and_deploy.py`) derives a per-module `<SLUG>_LOG_LEVEL` environment variable for every enabled module based on its mode in `modules/enabled.md`:

- **`enabled`** (build from local source) → `<SLUG>_LOG_LEVEL=DEBUG`
  - Modules in development mode emit `DEBUG`, `INFO`, `WARNING`, and `ERROR` logs.
- **`enabled-remote`** (pre-built images) → `<SLUG>_LOG_LEVEL=INFO`
  - Modules in production mode emit `INFO`, `WARNING`, and `ERROR` logs only.

The variable name is derived from the module's `slug` field in `module.json`, uppercased, and suffixed with `_LOG_LEVEL`:

- HostApp (slug `hostapp`) → `HOSTAPP_LOG_LEVEL`
- ModuleTemplate (slug `template`) → `TEMPLATE_LOG_LEVEL`
- A custom module (slug `sra`) → `SRA_LOG_LEVEL`

This prefixed variable is injected into both:

- The merged `deployment_root/.env` (used by composed execution)
- Each per-module `deployment_root/modules/<MODULE>/.env` (used by standalone execution)

Each backend service's `docker-compose.yml` maps the module-specific variable to the standard `LOG_LEVEL` variable in its `environment:` block:

```yaml
# HostApp backend
environment:
  - LOG_LEVEL=${HOSTAPP_LOG_LEVEL:-INFO}

# ModuleTemplate backend
environment:
  - LOG_LEVEL=${TEMPLATE_LOG_LEVEL:-INFO}
```

Docker Compose resolves `${TEMPLATE_LOG_LEVEL}` from the merged `.env` and passes it to the container as `LOG_LEVEL`. Because each service maps only its own slugged variable, the correct per-module level is delivered to each backend even when multiple modules run together. Remote modules therefore remain at `INFO` while local build-mode modules emit `DEBUG`.

### 13.2 Backend Logging Contract

Every backend `main.py` reads the standard `LOG_LEVEL` variable — no module-specific code is required:

1. Read `LOG_LEVEL` at import time:
   ```python
   _log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
   _app_log_level = getattr(logging, _log_level_str, logging.INFO)
   logging.getLogger().setLevel(_app_log_level)
   ```
2. Provide a startup event handler that re-applies the level after uvicorn configures its own logging:
   ```python
   @app.on_event('startup')
   async def _configure_logging():
       _level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
       _level = getattr(logging, _level_str, logging.INFO)
       root = logging.getLogger()
       root.setLevel(_level)
       if not root.handlers:
           handler = logging.StreamHandler()
           handler.setLevel(_level)
           handler.setFormatter(logging.Formatter('%(levelname)s - %(name)s - %(message)s'))
           root.addHandler(handler)
   ```

This guarantees that application loggers respect the deploy-script-computed per-module level regardless of uvicorn's default `INFO` configuration, while keeping backend code completely generic.
