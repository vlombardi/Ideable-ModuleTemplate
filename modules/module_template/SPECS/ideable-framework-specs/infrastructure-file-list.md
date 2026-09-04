# Infrastructure File List

This file is the canonical manifest of files and folders that the module_template export/sync scripts treat as infrastructure and keep aligned across remote modules.

If `scripts/module_only/sync-template-updates.sh` or `scripts/master_only/push-updates-to-module_template-repo.sh` changes this set, this manifest MUST be updated in the same change set.

## Repo-root infrastructure files

- `AGENTS.md`
- `CLAUDE.md`
- `IDEABLE-README.md`
- `.gitignore`
- `pytest.ini` — anchors pytest's rootdir at the repo root so the root `conftest.py` guard loads for every invocation.
- `pyproject.toml` — the Python static-analysis gate's configuration (ruff rule selection, per-file ignores, mypy). `scripts/common/run_enabled_tests.sh` runs `ruff check` as a gate, and ruff resolves `[tool.ruff]` from the nearest `pyproject.toml` walking up from its targets — so without this file a remote module runs the gate under ruff's *defaults* instead of the framework's rule set, which is a different gate wearing the same name. Synced with the runner that invokes it.
- `framework.env` — the framework version this project tracks (`IDEABLE_FRAMEWORK_VERSION`) and the dev tools image version that goes with it (`IDEABLE_DEVTOOLS_VERSION`, empty = follow the framework). Force-synced, so a value edited in a remote is replaced on the next sync; the shell environment overrides it for a one-off. Deliberately not `project.env.config`, which is deployer-owned, merged into deployed containers, and never overwritten by sync. Read by `scripts/dev/devtools_version.sh`; nothing deployed reads it.
- `conftest.py` — repo-root test-runner guard: hard-fails a direct `pytest` (no `TEST_REPORTS/` written) unless `IDEABLE_TEST_RUNNER=1` (set by the runner) or `IDEABLE_UNRECORDED_RUN=1` (explicit throwaway local iteration). See `rules/testing-guidelines.md` § "How tests must be run". It also defines the **`code_only`** fixture that every source-reading contract test uses; that is here and not in a repo-root module because a `TESTS/` directory carrying its own `conftest.py` gets *that* directory on `sys.path`, not the repo root — a root conftest's fixtures reach every `TESTS/` directory, an importable root module does not. Force-synced, and it must stay so: the force-synced `backend/TESTS/test_tenant_isolation.py` depends on that fixture.
- `project.env.config.example`
- `project.env.secrets.example`
- `redeploy.sh`
- `start.sh`
- `stop.sh`
- `status.sh`
- `update_backend.sh`
- `update_frontend.sh`

## Repo-root infrastructure folders

- `.githooks/` — the local git hooks, chiefly `pre-push`, which refuses a push whose code was never tested green (`rules/version-control.md` § *The remote gate*). Synced because that rule is synced: `scripts/common/ensure_hooks.sh` points `core.hooksPath` here on the first routine command, and it exits silently when the folder is absent — so a project without it read a rule describing a control it did not have. `scripts/TESTS/test_documented_controls_reach_remotes.py` fails if the rule and the shipped set disagree.
- `.agents/`
- `.kiro/`
- `.claude/`
- `.devin/`
- `rules/`
- `scripts/`
- `reusable.ui/` — shared `@ideable/ui` widget library (widgets, primitives, styles/tokens, hooks, i18n) consumed by host_app, module_template, and every remote module. Synced so remotes receive the full widget set. `node_modules/`, `dist/` are excluded (git-ignored; installed per build).

## Module-scoped infrastructure files

- `modules/*/.env.config`
- `modules/*/.env.config.example`
- `modules/*/.env.secrets`
- `modules/*/.env.secrets.example`
- `modules/host_app/.env.config`
- `modules/host_app/.env.config.example`
- `modules/host_app/.env.secrets`
- `modules/host_app/.env.secrets.example`
- `modules/host_app/module.json`
- `modules/host_app/docker-compose.yml`
- `modules/host_app/config/`

## Frontend build reproducibility (the reproducible-build work)

Not synced as infrastructure — each is module-owned — but listed here because they are the files a
remote module must **have**, and the ones whose absence silently un-pins a build:

- `modules/*/frontend/SOURCES/package-lock.json` — committed, and installed from with
  `npm ci --install-links --legacy-peer-deps`. Without it the frontend Dockerfile's `npm ci` fails
  outright, which is the intended failure: a missing lock means an unreproducible image.
- `reusable.ui/package-lock.json` — governs `npm run build:css`, whose output `compiled.css` is a
  tracked artifact.
- `modules/*/frontend/SOURCES/.ideable-ui` — a **tracked symlink** (git mode `120000`) to the
  repo-root `reusable.ui`, so a fresh clone resolves `@ideable/ui`'s `file:./.ideable-ui` dependency
  with no bootstrap command. It is excluded from the Docker build context by `.dockerignore` (it
  dangles in a SOURCES-rooted context) and the Dockerfile creates the real directory from the
  `ideable_ui` named build context.

An `npm install` lifecycle hook cannot substitute for the symlink: npm resolves `file:` dependencies
**before** running `preinstall`, so the hook never fires — verified, it fails with `ENOENT` on
`.ideable-ui/package.json`.

See `modules/host_app/SPECS/dependencies.md` § *npm dependencies are pinned by lockfile* for the
bump procedure.

## Shared framework-spec files

- `modules/module_template/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/auth-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md`
- `modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md`
- `modules/module_template/database/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/base_specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/framework-css-classes-reference.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/look-and-feel-branding.md`

## Shared framework tests

Framework contract/UI tests force-synced to every remote (via `SHARED_TESTS` in
`scripts/module_only/sync-template-updates.sh`). They are module-agnostic — either
static contract checks or slug-parameterized (`MODULE_SLUG`) UI specs.

- `modules/module_template/TESTS/test_module_dependency_resolver.py` (inter-module `dependsOn` resolver contract)
- `modules/module_template/TESTS/test_compose_deps.py` (cross-module `depends_on` generator contract)
- `modules/module_template/frontend/TESTS/test_module_manifest_contract.py`
- `modules/module_template/frontend/TESTS/test_i18n_contract.py`
- `modules/module_template/frontend/TESTS/test_lf_parity_contract.py`
- `modules/module_template/frontend/TESTS/test_entity_table_contract.py`
- `modules/module_template/backend/TESTS/test_auth_permissions_payload.py`
- `modules/module_template/database/TESTS/test_datamodel_source_sync.py`
- `modules/module_template/database/TESTS/test_authorization_source_sync.py`
- `modules/module_template/database/TESTS/test_bootstrap_compose_contract.py`
- Playwright UI/E2E harness — the `@ideable/ui` Widget Gallery suite (render + axe a11y
  + visual baseline) and the seeded-session specs:
  - `modules/module_template/frontend/TESTS/playwright/package.json`
  - `modules/module_template/frontend/TESTS/playwright/playwright.config.ts`
  - `modules/module_template/frontend/TESTS/playwright/.gitignore`
  - `modules/module_template/frontend/TESTS/playwright/README.md`
  - `modules/module_template/frontend/TESTS/playwright/auth/{personas,login,global-setup,session-fixture}.ts`
  - `modules/module_template/frontend/TESTS/playwright/lib/entity-graph.ts` (FK dependency-tree helper)
  - `modules/module_template/frontend/TESTS/playwright/tests/entity-pages.spec.ts`
  - `modules/module_template/frontend/TESTS/playwright/tests/crud-endpoints.spec.ts`
  - Force-synced = the module-agnostic **harness** (config + auth/) **and** the generic
    discovery-driven specs `entity-pages.spec.ts` (every page loads authenticated) +
    `crud-endpoints.spec.ts` (OpenAPI-driven create/read/update/delete per resource,
    logging each op into the report) — both work for any module with zero edits. The
    entity/page-specific specs under `tests/` (`widget-gallery`, `lf-parity`,
    `items-crud`) are **reference examples**, NOT force-synced — a remote copies them at
    init and adapts / replaces them for its own entities (see testing-guidelines.md
    § *CRUD E2E tests per entity*).
  - Excluded from sync: `node_modules/`, `test-results/`, `playwright-report/`, `auth/.auth/`
    (git-ignored / secret-bearing), and `tests/**/*-snapshots/` (each module owns its
    own per-brand visual baselines).

## Design References (not part of current implementation spec chain)

The following files live in `SPECS/` but are **not** distributed as implemented framework specs.
They record design explorations or future work that has not yet been promoted into the active chain.

- `modules/module_template/SPECS/ideable-framework-specs/access-log-audit-trail.md` — design reference
  for a potential standalone Audit Service (OIDC back-channel logout, webhook ingestion). Pending
  evaluation as part of the Access Log Audit Trail refactoring.

## Notes

- Repo-root `README.md` is intentionally not included here; it is treated as custom per-module content.
- Module-level `modules/<module_name>/README.md` is intentionally not included here; it is also treated as custom per-module content.
- Branding files are not listed here because they are only synced when explicitly requested with `--all`.
