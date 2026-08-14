---
trigger: on-demand
---

> Load this file during the **test** step (step 7) of the development process.

## Testing

### How tests must be run (single entry point) — MANDATORY

The **only** sanctioned way to execute the test-and-fix step is the runner
**`scripts/common/run_enabled_tests.sh`** (invoked directly, or via the
**`ideable-test-and-fix`** skill, which calls it). It is the **only** path that writes the
timestamped `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/` artifacts maintainers rely on.

**Agents (mandatory): never run `pytest` or `npx playwright test` directly for the test
step.** Always run the runner / skill. This is a rule, not a suggestion — it overrides any
skill wording.

This is enforced technically so a bypass fails loudly rather than silently producing no
report:
- The runner exports **`IDEABLE_TEST_RUNNER=1`**. The repo-root **`conftest.py`** (pytest)
  and every module's **`playwright.config.ts`** refuse to run without that marker.
- A **direct** `pytest …` / `npx playwright test …` therefore **hard-fails** with a message
  pointing back here — because it would produce no `TEST_REPORTS/` entry.
- **Fast local iteration is still possible**, but only as a conscious, unrecorded
  exception: prefix the command with **`IDEABLE_ALLOW_DIRECT=1`**. The tests then run, a
  loud warning notes that **no `TEST_REPORTS/` entry is created**, and the official/gate
  result must still come from the runner.

`pytest.ini` + `conftest.py` (repo root) and `playwright.config.ts` are framework-owned and
force-synced, so every remote inherits this guard automatically.

### Test Organization

* **Test Locations**: Tests are organized in `TESTS/` directories at both module and sub-module levels:
  - **Module-level tests**: `modules/<MODULE>/TESTS/` - integration tests across sub-modules
  - **Sub-module-level tests**: `modules/<MODULE>/<SUB_MODULE>/TESTS/` - unit and component tests

### Test Types

Each test suite should include appropriate test types based on the sub-module:

* **Unit Tests**: Test individual functions, classes, and components in isolation
  - Must have high coverage of critical business logic
  - Should be fast and independent
  - Mock external dependencies

* **Integration Tests**: Test interactions between components within a sub-module
  - Database interactions
  - API endpoint functionality
  - Service-to-service communication

* **End-to-End Tests**: Test complete user workflows across sub-modules
  - Critical user journeys
  - Multi-sub-module interactions
  - Real-world scenarios

### Test Execution

* **Test Step**: Tests are executed during the **test** step of the development process (step 7)
* **Test Frameworks**: Use standard frameworks appropriate for each technology:
  - **Python**: `pytest`, `unittest`
  - **JavaScript/TypeScript**: `jest`, `vitest`, and **Playwright** for frontend UI / E2E (see below)
* **Runner**: `scripts/common/run_enabled_tests.sh` runs, per enabled module, both `pytest`
  over `modules/<M>/TESTS` and Playwright over `modules/<M>/frontend/TESTS/playwright`
  (when present). It exits non-zero if any suite fails (pytest "no tests collected" is
  not a failure), so CI can gate on it.

### Test Reports

The runner writes human-readable, colour-cued Markdown reports. They serve two audiences
at once: a **quick glance** at status, and **enough detail for the fix phase**. Result
badges are used consistently everywhere — **✅ Passed** (green), **❌ Failed** (red),
**🔵 Skipped** (blue).

* **Locations** (all under `TEST_REPORTS/` at the project root):
  - `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-SUMMARY.md` — **cross-module general summary**:
    overall verdict, a totals table (✅/❌/🔵/Total), and a per-module/per-suite breakdown
    with a link to each detailed report. The runner also prints this as a **colour console
    summary** at the end of the run.
  - `TEST_REPORTS/<timestamp>-<MODULE>/test-report.md` — pytest (backend/integration).
  - `TEST_REPORTS/<timestamp>-<MODULE>/ui-test-report.md` — Playwright (frontend UI / E2E).
* **Each per-module report contains**, in order:
  - **Summary** — overall verdict + a ✅/❌/🔵/Total counts table.
  - **What was tested** — a table with one row per test: its result badge, a
    human-readable description (e.g. "Entity X creation", derived from the test name /
    Playwright title), and its location (`file::test` or `spec.ts:line`). Rows are ordered
    failures → skipped → passed so problems surface first.
  - **CRUD operations** (UI report) — the explicit `[CRUD]` per-operation log
    (create/read/update/delete with data + ids), each with a result badge.
  - **❌ Failures — details for the fix phase** — for each failure, the isolated
    traceback / error block (pytest `FAILURES` section; Playwright error block), so a fix
    can be made without re-running.
  - **Raw output** — the full runner output in a collapsed `<details>` block (last resort).

### Frontend UI / E2E tests (Playwright)

Frontend UI tests live in `modules/<MODULE>/frontend/TESTS/playwright/` (config
`playwright.config.ts`, specs under `tests/`). They run in two modes:

* **Stack-free (default, CI-portable)** — no running stack or auth. The canonical
  example is the **@ideable/ui Widget Gallery** suite (`tests/widget-gallery.spec.ts`):
  `playwright.config.ts` boots the module's dev server (on `TEMPLATE_DEV_PORT`, default
  3101) and loads `/template/gallery`, which renders every shared widget from synthetic
  data and never calls the backend. This is the regression surface for the shared widget
  library. It asserts:
  - **render** — the core widgets are present (table, buttons, chart);
  - **accessibility** — an `@axe-core/playwright` scan (`wcag2a`/`wcag2aa`) with **zero
    critical/serious** violations. `color-contrast` is intentionally excluded: contrast
    depends on a project's brand **token values** (which remotes override — see
    `framework-css-classes-reference.md`), not on widget structure. Fix structural a11y
    issues (accessible names, labels, roles) in the widget; treat contrast as a palette
    concern validated when tuning tokens.
  - **visual** — a `toHaveScreenshot` baseline (see below).

* **Stack-requiring (opt-in)** — set `RUN_STACK_E2E=1` to run specs that need a running
  authenticated stack (`tests/lf-parity.spec.ts` L&F parity, `tests/authenticated-items.spec.ts`).
  Without it they **skip**, so the default phase runs only the stack-free suites. Point them
  at the stack with `HOSTAPP_FRONTEND_URL` / `TEMPLATE_FRONTEND_URL`.

**Authentication — real-user login by persona.** Authentik has **no password/ROPC
grant**, and a `client_credentials` **service account is a machine identity that resolves
no profile** (host_app gates all content on an active profile), so authenticated specs
log in as a **real, profile-bearing user** by driving the actual Authentik login form
(Playwright is a browser — no interactive human needed):
- `auth/personas.ts` — a registry of login personas → Authentik user + password. The
  default `standard` persona is the bootstrap superadmin (`sadmin`, active profile
  `admin`). Add profile-scoped personas (reader, officer, …) here to assert
  authorization behaviour; each must be a real user in
  `modules/host_app/config/authorization.yaml`.
- `auth/login.ts` — drives the Authentik flow (identification `#ak-identifier-input` →
  password `#ak-stage-password-input`, clicking the *visible* stage button) and captures
  the session: `storageState` (cookies) **plus** the oidc-client-ts *User* blob from
  **sessionStorage** (which `storageState` can't carry).
- `auth/global-setup.ts` logs in each configured persona **once** (only when
  `RUN_STACK_E2E=1`) → `auth/.auth/<persona>.json` (git-ignored; holds a live session).
- `auth/session-fixture.ts` rehydrates a persona per test: a context from the captured
  `storageState` + an init script re-seeding the sessionStorage blob. Specs use
  `const test = personaTest('<persona>')` (default `standard`).
- Required env: `HOSTAPP_FRONTEND_URL` / `TEMPLATE_FRONTEND_URL`, `VITE_OIDC_AUTHORITY`,
  `VITE_OIDC_CLIENT_ID`, and the persona credentials (`SADMIN_USERNAME` /
  `AUTHENTIK_BOOTSTRAP_PASSWORD`, or `E2E_STANDARD_USER` / `E2E_STANDARD_PASSWORD`).
- The gallery suite auto-skips under `RUN_STACK_E2E` (it's the stack-free one); the
  authenticated specs auto-skip without it. Verified live: host_app `/users` and the
  module Items page render for the `standard` persona.

**What a remote gets automatically (zero manual work).** After a template sync, a remote
has everything to run UI E2E:
- The **harness** (`playwright.config.ts` + `auth/`) and the generic discovery-driven
  specs **`tests/entity-pages.spec.ts`** and **`tests/crud-endpoints.spec.ts`** are
  **force-synced**. `entity-pages` discovers the module's OWN pages from its
  `moduleManifest.ts` and asserts each loads for a logged-in persona (not the
  login/no-profile gate). `crud-endpoints` introspects the module's backend OpenAPI and
  round-trips create/read/update/delete for every discoverable resource — **logging each
  operation explicitly** (`[CRUD] <resource>: CREATE {…} -> 201 id=N`, `UPDATE id=N field
  "a"->"d"`, `DELETE id=N`), which `run_enabled_tests.sh` surfaces in the report's
  **"CRUD operations"** section so maintainers see exactly what ran. Resources whose
  create can't be satisfied generically (required FKs/constraints) are reported SKIPPED
  with the server reason, not failed. All work for any module (module_template's Items,
  SRA's companies/assets, …) with no edits.
- The runner (`run_enabled_tests.sh`) **auto-installs** Playwright + Chromium in the
  module's `frontend/TESTS/playwright` before running (no manual `npm install`).
- The login harness captures **whatever `oidc.user:*` session the app persists** (scans
  sessionStorage), so it is robust to the frontend's build-time OIDC identity differing
  from the test env.

**CRUD E2E tests — one suite per CRUD entity (required).** Every main entity that has
standard CRUD (backend endpoints + a frontend page) **must ship a CRUD E2E suite**,
authored alongside the entity and executed in the test-and-fix phase. It must verify
real, spec-defined data — not merely that "a table exists":
- **Create** through the **backend API** (this also tests the create endpoint + auth),
  using the persona's Bearer token (the `access_token` in the captured session).
- **Read** — load the page and assert the *specific* created rows/values appear (filter
  by a unique per-run marker so the suite is deterministic and repeatable).
- **Update / Delete / Create** through the **UI**, asserting the table reflects each
  change; plus filter/sort behaviour.
- **Clean up** every row the run created (delete by the unique marker) so re-runs are idempotent.

**Foreign-key ordering (dependency tree).** When entities reference each other, the CRUD
tests MUST respect those dependencies so FK-bearing entities can actually be created (not
skipped):
- Build an **entity dependency tree** from the datamodel with the shared helper
  `frontend/TESTS/playwright/lib/entity-graph.ts` (`parseEntityGraph(datamodelSql)`), which
  parses the `FOREIGN KEY … REFERENCES` clauses in `database/SOURCES/initdb/datamodel.sql`
  and returns the per-entity `parents` and a leaf-first `createOrder`. A **leaf** is an
  entity with no outgoing FK to another in-scope entity.
- **Create bottom-up (leaves → root):** topologically sort so every parent is created
  before its children; when creating a child, **valorize each FK field with a
  previously-created parent's id** (captured from that parent's create response).
- **Delete top-down (root → leaves):** reverse the create order so deletes don't violate
  FK constraints. Read/Update happen per entity as usual.
- On an unbreakable cycle or a required FK to an out-of-scope/external entity, that entity
  is reported SKIPPED with the reason (as the generic `crud-endpoints` probe already does).

Reference implementation to copy per entity: `modules/module_template/frontend/TESTS/playwright/tests/items-crud.spec.ts`
(Items has no FK; for FK-bearing entities apply the dependency-tree ordering above).
These are opt-in (`RUN_STACK_E2E=1` + a running authenticated stack); the runner executes
them in the test phase when invoked against a live stack, and skips them otherwise.

**Entity scoping in a remote module — cover exactly its own entities.** A module's
per-entity CRUD suites must correspond **one-to-one with the entities in that module's own
datamodel** (`database/SOURCES/initdb/datamodel.sql`): one suite per entity, and **no suite
for an entity the module doesn't define**. `items-crud.spec.ts` exists in module_template
only as the reference example for the template's `items` entity; it is **not force-synced**
and is **not** part of any real module's suite. So when a remote module is implemented (or
re-implemented) from specs, the defined, non-negotiable path — which agents follow
**without asking** — is:
- Generate a CRUD suite for **each** entity in the module's datamodel (named after the
  entity, FK-ordered per the dependency tree above).
- **Delete every template example CRUD spec whose entity is absent from this module**,
  chiefly `items-crud.spec.ts` when there is no `items` entity. The template's Items tests
  must be **absent**, not adapted or retained. The generic force-synced `entity-pages` +
  `crud-endpoints` specs remain (they self-discover the module's own pages/resources).

**Visual baselines.** Playwright names screenshot baselines per-OS. The visual test **skips**
when no baseline exists for the current platform, so a fresh checkout is never spuriously
red. Generate the CI baseline once in the **Linux** environment (ideally the official
`mcr.microsoft.com/playwright:v<version>-jammy` image so it matches CI pixels) with
`npm run test:update`, then **commit** the generated `tests/**/*-snapshots/*.png`. Baselines
are the one artifact that IS committed under the otherwise-ignored test dir.

**Prerequisite — standalone rendering.** A remote frontend must render standalone (dev
server) for the stack-free gallery suite to work: keep the Module Federation **async
boundary** (`main.tsx` → `import('./bootstrap')`) and the React **dedupe** alias in
`rsbuild.config.ts` so a single React loads outside host_app.

**Reports.** The runner writes `TEST_REPORTS/<timestamp>-<MODULE>/ui-test-report.md`
(alongside pytest's `test-report.md`).

### Test Best Practices

1. **Isolation**: Tests must be independent and not rely on execution order
2. **Clarity**: Test names should clearly describe what is being tested
3. **Maintainability**: Update tests whenever related code changes
4. **Documentation**: Document complex test scenarios and edge cases
5. **Coverage**: Aim for high coverage of critical paths, but prioritize meaningful tests over coverage percentages
6. **Speed**: Keep unit tests fast; reserve longer-running tests for integration suites
