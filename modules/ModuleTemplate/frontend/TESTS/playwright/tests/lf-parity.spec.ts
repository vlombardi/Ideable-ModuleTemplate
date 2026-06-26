import { test, expect } from '@playwright/test'

const HOSTAPP_URL = process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3000'
const TEMPLATE_URL = process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3001'

test.describe('HostApp/ModuleTemplate L&F parity snapshots', () => {
  test('hostapp users page baseline', async ({ page }) => {
    await page.goto(`${HOSTAPP_URL}/users`, { waitUntil: 'networkidle' })
    await page.setViewportSize({ width: 1440, height: 900 })

    const tableRegion = page.locator('table').first()
    await expect(tableRegion).toBeVisible()
    await expect(tableRegion).toHaveScreenshot('hostapp-users-table.png')
  })

  test('moduletemplate items page snapshot', async ({ page }) => {
    await page.goto(`${TEMPLATE_URL}/items`, { waitUntil: 'networkidle' })
    await page.setViewportSize({ width: 1440, height: 900 })

    const tableRegion = page.locator('table').first()
    await expect(tableRegion).toBeVisible()
    await expect(tableRegion).toHaveScreenshot('moduletemplate-items-table.png')
  })

  test('moduletemplate items controls snapshot', async ({ page }) => {
    await page.goto(`${TEMPLATE_URL}/items`, { waitUntil: 'networkidle' })

    const controlsRegion = page.locator('text=Rows per page:').first()
    await expect(controlsRegion).toBeVisible()
    await expect(page.locator('body')).toHaveScreenshot('moduletemplate-items-controls.png')
  })
})
