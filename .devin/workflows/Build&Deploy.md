---
description: Build SOURCES into DIST and deploy DIST to deployment_root for one or more modules/sub-modules (development process steps 3 and 4)
---
# General Guidelines

If the user asks to build without specifying a module, always build all enabled modules (see `modules/enabled.md`).
When building a module, build all its sub-modules — no partial builds.

# Workflow: Sources → Dist → deployment_root

This workflow guides a coding agent through **build step (step 3)** and **deployment step (step 4)** of the development process: compiling or packaging `SOURCES/` into `DIST/` folders, then copying `DIST/` contents to the correct locations inside `deployment_root/`.

## Build/Deploy invariants (MANDATORY)

- **`DIST/` exists only in the repository** (under `modules/<MODULE>/<SUBMODULE>/DIST`). It is a build artifact location.
- **`deployment_root/` never contains a `DIST/` folder**. The deployment step copies the **contents** of each `DIST/` into:
  - `deployment_root/modules/<MODULE>/<SUBMODULE>/`
- **Each module's `docker-compose.yml` is deployed to `deployment_root/modules/<MODULE>/docker-compose.yml`**, not to the `deployment_root/` root. The root-level `deployment_root/docker-compose.yml` is the auto-generated merge of all enabled modules.
- **`docker compose` is executed from `deployment_root/`** using explicit `-f modules/<MODULE>/docker-compose.yml` flags. Therefore:
  - All relative paths inside per-module compose files are resolved relative to `deployment_root/`.
  - Compose volume mounts must point to files that exist under `deployment_root/` (typically under `deployment_root/modules/<MODULE>/<SUBMODULE>/`), never to repository-only paths like `modules/<MODULE>/<SUBMODULE>/SOURCES` or `modules/<MODULE>/<SUBMODULE>/DIST`.

The canonical implementation of this workflow is the script `scripts/common/build_and_deploy.py`. **Always run that script** rather than performing manual build/copy steps, unless the script does not yet support the module being built (see Step 4).

## Prerequisites

Before starting, verify:
1. `modules/enabled.md` — identify which modules are enabled. Only build enabled modules.
2. Each module's `dependencies.md` (e.g. `modules/<MODULE>/dependencies.md`) — verify dependency versions and build prerequisites.
3. `rules/general-guidelines.md` — re-read the mandatory project rules before any action.
4. All `SOURCES/` folders for the target modules are present and consistent with their SPECS (run `/Specs2Sources` first if in doubt).

## Step 1 — Determine scope

Ask the user (or infer from context) which of the following is being built:
- A specific sub-module (e.g. `HostApp/backend`)
- An entire module (e.g. `HostApp`, all its sub-modules)
- All enabled modules

## Step 2 — Classify each sub-module's build type

For each sub-module in scope, determine its build type by inspecting its folder:

| Condition | Build type | Output |
|---|---|---|
| `SOURCES/Dockerfile` exists | **Docker image** | Image built locally; no `DIST/` required |
| `SOURCES/Dockerfile` exists AND non-Dockerfile files are present | **Docker image + file artifacts** | Image built locally; non-Dockerfile files copied to `DIST/` |
| No `Dockerfile` in `SOURCES/` | **File artifacts only** | Files copied from `SOURCES/` to `DIST/` |
| No `SOURCES/` folder | **Skip** | Nothing to build |

**CRITICAL**: Never place a `Dockerfile` in `DIST/`. Never reference `SOURCES/` paths from `deployment_root/`.

## Step 3 — Read sub-module SPECS Build sections

Before running the build script, read the `SPECS/base-specs.md` of each sub-module in scope. Locate the **Build** section to understand what the sub-module produces.

- If the Build section describes only standard tasks (Docker image build from `Dockerfile`, or flat file copy from `SOURCES/` to `DIST/`), the generic script covers them fully — proceed to Step 4.
- If the Build section references a `SPECS/build.sh` script, that script is the authoritative build for that sub-module. `build_and_deploy.py` detects and runs it automatically — no manual intervention is needed. Proceed to Step 4.
- If the Build section defines tasks that are **not yet covered** by either the generic logic or a `SPECS/build.sh`, those tasks must be encoded into a new `SPECS/build.sh` (see Step 5) before running the script.

**CRITICAL**: Never skip tasks explicitly defined in a sub-module's SPECS Build section. The Build section is authoritative for what must happen during the build step for that sub-module.

## Step 4 — Run build_and_deploy.py

Run the canonical build and deploy script from the project root:

```bash
python scripts/common/build_and_deploy.py
```

This script:
1. Reads `modules/enabled.md` to determine which modules to process
2. Discovers sub-modules automatically by scanning the module folder
3. Classifies each sub-module's build type (Docker image / file artifacts / both)
4. Builds Docker images with `docker build --no-cache`
5. Copies file artifacts to each sub-module's `DIST/` folder
6. Copies each `DIST/` to the correct path inside `deployment_root/`
7. Copies per-module `docker-compose.yml` and `.env` into `deployment_root/modules/<MODULE>/`
8. Merges all module `.env` files into `deployment_root/.env`
9. Generates the merged `deployment_root/docker-compose.yml`
10. Generates `deployment_root/start.sh` and `deployment_root/stop.sh`
11. Copies `create-merged-configuration.sh` into `deployment_root/scripts/` for standalone regeneration

If registry publication is needed, run `scripts/common/push_module_images_to_registry.sh` after the build step and pass the module names plus the tag you want to publish. That push script is the only step that tags and pushes images; it does not rebuild them.

If the script exits with a non-zero code, stop and report the error before proceeding.

## Step 5 — Handle sub-modules with non-standard build processes

`build_and_deploy.py` automatically discovers any sub-module that has a `SOURCES/` folder and handles two standard build types: building a Docker image from a `Dockerfile`, and copying file artifacts to `DIST/`. **No script changes are needed for new sub-modules that follow this convention.**

Step 5 only applies when a sub-module requires a **custom intermediate build step** that cannot be expressed as either of those two types — for example:
- A sub-module that must copy files into a specific `DIST/` subdirectory (not `DIST/` root)
- A sub-module that must run `npm run build` or another compiler before copying artifacts
- A sub-module that requires file permission changes (e.g. `chmod +x`) or other transformations

In such cases, follow the **Sub-Module Build Scripts** rule from `rules/general-guidelines.md`:
1. **Create `SPECS/build.sh`** inside the sub-module's `SPECS/` folder — this script is the single source of truth for that sub-module's build process; it must be deterministic and idempotent
2. **Reference `build.sh` in the sub-module's `base-specs.md`** — add it to the Specification Files Chain and describe what it does in the Build section
3. **`build_and_deploy.py` will detect and run it automatically** — if `SPECS/build.sh` exists, the generic build logic is bypassed for that sub-module; no script changes are needed
4. Re-run `build_and_deploy.py`

**Forbidden**: adding hardcoded sub-module-specific functions to `build_and_deploy.py`. All sub-module-specific build logic belongs in the sub-module's own `SPECS/build.sh`.

## Step 6 — Verify deployment_root consistency

After the script completes, verify:
1. All sub-modules with file artifacts have their contents correctly placed under `deployment_root/modules/<MODULE>/<SUB_MODULE>/`
2. Each enabled module has `deployment_root/modules/<MODULE>/docker-compose.yml` with `env_file: - ../../.env`
3. `deployment_root/docker-compose.yml` (merged) exists and is up to date
4. `deployment_root/.env` (merged from all modules) exists and is up to date — no slug-based env files (e.g. `.env.template`) should exist
5. `deployment_root/start.sh` and `deployment_root/stop.sh` exist, are executable, and reference `modules/<MODULE>/docker-compose.yml` paths
6. `deployment_root/scripts/create-merged-configuration.sh` exists and is executable
7. No `Dockerfile` or `SOURCES/` path references exist anywhere inside `deployment_root/`
8. No hardcoded values in compose files where an env var is available
9. All Docker images referenced by `docker-compose.yml` exist in the local Docker registry (`docker images`)

## Step 7 — Restart / upgrade running services

After a successful deployment, use the appropriate restart procedure based on what changed:

| What changed | Procedure |
|---|---|
| File artifacts only (no image rebuild, no compose/env change) | `docker compose restart <service>` for the affected service(s) |
| Docker image(s) rebuilt | `docker compose up -d` from `deployment_root/` — Docker will recreate containers whose image changed |
| `docker-compose.yml` or `.env` changed | `docker compose down && docker compose up -d` from `deployment_root/` |
| Database schema changed (new migrations or init scripts) | Apply migrations manually **before** restarting dependent services; do not rely on `start.sh` alone |
| First-time deployment (nothing running) | `./start.sh` from `deployment_root/` |
| Full redeploy (everything changed) | `docker compose down && ./start.sh` from `deployment_root/` |

**Notes**:
- Always run compose commands from `deployment_root/` where `docker-compose.yml` and `.env` are located.
- `start.sh` calls `docker compose up -d` and is safe for clean starts and image updates, but does **not** force-recreate containers — use `docker compose up -d --force-recreate` if containers are stale.
- After restarting, check service health with `docker compose ps` and `docker compose logs -f <service>`.

## Step 8 — Report

Summarise what was built and deployed, listing:
- Sub-modules built as Docker images (image name and tag)
- Sub-modules deployed as file artifacts (destination paths)
- Any sub-modules skipped and why
- Any open issues or errors encountered
