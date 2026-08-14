# Frontend UI / E2E tests (Playwright)

Full contract: `rules/testing-guidelines.md` § *Frontend UI / E2E tests (Playwright)*.

## Layout

```
playwright/
  playwright.config.ts        # chromium; boots the dev server for stack-free runs
  tests/
    widget-gallery.spec.ts       # stack-free: @ideable/ui gallery (render + axe a11y + visual)
    items-crud.spec.ts           # live-stack: full CRUD (create via API; R/U/D via UI)
    lf-parity.spec.ts            # live-stack: host_app/module_template L&F snapshots
  auth/                          # real-user login (Authentik has no password/ROPC grant,
    personas.ts                  #   so we drive the real login form as a real user)
    login.ts                     # drives the Authentik login flow, captures the session
    global-setup.ts              # logs in each persona once when RUN_STACK_E2E=1
    session-fixture.ts           # rehydrates a persona's session per test
```

## Two run modes

**Stack-free (default, CI-portable)** — no stack, no auth. Boots the module dev server
and runs the `@ideable/ui` Widget Gallery.
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
The gallery suite auto-skips on `RUN_STACK_E2E` (it's the stack-free one); the
authenticated specs auto-skip without it.

## Adding a profile-scoped persona (different profile / roles / permissions)

1. Ensure a **real user** with the target profile exists in Authentik — add it under
   `users:` in `modules/host_app/config/authorization.yaml` (`profiles: [<name>]`,
   `password_env: <SECRET>`), and re-bootstrap.
2. Add the persona in `auth/personas.ts` (username + password env).
3. In a spec: `const test = personaTest('<persona>')` (from `../auth/session-fixture`).

The persona logs in as that real user, so its token carries exactly that profile's
roles/permissions — enabling real authorization assertions.

## Visual baselines

Screenshot baselines are per-OS and (for lf-parity) depend on deployed L&F/data. The
visual tests **skip** when no baseline exists for the platform. Generate per environment
with `npm run test:update` and commit the result (for CI-stable pixels, generate inside
`mcr.microsoft.com/playwright`).

The framework runner `scripts/common/run_enabled_tests.sh` runs the stack-free `npm test`
here automatically for every enabled module with this directory.
