# Scripts

This folder contains utility scripts used to build, deploy, test, sync, and inspect the Ideable project.

## The layout answers two questions, and three rules keep it true

`scripts/` answers **when** a script runs at its top, and **who** runs it one level down. Nothing
sits at the top of the folder but this file, so there is no place to put a script that answers
neither.

```
scripts/
  dev/         used while developing, building, deploying, publishing and syncing — never at a site
    common/      both roles, shipped
    module/      the module maintainer, shipped
    master/      the framework maintainer, never shipped
  runtime/     exactly what a deployed site needs — this folder IS deployment_root/scripts/
  SPECS/       the specifications for the runtime scripts
  TESTS/       the framework's own suite, maintainer-only
  README.md
```

Three rules keep that shape from decaying, and each is a test rather than an intention:

1. **`runtime/` is copied whole.** The deploy copies the folder into `deployment_root/scripts/`
   with no exception list, so whether a file reaches a site is decided by where it sits.
   *Measured by `scripts/TESTS/test_runtime_is_the_deployed_folder.py`.*
2. **`runtime/` never names a path under `scripts/dev/`.** Dev may import runtime — the deploy
   imports `compose_merge.py` from `runtime/`, one file, so the deploy-time and site-time merges
   cannot diverge — but the reverse cannot work at a site, comments included: a path a reader is
   told to look at must exist where they are.
   *Measured by `scripts/TESTS/test_runtime_is_the_deployed_folder.py`.*
3. **Everything under `scripts/` ships except `dev/master/` and `TESTS/`.** One exclusion, not an
   allowlist, so a new folder travels without anyone remembering to list it — and the two paths a
   module project must not receive are the two that are named.
   *Measured by `scripts/TESTS/test_shipped_surface_is_covered.py` and
   `scripts/TESTS/test_scripts_are_positioned_by_when_they_run.py`.*

A layout move reaches existing projects whole: `scripts/dev/module/sync-template-updates.sh` removes
the old locations in the same run that delivers the new ones, so no project is left holding both
(`scripts/TESTS/test_sync_lands_a_layout_move.py`).

**`scripts/runtime/` IS the deployed `scripts/` folder.** The deploy copies it whole into
`deployment_root/scripts/`, so whether a file reaches a site is decided by where it sits and by
nothing else — there is no list to keep in sync, and `test_runtime_is_the_deployed_folder.py`
asserts the two file sets are equal. Two consequences follow. Anything a devops must be able to run
at a production site belongs in it. And nothing in it may name a path under `scripts/dev/`,
comments included: that path does not exist where the script runs, so it would send a reader
somewhere they are not.

`scripts/SPECS/` holds the specifications for the runtime scripts (`configure`, `start`,
`create-merged-configuration`, `change-secrets`, `update-deployable`) — the same `SPECS/` name every
other specs folder in the tree uses, so a spec is looked for in one place regardless of what it
governs.

## Active scripts, grouped by the folder that says when they run

`scripts/` answers **when** a script runs at its top — `dev/` or `runtime/` — and
**who** runs it one level down: `common/`, `module/`, `master/`. The catalogue is
grouped the same way, so a script is looked up by the question it answers rather than
by remembering its name. A script that nothing invokes is marked **manual-only**.

**A new script gets its entry here in the same change that adds it** —
`scripts/TESTS/test_script_catalogue_is_complete.py` fails otherwise, so the catalogue cannot lag
behind the folder. This file travels with the scripts it describes: a module project receives it,
and the entries a reader there follows are these.

### `scripts/dev/common/` — both roles use it, and it ships

Development-time scripts that mean the same thing in the framework repository and in a module
project: the deploy pipeline, the checks, the test runner, the dev-cycle router, the toolbox, the
schema workflow. Every one of them is copied into every module project, so a rule that names one
names a file its reader has.

The **repo-root entry points** are the real files behind the seven short commands, and they are
listed first because they are how everything below is usually reached.

#### Repo-root entry points
- **Purpose**: The commands a developer types from the repository root. Each one is a **symlink**
  into the folder that states when it runs; the real files live under `scripts/dev/common/`,
  because they run at development time and never at a deployed site.
- **Symlinks at the root**: `redeploy.sh`, `start.sh`, `stop.sh`, `status.sh`, `dev-cycle.sh`,
  `update_backend.sh`, `update_frontend.sh`. The root holds no script of its own.
- **Scripts** (the real files):
  - `scripts/dev/common/redeploy.sh` — full deploy wrapper with interactive prompts for rebuild, volume wipe, and container start.
  - `scripts/dev/common/start.sh` — starts the generated `deployment_root/` stack with `--pull missing` to ensure images are pulled when not available locally.
  - `scripts/dev/common/stop.sh` — stops the generated `deployment_root/` stack.
  - `scripts/dev/common/status.sh` — shows the status of the generated `deployment_root/` stack.
  - `scripts/dev/common/update_backend.sh` — rebuilds/deploys only the backend and restarts the backend container.
  - `scripts/dev/common/update_frontend.sh` — rebuilds/deploys only the frontend and recreates the frontend container.
- **Notes**:
  - The deployed site has its **own** `start.sh`, `stop.sh` and `status.sh`, which are different
    scripts: they come from `scripts/runtime/` and drive a site that never builds. Same three names,
    two different when-they-run answers, which is the reason the dev-time three moved under `dev/`.
  - A script reached through a root symlink must resolve `BASH_SOURCE[0]` before walking up to the
    repository root. Bash reports the path as invoked, so an unresolved walk to `../../..` lands
    one level **above** the repository, and `cd` succeeds there.
  - They are exported into `Ideable-ModuleTemplate` as symlinks and synced back by
    `scripts/dev/module/sync-template-updates.sh`.

#### `scripts/dev/common/build_and_deploy.py`
- **Purpose**: Builds enabled modules locally, deploys their artifacts into `deployment_root/`, merges compose files, merges env files, and copies `scripts/runtime/` into `deployment_root/scripts/`.
- **Usage**:
  ```bash
  python3 scripts/dev/common/build_and_deploy.py
  ```
- **Notes**:
  - Reads `project.env.config` + `project.env.secrets` first.
  - Uses `modules/enabled.md` to decide which modules participate.
  - Supports `--only-modules`, `--only-submodules`, `--skip-module-root-deploy`, and `--skip-generate-scripts`.
  - Builds Docker images locally as `<slug>.<submodule>:latest`, stamped with OCI labels (`revision`, `created`, `tech.ideable.dirty`) from git; keeps the replaced image as `:previous` and prunes the one that displaces. It does **not** push to a registry.
  - If you need registry publication, run the push script after build.
  - **`deployment_root/scripts/` is `scripts/runtime/`, copied whole.** The folder is the definition of what a site gets: add a file to `scripts/runtime/` and it is deployed, with no list in Python to keep in sync. `start.sh`, `stop.sh` and `status.sh` are **additionally** placed at the deployment root, where a devops runs them — they resolve the deployment root beside-or-above themselves, so both copies work. `framework.lock.json` is written to the deployment root through the resolver; `framework.env` is not copied, because a site inherits its release rather than choosing one.
  - **Uses**: module-specific `SPECS/build.sh` helpers, per-module `docker-compose.yml`, per-module `.env.config` + `.env.secrets`, `modules/enabled.md`.
  - **Used by**: `update_frontend.sh`, `update_backend.sh`.

#### `scripts/dev/common/push_module_images_to_registry.py`
- **Purpose**: Publishes a module's locally built images to its registry, under `latest` and — for a release — under the version too.
- **Usage**:
  ```bash
  python3 scripts/dev/common/push_module_images_to_registry.py -a              # publish :latest
  python3 scripts/dev/common/push_module_images_to_registry.py -a -t 1.7.0     # :1.7.0 and :latest
  python3 scripts/dev/common/push_module_images_to_registry.py host_app -t 1.7.0 --single-arch
  ```
- **Notes**:
  - A local build has one name, `<slug>.<submodule>:latest`. The registry is where a name starts meaning something, so that is where a version is chosen: `-t X.Y.Z` publishes both names **from one buildx build**.
  - `-t` is refused from a dirty working tree, and refused when the registry already holds that tag. There is no `--force`.
  - A partial publish is a failed publish: every ref the run owed is verified against the registry afterwards, and the last line reads `Published: n/n — complete` or `Published: FAILED — n/m`.
  - The registry comes from each module's own `MODULE_DOCKER_REGISTRY_PREFIX`, with `--registry` as a fallback. No version is read from any env file.
  - **Used by**: `scripts/dev/master/publish_framework.sh`, and module maintainers publishing their own module.

#### `scripts/dev/common/push_module_images_to_registry.sh`
- **Purpose**: Shell wrapper for `push_module_images_to_registry.py`.
- **Usage**:
  ```bash
  ./scripts/dev/common/push_module_images_to_registry.sh -a
  ./scripts/dev/common/push_module_images_to_registry.sh host_app module_template
  ```
- **Notes**:
  - Convenience entry point for shell users.
  - **Uses**: `push_module_images_to_registry.py`.
  - **Used by**: **manual-only** — nothing in this repository invokes it. A maintainer runs it, or shell-based automation outside the repository does.

#### `scripts/dev/common/run_enabled_tests.sh`
- **Purpose**: Runs `pytest` for every enabled module that has a `TESTS/` folder and writes a report under `TEST_REPORTS/`.
- **Usage**:
  ```bash
  ./scripts/dev/common/run_enabled_tests.sh
  ```
- **Notes**:
  - Uses `modules/enabled.md` to discover enabled modules.
  - Produces one report per module.
  - **Uses**: no other repo scripts.
  - **Used by**: the `Tests&Fix` workflow and the `test_and_fix` skill; otherwise manual runs.

#### `scripts/dev/common/update_skills.py`
- **Purpose**: Synchronises agent skill directories from the canonical `.agents/skills/` source. Ensures `.claude/skills` and `.kiro/skills` are symlinks. Generates `.devin/workflows/` files from Ideable-specific skills (`ideable-align-docs`, `ideable-build-and-deploy`, `ideable-implement-specs`, `ideable-test-and-fix`), stripping the `name:` frontmatter field. Fails validation if a second copy of the skills reappears at `.devin/skills/`.
- **Usage**:
  ```bash
  python3 scripts/dev/common/update_skills.py
  python3 scripts/dev/common/update_skills.py --dry-run
  python3 scripts/dev/common/update_skills.py --validate
  python3 scripts/dev/common/update_skills.py --target devin
  ```
- **Notes**:
  - The canonical source of truth for all agent skills is `.agents/skills/`. The per-tool directories are symlinks to it — editing a skill there immediately takes effect for all supported AI development environments (Claude Code, Windsurf/Devin, Kiro).
  - Devin gets no skills directory of its own. `.agents/skills/<name>/SKILL.md` is the first and recommended path in its [documented skill search](https://docs.devin.ai/product-guides/skills), so it reads the canonical real files directly. A `.devin/skills/` copy existed until 2026-08-31 and was measured stale in two skills when removed — `--validate` now fails if one comes back.
  - `.devin/workflows/` files are generated from the canonical skill `SKILL.md` files with the `name:` frontmatter line removed, keeping only `description:`.
  - `--dry-run` reports what would change without touching the filesystem.
  - `--validate` checks parity without modifying anything; exits 0 if all in sync, 1 otherwise.
  - `--target` limits the scope to one tool (`claude`, `windsurf`, `kiro`, `devin`) or `all` (default).
  - **Uses**: no other repo scripts.
  - **Used by**: **manual-only** — run by hand after a fresh clone and after adding or removing a skill. `--validate` is the topology check `rules/authoring-guidelines.md` points at, and `scripts/TESTS/test_agent_skill_topology.py` guards both its output and its source. No script invokes it: `push-updates-to-module_template-repo.sh` copies `.agents .kiro .claude .devin` as trees and depends on the symlinks this script maintains already being correct — a dependency, not a call.

#### `scripts/dev/common/validate_modules.sh`
- **Purpose**: Validates every module's `module.json` against the schema and its compose file against the framework's hard rules, and emits the `provides`-vs-reality and drift lints.
- **Usage**:
  ```bash
  ./scripts/dev/common/validate_modules.sh
  ```
- **Notes**:
  - Enforces the rules `rules/general-guidelines.md` states: no `build:` sections, no env-var placeholders in top-level `networks`/`volumes` keys, services must be mappings.
  - Also runs the tenancy-marker and application-DB-role gates below, both of which **fail** validation.
  - Runs the entity-DDL check as well, for every module that has backend models — and that one **reports without failing**, so a reader who does not look at the output will not see it. It is the only non-fatal check here; its binding assertion is `scripts/TESTS/test_entity_ddl_is_complete.py`, which carries the baseline that can be pruned as the gaps close.
  - **Uses**: `scripts/dev/common/check_tenancy_markers.py`, `scripts/dev/common/check_app_db_role.py`, `scripts/dev/common/check_entity_ddl.py`.
  - **Used by**: the deploy path and `gate.yml`.

#### `scripts/dev/common/verify_build_identity.py`
- **Purpose**: Fails a deploy whose images are not the build it just made, by reading the `org.opencontainers.image.revision` label off every locally built image and comparing it with `HEAD`.
- **Usage**:
  ```bash
  python3 scripts/dev/common/verify_build_identity.py [repo-root]
  ```
- **Notes**:
  - Every local image is `<slug>.<submodule>:latest`, so the name cannot say which build it is; the label can. `build_and_deploy.py` stamps it and calls `check_image()` right after each build (a failed `docker build` leaves the previous image under `latest`).
  - The CLI checks the whole deployed compose as a set: only images of modules enabled `local` — a consumed image carries the publisher's revision.
  - **Runs only after a build** from `redeploy.sh`; a plain restart has no build to compare with.
  - Says so — rather than claiming a pass — when the deployed compose names no locally built image.
  - **Used by**: `build_and_deploy.py` (per image), `redeploy.sh` (after the merged configuration is regenerated).

#### `scripts/dev/common/check_tenancy_markers.py`
- **Purpose**: Fails the build when a model does not **declare** whether it is tenant-scoped.
- **Usage**:
  ```bash
  python3 scripts/dev/common/check_tenancy_markers.py <module>
  ```
- **Notes**:
  - A build gate rather than a review habit because the failure mode is silent: a table without `tenant_id` does not raise, log or fail a test — it just holds every customer's rows in one undivided set.
  - **Uses**: no other repo scripts.
  - **Used by**: `scripts/dev/common/validate_modules.sh`.

#### `scripts/dev/common/check_app_db_role.py`
- **Purpose**: Fails the build when a tenant-scoped module has no restricted application DB role, or does not connect as it.
- **Usage**:
  ```bash
  python3 scripts/dev/common/check_app_db_role.py <module>
  ```
- **Notes**:
  - Row-Level Security cannot constrain a superuser — Postgres exempts them unconditionally — so a module whose rows belong to tenants needs a `NOSUPERUSER NOBYPASSRLS` role created by the bootstrap job.
  - Contract: `modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md` § *The application role*.
  - **Uses**: no other repo scripts.
  - **Used by**: `scripts/dev/common/validate_modules.sh`.

#### `scripts/dev/common/check_entity_ddl.py`
- **Purpose**: Reports the framework DDL an entity's declarations promise and does not have.
- **Usage**:
  ```bash
  python3 scripts/dev/common/check_entity_ddl.py <module>
  ```
- **Notes**:
  - Adding an entity means nine pieces of DDL, of which Alembic autogenerate writes one; two of the remaining eight fail silently.
  - **Uses**: no other repo scripts.
  - **Used by**: `scripts/dev/common/validate_modules.sh`, for every enabled module that has backend models — which puts the findings in front of the person validating the module. It **reports there and does not fail**: the binding assertion is `scripts/TESTS/test_entity_ddl_is_complete.py`, which carries the baseline that can be pruned as the gaps close.

#### `scripts/dev/common/check_shared_versions.py`
- **Purpose**: Fails the deploy when enabled modules disagree on a shared Module Federation singleton (`react`, `react-dom`, `react-router-dom`).
- **Usage**:
  ```bash
  python3 scripts/dev/common/check_shared_versions.py
  ```
- **Notes**:
  - Nothing compared those declarations before the browser did, and in the browser a singleton conflict is a white screen blamed on the module that happened to load second.
  - **Uses**: no other repo scripts.
  - **Used by**: the deploy path.

#### `scripts/dev/common/module_deps.py`
- **Purpose**: Resolves the inter-module dependency graph declared in each `module.json` (`provides` / `dependsOn`) into a providers-first build and startup order.
- **Usage**:
  ```bash
  python3 scripts/dev/common/module_deps.py
  ```
- **Notes**:
  - Canonical contract: `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md` §5.1.
  - **Uses**: no other repo scripts.
  - **Used by**: `scripts/dev/common/build_and_deploy.py`, `scripts/dev/common/compose_deps.py`.

#### `scripts/dev/common/compose_deps.py`
- **Purpose**: Generates an **additive** compose override expressing cross-module `depends_on` from the resolved dependency edges and each provider's declared readiness gates.
- **Usage**:
  ```bash
  python3 scripts/dev/common/compose_deps.py
  ```
- **Notes**:
  - Additive by design: it never rewrites a module's own compose file.
  - **Uses**: `scripts/dev/common/module_deps.py`.
  - **Used by**: `scripts/dev/common/build_and_deploy.py`.

#### `scripts/dev/common/container_stack_env.sh`
- **Purpose**: Defines where the running stack is, as seen from inside the dev tools container. Sourced, never executed.
- **Usage**:
  ```bash
  source scripts/dev/common/container_stack_env.sh
  container_stack_addresses
  container_module_addresses host_app module_template
  ```
- **Notes**:
  - One definition for both test runners; the addresses are service names (`http://backend:8001`) resolved on the stack network the container joins.
  - A module's `<SLUG>_API_URL` is derived from its `.env.config` backend port, and the port is **resolved**, not pattern-matched: a bare number, `${VAR:-8002}` or `${VAR}` all work, with `VAR` looked up in the environment, the module's own `.env.config`, `deployment_root/.env.config`, then `project.env.config`. `.env.config.example` ships the reference form, so a numeric-only match covered neither the module's own key nor the shape new modules start from.
  - When a port cannot be derived, it **says so per module** and names what is missing. It does not fall through silently: with no `<SLUG>_API_URL` the module's `conftest.py` uses its `http://localhost:<port>` default, which inside the container is the container, and every API test then skips while the run reports `0 failed`.
  - **Uses**: no other repo scripts.
  - **Used by**: `scripts/dev/common/run_enabled_tests.sh`, `scripts/dev/module/run_tests.sh`.

#### `scripts/dev/common/stack_free_tests.py`
- **Purpose**: Prints the test files that need nothing but a checkout — the set CI runs.
- **Usage**:
  ```bash
  python3 scripts/dev/common/stack_free_tests.py
  ```
- **Notes**:
  - **Computed, never hardcoded**: a committed list would be right the day it was written and wrong thereafter.
  - It is a selector — it decides which tests CI runs and runs none itself.
  - **Uses**: no other repo scripts.
  - **Used by**: `.github/workflows/gate.yml`, `scripts/dev/common/verify_stack_free.sh`.

#### `scripts/dev/common/verify_stack_free.sh`
- **Purpose**: Runs the CI-selected tests against a **pristine checkout** — exactly the condition CI has.
- **Usage**:
  ```bash
  ./scripts/dev/common/verify_stack_free.sh
  ```
- **Notes**:
  - The selector above is a heuristic over imports and conftest chains, and a heuristic is wrong until something checks it; twice it was.
  - **Uses**: `scripts/dev/common/stack_free_tests.py`, `scripts/dev/common/tool.sh`.
  - **Used by**: **manual-only** — nothing invokes it. A maintainer runs it to verify the CI gate's stack-free selection locally.

#### `scripts/dev/common/agent_conversation.py`
- **Purpose**: The router's side of a conversation with the agent it runs — permission requests and the agent's own questions, put to the person who ran the command.
- **Usage**: not run directly; imported by `scripts/dev/common/dev_cycle.py` when it performs an LLM node.
- **Notes**:
  - Supplies the Agent SDK's `can_use_tool`, so two things reach the terminal: permission for an action the project's allow-list did not settle, and an answer to a question only the maintainer can decide (`AskUserQuestion` — the mechanical form of the decision-authority rule).
  - `DEV_CYCLE_AGENT_PERMISSIONS` sets the policy: `ask` (default on a TTY) · `deny` (default without one) · `accept-edits` · `skip`. `deny` is the old behaviour, now named — an unattended run must neither block on a question nor grant one.
  - An `a` answer allows that ONE tool for the rest of the run and is never persisted; a standing grant belongs in `.claude/settings.json`.
  - A set of questions is answered **one at a time**: each is shown immediately before its own prompt, and the prompt names which question it collects (`your answer to question 2 of 2 (Doc convention):`). There is no syntax for answering several at once — a combined reply is one verbatim answer to the question being asked.
  - Appends one row per finished agent run to `TEST_REPORTS/AGENT-RUNS.md` — node/skill, seconds, turns, **seconds per turn**, cost, result, commit — recorded whether or not the run was `quiet`. Total seconds move with how much work a node was given; seconds per turn is the number that answers "are the agent steps getting slower?", which had no answer while the duration was printed and kept nowhere.
  - The SDK is an **optional** dependency: absent, the router falls back to suggesting the skill, and `--deterministic` drives the whole cycle without any agent.
  - **Used by**: `scripts/dev/common/dev_cycle.py`.

#### `scripts/dev/common/dev_cycle.py`
- **Purpose**: The deterministic dev-cycle router `scripts/dev/common/dev-cycle.sh` delegates to — it moves a plan between nodes, renames it, and folds test results back into it.
- **Usage**: invoked through `scripts/dev/common/dev-cycle.sh`; see that entry.
- **Notes**:
  - It does not run LLM steps; those stay with the skills.
  - Canonical graph: `rules/implementation-plan.md` § *Overall view*.
  - **Uses**: `scripts/dev/common/run_enabled_tests.sh`, `redeploy.sh`.
  - **Used by**: `scripts/dev/common/dev-cycle.sh`.

#### `scripts/dev/common/spec_workset.py`
- **Purpose**: Computes the incremental work-set for `ideable-implement-specs` — which specs are worth re-implementing this run.
- **Usage**:
  ```bash
  python3 scripts/dev/common/spec_workset.py [--force]
  ```
- **Notes**:
  - A cache **hint**, never a source of truth: it tracks the input, and correctness is established later by tests (`Done ⇐ contract tests pass`).
  - **Uses**: no other repo scripts.
  - **Used by**: the `ideable-implement-specs` skill.

#### `scripts/dev/common/ensure_hooks.sh`
- **Purpose**: Enables this repository's git hooks if they are not already enabled.
- **Usage**:
  ```bash
  ./scripts/dev/common/ensure_hooks.sh
  ```
- **Notes**:
  - `core.hooksPath` lives in `.git/config`, which is not repository content — git deliberately does not ship hooks with a clone, so a hook protects only the clone where someone turned it on.
  - **Uses**: no other repo scripts.
  - **Used by**: post-clone setup; the test runner.

#### `scripts/dev/common/tool.sh`
- **Purpose**: Runs any dev-cycle tool inside the dev tools container instead of on this machine — the project's single toolchain. Every shipped script that invokes `pytest`, `ruff`, `mypy` or `npx` re-execs through it first.
- **Usage**:
  ```bash
  ./scripts/dev/common/tool.sh ruff check modules scripts
  ./scripts/dev/common/tool.sh pytest -q scripts/TESTS
  ./scripts/dev/common/tool.sh --doctor          # assert the image carries every required tool
  ./scripts/dev/common/tool.sh --shell           # interactive
  ./scripts/dev/common/tool.sh --stop            # remove this project's container
  ```
- **Notes**:
  - One container per project, named `ideable.devtools.<APP_SLUG>`; a container carrying that name but another checkout's mount is recreated for the active checkout. See `rules/version-control.md` § *What a fresh clone needs* and § *One active checkout per project, on one host*.
  - Joins this project's stack network, matched on the compose project, so services resolve by name (`backend:8001`). With no identifiable project it joins nothing.
  - `IDEABLE_NO_CONTAINER=1` runs the host toolchain instead and gives up that parity.
  - The image is pulled **by the digest `framework.lock.json` records** and never built here. On a pinned version a local image that differs from the lock is a hard failure; on `latest` it is pulled and retagged to follow the lock.
  - **Uses**: `scripts/dev/common/devtools_version.sh` (and through it `scripts/runtime/framework_version.py`).
  - **Used by**: every shipped and master-only script that runs a dev tool, the `ideable-*` skills, and `.githooks/pre-push`.

#### `scripts/dev/common/devtools_version.sh`
- **Purpose**: The dev tools shell library — which image this project runs (asked of `scripts/runtime/framework_version.py`), how it is pulled and checked against the lock, and the project slug its container and stack are named for. Sourced, never executed.
- **Usage**:
  ```bash
  source scripts/dev/common/devtools_version.sh
  devtools_version            # latest | X.Y.Z
  devtools_image_ref          # ghcr.io/<owner>/ideable-devtools:<version>
  devtools_locked_digest      # sha256:…, from framework.lock.json
  devtools_ensure_locked_image <image> <digest> <version>
  devtools_pull_locked_image   <image> <digest>
  devtools_container_name     # ideable.devtools.<APP_SLUG>
  devtools_project_slug       # APP_SLUG, raw
  ```
- **Notes**:
  - Reads neither `framework.env` nor `framework.lock.json` itself: `scripts/runtime/framework_version.py` is the one reader, and a second parser in shell is how two readers stop agreeing. There is no precedence chain and no shell override.
  - One definition, several callers — `tool.sh`, `pull_devtools_image.sh` and the publish script must name the same image, and the container name and stack filter the same project.
  - **Uses**: `scripts/runtime/framework_version.py` (needs `python3` on the host).
  - **Used by**: `scripts/dev/common/tool.sh`, `scripts/dev/common/pull_devtools_image.sh`, `scripts/dev/master/push_devtools_image_to_registry.sh`.

#### `scripts/dev/common/pull_devtools_image.sh`
- **Purpose**: Makes the local dev tools image be exactly the one `framework.lock.json` names — pulled by digest and tagged with the project's reference — and optionally recreates the container from it.
- **Usage**:
  ```bash
  ./scripts/dev/common/pull_devtools_image.sh
  ./scripts/dev/common/pull_devtools_image.sh --restart
  ```
- **Notes**:
  - `tool.sh` pulls on its own when the image is absent, or on `latest` when the lock has moved. On a pinned version it refuses to replace a differing image, because that difference means a re-pushed tag or a hand-built image; this script is the deliberate act that replaces it.
  - A running container keeps the old image until it is recreated, which is what `--restart` does.
  - **Uses**: `scripts/dev/common/devtools_version.sh`.
  - **Used by**: manual runs — after a sync moved the lock, or to replace a toolbox the pinned-version check refused.

#### `scripts/dev/common/schema.sh`
- **Purpose**: Drives the four phases of the schema workflow — design → model → migration → verify — for a module's database.
- **Usage**:
  ```bash
  ./scripts/dev/common/schema.sh <phase> <module>
  ```
- **Notes**:
  - Mandated by `modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md` for every phase: the model is the schema, and only Alembic writes it.
  - **Uses**: `scripts/dev/common/tool.sh` (it drives `alembic` and `sqlacodegen` inside the container).
  - **Used by**: module maintainers changing any table.

#### `scripts/dev/common/loadtest.py`
- **Purpose**: Constant-concurrency load generator reporting throughput **and** status codes over time.
- **Usage**:
  ```bash
  python3 scripts/dev/common/loadtest.py --help
  ```
- **Notes**:
  - Reports status codes per second because a rolling deploy that drops requests for one second still looks fine in a 99.9% 2xx total.
  - **Uses**: no other repo scripts.
  - **Used by**: **manual-only** — nothing invokes it. A person runs it against a deployment to produce the horizontal-scale and rolling-deploy acceptance measurements.

#### `scripts/dev/common/dev-cycle.sh`
- **Purpose**: Thin deterministic router over the dev-cycle skill graph — nodes are dev states, arcs are the Ideable skills.
- **Usage**:
  ```bash
  ./scripts/dev/common/dev-cycle.sh status              # where are we, and what is next
  ./scripts/dev/common/dev-cycle.sh set <NODE>          # recolour the plan graph, set Current step
  ./scripts/dev/common/dev-cycle.sh run                 # run the current node and advance
  ./scripts/dev/common/dev-cycle.sh deliver [--pr]      # land a plan at Done on the target branch
  ```
- **Notes**:
  - Canonical graph and status legend: `rules/implementation-plan.md` § *Overall view*.
  - `NotStarted` and `Branching` are performed by the router itself (the second creates the plan branch); deterministic nodes run here; LLM nodes are performed by a headless agent, and it refuses to spawn a second agent onto the same plan.
  - **Uses**: `scripts/dev/common/dev_cycle.py`, `redeploy.sh`, `scripts/dev/common/run_enabled_tests.sh`.
  - **Used by**: maintainers driving a plan through the cycle.

#### `scripts/dev/common/push-deployable-to-git.sh`
- **Purpose**: Pushes the `deployment_root/` content to a git remote as a deployable bundle.
- **Usage**:
  ```bash
  ./scripts/dev/common/push-deployable-to-git.sh [MODULE_NAME] [-n REPO_NAME] [-t TAG] [-u GIT_USER] [-g GIT_REMOTE]
  ```
- **Notes**:
  - The publishing half of the deployable flow; the pull script below is its counterpart at the deployed site.
  - **Uses**: no other repo scripts.
  - **Used by**: **manual-only** — nothing invokes it. A module maintainer runs it when releasing a deployable.

### `scripts/dev/module/` — the module maintainer, and it ships

The three scripts a module maintainer runs in their own project: create the module, sync the
framework files for the version they track, run their module's tests. They ship for the same reason
`dev/common/` does — the reader is the person who runs them.

#### `scripts/dev/module/template_remote.sh`
- **Purpose**: States the module-side template repository URL once. Sourced, not executed.
- **Used by**: `sync-template-updates.sh` (fetches from it), `adopt_framework.sh` (reads a release's `framework.lock.json` out of it before any sync can run), `module-init.sh` (sets it as a new project's `template` remote).
- **Notes**:
  - The maintainer-side push uses the **SSH** form of the same repository, deliberately: pushing needs a key, fetching does not, and a remote project must never be handed a push URL it cannot use.

#### `scripts/dev/module/adopt_framework.sh`
- **Purpose**: Adopts a framework release in this project — reads that release's `framework.lock.json` out of the template repository, writes it and `IDEABLE_FRAMEWORK_VERSION`, then runs the sync that brings the release's files, so the project's choice and its facts move together or not at all.
- **Usage**:
  ```bash
  ./scripts/dev/module/adopt_framework.sh 1.6.3      # pin this project to that release
  ./scripts/dev/module/adopt_framework.sh latest     # follow the channel
  ./scripts/dev/module/adopt_framework.sh 1.6.3 -a   # further arguments go to the sync
  ```
- **Notes**:
  - **The mirror of `publish_framework.sh`.** The maintainer names a release once, to the publish; a project names the same release once, to this. Neither side asks anyone to edit `framework.env` and remember to act on it.
  - **It installs the lock rather than waiting for the sync to deliver it.** `framework.lock.json` is the file every other resolution reads, so arriving as one more force-synced file means it turns up during the step that already needed it — and a project whose lock is missing or corrupt then cannot sync, while the resolver's error tells the reader to run the sync. Reading it from the release's own tag first removes that deadlock; the sync then force-syncs the same bytes from the same ref.
  - **Nothing is written until the release is proven to exist**, and if the sync fails both files are restored. A project naming a release whose files it does not have resolves nothing, and that half-state is what this command exists to remove.
  - It finishes by running `framework_version.py check`, so an adoption that left the two files disagreeing is reported rather than declared complete.
- **Uses**: `scripts/dev/module/sync-template-updates.sh`, `scripts/runtime/framework_version.py`.

#### `scripts/dev/module/module-init.sh`
- **Purpose**: Creates a new module from `module_template` by renaming the template subtree and updating its metadata.
- **Usage**:
  ```bash
  ./scripts/dev/module/module-init.sh NewModuleName
  ```
- **Notes**:
  - Creates `framework.env` with `IDEABLE_FRAMEWORK_VERSION=latest` when absent — the one line the new project owns, which sync never writes.
  - The module name must start with a letter and contain only letters and numbers.
  - **Uses**: no other repo scripts.
  - **Used by**: **manual-only** — nothing invokes it. A person runs it once, to create a module.

#### `scripts/dev/module/run_tests.sh`
- **Purpose**: Runs backend and frontend tests for a single module.
- **Usage**:
  ```bash
  ./scripts/dev/module/run_tests.sh [module_name]
  ```
- **Notes**:
  - If no module is passed, the script tries to auto-detect one.
  - **Uses**: no other repo scripts.
  - **Used by**: **manual-only** — nothing invokes it. A module maintainer runs it for a single module; `scripts/dev/common/run_enabled_tests.sh` is what the dev cycle and CI run.

#### `scripts/dev/module/sync-template-updates.sh`
- **Purpose**: Brings the framework files for the version this project asks for into a module project.
- **Usage**:
  ```bash
  ./scripts/dev/module/sync-template-updates.sh --list-changes
  ./scripts/dev/module/sync-template-updates.sh --file frontend/SPECS/shared-ui-specs.md
  ./scripts/dev/module/sync-template-updates.sh
  ```
- **Notes**:
  - **The ref follows the framework version**: `main` on the `latest` channel, the version itself (`1.6.3`, not `v1.6.3`) when `framework.env` pins one. It asks `scripts/runtime/framework_version.py template-ref` rather than resolving it a second time.
  - A pinned version the framework never published is an **error** naming the line to change. There is no fall-back to `main`: that would deliver another version's files and report success.
  - `framework.lock.json` is force-synced (generated by the framework). `framework.env` is **never written** — it is the one line the module maintainer owns.
  - **A layout move lands whole.** Before any file is compared, the sync removes the locations a `scripts/` reorganisation left behind — the old role folders, `runtime/config/`, and anything loose at the top of `scripts/` or directly inside `scripts/dev/` — and renames a lower-case `specs` directory inside `scripts/` to `SPECS` through a temporary name, which is the only sequence that works for a case-only rename on a case-insensitive filesystem. Each removal prints a `[migrated]` line. Without it a project would hold both layouts, with the synced root commands resolving through whichever the shell reached first and nothing about it looking wrong.
  - **Uses**: `scripts/runtime/framework_version.py`, the `template` git remote.
  - **Used by**: module maintainers adopting a framework version.

### `scripts/dev/master/` — the framework maintainer, and it never ships

Publishing, pushing the template, and verifying that what was pushed is usable. These are the
scripts a module project must **not** receive: a remote that could publish could publish something
different. The folder is the exclusion — `scripts/dev/master` and `scripts/TESTS` are the two paths
the push script names, and everything else under `scripts/` travels by default.

#### `scripts/dev/master/check_module_template_lf_parity.sh`
- **Purpose**: Runs the module_template line-feed parity contract tests and, by default, the Playwright snapshot checks.
- **Usage**:
  ```bash
  ./scripts/dev/master/check_module_template_lf_parity.sh
  ```
- **Notes**:
  - Set `RUN_PLAYWRIGHT=0` to skip the Playwright part.
  - **Uses**: `pytest` and Playwright CLI commands.
  - **Used by**: **manual-only** — nothing invokes it. The maintainer runs it when changing the shared Look & Feel.

#### `scripts/dev/master/publish_framework.sh`
- **Purpose**: Publishes a framework version — the host_app images, the dev tools image, `framework.lock.json` and the template repository — under the one name given on its command line, which it writes into `framework.env` so every later step reads a single source.
- **Usage**:
  ```bash
  ./scripts/dev/master/publish_framework.sh 1.6.3        # publish that release
  ./scripts/dev/master/publish_framework.sh latest       # publish the channel
  ./scripts/dev/master/publish_framework.sh latest --dry-run   # show the plan, touch nothing
  ```
- **Notes**:
  - **A release ends in a commit, a tag and a push.** The two files the publish writes — `framework.env` and the regenerated `framework.lock.json` — are committed as `chore(release): framework <version>`, the tag is put on that commit, and both are pushed with `git push --follow-tags`. That flag is the only one-command answer: plain `git push` publishes no tags, and `git push origin <version>` leaves the branch ref behind so the release commit is reachable only from the tag. It is also why the tag is annotated — `--follow-tags` ignores lightweight ones. A branch with no upstream is not pushed, and the run says so and prints the command. The template repository is tagged in step 4 by the push itself.
  - **The version is required and named as a bare argument**, not a flag, and the script writes it into `IDEABLE_FRAMEWORK_VERSION` after the images and before the toolbox publish — so the argument is an input to the run, not a second place a version is stated. A failed run restores the previous value. There is no default: `framework.env` names a published version after any release, and republishing one is refused, so a bare form would break permanently. A release also moves `latest` and tags both git repositories.
  - **`latest` is a channel and may be published repeatedly.** It carries no `--tag`, so neither the immutability guard nor the dirty-tree gate applies: publish it, change something, publish it again. That is the loop a maintainer shares with a remote running `adopt_framework.sh latest` while a release is still being settled. A remote picks up each new publish from the template repository, which step 4 force-syncs, so it does not wait on the maintainer pushing their own repository.
  - The order is load-bearing and each step gates the next: the lock records the digests the registry actually resolved, so it cannot be written before the images exist, and the template push carries that lock.
  - A partial publish is a failed publish: the run stops at the first failure rather than shipping a lock that names images nobody pushed.
  - **Uses**: `push_module_images_to_registry.py`, `push_devtools_image_to_registry.sh`, `write_framework_lock.py`, `push-updates-to-module_template-repo.sh`, `scripts/runtime/framework_version.py`.
  - **Used by**: **manual-only** — nothing invokes it. The Ideable maintainer runs it for every framework publish.

#### `scripts/dev/master/push-updates-to-module_template-repo.sh`
- **Purpose**: Builds a curated export of the current repository and force-pushes it to the standalone `Ideable-ModuleTemplate` repository.
- **Usage**:
  ```bash
  ./scripts/dev/master/push-updates-to-module_template-repo.sh
  ./scripts/dev/master/push-updates-to-module_template-repo.sh --tag 1.6.3   # and tag the pushed commit
  ```
- **Notes**:
  - **`--tag <name>` tags the commit it just pushed**, which is how a release is identified on the receiving side: a project pinned to `<name>` fetches `refs/tags/<name>` from this repository. `publish_framework.sh` passes it for a release, so an untagged release — one nobody could adopt by name — is not a state the publish can reach. An existing tag is left alone rather than moved.
  - Copies the module_template subtree, host_app skeleton files, shared scripts, and selected repo-level docs/config.
  - Renames the exported long-form docs to `IDEABLE-README.md` and `MODULE-README.md`, then leaves placeholder `README.md` files in the repo root and module root for template users to customize.
  - Exports AI dev environment config: `AGENTS.md`, `CLAUDE.md`, `rules/`, `.agents/`, `.claude/`, `.kiro/`, `.cursor/`, `.github/`.
  - Also exports the seven repo-root entry points — `redeploy.sh`, `start.sh`, `stop.sh`, `status.sh`, `dev-cycle.sh`, `update_backend.sh` and `update_frontend.sh`, every one a symlink into `scripts/dev/common/` — copied with `cp -R`, which preserves a symlink as a link rather than duplicating its target.
  - **Uses**: copies `scripts/` **minus `dev/master/` and `TESTS/`** — one exclusion, so a new folder under `scripts/` travels without anyone remembering to list it — plus the repo-root helper symlinks; no other repo scripts are executed.
  - **Used by**: `scripts/dev/master/verify_remote_shape.sh`, which asks it for the skeleton with `--stage-only` rather than re-listing the inventory — so what a remote contains has one definition.

#### `scripts/dev/master/push_devtools_image_to_registry.sh`
- **Purpose**: Publishes the dev tools image to the GitHub Container Registry, multi-arch, and records the published digest in `framework.lock.json` (and the human-facing block in host_app's `dependencies.md`).
- **Usage**:
  ```bash
  ./scripts/dev/master/push_devtools_image_to_registry.sh                  # :latest
  ./scripts/dev/master/push_devtools_image_to_registry.sh --tag 1.2.0      # :1.2.0 and :latest
  ```
- **Notes**:
  - Master-only because only the main repository builds a dev tools image; a project that could build its own would have a second toolbox free to differ from the published one.
  - The image repository is the `devtools.image` the lock records (override with `--registry`).
  - **Uses**: `scripts/dev/common/devtools_version.sh`, `scripts/dev/master/write_framework_lock.py`.
  - **Used by**: the framework maintainer at release time.

#### `scripts/dev/master/write_framework_lock.py`
- **Purpose**: Writes `framework.lock.json` from what the registry actually holds — every digest is the registry's answer for a published tag. The lock names the template repository and no commit, because the publish copies the lock into the template commit it pushes. The lock is generated, never typed.
- **Usage**:
  ```bash
  python3 scripts/dev/master/write_framework_lock.py --version latest --devtools-tag 1.6.1 --hostapp-tag 1.6.0
  python3 scripts/dev/master/write_framework_lock.py --devtools-digest sha256:…   # record one pushed digest
  ```
- **Notes**:
  - Defaults (dev tools image, host_app registry, template repository) come from the existing lock; a first lock states them once with `--devtools-image`, `--registry`, `--template-repo`.
  - host_app's image names are read from `modules/host_app/docker-compose.yml`, the file that decides which images exist.
  - **Uses**: `scripts/runtime/framework_version.py`.
  - **Used by**: `scripts/dev/master/push_devtools_image_to_registry.sh`; the maintainer when bootstrapping or re-deriving the lock.

#### `scripts/dev/master/verify_remote_shape.sh`
- **Purpose**: Runs the CI-selected tests against a generated **remote module project** — the shape `gate.yml` runs in everywhere except this repository.
- **Usage**:
  ```bash
  ./scripts/dev/master/verify_remote_shape.sh
  ```
- **Notes**:
  - Stages the project by asking the push script to assemble it, rather than re-listing what ships.
  - Also proves the `scripts/` layout migration against the **shipped** sync script — the copy inside the staged project, which is the one a module maintainer runs — on a throwaway tree built on the old layout. A migration that existed only here would leave every real project holding both layouts.
  - `KEEP_REMOTE_SHAPE_DIR` builds it at a chosen path and leaves it there. A tree left that way is a fixture, not a checkout: a scan that walks it reads the old layout it deliberately contains as evidence the move never happened, which is why the layout tests exclude `.ideable-work/` and `tmp/`.
  - **Uses**: `scripts/dev/master/push-updates-to-module_template-repo.sh`, `scripts/dev/common/tool.sh`.
  - **Used by**: the maintainer before a template push.

#### `scripts/dev/master/verify_entity_from_specs.sh`
- **Purpose**: Asks whether a remote module maintainer can add an entity by following the shipped specs **alone**.
- **Usage**:
  ```bash
  ./scripts/dev/master/verify_entity_from_specs.sh
  ```
- **Notes**:
  - One level harder than `verify_remote_shape.sh`: that asks whether the framework's own tests pass in a generated project, this asks whether the specs shipped there are sufficient to build something new.
  - **Uses**: `scripts/dev/master/verify_remote_shape.sh`, `scripts/dev/common/check_entity_ddl.py`, `scripts/dev/common/tool.sh`.
  - **Used by**: **manual-only** — nothing invokes it. The maintainer runs it when changing entity specs.

### `scripts/runtime/` — what a deployed site runs

This folder **is** `deployment_root/scripts/`, copied whole. A devops at a production site has
these and nothing else, so each entry below is written for that reader: no build, no repository,
no `scripts/dev/` to reach for.

#### `scripts/runtime/framework_version.py`
- **Purpose**: The **one reader** of `framework.env` (the framework version a person chose: one line, `latest` or `X.Y.Z`) and `framework.lock.json` (the digests the publish recorded for it, and the template repository). Every other reference to a framework version is derived through it.
- **Usage**:
  ```bash
  python3 scripts/runtime/framework_version.py version              # latest | X.Y.Z
  python3 scripts/runtime/framework_version.py devtools-image-ref   # <image>:<version>
  python3 scripts/runtime/framework_version.py devtools-repo        # <image>, no tag, ungated
  python3 scripts/runtime/framework_version.py devtools-digest      # sha256:…
  python3 scripts/runtime/framework_version.py hostapp-image-refs   # <name> <ref> <digest> per line
  python3 scripts/runtime/framework_version.py deployed-hostapp-image-refs   # same, for a deployed site
  python3 scripts/runtime/framework_version.py template-ref         # <repo> <ref>
  python3 scripts/runtime/framework_version.py check                # both files valid and agreeing
  ```
- **Notes**:
  - `framework.env` holds exactly one key; a second key, or `IDEABLE_FRAMEWORK_VERSION` set in the shell, is a failure — the file is the only source, so a change to it shows in `git diff`.
  - Image references are derived only from a lock published for the version the file asks for; a mismatch names the command that resolves it (sync in a module project, the publish here).
  - **It travels to a deployed site**, because it lives in `scripts/runtime/` and that folder is copied whole into `deployment_root/scripts/`, and there it reads the deployed `framework.lock.json` and no `framework.env` — a site inherits the release the module maintainer chose rather than choosing one. `deployed-hostapp-image-refs` is that path: a tree holding the choice has the pair compared as always, and a tree holding only the lock is answered from the lock's own `version`.
  - **The deployed copy, in `deployment_root/scripts/`, refuses to guess its tree** and must be given `--root`. Relative to that copy the project root would be *above* the deployment root, so a default would resolve a parent checkout's release and report it as the site's — the defect that made the site-side puller pass in a maintainer's tree and fail everywhere else. Only the checkout copy, the one whose own directory is `scripts/runtime/`, defaults.
  - `--root PATH` reads another tree, which is how the tests stage a project and how the deployed copy is told which site it belongs to.
  - **Uses**: no other repo scripts.
  - **Used by**: `scripts/dev/common/devtools_version.sh` (and through it `tool.sh`, `pull_devtools_image.sh`, the devtools publish), `scripts/dev/master/write_framework_lock.py`, `build_and_deploy.py` (which also copies it to `deployment_root/scripts/`), and there the deployed `pull-hostapp-images.sh`.

#### `scripts/runtime/pull-module-deployable-from-git.sh`
- **Purpose**: Pulls a module deployable bundle from a git remote into the current `deployment_root/` folder.
- **Usage**:
  ```bash
  ./scripts/runtime/pull-module-deployable-from-git.sh [MODULE_NAME] [-n REPO_NAME] [-t TAG]
  ```
- **Notes**:
  - The receiving half of the flow above — run at the deployed site, which has only the runtime scripts.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/start.sh`
- **Purpose**: Starts all Docker Compose containers for this project at a deployed site.
- **Usage**:
  ```bash
  ./scripts/runtime/start.sh
  ```
- **Notes**:
  - The runtime scripts are what a deployed site has: images come from the registry as-is, with no sources and no build.
  - `deployment_root/start.sh` is the copy a deployer actually runs. It is this file, placed at the deployment root by the deploy in addition to the whole-folder copy under `deployment_root/scripts/`; both copies resolve the deployment root beside-or-above themselves.
  - **Uses**: no other repo scripts.
  - **Used by**: the deploy, which copies `scripts/runtime/` whole into `deployment_root/scripts/`.

#### `scripts/runtime/stop.sh`
- **Purpose**: Stops and removes all Docker Compose containers for this project.
- **Usage**:
  ```bash
  ./scripts/runtime/stop.sh
  ```
- **Notes**:
  - `down --remove-orphans`, without `-v`: named volumes survive, so the stack restarts with its data.
  - **Uses**: no other repo scripts.
  - **Used by**: the deploy, which copies `scripts/runtime/` whole into `deployment_root/scripts/`.

#### `scripts/runtime/status.sh`
- **Purpose**: Shows the status of all Docker Compose containers for this project.
- **Usage**:
  ```bash
  ./scripts/runtime/status.sh
  ./scripts/runtime/status.sh --deps      # inspect the resolved module dependency graph
  ```
- **Notes**:
  - `--deps` resolves the graph **inline**, from each deployed `modules/<MODULE>/module.json`. It does not call `scripts/dev/common/module_deps.py`: that path does not exist at a site, and nothing in `scripts/runtime/` may name one that does not.
  - **Uses**: no other repo scripts.
  - **Used by**: the deploy, which copies `scripts/runtime/` whole into `deployment_root/scripts/`.

#### `scripts/runtime/authz.sh`
- **Purpose**: Authorization operations at a deployed site — no redeploy, no rebuild.
- **Usage**:
  ```bash
  ./scripts/runtime/authz.sh --help
  ```
- **Notes**:
  - At production the deployables come from the registry as-is and a devops has only the runtime scripts, so everything that changes authorization has to be reachable from here.
  - **At a site it is `deployment_root/scripts/authz.sh`** — it reaches one because it is in `scripts/runtime/`, and that folder is deployed whole.
  - It locates the backend by its compose label rather than by path, so it runs from any directory.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/backup.sh`
- **Purpose**: Backs up every database in the deployment plus the artefacts needed to rebuild the stack.
- **Usage**:
  ```bash
  ./scripts/runtime/backup.sh [--dir <path>]
  ```
- **Notes**:
  - Databases alone do not rebuild a site; the artefacts are part of the backup for that reason.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site; `check-backup-freshness.sh` watches its output.

#### `scripts/runtime/restore.sh`
- **Purpose**: Restores a backup produced by `backup.sh`.
- **Usage**:
  ```bash
  ./scripts/runtime/restore.sh --from <backup-dir> [--yes] [--only <label>]
  ```
- **Notes**:
  - Restoring a single database on its own is unsupported — see `docs/RUNBOOK.md` for the paired-restore rule.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/verify-backup.sh`
- **Purpose**: Proves a backup can actually be restored, without touching production.
- **Usage**:
  ```bash
  ./scripts/runtime/verify-backup.sh [--from <backup-dir>] [--keep]
  ```
- **Notes**:
  - An untested backup is not a backup: this restores the latest (or a given) backup into a throwaway target, so the claim is measured rather than assumed.
  - **Uses**: reads what `backup.sh` writes.
  - **Used by**: devops at a deployed site; pairs with `check-backup-freshness.sh`, which only proves a backup is *recent*.

#### `scripts/runtime/check-backup-freshness.sh`
- **Purpose**: Alarms when no recent backup exists.
- **Usage**:
  ```bash
  ./scripts/runtime/check-backup-freshness.sh [--max-age-hours N]
  ```
- **Notes**:
  - A backup nobody checks is a backup nobody has; this is the check.
  - **Uses**: reads what `backup.sh` writes.
  - **Used by**: scheduled monitoring at a deployed site.

#### `scripts/runtime/rolling-deploy.sh`
- **Purpose**: Rolls a replicated service onto a new image with no client-visible errors.
- **Usage**:
  ```bash
  ./scripts/runtime/rolling-deploy.sh <service>
  ```
- **Notes**:
  - The acceptance criterion is zero 5xx for the whole deploy, which is why `scripts/dev/common/loadtest.py` reports status codes per second rather than a total.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/pull-hostapp-images.sh`
- **Purpose**: Pulls the host_app images this project consumes, by the digest `framework.lock.json` names.
- **Usage**:
  ```bash
  ./deployment_root/scripts/pull-hostapp-images.sh [--dry-run]   # the deployed copy, in a checkout
  ./scripts/pull-hostapp-images.sh [--dry-run]                   # the same file, at a deployed site
  ```
- **Notes**:
  - **Run the deployed copy, not this source file.** The source under `scripts/runtime/` cannot resolve a release, deliberately: the only resolver in a checkout is `scripts/runtime/framework_version.py`, and a script a site runs must not name a path that exists only in a checkout. The deploy places the resolver beside the script and the lock at the deployment root, so the deployed copy has both.
  - **Takes no tag, and a site does not choose its release.** It reads the deployed lock — the digests, and its own `version` — from the deployment root, which is `<script dir>/..` by construction. To move a project to another release, edit `IDEABLE_FRAMEWORK_VERSION` in `framework.env` in the checkout, sync, and redeploy. The deployed compose is generated from the same lock, so the puller and compose cannot name different images.
  - **The search for the site root stops at the deployment root.** It anchors on `framework.lock.json`, the file the deploy copies, one level up and no further. Anchoring on `framework.env` — which is never deployed — is what once let the search leave the site and report the release of whatever checkout sat above it: passing in a maintainer's tree, the one place the defect is harmless.
  - Pulls `<registry>/<name>@sha256:…` and then tags it `<registry>/<name>:<version>`, so compose resolves it locally instead of reaching for the registry at start-up.
  - Fails naming the digest the registry could not serve; there is no fallback to a moving tag.
  - **Uses**: `framework_version.py` and `framework.lock.json`, both as the deploy placed them.
  - **Used by**: a deployed site before `./start.sh`, and by an operator after changing the framework version, re-syncing and redeploying.

#### `scripts/runtime/audit-retention.sh`
- **Purpose**: Applies the audit compression and retention policies from environment settings.
- **Usage**:
  ```bash
  ./scripts/runtime/audit-retention.sh
  ```
- **Notes**:
  - The policies live here rather than in a migration, so changing how long audit history stays online is a deployment decision and not a schema change.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/seed-module.sh`
- **Purpose**: Seeds a module's authorization contract into Authentik on demand.
- **Usage**:
  ```bash
  ./scripts/runtime/seed-module.sh <module>
  ```
- **Notes**:
  - Bootstrap seeds a module automatically the first time it sees its authorization file; this is the on-demand path for afterwards.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/generate_authentik_blueprint_from_authorization_files.sh`
- **Purpose**: Regenerates the Authentik blueprint from the authorization files and re-applies bootstrap.
- **Usage**:
  ```bash
  ./scripts/runtime/generate_authentik_blueprint_from_authorization_files.sh
  ```
- **Notes**:
  - **Uses**: no other repo scripts.
  - **Used by**: devops after changing an `authorization.yaml`.

#### `scripts/runtime/reissue-certificates.sh`
- **Purpose**: Deletes Traefik's `acme.json` cache so certificates are re-issued on next startup.
- **Usage**:
  ```bash
  ./scripts/runtime/reissue-certificates.sh
  ```
- **Notes**:
  - Use only when new certificates are intentionally needed — Let's Encrypt rate-limits issuance.
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/list-containers.sh`
- **Purpose**: Lists all running containers for this project.
- **Usage**:
  ```bash
  ./scripts/runtime/list-containers.sh
  ```
- **Notes**:
  - **Uses**: no other repo scripts.
  - **Used by**: devops at a deployed site.

#### `scripts/runtime/list-exposed-ports.sh`
- **Purpose**: Lists host-exposed ports from a Docker Compose file, defaulting to `deployment_root/docker-compose.yml`.
- **Usage**:
  ```bash
  ./scripts/runtime/list-exposed-ports.sh [--compose <path>]
  ```
- **Notes**:
  - Useful after `build_and_deploy.py` has generated the merged compose file.
  - **Uses**: no other repo scripts.
  - **Used by**: `rules/general-guidelines.md`, `ImplementSpecs` guidance, and the `ideable-implement-specs` skill.

#### `scripts/runtime/create-merged-configuration.sh`
- **Purpose**: Regenerates the merged `deployment_root/.env.config`, `deployment_root/.env.secrets`, and `deployment_root/docker-compose.yml` from the per-module files already deployed under `deployment_root/modules/`.
- **Usage**:
  ```bash
  ./deployment_root/scripts/create-merged-configuration.sh
  ```
- **Notes**:
  - Runs from `deployment_root/scripts/` and operates on sibling `deployment_root/` files.
  - Discovers all modules under `deployment_root/modules/`, merges their `.env.config` and `.env.secrets` files with project/root values authoritative, then `host_app`, then remote modules; duplicate variables are emitted only once. It then **assembles** the merged `docker-compose.yml` from the per-module compose files — carrying over every comment (including the `SYNC-MANAGED-*` markers, which stay paired with the service they delimit) and ordering services by the `depends_on` graph, providers first, with each module's services kept together. `docker compose config` runs afterwards as a validation gate: a merged file it rejects is never written.
  - Before merging, creates any missing per-module `.env.secrets` from `.env.secrets.example`.
  - Generates a merged `deployment_root/.env.secrets.example` from project and per-module `.env.secrets.example` files.
  - **Auto-registers newly pulled modules**: Scans `module.json` files in module directories and automatically adds missing modules to `module-registry.json` and generates Traefik routes in `dynamic.yml.template`. This eliminates manual configuration after pulling module deployables with `pull-module-deployable-from-git.sh`.
  - This script is automatically executed by `redeploy.sh` after the deploy step and before the stack starts, so manual runs are only needed when per-module configs changed after the last deploy.
  - The merge itself is **not implemented here**: it lives in `scripts/runtime/compose_merge.py`, shared with `build_and_deploy.py` and copied to `deployment_root/scripts/` at deploy time. Because `redeploy.sh` runs this script immediately after the build-time merge, the two must agree exactly — when they were separate copies they drifted, and this one overwrote the correct output with a stale result.
  - **It looks for that module beside itself and nowhere else.** A checkout folder is not a candidate: it does not exist at a deployed site, so searching it could only let a broken deploy pass in the maintainer's tree — the one place the failure is harmless. Missing the module beside it is an error naming the deployed copy to run instead.
  - **Uses**: `scripts/runtime/compose_merge.py`.
  - **Used by**: `redeploy.sh`.

#### `scripts/runtime/update-deployable.sh`
- **Purpose**: Updates any Git-backed deployable repository while preserving local `.env.config` and `.env.secrets` customizations.
- **Usage**:
  ```bash
  ./scripts/runtime/update-deployable.sh [PATH] [--dry-run]
  ./scripts/update-deployable.sh [PATH] [--dry-run]
  ```
- **Notes**:
  - Uses `origin` and `main` by default; override them with `REMOTE` and `BRANCH`.
  - Snapshots every existing `.env.config` and `.env.secrets` file before resetting non-environment files to the remote commit.
  - Merges each remote environment template with the local values, adds new remote variables, reports removed variables, and keeps local values for conflicts in non-interactive mode.
  - Supports complete deployables and module deployable repositories when the target path is a Git repository.
  - `--dry-run` fetches and previews changes without resetting or writing repository files.
  - **Used by**: manual deployable updates.

#### `scripts/runtime/configure.sh`
- **Purpose**: Detects host and cross-module exposed-port conflicts and interactively updates port and project identity configuration.
- **Usage**:
  ```bash
  ./scripts/runtime/configure.sh
  ./scripts/configure.sh
  ```
- **Notes**:
  - Supports source and deployed contexts and discovers enabled modules from `modules/enabled.md`.
  - Validates replacement ports from 1 through 65535 and reports process/container owners when available.
  - Updates the authoritative environment file and synchronizes module fallback/default port values.
  - Provides optional prompts for `EXTERNAL_BASE_HOST`, `APP_NAME`, `APP_SLUG`, and `PROJECT_ROOT`.
  - **Used by**: manual deployment configuration.

#### `scripts/runtime/change_secrets.sh`
- **Purpose**: Interactively edits secret-like variables in project/root `.env.secrets` and enabled modules' `.env.secrets` files.
- **Usage**:
  ```bash
  ./scripts/runtime/change_secrets.sh
  ./deployment_root/scripts/change_secrets.sh
  ```
- **Notes**:
  - Detects source vs deployed context: uses `project.env.secrets` in source repos and `.env.secrets` at the deployment root in deployed bundles.
  - Scans target files for keys ending in `_PASSWORD`, `_TOKEN`, `_SECRET`, or `_SECRET_KEY` and prompts for new values using current values as defaults.
  - If the root `.env.secrets` file is missing but `.env.secrets.example` exists, it creates the root `.env.secrets` from the example before prompting.
  - If an enabled module's `.env.secrets` file is missing but `.env.secrets.example` exists, it creates the module `.env.secrets` from the example before prompting.
  - Run this in a fresh clone or deployable bundle to populate real secret values.
  - **Uses**: no other repo scripts.
  - **Used by**: manual secret rotation after deploy.

## Notes

- Prefer `scripts/dev/common/build_and_deploy.py` for build/deploy workflows.
- Prefer `deployment_root/start.sh`, `deployment_root/stop.sh`, and `deployment_root/status.sh` after deployment — the copies of `scripts/runtime/` the deploy places at the deployment root.
- If you decide to delete any legacy script, first confirm whether any external docs or personal workflows still depend on it.
