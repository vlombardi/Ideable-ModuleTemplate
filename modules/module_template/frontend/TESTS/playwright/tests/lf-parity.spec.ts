import { test, expect } from '../auth/session-fixture'
import fs from 'node:fs'
import type { TestInfo } from '@playwright/test'

const HOSTAPP_URL = process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3000'
const TEMPLATE_URL = process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3001'
// Route slug — 'template' locally, the remote's slug via MODULE_SLUG (see runner).
const SLUG = process.env.MODULE_SLUG ?? 'template'

// Visual baselines are per-OS and depend on the deployed L&F/data, so skip when no
// baseline is committed for this platform (never spuriously red). Generate per
// environment with `npm run test:update`; see testing-guidelines.md § UI tests.
function skipUnlessBaseline(testInfo: TestInfo, name: string): void {
  const updating = testInfo.config.updateSnapshots !== 'none'
  test.skip(
    !updating && !fs.existsSync(testInfo.snapshotPath(name)),
    `No visual baseline for ${process.platform}; run "npm run test:update" in the target env.`,
  )
}

test.describe('host_app/module_template L&F parity snapshots', () => {
  // These target authenticated pages of a *running* host_app + module_template stack
  // and rely on the seeded session from auth/global-setup. They are opt-in: set
  // RUN_STACK_E2E=1 (plus HOSTAPP_FRONTEND_URL / TEMPLATE_FRONTEND_URL and the auth
  // env) to run them. Without it they skip, so the stack-free gallery suite is the
  // only thing the default test phase runs. See testing-guidelines.md § UI tests.
  test.skip(
    !process.env.RUN_STACK_E2E,
    'L&F parity requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  test('hostapp users page baseline', async ({ page }, testInfo) => {
    skipUnlessBaseline(testInfo, 'hostapp-users-table.png')
    await page.goto(`${HOSTAPP_URL}/users`, { waitUntil: 'networkidle' })
    await page.setViewportSize({ width: 1440, height: 900 })

    const tableRegion = page.locator('table').first()
    await expect(tableRegion).toBeVisible()
    await expect(tableRegion).toHaveScreenshot('hostapp-users-table.png')
  })

  test('moduletemplate items page snapshot', async ({ page }, testInfo) => {
    skipUnlessBaseline(testInfo, 'moduletemplate-items-table.png')
    await page.goto(`${TEMPLATE_URL}/${SLUG}/items`, { waitUntil: 'networkidle' })
    await page.setViewportSize({ width: 1440, height: 900 })

    const tableRegion = page.locator('table').first()
    await expect(tableRegion).toBeVisible()
    await expect(tableRegion).toHaveScreenshot('moduletemplate-items-table.png')
  })

  test('moduletemplate items controls snapshot', async ({ page }, testInfo) => {
    skipUnlessBaseline(testInfo, 'moduletemplate-items-controls.png')
    await page.goto(`${TEMPLATE_URL}/${SLUG}/items`, { waitUntil: 'networkidle' })

    const controlsRegion = page.locator('text=Rows per page:').first()
    await expect(controlsRegion).toBeVisible()
    await expect(page.locator('body')).toHaveScreenshot('moduletemplate-items-controls.png')
  })
})
