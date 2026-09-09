# Infrastructure File List

This file is the canonical manifest of files and folders that the module_template export/sync scripts treat as infrastructure and keep aligned across remote modules.

If `scripts/dev/module/sync-template-updates.sh` or `scripts/dev/master/push-updates-to-module_template-repo.sh` changes this set, this manifest MUST be updated in the same change set.

## Repo-root infrastructure files

- `AGENTS.md`
- `CLAUDE.md`
- `IDEABLE-README.md`
- `.gitignore`
- `pytest.ini` — anchors pytest's rootdir at the repo root so the root `conftest.py` guard loads for every invocation.
- `pyproject.toml` — the Python static-analysis gate's configuration (ruff rule selection, per-file ignores, mypy). `scripts/dev/common/run_enabled_tests.sh` runs `ruff check` as a gate, and ruff resolves `[tool.ruff]` from the nearest `pyproject.toml` walking up from its targets — so without this file a remote module runs the gate under ruff's *defaults* instead of the framework's rule set, which is a different gate wearing the same name. Synced with the runner that invokes it.
- `framework.env` — exactly one line, `IDEABLE_FRAMEWORK_VERSION=<latest|X.Y.Z>`: the framework version this project runs, the one value a person edits. There is no shell override and no other key; the file is the only source, so a change to it is visible in `git diff`. Deliberately not `project.env.config`, which is deployer-owned and merged into deployed containers. Read only by `scripts/runtime/framework_version.py`; nothing deployed reads it, and **the deploy does not copy it** — a site inherits the release chosen here rather than holding a choice it could contradict the deployed facts with. **Shipped in a new project's skeleton and never written by sync** — it is the module maintainer's choice, and a sync that reset it would remove the only control they have over their framework version. `scripts/dev/module/module-init.sh` creates it, set to `latest`.
- `framework.lock.json` — the facts the framework version resolved to at publish time: the template repository, the dev tools image and its digest, the host_app registry and one digest per image. It records no template commit — the publish copies the lock into the template commit it pushes, so the release is identified by its tag instead. Written by the framework publish (`scripts/dev/master/write_framework_lock.py`), force-synced, never edited by hand. Read only by `scripts/runtime/framework_version.py`, from which `scripts/dev/common/tool.sh` and `scripts/dev/common/pull_devtools_image.sh` take the toolbox reference and the digest that must back it, and `build_and_deploy.py` takes host_app's registry and release. **Force-synced**, so a project always holds the lock published for the version it asks for — the opposite ownership from `framework.env` above, and deliberately so: one is generated, the other is chosen. **Also copied to `deployment_root/` by the deploy**, together with a copy of `framework_version.py` in `deployment_root/scripts/`: the deployed `pull-hostapp-images.sh` has to name a release at a site, and a deployable bundle is nothing but a copy of `deployment_root/`. It is written there *through* the resolver, so a lock disagreeing with the version `framework.env` asks for fails the deploy rather than travelling to a site as the answer; with no `framework.env` beside it, the deployed lock's own `version` is the whole statement of the release.
- `conftest.py` — repo-root test-runner guard: hard-fails a direct `pytest` (no `TEST_REPORTS/` written) unless `IDEABLE_TEST_RUNNER=1` (set by the runner) or `IDEABLE_UNRECORDED_RUN=1` (explicit throwaway local iteration). See `rules/testing-guidelines.md` § "How tests must be run". It also defines the **`code_only`** fixture that every source-reading contract test uses; that is here and not in a repo-root module because a `TESTS/` directory carrying its own `conftest.py` gets *that* directory on `sys.path`, not the repo root — a root conftest's fixtures reach every `TESTS/` directory, an importable root module does not. Force-synced, and it must stay so: the force-synced `backend/TESTS/test_tenant_isolation.py` depends on that fixture.
- `project.env.config.example`
- `project.env.secrets.example`
- `redeploy.sh`, `start.sh`, `stop.sh`, `status.sh`, `dev-cycle.sh`, `update_backend.sh`,
  `update_frontend.sh` — the commands a developer types, each a **relative symlink** into
  `scripts/dev/common/`, where the real files live because they run at development time and never
  at a deployed site. The repository root therefore holds no script of its own. A site has its own
  `start.sh`, `stop.sh` and `status.sh`, which are different scripts copied out of
  `scripts/runtime/`. The template push copies these with `cp -R` and the sync reproduces them as
  links, so a project receives seven working commands rather than seven copies; the relative target
  resolves because `scripts/dev/common/` ships too.

## Repo-root infrastructure folders

- `.githooks/` — the local git hooks, chiefly `pre-push`, which refuses a push whose code was never tested green (`rules/version-control.md` § *The remote gate*). Synced because that rule is synced: `scripts/dev/common/ensure_hooks.sh` points `core.hooksPath` here on the first routine command, and it exits silently when the folder is absent — so a project without it read a rule describing a control it did not have. `scripts/TESTS/test_documented_controls_reach_remotes.py` fails if the rule and the shipped set disagree.
- `.agents/`
- `.kiro/`
- `.claude/`
- `.devin/`
- `rules/`
- `scripts/` — **everything under it except `dev/master/` and `TESTS/`.** One exclusion, not an
  allowlist, so a new folder travels without anyone remembering to list it; the previous allowlist
  failed in the direction nobody looks, and `scripts/SPECS/` — the specifications for the very
  runtime scripts a project receives — never travelled at all. So a project gets `dev/common/`
  (both roles), `dev/module/` (its own role), `runtime/`, `SPECS/` and the `README.md` that
  catalogues them. `dev/master/` is the framework maintainer's own tooling — publishing, pushing
  this template — and `TESTS/` is the framework's own suite. The folder a file sits in **is** the
  decision: `scripts/` answers when a script runs and then who runs it, and the three rules that
  keep that true are in `rules/general-guidelines.md` § *Project structure* and
  `scripts/README.md`. A layout move lands **whole** —
  `scripts/dev/module/sync-template-updates.sh` removes the old locations in the same run that
  delivers the new ones, because a project holding both layouts has two answers to which script
  runs and nothing about it looks wrong.
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
`scripts/dev/module/sync-template-updates.sh`). They are module-agnostic — either
static contract checks or slug-parameterized (`MODULE_SLUG`) UI specs.

This list and `SHARED_TESTS` must name the same set, and
`scripts/TESTS/test_shared_tests_is_complete.py` fails when they disagree. It is checked because it
drifted: the section named 20 of the 36 entries while asserting it was the inventory, so a reader
counting on it to say what a remote receives was told less than the truth by a document whose
purpose is to say exactly that.

Module contracts:

- `modules/module_template/TESTS/test_module_dependency_resolver.py` (inter-module `dependsOn` resolver contract)
- `modules/module_template/TESTS/test_compose_deps.py` (cross-module `depends_on` generator contract)
- `modules/module_template/TESTS/test_registry_dep_projection.py` (registry projection of css/widget kinds to provider slugs)
- `modules/module_template/TESTS/test_horizontal_scale_contract.py` (compose replicability and rolling deploy)
- `modules/module_template/TESTS/test_bootstrap_contract.py` (database → migrations → seed → backend bootstrap chain)
- `modules/module_template/TESTS/test_tenancy_marker_gate.py` (every model declares `__tenant_scoped__`)

Frontend contracts:

- `modules/module_template/frontend/TESTS/test_permission_source_contract.py` (a frontend never derives permissions from the access token)
- `modules/module_template/frontend/TESTS/test_oidc_token_source_contract.py` (the token sent is the current session's, and a failed `/me` is not rendered as a denial)
- `modules/module_template/frontend/TESTS/test_module_manifest_contract.py`
- `modules/module_template/frontend/TESTS/test_i18n_contract.py`
- `modules/module_template/frontend/TESTS/test_lf_parity_contract.py`
- `modules/module_template/frontend/TESTS/test_shared_widgets_are_not_shadowed.py` (no module defines a component `@ideable/ui` already exports)
- `modules/module_template/frontend/TESTS/test_entity_table_contract.py`
- `modules/module_template/frontend/TESTS/test_e2e_cleanup_pages_within_the_api_cap.py` (an E2E suite pages within the API's cap and fails when its cleanup cannot finish)

Backend contracts:

- `modules/module_template/backend/TESTS/test_auth_permissions_payload.py`
- `modules/module_template/backend/TESTS/test_tenancy_contract_names.py` (the tenancy contract's static half)
- `modules/module_template/backend/TESTS/conftest.py` (the fixtures the force-synced backend suites depend on)
- `modules/module_template/backend/TESTS/test_migrations.py`
- `modules/module_template/backend/TESTS/test_audit_retention.py`
- `modules/module_template/backend/TESTS/test_audit_retention_is_observable.py`
- `modules/module_template/backend/TESTS/test_tenant_isolation.py` (RLS isolation; depends on the repo-root `conftest.py` fixture)

Database contracts:

- `modules/module_template/database/TESTS/test_datamodel_source_sync.py`
- `modules/module_template/database/TESTS/test_authorization_source_sync.py`
- `modules/module_template/database/TESTS/test_bootstrap_compose_contract.py`

Playwright UI/E2E harness — the module-agnostic harness (config + `auth/`) and the generic,
discovery-driven specs:

- `modules/module_template/frontend/TESTS/playwright/package.json`
- `modules/module_template/frontend/TESTS/playwright/playwright.config.ts`
- `modules/module_template/frontend/TESTS/playwright/.gitignore`
- `modules/module_template/frontend/TESTS/playwright/README.md`
- `modules/module_template/frontend/TESTS/playwright/auth/personas.ts`
- `modules/module_template/frontend/TESTS/playwright/auth/login.ts`
- `modules/module_template/frontend/TESTS/playwright/auth/global-setup.ts`
- `modules/module_template/frontend/TESTS/playwright/auth/session-fixture.ts`
- `modules/module_template/frontend/TESTS/playwright/lib/entity-graph.ts` (FK dependency-tree helper)
- `modules/module_template/frontend/TESTS/playwright/tests/entity-pages.spec.ts` (every page loads authenticated)
- `modules/module_template/frontend/TESTS/playwright/tests/crud-endpoints.spec.ts` (OpenAPI-driven create/read/update/delete per resource, logging each op into the report)
- `modules/module_template/frontend/TESTS/playwright/tests/entity-graph.spec.ts` (FK dependency-tree helper contract)
- `modules/module_template/frontend/TESTS/playwright/tests/module-css-loaded.spec.ts` (the module's stylesheet reaches the shell)

The four generic specs above work for any module with zero edits. The entity/page-specific specs
under `tests/` (`widget-gallery`, `lf-parity`, `items-crud`) are **reference examples**, NOT
force-synced — a remote copies them at init and adapts / replaces them for its own entities (see
testing-guidelines.md § *CRUD E2E tests per entity*).

Excluded from sync: `node_modules/`, `test-results/`, `playwright-report/`, `auth/.auth/`
(git-ignored / secret-bearing), and `tests/**/*-snapshots/` (each module owns its own per-brand
visual baselines).

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
