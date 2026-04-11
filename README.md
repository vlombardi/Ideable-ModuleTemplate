# Ideable

Ideable is a modular micro-frontend platform built around a host module (`HostApp`) and dynamically integrated remote modules.

The platform combines:
- Module Federation 2.0 for runtime frontend composition,
- a shared authentication/authorization model (Authentik + HostApp RBAC),
- containerized deployment with per-module compose files and a merged runtime compose.

## Repositories

### Main Ideable repository (this repo)

This repository is the **Ideable Framework maintainer codebase**. It contains:

- **`modules/HostApp/`** — the MF 2.0 host module with full specifications, source code, and tests. Its purpose is to define, maintain, and evolve the Ideable Framework as a whole: shell, authentication, authorization, routing, and the integration contract for remote modules.
- **`modules/ModuleTemplate/`** — the MF 2.0 remote module reference implementation with full specifications, source code, and tests. Its purpose is to define, maintain, and evolve the canonical blueprint for Ideable-compatible remote modules.

This repo is used exclusively by Ideable maintainers. It is **not** the starting point for external module developers.

### Ideable-ModuleTemplate repository

[`Ideable-ModuleTemplate`](https://github.com/vlombardi/Ideable-ModuleTemplate) is a **separate GitHub template repository** derived from this one. Its purpose is to offer external developers an initial blueprint for creating MF 2.0 remote modules that are compatible with Ideable HostApp.

Key structural differences from the main repo:
- `modules/HostApp/` is present **only with the `config/` folder** to allow HostApp customization. No SPECS, sub-modules, or TESTS for HostApp are included.
- `modules/ModuleTemplate/` contains the full module source (SPECS, SOURCES, TESTS) as the starting point for customization.
- The `modules/enabled.md` file controls which modules participate in the build and deployment process.

### Relationship between repositories

Maintainers keep `Ideable-ModuleTemplate` in sync with the main repo using:

```bash
./scripts/master_only/push-updates-to-ModuleTemplate-repo.sh
```

This script copies the relevant files (module sources, shared scripts, rules, tooling configuration) from the main repo to the template repo and force-pushes to its `main` branch.

External developers who started a module from the template can pull the latest framework updates (e.g., updated base specs, compatibility scripts) without losing their customizations:

```bash
./scripts/module_only/sync-template-updates.sh
```

This script only updates files that are not meant to be customized by developers — such as `base-specs.md` (defining the module compatibility contract with Ideable HostApp) and shared framework scripts. It **never touches** module source code, configuration files (`module.json`, `docker-compose.yml`, `.env`), or any developer customizations.

## Architecture

### HostApp (host module)

`HostApp` is responsible for:
- authentication and authorization APIs,
- shared UI shell and navigation,
- loading enabled remote modules from `public/module-registry.json`,
- exposing `GET /api/me` as the authorization context endpoint for external modules.

### Remote modules

Remote modules:
- expose a frontend manifest through Module Federation,
- publish backend APIs under `/module/<slug>/*`,
- validate JWTs via Authentik JWKS,
- resolve effective permissions via HostApp `GET /api/me`.

`ModuleTemplate` is the reference remote implementation and the basis of the `Ideable-ModuleTemplate` template repo.

## UI Composition Model (Module Federation 2.0)

The UI is composed at runtime by combining two layers:

1. **Host layer (`HostApp`)**
   - Owns shell layout (header, navigation, content area, shared route guards).
   - Loads remote module manifests from `module-registry.json`.
   - Mounts remote routes under each module base path.
   - Keeps host routes available even when a remote module is unavailable.

2. **Remote layer (additional modules)**
   - Exposes `./moduleManifest` through MF 2.0.
   - Contributes menu entries, route descriptors, and permissions.
   - Renders only module content pages (not host shell elements).
   - Uses HostApp auth context and authorization model.

### UI and L&F compatibility principles

- HostApp is the shell authority; remotes are content providers.
- Remotes use their own CSS prefix (`<slug>-`) to avoid collisions.
- Default L&F in remotes must match HostApp tokens and interactions.
- Module-specific L&F is allowed only via module-scoped overrides.
- Remote code must never mutate host-global selectors (`html`, `body`, `*`).

### Runtime integration flow

At startup/runtime:

1. HostApp fetches `/module-registry.json`.
2. For each enabled module, HostApp loads `/remotes/<slug>/mf-manifest.json`.
3. HostApp resolves `./moduleManifest` from the remote.
4. HostApp merges remote menu/routes into the shell.
5. User navigation enters remote pages inside HostApp content area.

## HostApp and Module - Integration logic

HostApp and each remote module are integrated through a two-file menu contract:

- HostApp defines **where and how** module menu nodes are positioned using `modules/HostApp/config/modules_menu_mapping.json`.
- Each remote module defines **what menu tree it exposes** using `modules/<RemoteModule>/config/menu_definition.json`.

Logical relation:

```text
┌──────────────────────────────────────────────────────────────────┐
│ HostApp                                                         │
│                                                                  │
│  config/modules_menu_mapping.json                                │
│  - selects module: <slug>                                        │
│  - points to module_menu_item_code_path                          │
│  - can override label/icon                                       │
└───────────────┬──────────────────────────────────────────────────┘
                │ resolves path against remote menu_definition
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ Generic Remote Module (blueprint = ModuleTemplate)              │
│                                                                  │
│  config/menu_definition.json                                     │
│  - authoritative module menu tree                                │
│  - menu_item_code hierarchy                                      │
│  - routing fragments per node                                    │
└───────────────┬──────────────────────────────────────────────────┘
                │ combined with MF ./moduleManifest (basePath/routes)
                ▼
        HostApp sidebar + integrated routes at runtime
```

File purposes:

- `modules/HostApp/config/modules_menu_mapping.json` — host-side composition map for remote menu injection; references remote nodes through `module_menu_item_code_path`.
- `modules/<RemoteModule>/config/menu_definition.json` — remote-side canonical menu definition used by host mapping resolution; copied/adapted by new modules created from `ModuleTemplate`.

## HostApp and Module - Development process

For HostApp + Remote compatibility, `SPECS/` must be the source of truth before implementation.

`modules/HostApp/SPECS/` must include at least:
- integration contract (`module-integration-specs.md`),
- auth and base specs aligned with runtime composition.

`modules/<RemoteModule>/SPECS/` (blueprint: `modules/ModuleTemplate/SPECS/`) must include at least:
- module metadata/contract specs,
- frontend/backend/database integration expectations.

After a correct full process (`SPECS` → `SOURCES` → build/deploy), deployment artifacts must include:
- `deployment_root/modules/HostApp/config/modules_menu_mapping.json`
- `deployment_root/modules/<RemoteModule>/config/menu_definition.json`

## HostApp and Module - Runtime configuration

At runtime, operators customize the deployed project from `deployment_root/`.

Main editable runtime files:

- `deployment_root/.env`
- `deployment_root/modules/HostApp/config/modules_menu_mapping.json`
- `deployment_root/modules/HostApp/config/favicon.png`
- `deployment_root/modules/HostApp/config/login_bg.png`
- `deployment_root/modules/<RemoteModule>/config/menu_definition.json`

All configuration files under each module's `config/` folder are mounted as Docker read-only volumes (`:ro`) so they can be changed without rebuilding images. The `config/` folder is copied verbatim from `modules/<MODULE>/config/` to `deployment_root/modules/<MODULE>/config/` during the deployment step.

## Tech Stack

- Frontend: React 18, TypeScript, Rsbuild, Module Federation 2.0, Tailwind CSS
- Backend: FastAPI, SQLAlchemy, Pydantic
- Auth: Authentik (OIDC/OAuth2 + JWKS)
- Edge routing: Traefik
- Database: PostgreSQL / TimescaleDB
- Runtime: Docker + Docker Compose

## Project Structure

### Main Ideable repository

```
Ideable/                              ← main maintainer repo
├── modules/
│   ├── enabled.md                    ← controls build/deploy scope
│   ├── dependencies.md               ← inter-module dependency graph
│   ├── HostApp/                      ← full HostApp codebase
│   │   ├── module.json
│   │   ├── docker-compose.yml
│   │   ├── config/                   ← runtime-mounted customization files
│   │   ├── SPECS/
│   │   ├── TESTS/
│   │   ├── frontend/
│   │   ├── backend/
│   │   ├── database/
│   │   ├── authentik/
│   │   └── traefik/
│   └── ModuleTemplate/               ← full ModuleTemplate codebase
│       ├── module.json
│       ├── docker-compose.yml
│       ├── config/                   ← runtime-mounted customization files
│       ├── SPECS/
│       ├── TESTS/
│       ├── frontend/
│       ├── backend/
│       └── database/
├── scripts/
│   ├── master_only/                  ← maintainer-only scripts
│   │   ├── build_and_deploy.py
│   │   └── push-updates-to-ModuleTemplate-repo.sh
│   ├── module_only/                  ← scripts shared with module repos
│   │   └── sync-template-updates.sh
│   ├── common/                       ← scripts shared across all repos
│   └── runtime/                      ← deployment runtime scripts
├── rules/
│   └── general-guidelines.md
├── .windsurf/workflows/
└── deployment_root/
```

### Ideable-ModuleTemplate repository (external developer starting point)

```
Ideable-ModuleTemplate/               ← GitHub template repo for external devs
├── modules/
│   ├── enabled.md
│   ├── HostApp/
│   │   ├── module.json               ← HostApp metadata (read-only reference)
│   │   └── config/                   ← HostApp customization files only
│   └── <YourModule>/                 ← rename from ModuleTemplate
│       ├── module.json
│       ├── docker-compose.yml
│       ├── config/
│       ├── SPECS/
│       ├── TESTS/
│       ├── frontend/
│       ├── backend/
│       └── database/
├── scripts/
│   ├── module_only/
│   │   └── sync-template-updates.sh  ← pull framework updates from template
│   ├── common/
│   └── runtime/
├── rules/
│   └── general-guidelines.md
└── deployment_root/
```

## Development Workflow

Ideable uses a specification-first process:

1. Define or update module specs in `SPECS/`.
2. Implement/update source code in `SOURCES/`.
3. Build and deploy module artifacts.
4. Run and validate integrated runtime.
5. Update specs and docs whenever architecture changes.

Built-in workflows:
- `/ImplementSpecs` for implementing sources from specs,
- `/Build&Deploy` for building and deploying artifacts,
- `/Tests2Fixes` for running tests and fixing regressions.

## Creating a Compatible Module

External developers start from the `Ideable-ModuleTemplate` GitHub template repository (see [Repositories](#repositories) above). Internal maintainers can copy `modules/ModuleTemplate/` directly.

Use this procedure when creating a new remote module that must be integrable with HostApp.

### 1) Initialize the module

Run the initialization script to copy and rename `ModuleTemplate` into a new module in one step:

```bash
./scripts/module_only/module-init.sh <NewModuleName>
```

This script:
- Renames `modules/ModuleTemplate/` to `modules/<NewModuleName>/`.
- Replaces all occurrences of `ModuleTemplate` / `template` / `template-` with the new name, slug, and CSS prefix across all source files, `module.json`, `docker-compose.yml`, `package.json`, and `.env`.
- Creates `modules/<NewModuleName>/.env` from `.env.example` with prefixed env vars.

After running it, review the output and adjust anything that needs manual attention.

### 2) Review and complete module identity

Verify `modules/<NewModuleName>/module.json`:

- `name`, `slug`, `displayName`, `cssPrefix` are correctly set.
- Module ports (`frontendPort`, `backendPort`) do not conflict with other enabled modules.

Keep slug/prefix coherent across all files (example: `inventory`, `inventory-`).

### 3) Update module environment

Edit `modules/<NewModuleName>/.env`:

- module ports (`*_BACKEND_PORT`, `*_FRONTEND_PORT`, optional DB port)
- backend URLs (`HOSTAPP_API_URL`, `AUTHENTIK_JWKS_URL`)
- frontend API URL (`VITE_<...>_API_URL`)
- DB target variables (entities/auth) if module uses split DB targets

### 4) Update frontend MF configuration

Update frontend files:

- `frontend/SOURCES/rsbuild.config.ts`
  - MF `name`
  - exposed module path (keep `./moduleManifest` contract)
  - `assetPrefix` to `/remotes/<slug>/`
- `frontend/SOURCES/src/moduleManifest.ts`
  - module `name`, `slug`
  - `menuItems` with HostApp absolute hrefs (`/<slug>/...`)
  - `routes` with module-local paths (`/...`, no base path duplication)
  - permission namespace `<slug>.<resource>.<action>`
- `frontend/SOURCES/tailwind.config.js`
  - set module prefix `<slug>-`

### 5) Update backend and authorization namespace

Update backend configuration/code to:

- validate JWT using Authentik JWKS
- query HostApp `GET /api/me` for effective permission context
- enforce permissions with `<slug>.<resource>.<action>` namespace

### 6) Update database model and bootstrap scripts

Update database artifacts according to module needs:

- `database/SOURCES/initdb/datamodel.sql`
- `database/SOURCES/initdb/authorization.sql` (or equivalent)
- related module database specs and tests

### 7) Rename/update compose references

Ensure compose and service naming are aligned with new slug/module naming conventions.

### 8) Align specs before implementation

Before coding, update `SPECS/` so they are the source of truth for:

- manifest contract
- route/menu rules
- UI widgets and L&F behavior
- authorization and DB rules

### 9) Enable and execute specs-to-deploy flow

1. Enable module in `modules/enabled.md`.
2. Run build/deploy:

```bash
python3 scripts/build_and_deploy.py
```

3. Start runtime:

```bash
./deployment_root/start.sh
```

4. Run module and integration tests.

Mandatory L&F parity validation before integration releases:

```bash
./scripts/check_moduletemplate_lf_parity.sh
```

This follows the standard development process:

1. `SPECS` → define/update behavior
2. `SOURCES` → implement behavior
3. Build/deploy artifacts
4. Run integrated stack
5. Execute tests and fix regressions

## Module Federation Integration

- Host runtime fetches registry from `/module-registry.json` at runtime.
- Registry source file: `modules/HostApp/frontend/SOURCES/public/module-registry.json` (copied to served root).
- Registry entries point to remote manifests at `/remotes/<slug>/mf-manifest.json`.
- HostApp mounts remote routes and sidebar menu sections dynamically.
- Remote load failures are handled gracefully (host static routes keep working).

## Authentication and Authorization

- Frontend performs OIDC login against Authentik.
- Backend services validate Bearer JWT via Authentik JWKS.
- HostApp serves authorization context at `GET /api/me`.
- Permission naming convention: `<module_slug>.<resource>.<action>`.

## Deployment Model

- Each module ships its own compose file (`docker-compose.yml` or supported naming variant).
- `scripts/build_and_deploy.py` deploys per-module compose/env files to `deployment_root/`.
- A merged `deployment_root/docker-compose.yml` is generated for enabled modules.
- Start/stop scripts are generated under `deployment_root/`.

## Enabled Modules and Remote Image Support

The `modules/enabled.md` file controls which modules participate in the build and deployment process. Each line follows the format:

```
<ModuleName>: <enabled|disabled> [<local|remote>]
```

- `enabled` / `disabled` — whether the module is included in the build/deploy cycle.
- `local` (default) — the module's full source is present in the `modules/<MODULE>/` folder and will be built and deployed locally.
- `remote` — the module is not built locally. Only its Docker images are expected to be available in a Docker registry (local or remote, as configured by `HOSTAPP_DOCKER_REGISTRY`; if that variable is not set, images are assumed to be present in the local Docker daemon, e.g., already pulled or restored from a previous `docker save`). In this case the `modules/<MODULE>/` folder contains only `module.json`, `config/`, and `.env` — no SPECS or sub-module source folders.

Example (`modules/enabled.md` in a module repo):

```
HostApp: enabled remote
MyModule: enabled local
```

This means HostApp is included via Docker images only, and MyModule is fully built from source.

## Quick Start

1. Configure enabled modules in `modules/enabled.md`.
2. Check module settings in `modules/<Module>/.env`.
3. Build/deploy enabled modules:

```bash
python3 scripts/build_and_deploy.py
```

4. Start services:

```bash
./deployment_root/start.sh
```

5. Stop services:

```bash
./deployment_root/stop.sh
```

## Kubernetes Readiness Notes

The platform is designed to stay Kubernetes-friendly:
- service-to-service communication uses DNS-style service names,
- module boundaries remain explicit (frontend/backend/database per module),
- host-path assumptions are minimized,
- health endpoints are available for orchestrator probes.

## License

This project is licensed under AGPL 3.0. See `LICENSE` for details.

