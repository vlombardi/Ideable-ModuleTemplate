import { test, expect } from '@playwright/test'
import { test as authTest, expect as authExpect } from '../auth/session-fixture'
import AxeBuilder from '@axe-core/playwright'
import fs from 'node:fs'

// Module route slug. module_template mounts at /template/*; a remote renames it,
// so it is read from MODULE_SLUG (the runner exports it per module) and defaults to
// 'template' — this file is force-synced to remotes verbatim, so it must not hardcode.
const SLUG = process.env.MODULE_SLUG ?? 'template'
// The stack-requiring association-view test below needs the deployed shell's own origin — a bare
// relative `page.goto` resolves against Playwright's `baseURL`, but every other stack-requiring
// spec in this module (`module-authorization.spec.ts`, `entity-pages.spec.ts`) builds the full URL
// explicitly instead, so this follows the same convention rather than relying on `baseURL` alone.
const BASE = process.env.HOSTAPP_FRONTEND_URL ?? process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3000'

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
    // ServerDataTable (react-table) rendered with the synthetic Items rows. `.first()` because the
    // gallery's `StandardEntityPage` card also renders its own master table on the same page.
    await expect(page.getByRole('table').first()).toBeVisible()
    await expect(page.getByText('Widget Alpha')).toBeVisible()

    // Button variants from the shared primitives.
    await expect(page.getByRole('button', { name: 'Default', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Destructive', exact: true })).toBeVisible()

    // TimeSeriesChart renders a Recharts SVG surface.
    await expect(page.locator('.recharts-surface').first()).toBeVisible()
  })

  // Card-boundary helper: `Section` renders each demo as its own `Card` (a `div` carrying the
  // `ideable:rounded-lg` class the shared primitive always sets — see `reusable.ui/primitives/card.tsx`).
  // Scoping assertions to that ancestor is what actually tells "own card" from "nested in another
  // card's content", rather than merely checking the elements exist somewhere on the page.
  const cardFor = (page: import('@playwright/test').Page, heading: string | RegExp) =>
    page
      .getByRole('heading', { name: heading })
      .locator('xpath=ancestor::div[contains(@class, "ideable:rounded-lg")][1]')

  test('"Open Items in a popup" is its own card, not nested inside StandardEntityPage', async ({ page }) => {
    const standardPageCard = cardFor(page, /StandardEntityPage — the first standard-pages catalogue entry/i)
    const popupCard = cardFor(page, 'Open Items in a popup')

    // The trigger button lives in its own card...
    await expect(popupCard.getByRole('button', { name: 'Open Items in a popup' })).toBeVisible()
    // ...and not inside the StandardEntityPage card's own content.
    await expect(
      standardPageCard.getByRole('button', { name: 'Open Items in a popup' }),
    ).toHaveCount(0)

    await popupCard.getByRole('button', { name: 'Open Items in a popup' }).click()
    await expect(
      page.getByRole('heading', { name: 'Items — the standard page, inside a popup' }),
    ).toBeVisible()
  })

  test('the StandardEntityPage gallery card shows the association strip', async ({ page }) => {
    const standardPageCard = cardFor(page, /StandardEntityPage — the first standard-pages catalogue entry/i)

    // The visit-mode toggle renders as soon as `associations` is passed — this is the half of the
    // catalogue entry the gallery previously left invisible (no `associations` prop at all).
    await expect(standardPageCard.getByRole('button', { name: 'Depth visit' })).toBeVisible()
    await expect(standardPageCard.getByRole('button', { name: 'Full perspective' })).toBeVisible()
    // The breadcrumb tabs strip for the chain this gallery demonstrates: items -> sub_items -> sub_item_notes.
    await expect(standardPageCard.getByRole('tab').first()).toBeVisible()
  })

  test('has no critical or serious accessibility violations', async ({ page }) => {
    // axe walks the whole gallery — every widget, every state — in one page.evaluate. Alone that
    // takes ~15s; inside the full suite, competing with other workers, it has exceeded the 90s
    // default and failed as a timeout rather than on any violation. test.slow() triples the
    // budget, which keeps a genuine violation failing fast while a loaded machine does not
    // manufacture a red run.
    test.slow()
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

// Authenticated coverage for the gallery's association view against the real, deployed backend
// (base_specs.md § "The gallery's StandardEntityPage section demonstrates a real association
// chain" requires a REAL chain, not synthetic data — which the stack-free suite above cannot
// prove, since it never reaches the backend). Opt-in via RUN_STACK_E2E=1, same as
// entity-pages.spec.ts / items-crud.spec.ts. The gallery has no menu entry (dev-only page), so
// it is reached by its own URL rather than through moduleManifest.ts discovery.
authTest.describe('@ideable/ui Widget Gallery — association view (live stack)', () => {
  authTest.skip(
    !process.env.RUN_STACK_E2E,
    'Requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  authTest(
    'the StandardEntityPage gallery card shows a real association table with real rows',
    async ({ page }) => {
      await page.goto(`${BASE}/${SLUG}/gallery`, { waitUntil: 'networkidle' })
      await authExpect(
        page.getByRole('heading', { name: /Ideable UI — Widget Examples/i }),
      ).toBeVisible()

      const standardPageCard = page
        .getByRole('heading', { name: /StandardEntityPage — the first standard-pages catalogue entry/i })
        .locator('xpath=ancestor::div[contains(@class, "ideable:rounded-lg")][1]')

      // 'Sample Item' / 'Sample Sub-Item' are seeded by database/SOURCES/initdb/seed.sql —
      // real rows through entityTransport, not the gallery's synthetic DEMO_ITEMS.
      await standardPageCard.getByRole('row', { name: /Sample Item\b/ }).click()

      // Depth visit (the default mode) resolves the seeded item's own sub_items.
      await authExpect(standardPageCard.getByRole('cell', { name: 'Sample Sub-Item', exact: true })).toBeVisible()

      // Full perspective reaches the same row through the items -> sub_items join and the
      // toggle visibly still shows it — proving the two halves are both wired, not just one.
      await standardPageCard.getByRole('button', { name: 'Full perspective' }).click()
      await authExpect(standardPageCard.getByRole('cell', { name: 'Sample Sub-Item', exact: true })).toBeVisible()
    },
  )
})
