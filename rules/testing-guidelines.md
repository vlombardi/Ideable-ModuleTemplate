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
  exception: prefix the command with **`IDEABLE_UNRECORDED_RUN=1`**. The tests then run, a
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
  (when present). It exits non-zero if any suite fails, so CI can gate on it. Only pytest
  **exit code 5** ("no tests collected") is a non-failure; any other non-zero exit that
  yields no countable failing test — a collection error, an internal error, an interrupted
  run — is reported as a failure, in the per-suite report **and** in the cross-module
  summary, naming the exit code and the cause. Zero counts cannot distinguish "nothing to
  test" from "nothing ran", so the exit code decides. Contract tests:
  `scripts/TESTS/test_test_runner_reporting.py`.

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
* **What is committed**: the `<timestamp>-SUMMARY.md` files only. The per-run
  `<timestamp>-<MODULE>/` directories are gitignored (`TEST_REPORTS/*/`): the runner rewrites them
  on every run and nothing reads a past one, so tracking them added 1835 files of noise to every
  grep and diff. A summary stays tracked because it is **evidence**: a plan delivery's
  `Test-Report:` trailer names one, and `test_plan_deliveries_say_what_they_did.py` re-adds its
  tables to prove the commit message's counts were measured. Consequence to know: a summary's links
  to its detail reports resolve in the tree that ran the tests, and not in a fresh clone — re-run
  the suite to regenerate them.
* **Each per-module report contains**, in order:
  - **Summary** — overall verdict + a ✅/❌/🔵/Total counts table.
  - **What was tested** — a table with one row per test: its result badge, a
    human-readable description (e.g. "Entity X creation", derived from the test name /
    Playwright title), and its location (`file::test` or `spec.ts:line`). Rows are ordered
    failures → skipped → passed so problems surface first.

    **This table is a machine-read contract, not only a human one.** `scripts/common/dev_cycle.py`
    parses the `Location` column to attribute results **per test file**, which is what lets a plan
    row be measured by the file that actually exercises it instead of by a module-wide roll-up
    (`rules/implementation-plan.md` § *Name what measures a row*). The badge and the location are
    therefore load-bearing: changing their shape changes which rows a plan can measure. It is also
    why the framework needs no JUnit XML — this table already carries everything a per-file
    verdict requires.
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

* **Stack-requiring (automatic when possible)** — specs that need a running authenticated
  stack (`tests/module-authorization.spec.ts`, `tests/items-crud.spec.ts`,
  `tests/crud-endpoints.spec.ts`, `tests/entity-pages.spec.ts`, `tests/module-claims.spec.ts`,
  `tests/remote-failure.spec.ts`, `tests/lf-parity.spec.ts`).

  **These enable themselves** whenever `run_enabled_tests.sh` can resolve an
  `E2E_TEST_PASSWORD` and a frontend URL; they skip only when something they need is genuinely
  absent. `RUN_STACK_E2E=1` forces them on, `=0` forces them off.

  **They were opt-in and that cost a shipped regression.** The access token became thin and a
  module page kept deriving its permissions from it, so every authorized user was told "You are
  not authorized to view this page". Every backend suite passed — the backend was right — while
  this layer reported "3 passed, 19 skipped" and the gate went green. The only tests that see what
  a *user* sees must not be the ones that are off by default.

**Authentication — real-user login by dedicated personas.** Authentik has **no password/ROPC
grant**, and a `client_credentials` **service account is a machine identity that resolves
no profile** (host_app gates all content on an active profile), so authenticated specs
log in as a **real, profile-bearing user** by driving the actual Authentik login form
(Playwright is a browser — no interactive human needed):
- `config/test-users.yaml` (per module) — the e2e accounts, `e2e_`-prefixed so they are
  identifiable at a glance in Authentik and in an access review. **Two gates, both required**,
  because they carry a known password: `E2E_TEST_USERS_ENABLED=true` (default **false**) and
  `IDEABLE_EXECUTION_MODE != prod` (refused outright in production, flag or no flag). The password
  comes from `E2E_TEST_PASSWORD`; no password, no accounts. They are declared **apart from**
  `config/bootstrap-users.yaml`, which holds the real first administrator — different risk,
  different file.

  **Give every persona a tenant, let the provisioner create it, and keep it distinct from the
  installation's own.** Tenant scoping fails closed, so a persona with no tenant is denied on every
  tenant-scoped endpoint and can exercise nothing — the suite then asserts 403s for the wrong reason
  and still passes. host_app's personas use **`TEST_TENANT`**, which the provisioner creates when
  the installation does not have it, under those same two gates.

  **It is not the seeded tenant.** `database/SPECS/seed.sql` seeds **`DEFAULT_TENANT`**, which
  exists for a production reason — a fresh installation needs one tenant before the first user sync
  — and which a deployment that creates its own tenants first never receives. Two tenants, two
  purposes, and the separation buys two things: a suite never drives the tenant a real installation
  uses, and because nothing but the provisioner ever creates a tenant by the test name, the suite's
  own row is identifiable rather than indistinguishable from a customer's.

  Both halves of that were learned the hard way. The personas first named `EU`, the seeded default
  of a reference install, so on any real installation the provisioner logged
  `no such tenant(s) ['EU'] — skipped`, created the account in Authentik and **no host_app row at
  all**; the browser suite then logged in successfully and drove an identity with no profile and no
  permissions, and twelve entity-page tests failed against a blank shell before anyone connected
  them to a warning in a deploy log. The first fix pointed the personas at the *renamed* seeded
  tenant, which fixed the skip and quietly made a production tenant and a test tenant the same row.
  `modules/host_app/backend/TESTS/test_e2e_personas_get_a_tenant.py` now asserts they differ.
- **Never test as `sadmin` or any production account.** Two reasons, and the second is the
  important one: it is a production identity, and it holds *every* permission — so a suite built
  around it can only ever assert that something is ALLOWED. Half of authorization is denial, and
  denial is only meaningful when the persona legitimately lacks the permission.
- `auth/personas.ts` — the registry. Personas are chosen to differ by exactly what they may do,
  which is what makes the matrix testable:

  | Persona | Profile | Sees Items | May edit |
  |---|---|:--:|:--:|
  | `hostAdmin` | `admin` | yes | yes |
  | `moduleAdmin` | `template_admin` | yes | yes |
  | `moduleReader` | `template_reader` | yes | **no** |
  | `noModule` | `reader` | **no** | no |
  | `officer` | `security_officer` | — | reads the privileged-access review, which `hostAdmin` cannot |

- `auth/login.ts` — drives the Authentik flow (identification `#ak-identifier-input` →
  password `#ak-stage-password-input`, clicking the *visible* stage button) and captures
  the session: `storageState` (cookies) **plus** the oidc-client-ts *User* blob from
  **sessionStorage** (which `storageState` can't carry).
- `auth/global-setup.ts` logs in each configured persona **once** (only when
  `RUN_STACK_E2E=1`) → `auth/.auth/<persona>.json` (git-ignored; holds a live session).
- `auth/session-fixture.ts` rehydrates a persona per test: a context from the captured
  `storageState` + an init script re-seeding the sessionStorage blob. Specs use
  `const test = personaTest('<persona>')` (default `hostAdmin`). A spec that needs a logged-in
  shell **must** import from `auth/session-fixture`, not from `@playwright/test` — the plain
  import yields an unauthenticated page that redirects to the identity provider, which looks
  exactly like the blank-page crash some of these specs exist to detect.

**Assert absence only after the decision has been made.** `expect(x).toHaveCount(0)` and
`not.toBeEmpty()` pass instantly on a page that has not finished loading, so an authorization
check written as "the refusal is not present" right after `goto` goes green against a build that
demonstrably refuses. Verified by re-deploying the original bug: the suite passed. Wait for a
positive signal first — the `/me` response, or the rendered heading — and assert absence after it.
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
  parses the `FOREIGN KEY … REFERENCES` clauses in `database/SPECS/schema.sql`
  and returns the per-entity `parents` and a leaf-first `createOrder`. A **leaf** is an
  entity with no outgoing FK to another in-scope entity.
- **Create bottom-up (leaves → root):** topologically sort so every parent is created
  before its children; when creating a child, **valorize each FK field with a
  previously-created parent's id** (captured from that parent's create response).
- **Delete top-down (root → leaves):** reverse the create order so deletes don't violate
  FK constraints. Read/Update happen per entity as usual.
- On an unbreakable cycle or a required FK to an out-of-scope/external entity, that entity
  is reported SKIPPED with the reason (as the generic `crud-endpoints` probe already does).

Reference implementation to copy per entity: `modules/<MODULE>/frontend/TESTS/playwright/tests/<entity>-crud.spec.ts` — shipped once as `items-crud.spec.ts` for the template's example entity, which a real module adapts or deletes
(Items has no FK; for FK-bearing entities apply the dependency-tree ordering above).
These are opt-in (`RUN_STACK_E2E=1` + a running authenticated stack); the runner executes
them in the test phase when invoked against a live stack, and skips them otherwise.

**Entity scoping in a remote module — cover exactly its own entities.** A module's
per-entity CRUD suites must correspond **one-to-one with the entities in that module's own
datamodel** (`database/SPECS/schema.sql`, the generated rendering of `app/models.py`): one
suite per entity, and **no suite
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

### Reading source in a contract test — use `code_only`

A test that asserts on the **text** of a source file is running a search, and a search over raw
source finds the comment that *explains* a defect and reports it as the defect. That is not an edge
case: it is the normal outcome, because the comment next to a defect names the defect.

So never hand-roll the stripping. The repo-root `conftest.py` provides a session fixture:

```python
def test_a_write_never_consults_the_read_permission(self, code_only):
    code = code_only(crud_source)                      # Python (default)
    assert "read_all_tenants" not in code              # the docstring explains why; the code must not
    shell = code_only(hook_source, "shell")            # `#` comments, quote-aware
```

- **Comments and docstrings go; other string literals stay.** Many correct assertions search for a
  message the code emits (`"TenantScope requires at least one tenant id" in auth`), so stripping
  every string would break them silently.
- **Docstrings are found with `ast`, comments with `tokenize`** — not a regex. A regex for triple
  quotes cannot tell a docstring from a triple-quoted SQL statement, and this repository has both.
- **A fragment works.** `src.split("def get_entity")[1]` is not valid Python; it is completed into
  each shape a slice takes, so its docstring is still removed.
- **It is a fixture, not an import**, because a `TESTS/` directory with its own `conftest.py` gets
  that directory on `sys.path` rather than the repo root — a root conftest's fixtures reach every
  `TESTS/` directory, a root module does not.

`scripts/TESTS/test_code_only_reads_code.py` fails if any suite defines a private `_code_only`.
Five had, each with a slightly different regex and one that would have eaten a triple-quoted SQL
block; five definitions of one idea are five chances for two assertions that look alike to mean
different things.

### Test Best Practices

1. **Isolation**: Tests must be independent and not rely on execution order
2. **Clarity**: Test names should clearly describe what is being tested
3. **Maintainability**: Update tests whenever related code changes
4. **Documentation**: Document complex test scenarios and edge cases
5. **Coverage**: Aim for high coverage of critical paths, but prioritize meaningful tests over coverage percentages
6. **Speed**: Keep unit tests fast; reserve longer-running tests for integration suites

## Where a test goes

The directory decides which plan column reports it, so put a test where its subject lives:

| Test subject | Directory | Column |
|---|---|---|
| backend code | `modules/<m>/backend/TESTS` | `BE test` |
| frontend code and UI | `modules/<m>/frontend/TESTS` (+ `/playwright`) | `FE test` |
| the module's compose, env, database, identity or menu contracts | `modules/<m>/TESTS`, `modules/<m>/<sub>/TESTS` | `Cfg test` |
| framework tooling under `scripts/` | `scripts/TESTS` | `Fw test` |

A framework test placed under a module counts as that module's coverage while testing code the
module does not own — misreporting both. `scripts/TESTS` exists so it has somewhere honest to go.

### What ships is tested here (mandatory)

**Everything the push/sync flow sends to a remote module project is tested in THIS repository, in
the shape the remote receives it** — a renamed module and slug, no `host_app` sub-module SOURCES, no
`docs/`, no `scripts/master_only/`, no `scripts/TESTS/`.
`scripts/master_only/verify_remote_shape.sh` is the mechanism: it stages that shape and runs the
tests against it, before anything is pushed.

A remote is **never** the place where framework correctness is established. It may not modify
framework-owned files (`rules/general-guidelines.md` § *Framework-owned files*), so a framework
failure it sees is only **reportable**, not fixable — the signal has to come back to the maintainer
to be acted on, which is where it should have been produced. Framework tooling tests therefore stay
in `scripts/TESTS` and are **never synced**; `rules/implementation-plan.md` states the same boundary
from the other side, where a remote's `Fw test` column is always `➖` — *ownership, not a gap*.

Testing a tool only against this repository is not testing what we ship. The master tree and a
generated project differ in exactly the ways that break tooling, and the framework has already paid
for it once: 21 framework tests hardcoded master-repo names and reported the framework's own
assumptions as the module's fault the first time a remote maintainer turned the gate on.

## A test owns the data it needs (mandatory)

**If a test requires specific database rows, users, tenants, permissions or tokens, the test itself
creates them and deletes them.** Never assume they are already there, and never leave them behind.

This is a hard rule because the alternative fails in both directions. A test that depends on
ambient data passes on the machine where that data happens to exist and fails everywhere else — or
worse, silently *skips*, which reads as green. A test that leaves data behind changes the ground
under every test after it, and the failure surfaces somewhere unrelated.

The tenant-scoping work is the worked example: its isolation tests needed two users in different tenants. Because
they did not provision them, the two-tenant assertion could not run at all, and the remaining
assertions skipped for want of a token. The security property was implemented and the test suite
reported success without ever exercising it.

### What this means in practice

- **Arrange in the test, not in the environment.** Rows, tenants, users, group memberships and
  permission grants are set up by the fixture that needs them.
- **Clean up unconditionally.** Use a fixture with `yield` (or `try/finally`), so teardown runs when
  the assertion fails — which is exactly when residue is most likely and most confusing.
- **Namespace everything with a per-run marker** (`f"E2E-{uuid4().hex[:8]}"`). A suite must be
  repeatable against a database that already contains other data, including its own earlier runs.
- **Never mutate shared reference data.** If the scenario needs a different shape, create a new row;
  do not edit the one everything else relies on.
- **Destructive setup goes on a scratch database**, never the deployed one — see
  `scripts/dev/schema.sh`, which creates and drops throwaway databases for exactly this reason.
- **Identities count as data.** A test needing a user with particular claims provisions that user
  (Authentik API) and removes it afterwards. "Set `TEST_AUTH_TOKEN` and hope" is not a fixture.
- **If it genuinely cannot provision, fail — do not skip.** A skip for missing data is a test that
  will never run again. Skips are for a deliberately absent *environment* (`RUN_STACK_E2E`), not for
  absent data the test was supposed to create.

### Reviewing your own test

Ask: *would this pass on a clean database, twice in a row, with no manual preparation?* If the
answer is no, the test is describing an environment rather than verifying behaviour.

## Static analysis gates the build (Python and TypeScript)

`scripts/common/run_enabled_tests.sh` runs **`ruff`**, **`mypy`** and **`tsc --noEmit`** before any
suite. A finding in either language fails the run. Configuration lives in `pyproject.toml`.

**`ruff` covers all of the repository's Python, and it prints its scope.** It used to lint three
application directories and report *"All checks passed!"* — true of those three and false of the
repository, where 18 findings sat unseen in `scripts/` and the TESTS trees. Two were live: a test
whose assertion checked a different region than its name claimed (exposed by `F841` on a dead local),
and a dead local in another test. **A gate that reports a pass without naming its scope is
indistinguishable from one that checked everything**, so the scope is printed with the result.

`pyproject.toml` is synced to every remote module for the same reason: `run_enabled_tests.sh` is
synced, and `ruff` resolves `[tool.ruff]` from the nearest `pyproject.toml`. Without it a remote runs
the gate under ruff's *defaults* — a different gate wearing the same name.

**Both languages, deliberately.** The frontends are transpiled without typechecking, and 27
TypeScript errors accumulated unseen — one of them a widget generic that made every association
table a type error, whose cascade then reported a dozen live identifiers as "declared but never
read". A gate covering only Python would leave the half that had already failed unguarded.

**The Python rule set is deliberately narrow**, and the reason is written into `pyproject.toml`
beside it: the full default set reports 892 findings, of which 606 are `pyupgrade` modernisation and
97 are `B008`, a false positive for FastAPI's `Depends()`. The gate enforces the rules that catch
*defects* — undefined names, unused imports and locals, redefinitions, empty f-strings, and silently
swallowed exceptions. On its first run it found one: a keyset-pagination predicate that was built,
bound and then dropped from the query, so every cursor page returned the first page.

**Do not widen a rule by silencing it.** An exception is justified **at its site** with
`# noqa: <rule> — <reason>`, never by a blanket per-file ignore: the value of a rule is in the next
violation, not the ones already reviewed. Widening the selected set is a change with its own diff.

**A missing tool is reported, not skipped silently.** If `ruff`, `mypy` or `npx` is absent the runner
says so explicitly — an unchecked build must never be indistinguishable from a clean one.


## A skip is explained, never just counted (mandatory)

A skip count is not information. `module_template`'s backend reported **19 skipped** inside a green
total for as long as the tests existed; nothing in the runner ever set the `TEST_AUTH_TOKEN` they
waited for, so those 19 — authenticated CRUD, JWT hot-path validation, history pagination — had
**never executed once**. Turning them on immediately found four defects, including two fixtures that
shadowed the shared one and a test that contradicted its own sibling.

A skip means one of two different things, and the count cannot tell them apart:

- **Not applicable here** — a visual baseline with no committed snapshot for this OS. Expected, fine.
- **The runner failed to configure it** — the test has never run. A coverage gap wearing the same
  badge.

**Rules:**

1. **Every suite publishes its skip *reasons*, and the runner prints them** — in the console summary
   and in `TEST_REPORTS/<stamp>-SUMMARY.md`. Reasons that look like unconfigured (`not set`,
   `unset`, `not configured`, `missing`, …) are flagged **separately** from the benign kind. Flagging
   both alike would train the reader to skim past the real ones.
2. **Never write a bare `pytest.skip()`.** Give a reason: an unexplained skip is an
   explanation-shaped hole where the explanation goes. (pytest's `-v` line carries no reason at all —
   only the `-rs` short-summary block does, which is why the runner passes `-rs`.)
3. **The reasons must reconcile with the count.** The runner asserts that every counted skip is
   accounted for, and says so when they disagree in *either* direction — a whole module skipped at
   import produces a reason with no per-test line, which is normal and worth stating rather than
   subtracting into a negative.
4. **Prefer making the test run to explaining why it cannot.** A fixture that can obtain what it
   needs should obtain it and **fail** if it cannot, rather than skip: these are integration tests
   against a deployed stack, and the unauthenticated tests beside them already fail outright when the
   stack is down. A skip there was never consistent with them — only quieter.
5. **A missing test dependency is a skipped module, and therefore invisible.**
   `pytest.importorskip("sqlalchemy_continuum")` silently removed six tests from every run because
   the package was absent from the test venv. Reporting reasons is what surfaced it. Install what the
   suite needs; do not let `importorskip` become the reason a module never runs.
