# Frontend UI / E2E tests (Playwright)

Full contract: `rules/testing-guidelines.md` § *Frontend UI / E2E tests (Playwright)*.

## Layout

Two kinds of file live here, and the difference decides who owns them.

**Force-synced — the harness and the generic suites.** Every module has these, they are overwritten
by each `sync-template-updates.sh`, and they need no edit in any module because each one discovers
what to exercise from the module's own sources:

```
playwright/
  playwright.config.ts        # chromium; boots the dev server for stack-free runs
  package.json
  lib/
    entity-graph.ts              # FK dependency tree from the module's own schema.sql
  auth/                          # real-user login (Authentik has no password/ROPC grant,
    personas.ts                  #   so we drive the real login form as a real user)
    login.ts                     # drives the Authentik login flow, captures the session
    global-setup.ts              # logs in each persona once when RUN_STACK_E2E=1
    session-fixture.ts           # rehydrates a persona's session per test
  tests/
    entity-pages.spec.ts         # every entity page in THIS module's manifest loads authenticated
    crud-endpoints.spec.ts       # CRUD round-trip per resource discovered in THIS module's OpenAPI
    entity-graph.spec.ts         # unit test for the FK ordering helper
    module-css-loaded.spec.ts    # the module's stylesheet reaches the browser
```

**The module's own — the per-entity and dev-only examples.** `tests/` also receives reference
specs at module init, and from then on they belong to the module: it keeps the ones whose entities
it has, adapts them, or deletes them. Two are worth naming as examples rather than inventory —
a CRUD spec written against the reference module's `items` entity, and a Widget Gallery spec that
drives `/<slug>/gallery`, a dev-only page only `module_template` ships, which fails anywhere else
until it is removed. See `rules/testing-guidelines.md` § *CRUD E2E tests per entity* and the
`ideable-implement-specs` skill, Step 7 (*Entity scoping*), for the defined path: ship one CRUD
suite per entity in **this** module's datamodel, and delete any example whose entity is absent.

So this section describes the first list and not the second, deliberately. It named three specs by
filename until it was pointed out that all three were from the second list — two of which a remote
is instructed to delete — while none of the four suites every module is guaranteed to have were
mentioned at all. A force-synced document cannot hold an inventory of files the module is free to
remove.

## Two run modes

**Stack-free (default, CI-portable)** — no stack, no auth. Boots the module dev server and runs
every spec that needs neither: the FK-ordering helper's own test always, plus any of the module's
own specs that render pages without authentication (in `module_template` that is the `@ideable/ui`
Widget Gallery).
```bash
npm install && npx playwright install chromium
npm test
```

**Live-stack (authenticated)** — real login against a running stack. Playwright drives
the real Authentik login form as a **persona** (a real, profile-bearing user — a
`client_credentials` service account resolves no profile and is gated out). The default
persona `standard` is the bootstrap superadmin (`sadmin`, active profile `admin`).
```bash
RUN_STACK_E2E=1 \
  HOSTAPP_FRONTEND_URL=https://<host> TEMPLATE_FRONTEND_URL=https://<host> \
  VITE_OIDC_AUTHORITY=https://<host>/application/o/<app_slug>/ VITE_OIDC_CLIENT_ID=<app_slug>-client \
  SADMIN_USERNAME=sadmin AUTHENTIK_BOOTSTRAP_PASSWORD=<pw> \
  npm test
```
(These env values live in `deployment_root/.env.config` + `.env.secrets`; source them.)
Each spec declares which mode it belongs to and skips in the other, so both commands are safe to
run in any module: the authenticated specs skip without `RUN_STACK_E2E`, and the stack-free ones
skip with it.

## Adding a profile-scoped persona (different profile / roles / permissions)

1. Declare the account under `users:` in **`modules/host_app/config/test-users.yaml`**
   (`profiles: [<name>]`, `password_env: E2E_TEST_PASSWORD`, `tenants: [TEST_TENANT]`), and
   re-provision. `authorization.yaml` is not the place: it declares what ships with the code —
   permissions, roles, profiles — and its own header says users are not declared there.
2. Add the persona in `auth/personas.ts` (username + password env).
3. In a spec: `const test = personaTest('<persona>')` (from `../auth/session-fixture`).

The persona logs in as that real user, so its token carries exactly that profile's
roles/permissions — enabling real authorization assertions.

Two gates apply to every account in `test-users.yaml`, because they carry a known password:
`E2E_TEST_USERS_ENABLED=true` (explicit opt-in, default false) and `IDEABLE_EXECUTION_MODE != prod`
(refused in production, flag or no flag). Give each persona a tenant: tenant scoping fails closed,
so a persona without one is denied on every tenant-scoped endpoint and can exercise nothing.

Use **`TEST_TENANT`** and nothing else. The provisioner creates it when the installation does not
have it, so the personas work anywhere, and it is deliberately **not** the tenant a fresh
installation is seeded with (`DEFAULT_TENANT`) — a suite must not drive the tenant a real
installation uses, and a tenant only this provisioner ever creates is one whose rows are
identifiable as the suite's own.

## Visual baselines

Screenshot baselines are per-OS, and where a spec compares a module against host_app they also
depend on the deployed L&F and data. The visual tests **skip** when no baseline exists for the
platform. Generate per environment
with `npm run test:update` and commit the result (for CI-stable pixels, generate inside
`mcr.microsoft.com/playwright`).

The framework runner `scripts/common/run_enabled_tests.sh` runs the stack-free `npm test`
here automatically for every enabled module with this directory.
