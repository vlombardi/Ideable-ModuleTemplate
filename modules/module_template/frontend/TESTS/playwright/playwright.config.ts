import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// --- Ideable test-runner guard -------------------------------------------------------
// The sanctioned test path is scripts/common/run_enabled_tests.sh (directly or via the
// ideable-test-and-fix skill) — the only path that writes TEST_REPORTS/. It exports
// IDEABLE_TEST_RUNNER=1. A direct `npx playwright test` produces no report, so it
// hard-fails here at config load — unless the developer explicitly opts into throwaway
// local iteration with IDEABLE_ALLOW_DIRECT=1 (loud warning; still no report).
// Framework-owned; force-synced. See rules/testing-guidelines.md § "How tests must be run".
{
  const viaRunner = process.env.IDEABLE_TEST_RUNNER === '1'
  const allowDirect = process.env.IDEABLE_ALLOW_DIRECT === '1'
  if (!viaRunner && !allowDirect) {
    console.error(
      '\nERROR: Ideable Playwright tests must be run through the test-and-fix runner,\n' +
      'which records results under TEST_REPORTS/:\n' +
      '    ./scripts/common/run_enabled_tests.sh\n' +
      '  (or invoke the `ideable-test-and-fix` skill, which calls it).\n\n' +
      'For throwaway LOCAL iteration only (no TEST_REPORTS/ written), opt in explicitly:\n' +
      '    IDEABLE_ALLOW_DIRECT=1 npx playwright test\n',
    )
    process.exit(1)
  }
  if (!viaRunner && allowDirect) {
    console.warn(
      '\n⚠️  Playwright is running OUTSIDE the Ideable test-and-fix runner ' +
      '(IDEABLE_ALLOW_DIRECT=1). NO TEST_REPORTS/ entry will be created.\n',
    )
  }
}
// -------------------------------------------------------------------------------------

const here = path.dirname(fileURLToPath(import.meta.url))
const SOURCES = path.resolve(here, '../../SOURCES')

// Two run modes:
//  - Unauthenticated Widget Gallery (default, CI-friendly): no running stack needed.
//    Playwright boots the module_template dev server on TEMPLATE_DEV_PORT (default 3101,
//    kept off the deployed :3001) and serves /template/gallery, which renders from
//    synthetic data and never calls the backend.
//  - Authenticated pages (items, host_app parity): set TEMPLATE_FRONTEND_URL /
//    HOSTAPP_FRONTEND_URL to a running stack; the session is seeded by auth/global-setup.
const DEV_PORT = Number(process.env.TEMPLATE_DEV_PORT ?? 3101)
const BASE_URL = process.env.TEMPLATE_FRONTEND_URL ?? `http://localhost:${DEV_PORT}`
const usesRunningStack = !!process.env.TEMPLATE_FRONTEND_URL

export default defineConfig({
  testDir: './tests',
  // Mints a service session for authenticated specs when RUN_STACK_E2E=1; a no-op
  // otherwise (see auth/global-setup.ts).
  globalSetup: './auth/global-setup.ts',
  timeout: 90_000,
  expect: {
    timeout: 15_000,
    toHaveScreenshot: { maxDiffPixelRatio: 0.02 },
  },
  // Never auto-write baselines on a normal run; the visual test skips when a
  // platform baseline is missing. Baselines are written only when the run passes
  // --update-snapshots (which overrides this), keeping generation explicit.
  updateSnapshots: 'none',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Tolerate the live stack's TLS cert on authenticated runs (internal/self-signed
    // certs are common in staging/CI); the dev-server stack-free run is plain HTTP.
    ignoreHTTPSErrors: usesRunningStack,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: usesRunningStack
    ? undefined
    : {
        command: 'npm run dev',
        cwd: SOURCES,
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          PORT: String(DEV_PORT),
          WIDGET_EXAMPLES: 'true',
          // Give the standalone dev shell a non-empty <title>; in production
          // host_app sets this. Keeps the gallery a11y scan clean (WCAG 2.4.2).
          VITE_APP_TITLE: 'Module Template — Widget Gallery (dev)',
        },
      },
})
