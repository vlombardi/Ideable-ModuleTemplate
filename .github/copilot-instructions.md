# Ideable — Agent Instructions

> **Cursor users**: `.cursor/rules/` contains path-scoped `.mdc` files that inject the right context automatically when you open files under `modules/HostApp/`, `modules/ModuleTemplate/`, or test directories. This file provides the fallback and the universal rules.

## Core rules (read every task)

`rules/general-guidelines.md` is **mandatory** for every task. Read it completely before taking any action.

Key invariants from that file (do not skip reading the source):
- No `build:` sections in compose files; images are pre-built and referenced by `image:`.
- `Dockerfile` files live only in `<SUB_MODULE>/SOURCES/`. Never in `DIST/`, `deployment_root/`, or module root.
- Volume mounts must only reference paths inside `deployment_root/`, never `SOURCES/` or `DIST/`.
- Deployed compose files use `env_file: - ../../.env`; source compose files use `env_file: - .env`.
- Test reports go to `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md`.
- `SPECS/dependencies.md` is the single source of truth for versions — update it when any dependency changes.
- Decision authority belongs to the human developer. Stop and ask on any ambiguity.
- Project rules in `rules/` override all skill suggestions. Skills are advisory; rules are mandatory.

## Reference files — load only when relevant

**Working on any module or sub-module (coding / spec implementation):**
- Read `modules/<MODULE>/SPECS/base-specs.md` first; follow every file it references.
- Read `modules/<MODULE>/<SUB_MODULE>/SPECS/base-specs.md` for the specific sub-module.
- Read `modules/<MODULE>/<SUB_MODULE>/SPECS/general_bug_avoider.md` before writing or changing code.
- Read `modules/<MODULE>/<SUB_MODULE>/SPECS/datamodel_related_bug_avoider.md` if it exists.

**Working on HostApp:**
- `modules/HostApp/SPECS/base-specs.md` — module overview and spec chain entry point.
- `modules/HostApp/SPECS/auth-specs.md` — authentication and SSO contracts (load for auth-related tasks).
- `modules/HostApp/backend/SPECS/base_specs.md` — backend sub-module spec.
- `modules/HostApp/backend/SPECS/general_bug_avoider.md` — known backend pitfalls.
- `modules/HostApp/frontend/SPECS/base_specs.md` — frontend sub-module spec.
- `modules/HostApp/frontend/SPECS/general_bug_avoider.md` — known frontend pitfalls.
- `modules/HostApp/frontend/SPECS/ui-specs.md` and `ui-widgets-specs.md` — UI contracts (load for UI tasks).
- `modules/HostApp/database/SPECS/base-specs.md` — database sub-module spec.
- `modules/HostApp/authentik/SPECS/base-specs.md` — identity provider config spec.
- `modules/HostApp/traefik/SPECS/base-specs.md` — reverse proxy config spec.

**Working on any module — shared framework bug rules (read before module-specific bug-avoiders):**
- `modules/ModuleTemplate/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md` — Continuum version_class, synthetic creation entry, NULL-integer FK normalization, actor-before-commit.
- `modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md` — AuditTrailPopup diffs, view/edit action icons, au_* columns, computeDiffs synthetic rows.

**Working on ModuleTemplate (or any remote module derived from it):**
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/base-specs.md` — framework contract entry point.
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/module-integration-specs.md` — MF integration rules.
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/audit-trail-specs.md` — audit trail contract.
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/auth-specs.md` — auth contract for remote modules.
- `modules/ModuleTemplate/backend/SPECS/ideable-framework-specs/base-specs.md` — backend framework spec.
- `modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/base_specs.md` — frontend framework spec.
- `modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md` — shared UI contracts.
- `modules/ModuleTemplate/database/SPECS/ideable-framework-specs/base-specs.md` — database framework spec.

**Test step tasks (step 7):**
- `rules/testing-guidelines.md` — test organization, types, frameworks, report location.

**Git / commit / branch / PR tasks:**
- `rules/version-control.md` — branching strategy, commit format, PR process, breaking changes.

**Build or deployment tasks:**
- `modules/<MODULE>/SPECS/dependencies.md` — pinned versions for all sub-modules.
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/infrastructure-file-list.md` — canonical file inventory.

**Enabled modules:** `modules/enabled.md` — authoritative list of which modules are active.
