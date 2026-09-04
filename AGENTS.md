# Ideable — Agent Instructions

> **Cursor users**: `.cursor/rules/` contains path-scoped `.mdc` files that inject the right context automatically when you open files under `modules/host_app/`, `modules/module_template/`, or test directories. This file provides the fallback and the universal rules.

## Core rules (read every task)

`rules/general-guidelines.md` is **mandatory** for every task. Read it completely before taking any action.

Key invariants from that file (do not skip reading the source):
- No `build:` sections in compose files; images are pre-built and referenced by `image:`.
- `Dockerfile` files live only in `<SUB_MODULE>/SOURCES/`. Never in `DIST/`, `deployment_root/`, or module root.
- Volume mounts must only reference paths inside `deployment_root/`, never `SOURCES/` or `DIST/`.
- Deployed compose files use `env_file: - ../../.env.config` and `- ../../.env.secrets`; source compose files use `env_file: - .env.config` and `- .env.secrets`.
- Test reports go to `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md`.
- `SPECS/dependencies.md` is the single source of truth for versions — update it when any dependency changes.
- Decision authority belongs to the human developer. Stop and ask on any ambiguity.
- Project rules in `rules/` override all skill suggestions. Skills are advisory; rules are mandatory.

## Framework-owned files — never modify in remote module projects

In projects derived from `Ideable-ModuleTemplate`, the following files are **framework-owned** and must **never** be directly modified by AI coding agents:

- `redeploy.sh`, `start.sh`, `stop.sh`, `status.sh`, `update_backend.sh`, `update_frontend.sh`
- Any file under `scripts/` (including `scripts/common/build_and_deploy.py`)
- `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `rules/`, `.agents/`, `.kiro/`, `.claude/`, `.devin/`
- `IDEABLE-README.md`, `.gitignore`, `project.env.*.example`
- `modules/host_app/` in its entirety
- `reusable.ui/` in its entirety (the shared `@ideable/ui` widget library, styles, and canonical design tokens)
- `modules/module_template/SPECS/ideable-framework-specs/`

**When a change to any of these files is needed**: do not edit the file. Inform the user with:
- **Reason**: why the change is needed
- **Change**: concise description of the modification

Then direct the user to ask the Ideable maintainer to apply the change in the main Ideable repository and follow the push/sync flow to propagate it.

See `rules/general-guidelines.md` § "host_app / Remote Boundary" for the full rule.

## Reference files — load only when relevant

**Whole-system / framework overview:**
- `IDEABLE-README.md` (repo root) — the **primary, authoritative reference** for the Ideable framework: architecture, module-creation workflow, integration/menu/auth contracts, the shared `reusable.ui`/`@ideable/ui` widget library, deployment, and sync. Canonical for maintainers and module maintainers alike; framework-owned. Read it for the whole-system picture (it documents its own *when to update* + how it propagates to remotes). `rules/general-guidelines.md` stays the mandatory hard-constraints source; the SPECS below stay the source of truth for implementation details.

**Creating or modifying a rule, a spec, a skill, or a documented "way of working":**
- `rules/authoring-guidelines.md` — which layer to use (rule vs spec vs skill), where each physically lives (framework-owned vs module-owned), and the invariant *specs hold the truth; rules bind; skills index*. Read it before adding framework or module guidance.

**Building any frontend UI element from specs (table, form, popup, dialog, chart, button, toggle, menu icon):**
- Invoke the **`ideable-ui`** skill first. `reusable.ui`/`@ideable/ui` (the top-level `reusable.ui/` folder) is the **single source of truth** for UI, Look & Feel (all CSS/design tokens), and widget definitions — consumed by host_app, module_template, and every remote module. The skill points at it and at the live `WidgetGallery` example in `module_template`. Reuse those widgets — never hand-roll a table/popup/dialog/chart/primitive, and never redefine the shared palette locally.
- **Human/developer guide:** `reusable.ui/README.md` — benefits, how a remote module developer **receives** platform UI‑widget updates (template sync), **adopts/uses** the widgets (import, prefix/token rules, examples), and **rebrands** (build-time `data-lf="module"` token overrides, or runtime `config/theme-override.css` in the deployed folder — no host_app access, no rebuild). Read it when onboarding to the shared widget library.
- **Canonical L&F / token source:** `reusable.ui/styles/base-tokens.css` (the one authoritative `:root`/`.dark` palette) and `reusable.ui/styles/tokens.css` (the `.ideable-scope` cascade + `data-lf` parity/branding). The `framework-css-classes-reference.md` spec catalogs the class tokens.
- **Changing the Look & Feel (colors, logo, fonts) — build time vs deploy time, by role:** `modules/module_template/frontend/SPECS/ideable-framework-specs/look-and-feel-branding.md`. Deployers rebrand live (no rebuild) by editing `deployment_root/modules/<module>/config/theme-override.css` (+ swapping `favicon.png`/`login_bg.png`/`home.html`); developers change the baked-in defaults in `reusable.ui/styles/base-tokens.css` or module `data-lf="module"` tokens.

**Working on any module or sub-module (coding / spec implementation):**
- Read `modules/<MODULE>/SPECS/base-specs.md` first; follow every file it references.
- Read `modules/<MODULE>/<SUB_MODULE>/SPECS/base-specs.md` for the specific sub-module.
- Read `modules/<MODULE>/<SUB_MODULE>/SPECS/general_bug_avoider.md` before writing or changing code.
- Read `modules/<MODULE>/<SUB_MODULE>/SPECS/datamodel_related_bug_avoider.md` if it exists.

**Working on host_app:**
- `modules/host_app/SPECS/base-specs.md` — module overview and spec chain entry point.
- `modules/host_app/SPECS/auth-specs.md` — authentication and SSO contracts (load for auth-related tasks).
- `modules/host_app/backend/SPECS/base_specs.md` — backend sub-module spec.
- `modules/host_app/backend/SPECS/general_bug_avoider.md` — known backend pitfalls.
- `modules/host_app/frontend/SPECS/base_specs.md` — frontend sub-module spec.
- `modules/host_app/frontend/SPECS/general_bug_avoider.md` — known frontend pitfalls.
- `modules/host_app/frontend/SPECS/ui-specs.md` and `ui-widgets-specs.md` — UI contracts (load for UI tasks).
- `modules/host_app/database/SPECS/base-specs.md` — database sub-module spec.
- `modules/host_app/authentik/SPECS/base-specs.md` — identity provider config spec.
- `modules/host_app/traefik/SPECS/base-specs.md` — reverse proxy config spec.

**Working on any module — shared framework bug rules (read before module-specific bug-avoiders):**
- `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md` — Continuum version_class, synthetic creation entry, NULL-integer FK normalization, actor-before-commit.
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md` — AuditTrailPopup diffs, view/edit action icons, au_* columns, computeDiffs synthetic rows.

**Working on module_template (or any remote module derived from it):**
- `modules/module_template/SPECS/ideable-framework-specs/base-specs.md` — framework contract entry point.
- `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md` — MF integration rules.
- `modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md` — audit trail contract.
- `modules/module_template/SPECS/ideable-framework-specs/auth-specs.md` — auth contract for remote modules.
- `modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md` — backend framework spec.
- `modules/module_template/frontend/SPECS/ideable-framework-specs/base_specs.md` — frontend framework spec.
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md` — shared UI contracts.
- `modules/module_template/frontend/SPECS/ideable-framework-specs/framework-css-classes-reference.md` — host_app CSS token reference for remote module L&F alignment (load for CSS/styling tasks).
- `modules/module_template/database/SPECS/ideable-framework-specs/base-specs.md` — database framework spec.
- `modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md` — **read before changing any table**: the model is the schema and only Alembic writes it; the design → model → migration → verify phases (`scripts/dev/schema.sh`); baselines, squashing, and expand → migrate → contract.

**Implementation plan (status tracking across the workflow skills):**
- `rules/implementation-plan.md` — canonical format, status-symbol legend, naming and location (`implementation-plans/`), active-plan resolution, the kanban card's move from `todo/` to `doing/` when a plan is created, and the **Purpose** + **Overall view** chapters (Created at / Last updated / Current step + the canonical dev-cycle Mermaid graph with the current node highlighted yellow). The plan artifact is created and kept current by `ideable-implement-specs`, `ideable-test-and-fix`, `ideable-build-and-deploy`, `ideable-align-docs`, `ideable-bugfixing-and-changes`, and `ideable-commit-changes`. Load when creating or updating an implementation plan.

**Dev-cycle orchestration (nodes = dev states, arcs = skills):**
- `scripts/dev-cycle.sh` — thin deterministic router over the skill graph: `status` (where are we + next transition), `set <NODE>` (recolour the plan's graph + set Current step / Last updated), `run` (execute the current node **and advance the highlight**). Deterministic nodes (BuildDeploy → `redeploy.sh`, Testing → `run_enabled_tests.sh`) run here and Testing branches on the exit code (pass → `Documenting`, fail → `Fixing`); LLM nodes (Implementing/Fixing/Documenting/Committing) are **performed automatically via a headless agent CLI** (`claude`, or `$DEV_CYCLE_AGENT_BIN`) by default, falling back to suggesting the skill when the CLI is unavailable. **If you are an agent, this does not apply to you: the router detects an agent-driven run (`$CLAUDECODE`) and refuses to spawn a second agent onto the same plan — you are told to perform the skill yourself and run it again.** Do not work around that with `--allow-nested-agent`: two agents on one plan edit the tree concurrently, and each then sees the other's diffs with no idea where they came from. If unexplained changes ever do appear in `git status` after you ran this router, they are the consequence of *your* command — never report them as an outside event. After a `Testing` run it folds the latest `TEST_REPORTS/*-SUMMARY.md` into the plan (each thing's `BE test`/`FE test` cell — BE ⇐ pytest, FE ⇐ playwright — plus the Repos `Tests` counts). A plan row that **names the test file(s) measuring it** (`test_migrations.py`) is folded from exactly those files' results, read out of that run's per-module report; a row naming none gets the module roll-up in its test cell and **keeps its `Impl`**, because "something in this module failed" is not a statement about that thing — see `rules/implementation-plan.md` § *Name what measures a row*. Flags: `--auto-advance [N]` chains steps (bare = until Done, `N` = N steps); `--deterministic` advances only deterministic nodes and just suggests the skill for LLM nodes (decision-authority opt-out); `--keep-history` keeps every transition's plan file instead of rolling a single one. **Branch-per-plan** (always on; `DEV_CYCLE_NO_GIT=1` opts out): `run` works on the plan's `plan/<description>` branch (created if missing), commits the working tree there after each execution. Nothing is merged by `run` and nothing is asked at `Committing`: landing the work is the separate `deliver` action, which runs only on a plan at `Done` and lands it as ONE commit whose message is the plan's abstract. `deliver --pr` opens a **pull request** instead, when the maintainer wants the work reviewed — target untouched, branch kept, and the merge run with the command it prints so GitHub's squash-merge does not replace the message's trailers; plain `deliver` squashes onto the target itself and deletes the plan branch. A moved target is refused, not merged (`rules/version-control.md` § *Delivering a plan*). Plan files are named `<date> - <time> - <description> (<state>).md` — the router renames the plan at every transition, re-stamping the date/time with that execution's timestamp and updating the state (the creation time stays in the file's `Created at`).
- `ideable-align-docs` skill — drives the **`Documenting`** node, between a green `Testing` and `Committing`: the specs and docs governing the sub-set's diff are brought into line with what is now true (present tense only, nothing removed still named as live), it records a `Docs` cell per thing, and it ends on a green docs gate. It **reconciles, it does not legislate** — a change that would require deciding something the plan never decided goes to `Blocked`, and framework-owned files in a remote module project are reported, never edited. See `rules/implementation-plan.md` § *Documenting*.
- `ideable-spec-driven-edit` skill — the **atomic** safe-edit discipline every code/config change routes through (look-first in bug-avoiders/specs, edit only on the codebase, no fallbacks/hardcoding, propose-don't-edit specs + stop-and-ask, record back). Referenced by `ideable-implement-specs`, `ideable-test-and-fix`, and `ideable-bugfixing-and-changes`.
- `scripts/common/spec_workset.py` — incremental work-set for `ideable-implement-specs` (reference graph rebuilt each run, git as change oracle, `changed ∪ transitive-dependents`, `--force` full run). A cache hint only — `Done ⇐ contract tests pass`.

**Test step tasks (step 7):**
- `rules/testing-guidelines.md` — test organization, types, frameworks, report location.

**Documentation step tasks (step 8):**
- `rules/general-guidelines.md` § *Development process* step 8 — the mandatory rule.
- `rules/implementation-plan.md` § *Documenting* — the node, the `Docs` column, the docs gate.
- Invoke the **`ideable-align-docs`** skill; it owns the procedure.

**Git / commit / branch / PR tasks:**
- `rules/version-control.md` — branching strategy, commit format, PR process, breaking changes.
  Two routes land on `main`, and **the maintainer decides which** — having a plan does not decide it. The default for both is landing directly as ONE squashed commit; `deliver --pr` opens a pull request when review is wanted. A change simple enough to need no implementation plan takes the **fast lane** (`ideable-bugfixing-and-changes`) — still running the tests and aligning the docs when they are needed.

**Build or deployment tasks:**
- `modules/<MODULE>/SPECS/dependencies.md` — pinned versions for all sub-modules.
- `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md` — canonical file inventory.

**Enabled modules:** `modules/enabled.md` — authoritative list of which modules are active.
