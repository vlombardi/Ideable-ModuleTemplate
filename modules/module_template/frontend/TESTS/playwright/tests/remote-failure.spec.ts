import { test, expect } from '../auth/session-fixture'

// A down remote must cost its own menu entry, not the application. The failure this guards
// against is the one users actually report as "the app is broken": the shell renders a blank
// page because a module it federates failed, and nothing on the server side shows it.
//
// Runs AUTHENTICATED, via the session fixture. It used to import the plain Playwright `test`, so
// the shell had no session, redirected to the identity provider, and was measured mid-redirect —
// an empty body that looked exactly like the crash this test is for. It was skipped in the gate,
// so the mismatch never surfaced. The scenario being protected is a logged-in user whose module
// went down, so the persona has to be logged in.
//
// The spec simulates the outage at the network layer rather than by stopping the container, so it
// runs against a healthy stack and leaves it healthy: every request for the remote's assets is
// aborted, which is what the browser sees when `template-frontend` is down.
//
// Opt-in via RUN_STACK_E2E=1 (+ stack URL), like the other stack E2E specs.

const BASE = process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3000'
const REMOTE_SLUG = process.env.TEMPLATE_SLUG ?? 'template'
const shouldRun = process.env.RUN_STACK_E2E === '1'

test.describe('shell survives a remote module outage', () => {
  test.skip(!shouldRun, 'stack E2E is opt-in: set RUN_STACK_E2E=1')

  test('shell still renders when the remote is unreachable', async ({ page }) => {
    const blocked: string[] = []
    // Everything the remote serves: manifest, remoteEntry and its chunks.
    await page.route(`**/remotes/${REMOTE_SLUG}/**`, (route) => {
      blocked.push(route.request().url())
      return route.abort('connectionfailed')
    })

    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    const response = await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    expect(response?.status(), 'the shell itself must still be served').toBeLessThan(400)

    // The shell must render something — a blank body is the failure being tested for.
    //
    // Waited on a POSITIVE signal rather than asserted straight after `goto`. `domcontentloaded`
    // fires before React mounts, so the body is legitimately empty for a moment and an immediate
    // assertion reports a failure the product does not have. Measured: the shell renders its
    // sidebar and home content ~1-2s after DOMContentLoaded with the remote blocked, which is the
    // behaviour this test exists to protect.
    await expect(page.getByRole('navigation').or(page.locator('#root > *')).first()).toBeVisible({
      timeout: 20_000,
    })
    const bodyText = (await page.locator('body').innerText()).trim()
    expect(bodyText.length, 'the shell rendered an empty page').toBeGreaterThan(0)

    // And it must not be a React crash page: the root stays mounted.
    await expect(page.locator('#root')).toBeAttached()

    expect(blocked.length, 'the remote was never requested — the test proved nothing').toBeGreaterThan(0)
    // The remote's own failure is expected to be logged; that is the shell handling it, not
    // swallowing it. What must not happen is the shell dying with it.
    expect(consoleErrors.join('\n')).not.toContain('Minified React error #418')
  })

  test('a healthy stack still exposes the remote (control)', async ({ page }) => {
    // Without this, the previous test would pass equally well against a stack where the remote
    // never existed — proving nothing about isolation.
    const response = await page.request.get(`${BASE}/remotes/${REMOTE_SLUG}/mf-manifest.json`)
    expect(response.status(), 'remote should be reachable when not blocked').toBe(200)
  })
})
