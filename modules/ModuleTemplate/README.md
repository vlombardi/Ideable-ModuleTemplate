# ModuleTemplate

`ModuleTemplate` is the reference remote module used to create new modules for Ideable.

Distribution contract:
- `ModuleTemplate` is source-shared with module developers.
- `HostApp` is consumed as a ready-to-run Docker image in external developer environments (no HostApp source required).
- In maintainer repositories where both codebases coexist, `ModuleTemplate` is exported with `git subtree split`.

It demonstrates the complete integration pattern:
- frontend remote via Module Federation,
- backend API with shared auth model,
- module-local database,
- compose-based deployment on shared network.

## MF 2.0 UI Composition (General Concepts)

`ModuleTemplate` represents the **remote-side contract** in the HostApp + remote composition model.

### Host/remote split

- HostApp owns shell UI (header, menu, route guards, overall layout).
- ModuleTemplate contributes only module pages and module-specific routes/menu metadata.
- HostApp loads ModuleTemplate through MF 2.0 runtime manifests and mounts module pages in the host content area.

### Manifest and route principles

- Remote must expose `./moduleManifest`.
- `menuItems[].href` must be HostApp absolute paths (`/<slug>/...`).
- `routes[].path` must be module-local (`/...`, without duplicating base path).
- Permission naming follows `<module_slug>.<resource>.<action>`.

### L&F compatibility principles

- Default mode: inherit HostApp visual tokens and interaction patterns.
- Override mode: optional module-specific visual overrides, scoped to module root only.
- Remote CSS must stay isolated via module prefix and must not mutate host-global selectors.

## HostApp and Module - Integration logic

`ModuleTemplate` is the blueprint for a HostApp-compatible remote module.

Integration uses two coordinated configuration files:

- Host side: `modules/HostApp/config/modules_menu_mapping.json`
- Remote side: `modules/ModuleTemplate/config/menu_definition.json`

Integration files diagram (what each side must provide):

```text
┌──────────────────────────── Host Side (HostApp) ────────────────────────────┐
│ Required files                                                               │
│ 1) modules/HostApp/config/modules_menu_mapping.json                          │
│    - menu_mapping[]                                                          │
│    - item keys: module, module_menu_item_code_path, sub_items               │
│      (optional: menu_item_code, menu_item_name, icon)                       │
│                                                                              │
│ 2) modules/HostApp/frontend/SOURCES/public/module-registry.json              │
│    - modules[] entries with name, entry, basePath                            │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ resolves module_menu_item_code_path
                                ▼
┌────────────────────────── Remote Side (ModuleTemplate) ──────────────────────┐
│ Required files                                                               │
│ 1) modules/ModuleTemplate/config/menu_definition.json                        │
│    - menu_definition[]                                                       │
│    - item keys: menu_item_code, menu_item_name, icon, sub_items             │
│      (optional: routing)                                                     │
│                                                                              │
│ 2) modules/ModuleTemplate/frontend/SOURCES/src/moduleManifest.ts             │
│    - slug, menuItems[], routes[], permissions[]                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ combined at runtime by HostApp
                                ▼
                      Integrated sidebar, routes, and permissions
```

Purpose split:

- `modules_menu_mapping.json` decides which remote menu nodes are exposed/renamed/iconized in HostApp.
- `menu_definition.json` is the remote authoritative menu tree used by host mapping resolution.

### Self-contained compatibility contract (defined here)

ModuleTemplate compatibility must be understandable without opening HostApp files. The minimum contract is:

- Remote must expose `./moduleManifest` with:
  - `slug`
  - `menuItems[]` (`name`, `href`, `icon`, optional `order`)
  - `routes[]` (`path`, lazy `component`)
  - optional `permissions[]`
- `menu_definition.json` must contain `menu_definition[]` where each item includes:
  - `menu_item_code`, `menu_item_name`, `icon`, `sub_items[]`
  - optional `routing`
- Host-side mapping compatibility requirement (for the host mapping file):
  - `menu_mapping[]` with `module`, `module_menu_item_code_path`, `sub_items[]`
  - optional `menu_item_code`, `menu_item_name`, `icon`
- External remote backend namespace is `/module/<slug>/*`.
- Host authorization context endpoint is `GET /api/me`.

## HostApp and Module - Development process

For compatibility, start from `SPECS/` and only then implement `SOURCES/`.

`modules/ModuleTemplate/SPECS/` (or cloned module SPECS) must define:

- module integration constraints matching HostApp contracts,
- frontend/backend/database expectations for composed runtime behavior.

`modules/ModuleTemplate/config/menu_definition.json` defines the module menu hierarchy and routing fragments.

HostApp side specs must provide the matching mapping in `modules/HostApp/config/modules_menu_mapping.json`.

For source-sharing of ModuleTemplate only (Option B internal layout), use:

```bash
./scripts/export_moduletemplate_subtree.sh <target_repo_url> [target_branch] [source_ref]
```

Example:

```bash
./scripts/export_moduletemplate_subtree.sh git@github.com:org/ideable-module-template.git main HEAD
```

After full correct process execution (`SPECS` → `SOURCES` → build/deploy), deployment output must include:

- `deployment_root/modules/ModuleTemplate/menu_definition.json`
- `deployment_root/modules/HostApp/modules_menu_mapping.json`

## HostApp and Module - Runtime configuration

After deployment, runtime customization is performed from `deployment_root/` by editing:

- `deployment_root/.env`
- `deployment_root/modules/ModuleTemplate/menu_definition.json`
- `deployment_root/modules/HostApp/modules_menu_mapping.json`
- `deployment_root/modules/HostApp/favicon.png`
- `deployment_root/modules/HostApp/login_bg.png`

Specification requirement: these files are runtime configuration and must be mounted as Docker read-only volumes (`:ro`) so operators can adjust menu composition and branding without rebuilding module images.

Required mount intent:

- remote frontend container mounts `menu_definition.json`
- HostApp frontend container mounts `modules_menu_mapping.json`
- HostApp branding consumers mount `favicon.png` and `login_bg.png`

## Components

- `frontend`: Rsbuild + Module Federation remote.
- `backend`: FastAPI service (externally routed as `/module/template/*`).
- `database`: PostgreSQL schema with `template_items` example table.
- `module.json`: module metadata (`slug`, `displayName`, `role`, `cssPrefix`).

## Configuration

Main configuration file:
- `modules/ModuleTemplate/.env`

Important variables:
- `APP_SLUG`, `APP_NAME`
- `TEMPLATE_BACKEND_PORT`, `TEMPLATE_FRONTEND_PORT`, `TEMPLATE_POSTGRES_PORT`
- `TEMPLATE_ENTITIES_DB_*` (entities DB target)
- `TEMPLATE_AUTH_DB_*` (authorization seed DB target)
- `AUTHENTIK_JWKS_URL`
- `HOSTAPP_API_URL`
- `VITE_TEMPLATE_API_URL`
- `VITE_TEMPLATE_LF_MODE` (`hostapp` default, optional `module` override mode)

Compose file:
- `modules/ModuleTemplate/docker-compose.yml`

## How to Clone and Customize

1. Copy `modules/ModuleTemplate/` to `modules/<NewModuleName>/`.
2. Update `module.json`:
   - `name`
   - `slug`
   - `displayName`
   - `cssPrefix`
   - ports
3. Update `.env` values for new ports/URLs.
4. Update frontend:
   - MF `name` and `assetPrefix` in `frontend/SOURCES/rsbuild.config.ts`
   - menu/routes/permissions in `frontend/SOURCES/src/moduleManifest.ts`
   - Tailwind prefix in `frontend/SOURCES/tailwind.config.js`
5. Update backend:
   - API base prefix (for example `/module/<newslug>/api`)
   - permission namespace (`<newslug>.<resource>.<action>`)
6. Update database schema (`database/SOURCES/initdb/datamodel.sql`).
7. Add/rename compose file to module naming convention.
8. Enable module in `modules/enabled.md`.

## Full Compatible-Module Creation Workflow (from Template to Deploy)

Use this sequence to create a new module that is integrable/compatible with HostApp.

### A. Copy and rename

1. Copy `modules/ModuleTemplate/` to `modules/<NewModuleName>/`.
2. Define final slug and prefix (for example `inventory` + `inventory-`).
3. Apply rename consistently in:
   - `module.json`
   - `.env`
   - frontend MF config and manifest
   - backend permission namespace
   - compose service names and paths

### B. Align specs first (`SPECS`)

Before implementation, update module specs to declare:

- entity and authorization model
- route/menu contract
- UI widget behavior and L&F expectations
- backend authorization contract
- deployment/runtime expectations

### C. Implement sources (`SOURCES`)

Apply implementation changes in:

- `frontend/SOURCES/` (MF config, pages, manifest, styles)
- `backend/SOURCES/` (API, auth/JWKS validation, HostApp context integration)
- `database/SOURCES/` (schema + seed/bootstrap SQL)

### D. Build and deploy

From repository root:

```bash
python3 scripts/build_and_deploy.py
./deployment_root/start.sh
```

This regenerates module deployment artifacts, merged compose, and startup scripts.

### E. Test and validate

- Run module tests (`frontend/TESTS`, `backend/TESTS`, `database/TESTS` where applicable).
- Validate remote registration in HostApp (`/module-registry.json`, `/remotes/<slug>/mf-manifest.json`).
- Validate menu/route composition, auth behavior, and L&F compatibility.

Mandatory L&F parity validation:

```bash
./scripts/check_moduletemplate_lf_parity.sh
```

This runner executes:
- automated source-level parity contracts,
- Playwright visual snapshots for HostApp/ModuleTemplate shared screens.

### F. Keep compatibility contract aligned

Whenever HostApp integration contracts evolve, update ModuleTemplate specs and implementation in the same change cycle.

## HostApp Integration

Remote module integration expectations:
- frontend exposes `./moduleManifest` for dynamic route/menu loading,
- backend validates JWT via Authentik JWKS,
- backend queries HostApp `GET /api/me` for effective permissions,
- permissions follow `<module_slug>.<resource>.<action>` naming.

After enabling the module, run:

```bash
python3 scripts/build_and_deploy.py
```

This regenerates:
- module registry for HostApp frontend,
- per-module deployment artifacts,
- merged `deployment_root/docker-compose.yml`.

## Related Specs

- `modules/ModuleTemplate/SPECS/base-specs.md`
- `modules/ModuleTemplate/frontend/SPECS/base_specs.md`
- `modules/ModuleTemplate/backend/SPECS/base_specs.md`
- `modules/HostApp/SPECS/module-integration-specs.md`
