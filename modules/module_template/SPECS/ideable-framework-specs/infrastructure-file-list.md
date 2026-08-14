# Infrastructure File List

This file is the canonical manifest of files and folders that the module_template export/sync scripts treat as infrastructure and keep aligned across remote modules.

If `scripts/module_only/sync-template-updates.sh` or `scripts/master_only/push-updates-to-module_template-repo.sh` changes this set, this manifest MUST be updated in the same change set.

## Repo-root infrastructure files

- `AGENTS.md`
- `CLAUDE.md`
- `IDEABLE-README.md`
- `.gitignore`
- `pytest.ini` — anchors pytest's rootdir at the repo root so the root `conftest.py` guard loads for every invocation.
- `conftest.py` — repo-root test-runner guard: hard-fails a direct `pytest` (no `TEST_REPORTS/` written) unless `IDEABLE_TEST_RUNNER=1` (set by the runner) or `IDEABLE_ALLOW_DIRECT=1` (explicit throwaway local iteration). See `rules/testing-guidelines.md` § "How tests must be run".
- `project.env.config.example`
- `project.env.secrets.example`
- `redeploy.sh`
- `start.sh`
- `stop.sh`
- `status.sh`
- `update_backend.sh`
- `update_frontend.sh`

## Repo-root infrastructure folders

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

## Shared framework-spec files

- `modules/module_template/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/auth-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md`
- `modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md`
- `modules/module_template/database/SPECS/ideable-framework-specs/base-specs.md`
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
- `modules/module_template/frontend/TESTS/test_template_items_table_contract.py`
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
