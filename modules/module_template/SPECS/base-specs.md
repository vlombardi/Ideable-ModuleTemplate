# IMPORTANT: Read This First

This is the **entry point** for any work on this module — `AGENTS.md` and
`rules/general-guidelines.md` both name `modules/<MODULE>/SPECS/base-specs.md` as the mandatory
starting point, and this is that file.

It is **module-owned**: `module-init.sh` substitutes the slug here when a project is generated, and a
template sync never overwrites it. Adapt it as the module grows. The framework contracts it points at
are the opposite — force-synced and not to be edited locally.

> If you are reading this in a generated project and it still says `module_template` or `template`,
> the rename did not run. Report it rather than working around it.

## Specification Files Chain

Read these **in order**, completely, before writing or changing anything.

### 1. Mandatory for every task

| File | What it governs |
|---|---|
| `rules/general-guidelines.md` | hard project constraints — compose, Dockerfiles, env, deployment layout |
| `SPECS/ideable-framework-specs/base-specs.md` | the framework contract this module implements |
| `SPECS/ideable-framework-specs/module-integration-specs.md` | Module Federation, routing, menu, registry |
| `SPECS/ideable-framework-specs/auth-specs.md` | identity, claims, permissions, tenant scoping |
| `SPECS/ideable-framework-specs/audit-trail-specs.md` | versioning, history endpoints, audit storage |

### 2. The sub-module you are touching

| Sub-module | Read |
|---|---|
| backend | `backend/SPECS/ideable-framework-specs/base-specs.md`, then `backend/SPECS/module-specs.md`, then **both** bug-avoiders (`backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md` and `backend/SPECS/general_bug_avoider.md`) |
| frontend | `frontend/SPECS/ideable-framework-specs/base_specs.md`, `shared-ui-specs.md`, `shared-ui-widgets-specs.md`, then `frontend/SPECS/module-specs.md` and both bug-avoiders |
| database | `database/SPECS/ideable-framework-specs/schema-workflow.md` **first** — it is the authority on the schema — then `database/SPECS/ideable-framework-specs/base-specs.md` and `database/SPECS/module-specs.md` |

### 3. Module-owned, and yours to maintain

- `SPECS/dependencies.md` — pinned versions per sub-module. **Update it whenever a dependency
  changes**; `validate_modules.sh` checks it exists.
- `<sub-module>/SPECS/module-specs.md` — this module's own entities and rules.
- `<sub-module>/SPECS/general_bug_avoider.md` — what broke here before, so it does not break again.

## Warnings that cost real defects

- **The model is the schema, and only Alembic writes it.** `datamodel.sql` is retired; DDL written
  into an init script is executed by nothing on an already-bootstrapped database. See
  `schema-workflow.md`.
- **Permissions are fully qualified.** `require_permission('<slug>.<entity>:view')`, never a bare
  `'<entity>:view'` — the bare form matches nothing at runtime and 403s every request.
- **A frontend never derives permissions from the access token.** The token is thin; read the
  permission set from host_app's `/me` (`services/permissions.ts`).
- **Every model declares `__tenant_scoped__`.** A build-time gate
  (`scripts/common/check_tenancy_markers.py`) fails the build otherwise, because the alternative is a
  table that silently holds every customer's rows.

## Adding an entity

The framework contract for this is
`SPECS/ideable-framework-specs/base-specs.md` § *Adding an entity* — follow it rather than copying
another entity by eye, and record anything module-specific in the relevant `module-specs.md`.

## Build · Deployment · Configuration · Execution · Test

These are framework-wide and defined once, not restated here:

- **Build / Deployment**: `rules/general-guidelines.md` § *Development process*, and
  `SPECS/ideable-framework-specs/infrastructure-file-list.md` for the canonical file inventory.
- **Configuration**: `.env.config` / `.env.secrets` rules in `rules/general-guidelines.md` § *.env rules*.
- **Execution**: `docker-compose.yml` in this module's root; probes and readiness in
  `backend/SPECS/ideable-framework-specs/base-specs.md` § *Diagnostic probes*.
- **Test**: `rules/testing-guidelines.md` — the runner `scripts/common/run_enabled_tests.sh` is the
  only sanctioned entry point.
