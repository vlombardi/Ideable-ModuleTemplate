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
It exports the maintainer-repo root documentation as `IDEABLE-README.md` and the ModuleTemplate documentation as `MODULE-README.md` in the exported template repo, then leaves placeholder `README.md` files in the repo root and module root for template users to customize.

External developers who started a module from the template can pull the latest framework updates (e.g., updated base specs, compatibility scripts) without losing their customizations:

```bash
./scripts/module_only/sync-template-updates.sh
```

This script only updates files that are not meant to be customized by developers — such as the shared framework specs under `SPECS/ideable-framework-specs/` and shared framework scripts. Files outside that folder but still under `SPECS/` are treated as module-specific specs. For env files, it syncs `.env.example` files and backfills only missing keys into the matching `.env` files; existing `.env` values are preserved.

## Architecture

### HostApp (host module)

`HostApp` is responsible for:
- authentication and authorization APIs,
- shared UI shell and navigation,
- loading enabled remote modules from `public/module-registry.json` (manifest + `remoteEntry` URLs),
- exposing Authentik-backed admin/control surfaces and validating JWTs against Authentik JWKS.

### Remote modules

Remote modules:
- expose a frontend manifest through Module Federation,
- publish backend APIs under `/module/<slug>/*`,
- validate JWTs via Authentik JWKS,
- resolve permissions directly from Authentik JWT claims.

`ModuleTemplate` is the reference remote implementation and the basis of the `Ideable-ModuleTemplate` template repo. Its framework contract lives in `modules/ModuleTemplate/SPECS/ideable-framework-specs/`.

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
2. For each enabled module, HostApp loads `/remotes/<slug>/mf-manifest.json` (registry `entry`).
3. HostApp uses the manifest to locate `/remotes/<slug>/remoteEntry.js` (registry `remoteEntry`, falling back to `entry`) and resolves `./moduleManifest` from the remote.
4. HostApp merges remote menu/routes into the shell.
5. User navigation enters remote pages inside HostApp content area.

## HostApp and Module - Integration logic

HostApp and each remote module are integrated through a two-file menu contract:

- HostApp defines **where and how** module menu nodes are positioned using `modules/HostApp/config/modules_menu_mapping.json`.
- Each remote module defines **what menu tree it exposes** using `modules/<RemoteModule>/config/menu_definition.json`.
- Each remote module may optionally propose **its own host placement** by providing `modules/<RemoteModule>/config/modules_menu_mapping.json`.

**Menu mapping production at deploy time:**

1. If `modules/HostApp/config/modules_menu_mapping.json` exists, it is used **directly** as the explicit composition map.
2. If the HostApp file does **not** exist, `create-merged-configuration.sh` auto-merges all enabled modules' `config/modules_menu_mapping.json` files into a single `deployment_root/modules/HostApp/config/modules_menu_mapping.json`.

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

- `modules/HostApp/config/modules_menu_mapping.json` — explicit host-side composition map for remote menu injection; when present, overrides any module-proposed mappings.
- `modules/<RemoteModule>/config/modules_menu_mapping.json` — optional module-proposed host placement; merged into the deployed HostApp config when no explicit HostApp mapping exists.
- `modules/<RemoteModule>/config/menu_definition.json` — remote-side canonical menu definition used by host mapping resolution; copied/adapted by new modules created from `ModuleTemplate`.

HostApp menu mapping now also supports prefix-based nesting under an existing HostApp menu code.

- Example: `ADMIN.MYMENU` renders the module node `MYMENU` under the built-in HostApp `Admin` branch.
- Nested mapped trees are rendered up to four levels deep total.

When using this form, the first path segment must match the HostApp parent menu code.

## HostApp and Module - Development process

For HostApp + Remote compatibility, the relevant `SPECS/` files must be the source of truth before implementation.

`modules/HostApp/SPECS/` must include at least:
- integration contract (canonical copy in `modules/ModuleTemplate/SPECS/ideable-framework-specs/module-integration-specs.md`),
- auth and base specs aligned with runtime composition.

`modules/<RemoteModule>/SPECS/` is split into:
- the framework-owned `ideable-framework-specs/` folders that must stay aligned across HostApp, ModuleTemplate, and derived remotes,
- the remaining `SPECS/` files for module-specific specifications and implementation contracts.

Framework-owned contracts live in the `ideable-framework-specs/` folders under `SPECS/`, `backend/SPECS/`, `database/SPECS/`, and `frontend/SPECS/`; those files are the shared baseline and must be kept in sync across the ecosystem.

After a correct full process (`SPECS` → `SOURCES` → build/deploy), deployment artifacts must include:
- `deployment_root/modules/HostApp/config/modules_menu_mapping.json`
- `deployment_root/modules/<RemoteModule>/config/menu_definition.json`

## HostApp and Module - Runtime configuration

At runtime, operators customize the deployed project from `deployment_root/`.

Main editable runtime files:

- `deployment_root/.env.config`
- `deployment_root/.env.secrets`
- `deployment_root/modules/HostApp/config/modules_menu_mapping.json`
- `deployment_root/modules/HostApp/config/favicon.png`
- `deployment_root/modules/HostApp/config/login_bg.png`
- `deployment_root/modules/<RemoteModule>/config/menu_definition.json`

All configuration files under each module's `config/` folder are mounted as Docker read-only volumes (`:ro`) so they can be changed without rebuilding images. The `config/` folder is copied verbatim from `modules/<MODULE>/config/` to `deployment_root/modules/<MODULE>/config/` during the deployment step.

## Logging

Per-module log levels are derived automatically by the deploy script based on each module's mode in `modules/enabled.md`.

- **`local`** (build from local source) → `<SLUG>_LOG_LEVEL=DEBUG`
- **`remote`** (pre-built images) → `<SLUG>_LOG_LEVEL=INFO`

The variable name is derived from the module's `slug` (uppercased) + `_LOG_LEVEL`:
- HostApp (slug `hostapp`) → `HOSTAPP_LOG_LEVEL`
- ModuleTemplate (slug `template`) → `TEMPLATE_LOG_LEVEL`

Each backend service's `docker-compose.yml` maps its own slugged variable to the standard `LOG_LEVEL`:
```yaml
environment:
  - LOG_LEVEL=${HOSTAPP_LOG_LEVEL:-INFO}
```

Backend `main.py` reads the generic `LOG_LEVEL` at import time and re-applies it in a startup event handler so application loggers respect the configured level regardless of uvicorn's default `INFO` configuration.

The full framework logging contract is defined in `modules/ModuleTemplate/SPECS/ideable-framework-specs/module-integration-specs.md` §13.

## AI Development Environments

Ideable supports multiple AI coding assistants. Compatibility is maintained through a single canonical configuration that all supported tools read.

### Supported environments

| Environment | Entry point read | Skills location |
|---|---|---|
| **Claude Code** (Anthropic) | `CLAUDE.md` → `@AGENTS.md` | `.claude/skills/` (symlink) |
| **GitHub Copilot** | `.github/copilot-instructions.md` (symlink) | n/a |
| **OpenAI Codex CLI** | `AGENTS.md` (walks root → CWD) | n/a |
| **Cursor** | `.cursor/rules/*.mdc` (always + path-scoped) + `AGENTS.md` (fallback) | n/a |
| **Devin** | `AGENTS.md` (auto-read) | `.devin/skills/` (copy) + `.devin/workflows/` |
| **Kiro (Amazon Q)** | plugin-based, no repo file | `.kiro/skills/` (symlink) |

### How compatibility is kept

**Single source of truth — `AGENTS.md`**

All supported tools read `AGENTS.md` as their primary instruction source, either natively or via a dedicated alias:

- `CLAUDE.md` (one line: `@AGENTS.md`) — makes Claude Code read `AGENTS.md` through its native `@import` mechanism, independently of any harness bridging.
- `.github/copilot-instructions.md` — symlink to `AGENTS.md`; gives GitHub Copilot a dedicated entry point at the path it prioritizes.
- Windsurf, Devin, and Codex CLI all auto-read `AGENTS.md` natively — no extra file needed.

`AGENTS.md` is intentionally compact. It contains only the stable, universal rules and a "Reference files" section pointing agents to the right SPECS on demand. This keeps the always-loaded context prefix small and cache-stable across sessions.

**Cursor — path-scoped rules via `.cursor/rules/`**

Cursor is configured with a first-class `.cursor/rules/` directory instead of relying solely on `AGENTS.md`. This gives Cursor automatic, glob-based context injection without requiring the agent to read and follow the reference prose in `AGENTS.md`:

| File | Scope |
|---|---|
| `ideable.mdc` | `alwaysApply: true` — core rules, always active |
| `hostapp.mdc` | `globs: ["modules/HostApp/**"]` — HostApp spec pointers |
| `moduletemplate.mdc` | `globs: ["modules/ModuleTemplate/**"]` — framework spec pointers |
| `testing.mdc` | `globs: ["**/TESTS/**"]` — testing constraints |
| `version-control.mdc` | `globs: [".github/**", "*.md"]` — commit format rule |

Cursor still falls back to `AGENTS.md` for any context not covered by the `.mdc` files.

**Single source of truth — `.agents/skills/`**

All per-tool skill directories are symlinks to `.agents/skills/`:

```
.agents/skills/          ← canonical source (edit here)
.claude/skills/          → symlink → ../.agents/skills
.kiro/skills/            → symlink → ../.agents/skills
.devin/skills/           → copy of .agents/skills/ (synced by update_skills.py)
.devin/workflows/        → generated from Ideable-specific skills
```

Editing a skill in `.agents/skills/` takes effect immediately for all supported environments. No manual sync is needed.

**Maintaining the symlinks**

If symlinks are lost after a fresh clone or accidental copy:

```bash
python3 scripts/common/update_skills.py
```

This verifies and restores all symlinks and syncs `.devin/skills/` and `.devin/workflows/`. Use `--dry-run` to preview changes without applying them. The script is idempotent — safe to run at any time.

**Adding a new AI environment**

When a new AI coding environment gains enough adoption to merit support:

1. Identify the file or directory path it auto-loads at session start.
2. If it reads `AGENTS.md` natively → no change needed, it already works.
3. If it requires a different entry point file → create a symlink from that path to `AGENTS.md`.
4. If it requires a skill directory → create a symlink from its skill directory to `.agents/skills/`, add the tool dir name to `TOOL_DIRS` in `scripts/common/update_skills.py`.
5. If it supports path-scoped rules (like Cursor's `.mdc`) → create a `.<tool>/rules/` directory with the appropriate rule files mirroring the `.cursor/rules/` pattern.
6. Add the environment to the table above.
7. Add its config directory/files to the `is_infrastructure` function in `scripts/module_only/sync-template-updates.sh` and to the infrastructure copy list in `scripts/master_only/push-updates-to-ModuleTemplate-repo.sh`.
8. Run `push-updates-to-ModuleTemplate-repo.sh` to propagate all changes to the template repo.

**Scope of per-tool directories**

- `.claude/`, `.kiro/` — each holds only the `skills/` symlink. Tool-specific settings or per-session configuration that do not belong in shared version control (e.g. `.claude/settings.local.json`) are gitignored.
- `.devin/` — holds `skills/` (real-directory copy synced from `.agents/skills/`) and `workflows/` (generated from Ideable-specific skills). Devin requires real files, not symlinks.
- `.cursor/` — holds only the `rules/` directory with the `.mdc` rule files above. No other Cursor-specific state belongs here.
- `.github/` — holds only `copilot-instructions.md` (symlink to `AGENTS.md`). CI/CD workflows, if added later, go here too.

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
├── AGENTS.md                         ← cross-tool agent instructions (all envs read this)
├── CLAUDE.md                         ← one line: @AGENTS.md (Claude Code entry point)
├── .github/
│   └── copilot-instructions.md       ← symlink → ../AGENTS.md (Copilot entry point)
├── .agents/
│   └── skills/                       ← canonical skill definitions (edit here)
├── .claude/
│   └── skills/                       ← symlink → ../.agents/skills
├── .kiro/
│   └── skills/                       ← symlink → ../.agents/skills
├── .cursor/
│   └── rules/
│       ├── ideable.mdc               ← always-on: core rules pointer (alwaysApply: true)
│       ├── hostapp.mdc               ← auto-loaded for modules/HostApp/**
│       ├── moduletemplate.mdc        ← auto-loaded for modules/ModuleTemplate/**
│       ├── testing.mdc               ← auto-loaded for **/TESTS/**
│       └── version-control.mdc       ← auto-loaded for .github/**, *.md
├── modules/
│   ├── enabled.md                    ← controls build/deploy scope
│   ├── dependencies.md               ← inter-module dependency graph
│   ├── HostApp/                      ← full HostApp codebase
│   │   ├── CLAUDE.md                 ← 1-line module scoping hint
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
│       ├── CLAUDE.md                 ← 1-line module scoping hint
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
│   ├── general-guidelines.md         ← universal rules (loaded every session)
│   ├── testing-guidelines.md         ← loaded on demand: test step only
│   └── version-control.md            ← loaded on demand: git/commit/PR tasks
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

## Development Workflow: Creating a Compatible Module

This chapter describes the complete process for creating a new HostApp-compatible module from scratch. It fuses the development workflow with module creation into a single cohesive guide.

### Step 1: Create Repository from Template

**For external developers:**
1. Go to `https://github.com/vlombardi/Ideable-ModuleTemplate`
2. Click "Use this template" → "Create a new repository"
3. Name it `Ideable-<YourModuleName>`
4. Clone your new repo locally

**For internal maintainers:** You can skip this step and work directly in the `Ideable/` main repository.

---

### Step 2: Initialize the Module

Run the initialization script to transform the template into your module:

```bash
./scripts/module_only/module-init.sh <NewModuleName>
```

**What this script does (auto-handled, verify only):**

| Task | Status | Details |
|------|--------|---------|
| Copy `modules/ModuleTemplate/` → `modules/<NewModuleName>/` | ✅ Automatic | Physical rename |
| Update `module.json` | ✅ Automatic | `name`, `slug`, `displayName`, `cssPrefix` |
| Update `docker-compose.yml` | ✅ Automatic | Service names, container names |
| Update frontend MF config | ✅ Automatic | `rsbuild.config.ts`, `moduleManifest.ts`, `tailwind.config.js` |
| Update backend auth | ✅ Automatic | JWT validation, permission namespace |
| Sync `.env.config.example`/`.env.secrets.example` and backfill `.env.config`/`.env.secrets` | ✅ Automatic | Missing keys from `.env.config.example`/`.env.secrets.example` are appended to the matching `.env.config`/`.env.secrets` without overwriting existing values |
| Create `project.env.config` + `project.env.secrets` | ✅ Automatic | Copied from repo-root `project.env.config.example`/`project.env.secrets.example` if missing, then normalized for the current repo path |
| Add to `modules/enabled.md` | ✅ Automatic | Enables module for build/deploy |

**Review points:**
- Verify `module.json` ports don't conflict with other modules
- Check that slug/prefix are coherent (e.g., `inventory`, `inventory-`)

---

### Step 3: Configure Environment

Edit `project.env.config`, `project.env.secrets`, and `modules/<NewModuleName>/.env.config` + `.env.secrets`:

- **Project-wide identity** — `APP_SLUG`, `APP_NAME` in `project.env.config`
- **Module-local identity** — `MODULE_SLUG` inside each module's `.env.config` for module-specific naming and runtime isolation
- **Project-wide paths** — `PROJECT_ROOT`, `DATA_FOLDER` are auto-filled by `module-init` but can be reviewed if needed
- **Module ports** — only if defaults conflict (`*_BACKEND_PORT`, `*_FRONTEND_PORT`)
- **URLs** — defaults point to local HostApp/Authentik
- **Database targets** — if using split entities/auth databases

**Defaults work out of the box for local development.** Only change what you need.

---

### Step 4: Define Module Specifications

This is the **critical creative step**. Specifications are the source of truth — the AI coding agent implements from them.

#### Database Specifications (`database/SPECS/`)

**⚠️ Do NOT edit `base-specs.md`** — it will be automatically updated by framework sync.

**Create/edit these files:**

| File | Purpose | AI Agent Role |
|------|---------|---------------|
| `datamodel.sql` | Entity schema, relationships, constraints | Can write from your prompts |
| `seed.sql` (optional) | Bootstrap seed data for application entities only | Can write from your prompts |

**Execution order:** init files run in lexicographic order. Use naming like:
- `01_datamodel.sql` — DDL for tables
- `03_seed.sql` — Seed data

#### Frontend Specifications (`frontend/SPECS/`)

**⚠️ Do NOT edit these files** — they will be automatically updated by framework sync:
- `base_specs.md`
- `shared-ui-specs.md`
- `shared-ui-widgets-specs.md`

**Focus on: `module-ui-specs.md`** — this is where you define:
- Your entities and their UI behavior
- Routes and menu items (use `/${APP_SLUG}/your-entity` — placeholder works automatically)
- Page layouts and widget configurations
- Module-specific business logic

**Normative precedence:** `module-ui-specs.md` > `base_specs.md` > `shared-ui-specs.md` > `shared-ui-widgets-specs.md`

Rules in earlier files override rules in later files.

#### Backend Specifications (`backend/SPECS/`)

**⚠️ Do NOT edit `base-specs.md`** — it will be automatically updated by framework sync.

**Create: `module-bl-specs.md`** — define:
- API endpoints for your entities
- Business logic rules
- Permission namespaces: `${APP_SLUG}.your_entity.read`

**Normative precedence:** `module-bl-specs.md` > `base-specs.md`

#### Module-Level Specifications (`SPECS/`)

Define:
- Module dependencies (`dependencies.md`)
- Integration contracts
- Deployment requirements
- Module-specific Authentik authorization config (`authorization.yaml`)

Authorization bootstrap is split by scope:

- `modules/HostApp/config/authorization.yaml` contains the initial HostApp authorization data needed to start the app.
- `modules/<ModuleName>/config/authorization.yaml` contains module-specific authorization data.
- When HostApp gains new app-wide authorization needs, update HostApp's authorization config.
- When a module needs additional authorization data, update that module's own authorization config.


### Step 5: Configure Menu and HostApp Integration

#### Menu

Two coordinated files define how your module integrates with HostApp:

**Your module side:** `config/menu_definition.json`
- Defines your module's menu tree hierarchy
- Menu item codes, names, icons, routing fragments

**HostApp side:** `modules/HostApp/config/modules_menu_mapping.json`
- References your module via `module: "<your-slug>"`
- Maps `module_menu_item_code_path` to position your menu nodes in HostApp's sidebar
- Can override labels and icons

**Integration flow:**
```
HostApp menu_mapping.json ──► resolves path ──► Your module menu_definition.json
                                                        │
                                                        ▼
                                        Combined with MF moduleManifest
                                                        │
                                                        ▼
                                        HostApp sidebar + integrated routes
```

**Branding customization:**
- `modules/HostApp/config/favicon.png` — browser tab icon
- `modules/HostApp/config/login_bg.png` — login page background

These are runtime-mounted via Docker volumes (`:ro`), so you can change them without rebuilding images.

---

### Step 6: Implement with `@[/ImplementSpecs]`

Run the agent workflow to generate SOURCES from SPECS:

```
@[/ImplementSpecs]
```

**What happens:**
1. Agent reads all SPECS files in dependency order
2. Resolves `${APP_SLUG}` from `module.json`
3. Generates/updates SOURCES for frontend, backend, and database
4. Verifies test coverage exists

**If something needs fixing:**

**Option A (Recommended):** Update the specifications, then re-run:
```
# Edit the relevant SPECS file
@[/ImplementSpecs]
```

**Option B (Direct changes):** Tell the agent to directly modify SOURCES, but **remember to sync SPECS afterward**:
```
# Ask agent: "Fix X in the backend"
# After verification works:
# Update (or ask agent to update) the relevant SPECS file
```

**Never let SPECS and SOURCES diverge** — SPECS must always be the source of truth.

---

### Step 7: Build and Deploy with `@[/Build&Deploy]`

Compile SOURCES → DIST → deployment_root:

```
@[/Build&Deploy]
```

**What happens:**
1. Builds Docker images from SOURCES/ for the current build environment
2. Creates DIST/ folders for each sub-module
3. Copies to `deployment_root/modules/<YourModule>/`
4. Generates merged compose file

**Publishing Docker images:**
- `@[/Build&Deploy]` only prepares the local images and deployment artifacts.
- To publish images to a registry, run `./scripts/common/push_module_images_to_registry.sh` **after** the build step.
- Choose the exact modules to publish and the tag to apply, for example:
  ```bash
  ./scripts/common/push_module_images_to_registry.sh -a -t v1.2.3
  ./scripts/common/push_module_images_to_registry.sh HostApp ModuleTemplate -t v1.2.3
  ```
- The push script is the only step that tags and pushes images to the registry; it does not rebuild them.

**If build fails:**
- Check that all files referenced by Dockerfiles exist in SOURCES/
- Verify environment variables are documented in `.env.example`
- Update SPECS if the issue is architectural, then re-run `@[/ImplementSpecs]`

---

### Step 8: Test with `@[/Tests&Fix]`

Run all enabled module tests:

```
@[/Tests&Fix]
```

**Includes:**
- Unit and integration tests for your module
- L&F parity validation (`check_moduletemplate_lf_parity.sh`)
- Cross-module contract tests

**If tests fail:**

**Option A (Recommended):** Update SPECS to fix the underlying issue, then:
```
@[/ImplementSpecs]
@[/Build&Deploy]
@[/Tests&Fix]
```

**Option B (Direct fixes):** Ask agent to fix SOURCES directly, then sync SPECS:
```
# "Fix the failing test X"
# After it works: "Update SPECS to reflect the fix we made"
```

---

### Step 9: Deploy with `redeploy.sh`

Final deployment to create and populate `deployment_root/`:

```bash
./redeploy.sh
```

**Interactive prompts:**
- Wipe volumes? (default: **no**)
- Start containers? (default: **yes**)

**What `redeploy.sh` does:**
1. Loads project-wide config first from `project.env.config` + `project.env.secrets`
2. Loads module `.env.config` + `.env.secrets` files for module-scoped build/runtime variables
3. Prompts to optionally wipe volumes (default: **no**)
4. Prompts to optionally start containers after deploy (default: **yes**)
5. Runs `@[/Build&Deploy]` (builds Docker images locally, creates DIST/, populates `deployment_root/`)
6. Regenerates the merged `deployment_root/.env.config` + `deployment_root/.env.secrets` and `deployment_root/docker-compose.yml` by executing `deployment_root/scripts/create-merged-configuration.sh`
7. If you want to publish registry images, run `./scripts/common/push_module_images_to_registry.sh` separately with the modules and tag you want
8. Optionally executes `deployment_root/start.sh` to start the stack using the project namespace

**Prerequisites:** You must run `@[/ImplementSpecs]` **before** `redeploy.sh` to ensure SOURCES are up to date with SPECS.

**`deployment_root/` contents:**
```
deployment_root/
├── docker-compose.yml          ← merged from all enabled modules (project-namespaced)
├── .env.config                 ← merged project + module configuration
├── .env.secrets                ← merged project + module secrets
├── start.sh / stop.sh          ← runtime control scripts
├── scripts/
│   └── create-merged-configuration.sh  ← regenerates merged .env.config/.env.secrets and docker-compose.yml
└── modules/
    ├── HostApp/
    │   ├── config/
    │   │   ├── modules_menu_mapping.json  ← mount:ro
    │   │   ├── module-registry.json       ← generated, mount:ro
    │   │   ├── favicon.png                ← mount:ro
    │   │   └── login_bg.png               ← mount:ro
    └── <YourModule>/
        ├── docker-compose.yml
        ├── .env.config
        ├── .env.secrets
        ├── config/
        │   └── menu_definition.json       ← mount:ro
        ├── frontend/
        ├── backend/
        └── database/
```

**"Docker image first" logic:**
- Services with `image:` references use pre-built images
- No `build:` sections in production compose files (per general guidelines)
- Images are built during `@[/Build&Deploy]` and stored locally for the build machine
- Registry publication is explicit and happens only through `push_module_images_to_registry.sh`

---

### Step 10: Customize Runtime Deployment

After `redeploy.sh`, customize via runtime-mounted files (no rebuild needed):

| File | Purpose | Change Effect |
|------|---------|-------------|
| `deployment_root/.env` | Global environment | Restart containers |
| `deployment_root/modules/HostApp/config/authorization.yaml` | HostApp auth bootstrap contract | Re-run deployment/bootstrap |
| `deployment_root/modules/<YourModule>/config/authorization.yaml` | Module auth bootstrap contract | Re-run deployment/bootstrap |
| `deployment_root/modules/HostApp/config/modules_menu_mapping.json` | Host menu structure | Immediate (HostApp detects changes) |
| `deployment_root/modules/HostApp/config/module-registry.json` | Remote module registry | Restart HostApp frontend |
| `deployment_root/modules/HostApp/config/home.html` | HostApp landing page content | Immediate after refresh |
| `deployment_root/modules/HostApp/config/favicon.png` | Browser icon | Hard refresh |
| `deployment_root/modules/HostApp/config/login_bg.png` | Login background | Hard refresh |
| `deployment_root/modules/<YourModule>/config/menu_definition.json` | Module menu tree | Immediate (HostApp re-resolves) |
| `deployment_root/modules/<YourModule>/database/initdb/` | Seed SQL (if not in image) | Wipe volume, restart |

**Important:** These are `:ro` (read-only) volume mounts into containers. Edit them in `deployment_root/`, not in the source repository (which gets overwritten on next deploy).

---

### Post-Deployment: Sync with Template Updates

When ModuleTemplate evolves, pull updates:

```bash
# Check what's new
./scripts/module_only/sync-template-updates.sh --list-changes

# Sync specific file
./scripts/module_only/sync-template-updates.sh --file frontend/SPECS/shared-ui-specs.md

# Sync all framework files (auto-handled SPECS + scripts)
./scripts/module_only/sync-template-updates.sh
```

**What gets synced:**
- `base_specs.md`, `shared-ui-*.md` — framework-level specs (safe, generic placeholders)
- `scripts/` — build and utility scripts
- `AGENTS.md` — agent guidance used by the repository
- `rules/` — shared rules and workflow guidance
- Test framework files
- `modules/HostApp/docker-compose.yml` and `modules/HostApp/.env.example` — HostApp structural compose and defaults
- Repo-root runtime helpers (`start.sh`, `stop.sh`, `status.sh`, `redeploy.sh`, `update_backend.sh`, `update_frontend.sh`) when present in the template export

**What you keep:**
- Your `module-ui-specs.md`, `module-bl-specs.md` — your business logic
- Your `datamodel.sql`, seed data — your domain
- Your `SOURCES/` — unless you want to adopt new patterns

---

### Quick Reference: Commands

| Task | Command |
|------|---------|
| Initialize module | `./scripts/module_only/module-init.sh MyModule` |
| Implement specs | `@[/ImplementSpecs]` |
| Build & deploy | `@[/Build&Deploy]` |
| Run tests | `@[/Tests&Fix]` |
| Full deploy | `./redeploy.sh` |
| Start services (repo root wrapper) | `./start.sh` |
| Stop services (repo root wrapper) | `./stop.sh` |
| Show status (repo root wrapper) | `./status.sh` |
| Update backend only | `./update_backend.sh` |
| Update frontend only | `./update_frontend.sh` |
| Check template updates | `./scripts/module_only/sync-template-updates.sh --list-changes` |
| Sync updates | `./scripts/module_only/sync-template-updates.sh` |

## Module Federation Integration

- Host runtime fetches registry from `/module-registry.json` at runtime.
- Registry source file: `modules/HostApp/frontend/SOURCES/public/module-registry.json` (copied to served root).
- Registry entries point to remote manifests at `/remotes/<slug>/mf-manifest.json` and declare `/remotes/<slug>/remoteEntry.js` so the runtime can hydrate the container without guessing file names.
- HostApp mounts remote routes and sidebar menu sections dynamically.
- Remote load failures are handled gracefully (host static routes keep working).

## Authentication and Authorization

- Frontend performs OIDC login against Authentik.
- Backend services validate Bearer JWT via Authentik JWKS.
- HostApp authorization decisions are based on Authentik JWT claims.
- Permission naming convention: `<module_slug>.<resource>.<action>`.

### Authorization system overview (HostApp + modules)

1. **Specs as the authorization config.** Every module ships an `authorization.yaml` authorization config that declares profiles, roles, permissions, and associations using canonical `resource:action` names. Menu visibility is encoded through dedicated `:menu_access` permissions (e.g., `users:menu_access`).
2. **Bootstrap execution.** `modules/HostApp/authentik/SOURCES/bootstrap_authentik.py` ingests the enabled modules' `authorization.yaml` files, ensures Authentik profiles/roles/users exist, and reconciles the `Ideable Permissions Claims` property mapping.
   - During this step bootstrap also materializes the registry groups `app:available-permissions-registry`, `app:permissions-to-role-registry`, and `app:roles-to-profile-registry`.
   - The registries live in Authentik and are the runtime source for UI/API reads.
4. **JWT emission.** When a user logs in, Authentik emits:
   - `<module_slug>.permissions` → all permissions, including `<resource>:menu_access` for menu visibility.
   - `hostapp.available_permissions` → the metadata array described above.
   - `hostapp.roles_mapping` → role→permission associations so frontends can render admin tooling without re-querying Authentik.
   - `hostapp.company_ids` → the user’s company identifiers, sourced from Authentik user attributes and kept in sync by HostApp.
   - `hostapp.active_profile` → the user’s current active profile, sourced from the Authentik user attribute of the same name.
   - HostApp APIs read the `app:roles-to-profile-registry` group to display every role linked to a profile.

**Company / active profile model.** HostApp treats company membership and active profile as Authentik-backed user data, not as role data or local DB authorization state.
- The canonical source in HostApp is the user’s `company_fk` reference to the local Companies table.
- When HostApp creates or updates a user, it mirrors that association into Authentik user attributes under `hostapp.company_ids` using the `CompanyName(ID)` format.
- Startup plan sync backfills the same attribute for users defined in the auth plan, and the JWT scope mapping emits the attribute so downstream UI/API code can read it after login.
- The scope mapping also accepts legacy attribute names (`user_companies` and `company_ids`) for existing users during migration.
- The active profile is stored only in the Authentik user attribute `hostapp.active_profile`; HostApp reads it from JWT claims and does not keep a separate authorization mirror in its database.

#### Example: `authorization.yaml` → JWT claims

**template_module/authorization.yaml**
```yaml

users:
  - username: template_admin
    email: template_admin@ideable.tech
    full_name: Template Admin
    profiles:
      - template_admin
  - ext_user: sadmin   # NOTE: The ext_user keyword indicates that the user referenced here is defined in another Module (in this case, in HostApp).
                       #       This is a special way to associate profiles defined here to a user that is defined esternally.
                       #       Do not define here other users pecific data like full_name, email, etc. (they whould be ignored to avoid conflicts/overwritings)
                       #       The external Module that defines the user must be declared in the module's dependencies.
    profiles:
      - template_admin
profiles:
  - ext_profile: admin # NOTE: The ext_profile keyword indicates that the profile referenced here is defined in another Module (in this case, in HostApp).
                       #       This is a special way to associate roles defined here to a profile that is defined esternally.
                       #       Do not define here other profiles pecific data like description, etc. (they whould be ignored to avoid conflicts/overwritings)
                       #       The external Module that defines the profile must be declared in the module's dependencies.
    roles:
      - template_items_manager
  - profile: template_admin
    description: ModuleTemplate administrators
    roles:
      - template_items_manager
  - profile: template_reader
    description: ModuleTemplate read-only users
    roles:
      - template_items_reader
roles:

  - ext_role: guest # NOTE: The ext_role keyword indicates that the role referenced here is defined in another Module (in this case, in HostApp).
                    #       This is a special way to associate permissions defined here to a role that is defined esternally.
                    #       Do not define here other roles pecific data like description, etc. (they whould be ignored to avoid conflicts/overwritings)
                    #       The external Module that defines the role must be declared in the module's dependencies.
    permissions:
      - items:view
      - items:menu_access

  - role: template_items_manager
    description: CRUD access to Template Items
    permissions:
      - items:view
      - items:edit
      - items:menu_access
  - role: template_items_reader
    description: Read access to Template Items
    permissions:
      - items:view
      - items:menu_access
permissions:
  - name: items:view
    description: View template items
  - name: items:edit
    description: Edit template items
  - name: items:menu_access
    description: Access items menu

```
**modules/HostApp/config/authorization.yaml**
```yaml
# HostApp bootstrap authorization config

users:
  - username: sadmin
    email: sadmin@ideable.tech
    full_name: Super Admin
    profiles:
      - admin
      - security_officer
      - reader
    superadmin: true
  - username: guest
    email: guest@ideable.tech
    full_name: Guest User
    profiles:
      - reader
    superadmin: false
profiles:
  - profile: admin
    description: Administrators
    roles:
      - authorization_full_editor
  - profile: security_officer
    description: Security officers
    roles:
      - user_profiler
      - authorization_viewer    
  - profile: reader
    description: Read-only users
    roles:
      - authorization_viewer    
roles:
  - role: authorization_full_editor
    description: Full HostApp administration access
    permissions:
      - access_logs:menu_access
      - access_logs:view
      - companies:view
      - companies:edit
      - companies:menu_access
      - home:menu_access
      - permission_to_role_assignments:edit
      - permission_to_role_assignments:view
      - permissions:menu_access
      - permissions:edit
      - profiles:menu_access
      - permissions:view
      - profile_to_user_assignments:edit
      - profile_to_user_assignments:view
      - profiles:edit
      - profiles:view
      - role_to_profile_assignments:edit
      - role_to_profile_assignments:view
      - roles:edit
      - roles:menu_access
      - roles:view
      - users:edit
      - users:menu_access
      - users:password_change
      - users:view
      - users_and_permissions:menu_access    
  - role: authorization_viewer
    description: Read-only HostApp visibility access
    permissions:
      - access_logs:menu_access
      - access_logs:view
      - companies:menu_access
      - companies:view
      - home:menu_access
      - permission_to_role_assignments:view
      - permissions:menu_access
      - permissions:view
      - profile_to_user_assignments:view
      - profiles:menu_access
      - profiles:view
      - roles:menu_access
      - roles:view
      - role_to_profile_assignments:view
      - users_and_permissions:menu_access
      - users:menu_access
      - users:view
  - role: user_profiler
    description: Security officer access to HostApp administration areas
    permissions:
      - access_logs:menu_access
      - access_logs:view
      - companies:menu_access
      - companies:view
      - home:menu_access
      - permission_to_role_assignments:view
      - permissions:menu_access
      - permissions:view
      - profile_to_user_assignments:edit
      - profile_to_user_assignments:view
      - profiles:menu_access
      - profiles:view
      - role_to_profile_assignments:view
      - roles:menu_access
      - roles:view
      - users_and_permissions:menu_access
      - users:menu_access
      - users:password_change  
      - users:view
  - role: guest
    description: HostApp login, no access to administration areas
    permissions:
      - home:menu_access
permissions:
  - name: users:view
    description: View users (read-only)
  - name: users:edit
    description: Edit users (create, update, delete)
  - name: profiles:view
    description: View profiles (read-only)
  - name: profiles:edit
    description: Edit profiles (create, update, delete)
  - name: roles:view  
    description: View roles (read-only)
  - name: roles:edit
    description: Edit roles (create, update, delete)
  - name: permissions:edit
    description: Edit permissions (create, update, delete)
  - name: permissions:view
    description: View permissions (read-only)
  - name: profile_to_user_assignments:view
    description: View profile to user assignments (read-only)
  - name: profile_to_user_assignments:edit
    description: Assign-unassign profile to user
  - name: role_to_profile_assignments:view
    description: View role to profile assignments (read-only)
  - name: role_to_profile_assignments:edit
    description: Assign-unassign role to profile
  - name: permission_to_role_assignments:view
    description: View permission to role assignments (read-only)
  - name: permission_to_role_assignments:edit
    description: Assign-unassign permission to role
  - name: access_logs:view
    description: View access logs
  - name: users:password_change
    description: Change user password
  - name: home:menu_access
    description: Access home menu
  - name: users_and_permissions:menu_access
    description: Access users and permissions menu
  - name: users:menu_access
    description: Access users menu
  - name: profiles:menu_access
    description: Access profiles menu
  - name: roles:menu_access
    description: Access roles menu
  - name: permissions:menu_access
    description: Access permissions menu
  - name: companies:view
    description: View companies (read-only)
  - name: companies:edit
    description: Edit companies (create, update, delete)
  - name: companies:menu_access
    description: Access companies menu
  - name: access_logs:menu_access
    description: Access access logs menu
  - name: template_items:view
    description: View template items (read-only)
  - name: template_items:edit
    description: Edit template items (create, update, delete)
  - name: template_items:menu_access
    description: Access template items menu

```


Once `bootstrap_authentik.py` processes this spec the resulting JWT (trimmed for clarity) contains:

```json
{
  "iss": "https://myhost.com/application/o/ideable/",
  "sub": "sadmin",
  "aud": "ideable-client",
  "exp": 1780041739,
  "iat": 1780041439,
  "auth_time": 1780041437,
  "acr": "goauthentik.io/providers/oauth2/default",
  "amr": [
    "pwd"
  ],
  "sid": "5868879d4070ef8b8fdf7f0588cfaafb4383b8bc22f48c4ab6d78175543469a7",
  "email": "sadmin@localhost",
  "email_verified": false,
  "hostapp.permissions": [
    "access_logs:menu_access",
    "access_logs:view",
    "companies:edit",
    "companies:menu_access",
    "companies:view",
    "home:menu_access",
    "permission_to_role_assignments:edit",
    "permission_to_role_assignments:view",
    "permissions:edit",
    "permissions:menu_access",
    "permissions:view",
    "profile_to_user_assignments:edit",
    "profile_to_user_assignments:view",
    "profiles:edit",
    "profiles:menu_access",
    "profiles:view",
    "role_to_profile_assignments:edit",
    "role_to_profile_assignments:view",
    "roles:edit",
    "roles:menu_access",
    "roles:view",
    "template_items:menu_access",
    "users:edit",
    "users:menu_access",
    "users:password_change",
    "users:view",
    "users_and_permissions:menu_access"
  ],
  "template.permissions": [
    "items:menu_access",
    "items:view",
    "items:edit"
  ],
  "active_profile": "admin",
  "name": "Super Admin",
  "given_name": "Super Admin",
  "preferred_username": "sadmin",
  "nickname": "sadmin",
  "groups": [
    "admin",
    "security_officer",
    "reader"
  ],
  "azp": "ideable-client",
  "uid": "VJa3H9SPCibmAsTiBFEzPCIEvTBW6YM0xdgVS6Rw",
  "scope": "email openid profile hostapp offline_access"
}
```

### Where to find Ideable authorization elements in Authentik UI

- **Users**: `https://<your-authentik-domain>:9443/if/admin/#/identity/users`
- **Ideable Profiles (Authentik Groups)**: `https://<your-authentik-domain>:9443/if/admin/#/identity/`
- **Roles**: `https://<your-authentik-domain>:9443/if/admin/#/identity/roles`
- **Permissions**: `https://<your-authentik-domain>:9443/if/admin/#/core/property-mappings`

Permissions are defined as Property Mappings in Authentik. The naming convention is `<module_slug>.<resource>.<action>`.
**Notes about Permissions**
- Source of truth remains the Modules' YAML files.
`modules/HostApp/config/authorization.yaml` defines every logical permission, role, and profile. 

- Bootstrap reads this and builds a JSON “plan”. No Authentik “object/global permissions” row is ever created.

- Claims are generated via a `Property Mapping` (not RBAC permissions), as a single Scope property mapping named “Ideable Permissions Claims”. This mapping emits the runtime claims needed by HostApp, including `hostapp.permissions` and `hostapp.company_ids`, so every JWT contains the authoritative state at mint time.


## Remote Module Auth/Authz Implementation Specification

This section is the **quick contract** for AI coding agents and humans building a remote module. The rule is simple: **Authentik mints the JWT, and the JWT is the only runtime source of truth for authorization**.

#### What a remote module must do

1. **Use Authentik as the only identity provider.**
   - Do not create your own users, roles, or permissions.
   - Do not keep a local RBAC system for runtime authorization.

2. **Trust the bearer token for all authorization decisions.**
   - Validate the JWT with Authentik JWKS.
   - Read permissions and menu access from the token claims only.
   - Do not query HostApp or a local database to decide whether a user can act.

3. **Use the standard claim layout.**
   - `<module_slug>.permissions` controls actions like `read`, `create`, `update`, `delete`, and `menu_access`.
   - `hostapp.company_ids` is used for company scoping and comes from Authentik user attributes.

4. **Map claims to UI behavior.**
   - Hide menu entries when the matching `<resource>:menu_access` permission is missing from `*.permissions`.
   - Hide or disable buttons when the matching `*.permissions` claim is missing.
   - Use the same claims for table action icons and edit/view toggles.

5. **Treat profile switching as token switching.**
   - When the active profile changes, the next token must reflect the new claims.
   - Your module should simply re-read the token-derived auth state; it should not compute permissions itself.

6. **Handle `401` and `403` correctly.**
   - `401` means the token is missing or expired.
   - `403` means the token is valid but does not contain the required claim.

7. **Keep module authorization declarative.**
   - Define permissions in `authorization.yaml`.
   - Let the bootstrap pipeline convert those declarations into Authentik claims.
   - Do not hardcode authorization rules in the frontend or backend beyond checking claims.

#### Minimal checklist

- **Backend**: validate JWT with Authentik JWKS.
- **Backend**: protect endpoints with claim checks on `<module_slug>.permissions`.
- **Frontend**: read claims from the current token before showing menus or action buttons.
- **Frontend**: never use local RBAC tables or HostApp DB state for runtime access control.
- **Companies**: read `hostapp.company_ids` from the token; keep the raw company association in Authentik user attributes.


**Important rules:**
- Permission names in `authorization.yaml` use the short form (`resource:action`). 
- `menu_access` permissions (`action == "menu_access"`) are emitted as `<resource>:menu_access` into `<module_slug>.permissions`.
- Users listed here are created/reconciled idempotently on every bootstrap. Password source precedence: `password_env` → `password` → `AUTHENTIK_DEFAULT_USER_PASSWORD`.

---

### F. Menu Visibility Integration

Menu items declared in `config/menu_definition.json` are shown or hidden based on explicit `<resource>:menu_access` permissions inside `<module_slug>.permissions`.

```json
{
  "menu_items": [
    {
      "menu_item_code": "items",
      "name": "Items",
      "icon": "Package",
      "route": "/items",
      "authorization_resource": "items"
    }
  ]
}
```

HostApp shows the menu entry when the exact permission `"items:menu_access"` is present in the `<module_slug>.permissions` array of the JWT.

---

### G. Company Filtering (if applicable)

If your module stores entities scoped to a company:

- Read `hostapp.company_ids` from the JWT. Each entry is `"CompanyName(ID)"`. Extract the numeric ID with a regex: `\((\d+)\)$`.
- Filter queries to only return records whose `company_fk` is in the user's company ID set.
- Superadmin users (have `"superadmin"` in `hostapp.permissions`) see all companies.

```python
import re

def get_company_ids_from_claims(claims: dict) -> list[int]:
    raw: list[str] = claims.get("hostapp.company_ids", [])
    ids = []
    for entry in raw:
        m = re.search(r"\((\d+)\)$", entry)
        if m:
            ids.append(int(m.group(1)))
    return ids
```

---

### H. Full Environment Variable Reference for a Remote Module Backend

| Variable | Source | Description |
|---|---|---|
| `MODULE_SLUG` | module `.env.config` | Your module's slug (e.g. `inventory`). Must match `module.json`. |
| `AUTHENTIK_JWKS_URL` | project `.env.config` / module `.env.config` | JWKS endpoint. Use internal Docker URL in production: `http://authentik-server:9000/application/o/<APP_SLUG>/jwks/`. |
| `AUTHENTIK_ISSUER` | project `.env.config` | Optional. If set, must equal the `iss` claim exactly: `https://<host>/application/o/<APP_SLUG>/`. |
| `AUTHENTIK_API_URL` | project `.env.config` | Authentik REST API base (needed only if your module calls Authentik directly). |
| `AUTHENTIK_API_TOKEN` | project `.env.secrets` | Bootstrap token reused as API token. Equal to `AUTHENTIK_BOOTSTRAP_TOKEN`. |
| `EXTERNAL_BASE_HOST` | project `.env.config` | Public hostname. Used to construct OIDC/JWKS URLs. |
| `APP_SLUG` | project `.env.config` | Authentik application slug (`hostapp`). Used in JWKS and OIDC paths. |

---

### I. Common Mistakes

| Mistake | Correct approach |
|---|---|
| Reading permissions from a local DB table | Read from JWT claim `<module_slug>.permissions` |
| Running OIDC login in the remote module | Let HostApp own the session; return `401` |
| Checking `hostapp.permissions` for module permissions | Check `<module_slug>.permissions` for your module's perms |
| Hardcoding the full permission name in `authorization.yaml` | Write short form `resource:action`; bootstrap adds the prefix |
| Using `allowed_roles` lists for menu visibility | Use `authorization_claim` in `menu_definition.json` with `<resource>:menu_access` matched against `<module_slug>.permissions` |
| Connecting to HostApp DB | Remote modules have no access to HostApp DB; all auth state is in the JWT |
| Validating JWT against a self-managed key | Always validate against Authentik JWKS; never generate or cache your own signing keys |

---

## Deployment Model

- Each module ships its own compose file (`docker-compose.yml` or supported naming variant).
- `scripts/common/build_and_deploy.py` deploys per-module compose/env files to `deployment_root/`.
- A merged `deployment_root/docker-compose.yml` is generated for enabled modules.
- Start/stop scripts are generated under `deployment_root/`.

## Enabled Modules and Remote Image Support

The `modules/enabled.md` file controls which modules participate in the build and deployment process. Each line follows the format:

```
<ModuleName>: <local|remote>
```

- A module that is neither `local` nor `remote` is considered disabled and should be commented out or removed from `modules/enabled.md`.
- `local` — the module's full source is present in the `modules/<MODULE>/` folder and will be built and deployed locally.
- `remote` — the module is not built locally. Only its Docker images are expected to be available in a Docker registry. The `image:` references in the module's `docker-compose.yml` must already include the registry prefix when images are hosted remotely (e.g. `ghcr.io/owner/app.module.backend:latest`). If no registry prefix is present, images are assumed to be available in the local Docker daemon (e.g., already pulled or restored from a previous `docker save`). In this case the `modules/<MODULE>/` folder contains only `module.json`, `config/`, and `.env` — no SPECS or sub-module source folders.

Example (`modules/enabled.md` in a module repo):

```
HostApp: remote
MyModule: local
```

This means HostApp is included via Docker images only, and MyModule is fully built from source.

## Pushing Module Images to a Registry

When a module has already been built locally, you can push its Docker images to a registry. Each module's `.env` file may declare `MODULE_DOCKER_REGISTRY_PREFIX` (e.g. `ghcr.io/OWNER/`). The push script reads this per-module value to determine the target registry, and compose services reference it via `${MODULE_DOCKER_REGISTRY_PREFIX}${MODULE_SLUG}.<submodule>:latest`. You can also use the optional `--registry` argument as a fallback for modules that do not define `MODULE_DOCKER_REGISTRY_PREFIX`.

Use one of the following commands:

```bash
./scripts/common/push_module_images_to_registry.sh -a
./scripts/common/push_module_images_to_registry.sh -a -t 1.1.0
./scripts/common/push_module_images_to_registry.sh HostApp ModuleTemplate
./scripts/common/push_module_images_to_registry.sh -a -t 1.1.0 --platform linux/amd64,linux/arm64
./scripts/common/push_module_images_to_registry.sh -a --single-arch
```

- `-a` / `--all` pushes every enabled module that is declared as `local` in `modules/enabled.md`.
- Explicit module names let you push a subset of enabled modules.
- Module names are case-sensitive and must match the names in `modules/enabled.md` exactly (for example `HostApp`, not `hostapp`).
- Modules marked as `remote` are skipped, because their registry push must be done from the owning project.
- The script checks that each selected module exists, has the required module files, and has local images already built before pushing.
- By default the script uses `docker buildx build --push` to publish a multi-architecture manifest.
- `--single-arch` opts out of multi-arch and pushes the existing local single-arch image instead.
- `--platform` sets the comma-separated platform list for multi-arch builds and defaults to `linux/amd64,linux/arm64`.
- Multi-arch pushes require a `docker-container` buildx builder; the script will create and bootstrap `ideable-multiarch-builder` automatically when possible.

When `MODULE_DOCKER_REGISTRY_PREFIX` (or `--registry`) is just `ghcr.io`, the script expands it with the repository owner before tagging and pushing.

## Quick Start

1. Copy `project.env.config.example` to `project.env.config` and `project.env.secrets.example` to `project.env.secrets` if needed, then configure project identity there.
2. Configure enabled modules in `modules/enabled.md`.
3. Check module settings in `modules/<Module>/.env.config` and `.env.secrets`.
4. Build/deploy enabled modules:

```bash
python3 scripts/common/build_and_deploy.py
```

5. Start services:

```bash
./deployment_root/start.sh
```

6. Stop services:

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

