import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'

// Module route slug. module_template mounts at /template/*; a remote renames it,
// so it is read from MODULE_SLUG (the runner exports it per module) and defaults to
// 'template' — this file is force-synced to remotes verbatim, so it must not hardcode.
const SLUG = process.env.MODULE_SLUG ?? 'template'

// Unauthenticated E2E coverage for the @ideable/ui shared widget library, exercised
// through module_template's dev-only Widget Gallery (/template/gallery). The gallery
// renders every framework widget from synthetic data and never calls the backend, so
// this suite needs no running stack or auth — it runs against the dev server that
// playwright.config.ts boots. It is the CI-portable slice of the UI test phase.

test.describe('@ideable/ui Widget Gallery', () => {
  // Stack-free suite: it boots the module's dev server and renders the gallery
  // standalone (synthetic data, no auth). Skip it on the live-stack authenticated run
  // (RUN_STACK_E2E), where /<slug>/gallery sits behind host_app's auth/profile wall.
  test.skip(
    !!process.env.RUN_STACK_E2E,
    'Widget Gallery is the stack-free suite; run it without RUN_STACK_E2E',
  )

  test.beforeEach(async ({ page }) => {
    await page.goto(`/${SLUG}/gallery`, { waitUntil: 'networkidle' })
    await expect(
      page.getByRole('heading', { name: /Ideable UI — Widget Examples/i }),
    ).toBeVisible()
  })

  test('renders the core framework widgets', async ({ page }) => {
    // ServerDataTable (react-table) rendered with the synthetic Items rows.
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByText('Widget Alpha')).toBeVisible()

    // Button variants from the shared primitives.
    await expect(page.getByRole('button', { name: 'Default', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Destructive', exact: true })).toBeVisible()

    // TimeSeriesChart renders a Recharts SVG surface.
    await expect(page.locator('.recharts-surface').first()).toBeVisible()
  })

  test('has no critical or serious accessibility violations', async ({ page }) => {
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      // color-contrast depends on the project's brand token *values* (which remotes
      // are meant to override — see framework-css-classes-reference.md), not on the
      // widgets' structure. This gate enforces structural a11y (names, labels, roles);
      // contrast is a palette concern validated when a project tunes its tokens.
      .disableRules(['color-contrast'])
      .analyze()
    const blocking = results.violations.filter(
      (v) => v.impact === 'critical' || v.impact === 'serious',
    )
    if (blocking.length) {
      // Surface actionable detail in the test log before failing.
      console.log(
        'axe violations:\n' +
          JSON.stringify(
            blocking.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length })),
            null,
            2,
          ),
      )
    }
    expect(blocking, 'gallery must have no critical/serious a11y violations').toEqual([])
  })

  test('matches the visual baseline', async ({ page }, testInfo) => {
    // Playwright names screenshot baselines per-platform (e.g. …-linux.png).
    // Skip cleanly when no baseline is committed for this OS so a fresh checkout
    // is never spuriously red; the maintainer generates the CI (Linux) baseline
    // once via `npm run test:update` in the Playwright Docker image and commits it,
    // after which this test enforces visual regressions. See testing-guidelines.md.
    const baseline = testInfo.snapshotPath('widget-gallery.png')
    const updating = testInfo.config.updateSnapshots !== 'none'
    test.skip(
      !updating && !fs.existsSync(baseline),
      `No visual baseline for ${process.platform}; run "npm run test:update" in the CI/Linux env and commit it.`,
    )

    // Freeze transitions/animations for deterministic pixels across runs.
    await page.addStyleTag({
      content: '*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}',
    })
    await expect(page).toHaveScreenshot('widget-gallery.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
    })
  })
})
