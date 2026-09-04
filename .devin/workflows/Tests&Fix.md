---
description: Run tests for all enabled modules (modules/enabled.md) — run full suite or a specific module/suite
---

# Workflow: Run Tests

Executes test suites for **all enabled modules** listed in `modules/enabled.md`.

Each module may have:
- a module-level test suite in `modules/<MODULE>/TESTS/`
- optional sub-module suites in `modules/<MODULE>/<SUBMODULE>/TESTS/`

## Prerequisites

1. Containers must be running. If not, start them first:
```bash
cd deployment_root && ./start.sh
```

2. Install test dependencies (first time only):
```bash
pip install -r modules/host_app/TESTS/requirements.txt
```

3. Install Playwright browser (first time only, only needed for frontend suite):
```bash
playwright install chromium
```

## Step 1 — Determine scope

Ask the user (or infer from context) what to run:
- **all enabled modules** (default) — run `pytest` for every enabled module that has a `TESTS/` folder
- **one module** — e.g. `host_app`
- **one suite inside a module** — module-specific, depends on folder layout (example below for `host_app`)

## Step 2 — Set environment

The tests read connection parameters from `modules/<MODULE>/.env` automatically via `python-dotenv`.
If the file is not present or values differ, export overrides before running:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5433
export POSTGRES_USER=vinz
export POSTGRES_PASSWORD=vinz
export POSTGRES_DB=vinz
export BACKEND_URL=http://localhost:8001
export AUTHENTIK_URL=http://localhost:9000
export AUTHENTIK_BOOTSTRAP_TOKEN=authentik-bootstrap-token
export TRAEFIK_DASHBOARD_URL=http://localhost:8088
export FRONTEND_URL=http://localhost:3000
export EXTERNAL_BASE_HOST=localhost
# Optional explicit full URL used by endpoint-reference smoke tests
# export EXTERNAL_BASE_URL=https://mydomain.com
```

## Step 3 — Run tests

> **Single sanctioned entry point (mandatory).** `run_enabled_tests.sh` is the **only**
> path that writes `TEST_REPORTS/`. It is enforced: the repo-root `conftest.py` and each
> module's `playwright.config.ts` **hard-fail a direct `pytest` / `npx playwright test`**
> (they'd produce no report) unless the runner's `IDEABLE_TEST_RUNNER=1` marker is set.
> **Always run the runner (this Step 3) for the official / gate result — never invoke
> `pytest` or `npx playwright test` directly.** The per-module / per-suite commands below
> are for **local iteration only**; because of the guard they now require an explicit
> opt-in prefix `IDEABLE_UNRECORDED_RUN=1` (which runs the tests but writes **no**
> `TEST_REPORTS/` entry — e.g. `IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/`).
> See `rules/testing-guidelines.md` § *How tests must be run*.

### All enabled modules (deterministic)

Use the centralized test runner script for consistent, reproducible test execution across all enabled modules:

// turbo
```bash
./scripts/common/run_enabled_tests.sh
```

**Purpose of this script:** The `run_enabled_tests.sh` script exists to make the Tests&Fix process **deterministic** — it ensures:
- Same module discovery logic (reads `modules/enabled.md` consistently)
- Same test execution order and pytest flags
- Same report generation format (timestamped markdown reports in `TEST_REPORTS/`)
- Same error handling and exit codes

This prevents drift between manual test runs and ensures CI/agent executions produce identical results.

**What the script does:**
1. Reads enabled modules from `modules/enabled.md`
2. For each module, independently:
   - runs `pytest -v --tb=short` over `modules/<m>/TESTS` (if present), and
   - runs the **Playwright** frontend suite over `modules/<m>/frontend/TESTS/playwright`
     (if present) — installs deps + chromium, derives `MODULE_SLUG` from the module
     manifest, runs `npx playwright test`
3. Generates human-readable, colour-cued reports (✅ Passed / ❌ Failed / 🔵 Skipped):
   per-module `test-report.md` (pytest) and `ui-test-report.md` (Playwright) — each with a
   Summary counts table, a **"What was tested"** table (human-readable name + result +
   location, failures first), the explicit CRUD-operation log, and an isolated failure
   traceback per failed test **for the fix phase** — plus a cross-module
   `TEST_REPORTS/<timestamp>-SUMMARY.md` and a colour console summary at the end.
4. Runs all modules, then **exits non-zero if any suite failed** (pytest "no tests
   collected" is not a failure) so CI can gate on it

> **Frontend UI / E2E (Playwright).** By default the runner executes only the
> **stack-free** UI suites — chiefly the `@ideable/ui` **Widget Gallery** (render +
> `@axe-core/playwright` a11y + a per-OS visual baseline), which boots its own dev
> server and needs no stack or auth. Specs that need a running authenticated stack
> (L&F parity, authenticated pages) run only when `RUN_STACK_E2E=1` is exported (they
> log in as a real, profile-bearing persona by driving the Authentik form — no ROPC,
> no human). Full contract, env, and
> baseline-generation steps: `rules/testing-guidelines.md` § *Frontend UI / E2E tests
> (Playwright)*. This is distinct from the legacy pytest-playwright suite below.

> **Local-iteration commands below require the explicit opt-in prefix
> `IDEABLE_UNRECORDED_RUN=1`.** Without it, the repo-root `conftest.py` / `playwright.config.ts`
> guard **hard-fails** a direct `pytest` / `npx playwright test` (see
> `rules/testing-guidelines.md` § *How tests must be run*). These commands run the tests but
> write **no** `TEST_REPORTS/` entry — the official / gate result must still come from the
> runner (Step 3 above). They are intentionally **not** `// turbo` (conscious opt-in only).

### One module (example: host_app) — local iteration only
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/ -v --tb=short
```

### One suite inside a module (example: host_app)

Database suite only:
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/database/ -v --tb=short
```

Backend suite only:
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/backend/ -v --tb=short
```

Authentik + Traefik suite only:
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/authentik_traefik/ -v --tb=short
```

Authentik + Traefik endpoint-reference smoke tests only:
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/authentik_traefik/test_authentik_traefik.py -v --tb=short -k TestExternalEndpointReference
```

Notes:
- `TestExternalEndpointReference` validates the endpoint URLs printed by `redeploy.sh`:
  - `/health`, `/api`, `/api/docs`, `/api/openapi.json`
  - `/module/template/health`, `/module/template/api`, `/module/template/api/docs`, `/module/template/api/openapi.json`
  - `/module-registry.json`, `/remotes/template/mf-manifest.json`
- These tests run automatically when running all host_app tests or the whole `authentik_traefik` suite.

Frontend UI / E2E (Playwright, Node — the @ideable/ui gallery + seeded-session specs):
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh bash -c 'cd modules/module_template/frontend/TESTS/playwright && npm ci && npm test'
```

Legacy frontend E2E suite (pytest-playwright; authenticated cases are `@skip` pending a
headless-login story — the Node suite above is the maintained path):
```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/tool.sh pytest modules/host_app/TESTS/frontend/ -v --tb=short
```

## Step 4 — Interpret results

After the run completes, report:
- Total tests collected, passed, failed, skipped
- For each failure: test name, error message, and likely cause

**Update the implementation plan.** Resolve the active plan (the most-recently-modified
`*.md` in `implementation-plans/`, per `rules/implementation-plan.md`). If one exists, set
each thing's `BE test` / `FE test` cell from the results (🔄 while running, ✅ passing, ❌
failing, ➖ when that side does not apply), update the Repos `Tests` counts
(`<n> passed / <n> failed / <n> pending`), and refresh the Status summary. Honour
`rules/implementation-plan.md` § *A failure must be visible, and sticky*: a failing suite marks
**every** thing it covers ❌ (never leave the table green or 🔲 after a failing run), a ❌ stays
until that same thing passes again, the thing's `Impl` becomes 🛠️ while it fails, and the Status
summary states how many tests fail and where. Also set the
Overall-view **Current step** to `Testing (ideable-test-and-fix)`, move the graph highlight to
the `Testing` node (rewrite the two `class` lines), and refresh **Last updated**. If no plan
exists, skip silently and note it in the report — do not create one from this skill.

**Where a green run goes next.** A passing suite hands off to **`Documenting`**
(`ideable-align-docs`), not to `Committing`: the specs and docs governing what changed are brought
into line with what is now true, and only then is anything committed. A failing suite still goes to
`Fixing`. Do not advance a green run straight to `Committing` — that skips a node of the canonical
graph.
- Common failure patterns and their meaning:

| Failure pattern | Likely cause |
|---|---|
| `psycopg2.OperationalError` | Database container not running or wrong port |
| `requests.exceptions.ConnectionError` on backend | Backend container not running or wrong `BACKEND_URL` |
| `AssertionError: 401` on backend CRUD | Auth headers not forwarded — check `conftest.py` `backend_headers` fixture |
| `AssertionError: No application with slug` | Authentik bootstrap container did not complete successfully |
| `AssertionError: Traefik dashboard returned 4xx` | Traefik not running or dashboard port not exposed |
| `TimeoutError` in Playwright | Frontend container not running, page not loading, or selector mismatch |
| `AssertionError` on nav link / heading | Frontend routing or component changed — re-check `App.tsx` routes and page headings |

## Step 5 — Create bug-fix plan (interactive)

After running tests, open the generated report(s), starting with the cross-module summary:
- `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-SUMMARY.md` — overall verdict + per-module breakdown
  (start here for the quick glance; it links to each detailed report).
- `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md` (pytest) and
  `ui-test-report.md` (Playwright) — the **"What was tested"** table shows each test's
  result, and the **"❌ Failures — details for the fix phase"** section has the isolated
  traceback for each failure to drive the fixes below.

Then ask:
- **Do you want to fix the reported bugs now?**

If the user confirms, enter the `Fixing` node:

- **Fix each bug through the `ideable-spec-driven-edit` discipline — do not patch inline.**
  That atomic skill is the single rulebook every code/config change must obey, so a fix from
  the test loop honours the exact same rails as `ideable-implement-specs` /
  `ideable-bugfixing-and-changes`: **look in the affected sub-module's `general_bug_avoider.md`
  and specs first**; edit only on the codebase (never running containers/`deployment_root`/`DIST`);
  **no fallbacks, no hardcoding, no silent schema/spec deviation**; **propose spec changes and
  stop-and-ask on ambiguity** rather than coding around them; and **record the fix back** into
  the appropriate bug-avoider/spec (what failed, root cause, fix, how to avoid the regression).
  Read `ideable-spec-driven-edit` and follow it for every fix here.
- **Plan bookkeeping (this skill's duty):** while fixing a thing that failed its tests, set its
  `Impl` cell to 🛠️ (`Fixing`) and its Repos `Implementation` to `Fixing`; once its tests pass,
  set `Impl` back to ✅ and the test cell to ✅. Set **Current step** to `Fixing (ideable-test-and-fix)`,
  move the Overall-view highlight to the `Fixing` node, and refresh **Last updated** (per
  `rules/implementation-plan.md`). A fix changes SOURCES only, so re-enter `BuildDeploy` (redeploy)
  before re-running the tests.

## Step 6 — Reports

Do **not** hand-roll a report. The sanctioned runner (Step 3) already writes the timestamped
Markdown reports under `TEST_REPORTS/` — the only place reports may live (never inside
`TESTS/`, per `rules/general-guidelines.md` § *Testing* and `rules/testing-guidelines.md` §
*Test Reports*):
- `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-SUMMARY.md` — cross-module summary.
- `TEST_REPORTS/<timestamp>-<MODULE>/test-report.md` (pytest) and `ui-test-report.md`
  (Playwright).

These are the artifacts to open in Step 5 and to cite in the report. A direct
`pytest`/`playwright` run (even with `IDEABLE_UNRECORDED_RUN=1`) writes **no** `TEST_REPORTS/`
entry by design.
