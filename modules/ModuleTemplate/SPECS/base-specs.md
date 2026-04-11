# IMPORTANT: Read This First

**This file (`base-specs.md`) is the MANDATORY starting point for any coding agent action on this module and is the baseline contract for all remote modules unless explicitly overridden.**

Before implementing, modifying, or troubleshooting any Module component, you MUST:
1. Read this entire file.
2. Follow all references in the specification chain.
3. Read the relevant sub-module `base-specs` file fully.
4. Follow the related `general_bug_avoider.md` files for the touched sub-modules.

## General Deployment Rules Reference

This module follows the deployment rules defined in `rules/general-guidelines.md`. Critical requirements:

- **No `build:` sections in docker-compose**: All Docker images must be pre-built before deployment.
- **No `SOURCES/` references in docker-compose volume mounts**: Only deployment paths are allowed.
- **No `Dockerfile` in deployment**: Dockerfiles stay in `SOURCES/` only.

See `rules/general-guidelines.md` lines 98-115 for complete deployment constraints.

## Build-time SPECS JSON artifact rule

- Any `.json` file located in `SPECS/` that is required at deployment/runtime must be materialized into the related sub-module `DIST/` during the build step.
- These JSON files must not be read directly from `SPECS/` by runtime containers.
- If a sub-module needs non-standard copy logic for these files, define it in that sub-module `SPECS/build.sh` so `scripts/build_and_deploy.py` can execute it during build.

# ModuleTemplate Base Specs

ModuleTemplate is the baseline remote-module specification for Ideable modules and also serves as a starter reference implementation.

## Distribution and ownership contract

- ModuleTemplate is the only source-distributed blueprint for third-party module developers.
- HostApp source code is maintainer-internal and is distributed externally only as ready-to-run Docker images.
- In the maintainer repository, HostApp and ModuleTemplate may coexist in-tree, but ModuleTemplate must remain independently exportable.
- Official export mechanism for public sharing is `git subtree split --prefix modules/ModuleTemplate`.

Required export helper:
- `scripts/export_moduletemplate_subtree.sh`

## Purpose

- Demonstrate the expected structure of a remote module.
- Provide a minimal but complete reference implementation.
- Ensure compatibility with HostApp host-module integration patterns.

## Integration Reference

- Follow HostApp integration rules in:
  - `modules/HostApp/SPECS/module-integration-specs.md`

## Self-contained minimum integration contract

ModuleTemplate must remain understandable even without reading HostApp files. The minimum contract is explicitly defined here:

- Remote frontend exposes `./moduleManifest` with fields:
  - `name`, `slug`, `menuItems[]`, `routes[]`, optional `permissions[]`
- `menuItems[]` entries include: `name`, `href`, `icon`, optional `order`
- `routes[]` entries include: `path`, lazy `component`
- Remote `config/menu_definition.json` exposes `menu_definition[]`; each node includes:
  - `menu_item_code`, `menu_item_name`, `icon`, `sub_items[]`, optional `routing`
- Host-side compatibility requirement (for host mapping file):
  - `menu_mapping[]` items include `module`, `module_menu_item_code_path`, `sub_items[]`
  - optional: `menu_item_code`, `menu_item_name`, `icon`
- External remote backend namespace is `/module/<slug>/*`
- Host authorization context endpoint required by remotes is `GET /api/me`

## Frontend Remote Setup

- Build tool: Rsbuild.
- Module Federation role: remote.
- Exposes `./moduleManifest` for dynamic menu/routes integration.
- Uses module-specific Tailwind prefix: `template-`.
- Must not own or define HostApp branding variables (for example `VITE_APP_TITLE`).

## L&F source-of-truth rule

- ModuleTemplate frontend L&F definitions (tokens, shared table/control patterns, class structure conventions) are authoritative for reusable remote-module UX.
- HostApp maintainers must align HostApp shared component behavior to ModuleTemplate L&F contracts for common reusable patterns.
- Any divergence between HostApp reusable patterns and ModuleTemplate contracts must be explicitly documented in both HostApp and ModuleTemplate SPECS before release.

Mandatory parity validation:
- automated parity contract tests in `modules/ModuleTemplate/frontend/TESTS/test_lf_parity_contract.py`
- visual snapshot parity checks in `modules/ModuleTemplate/frontend/TESTS/playwright/`
- orchestrated runner: `scripts/check_moduletemplate_lf_parity.sh`

Verification URLs (deployed environment):
- `https://<host>/module-registry.json`
  - Must contain a `template` entry with `entry: "/remotes/template/mf-manifest.json"`.
- `https://<host>/remotes/template/mf-manifest.json`
  - Must be reachable and include exposed module `./moduleManifest`.

## Backend Authentication and Authorization

- FastAPI backend validates JWT tokens against Authentik JWKS.
- Backend queries HostApp `GET /api/me` to resolve effective permissions.
- Protected endpoints enforce permissions in `template.items.*` namespace.

## Database Schema

- Includes a single example entity table: `template_items`.
- Uses standard audit columns (`au_creation_timestamp`, `au_last_update_timestamp`, `au_created_by_user`, `au_last_updated_by_user`).
- The authoritative schema source is `modules/ModuleTemplate/database/SPECS/datamodel.sql`.
- `datamodel.sql` is initially authored in `SPECS/` during the specifications step.
- During `/Specs2Sources`, schema SQL is materialized to `modules/ModuleTemplate/database/SOURCES/initdb/datamodel.sql` for runtime initialization.

## Database Targets (Entities vs Authorization)

- ModuleTemplate uses two independent database targets configured via env vars:
  - Entities DB target (`TEMPLATE_ENTITIES_DB_*`) for module entities and backend runtime.
  - Authorization DB target (`TEMPLATE_AUTH_DB_*`) for `authorization.sql` RBAC seeding.
- `authorization.sql` must always run against the authorization DB target.
- `datamodel.sql` is for entities schema lifecycle only.
- `datamodel.sql` and `authorization.sql` must be executed only once during the first bootstrap execution.
- SQL execution must be handled by a dedicated module bootstrap container that:
  - explicitly depends on HostApp authorization bootstrap completion before executing module SQL bootstrap;
  - waits until both DB targets are up and accepting connections;
  - then executes `datamodel.sql` on the entities DB target and `authorization.sql` on the authorization DB target.
- If entities DB target resolves to HostApp DB target (`HOSTAPP_DB_*`), `template-database` must not be instantiated.

Implementation-time mandatory rule:
- Any compose/runtime implementation for ModuleTemplate bootstrap is non-compliant unless it preserves an explicit service dependency that guarantees HostApp authorization bootstrap completion before ModuleTemplate authorization seeding starts.

## Entity-to-menu consistency rules

- Main entities are derived from `modules/ModuleTemplate/database/SPECS/datamodel.sql`.
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
- Produces Docker image only; no DIST folder.

### backend
- Build Docker image: `docker build --no-cache -t template/backend:latest ./backend/SOURCES/`
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
- Volume mounts reference deployment paths only (e.g., `./modules/ModuleTemplate/database/initdb` not `./database/SOURCES/initdb`)
- Deployed compose uses `env_file: - ../../.env` (pointing to the merged `deployment_root/.env`)
- No hardcoded values where an env var is available

## Deployment Paths

- Database init scripts: `database/DIST/initdb/` → `deployment_root/modules/ModuleTemplate/database/initdb/`
- Docker compose: `docker-compose.yml` → `deployment_root/modules/ModuleTemplate/docker-compose.yml`
- Environment variables: `modules/ModuleTemplate/.env` is merged into `deployment_root/.env` by `scripts/build_and_deploy.py`
