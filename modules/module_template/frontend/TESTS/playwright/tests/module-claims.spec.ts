import { test, expect } from '../auth/session-fixture'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PERSONA } from '../auth/personas'

// A logged-in user must actually receive this module's permission claims, and the shell must
// render its menu entry as a result.
//
// This exists because of an outage that every other test passed through. host_app mounts the
// modules directory so the Authentik bootstrap can read each module's authorization.yaml and
// build the authorization plan. A path rewrite left that mount pointing outside deployment_root;
// Docker created the missing directory empty rather than failing, so the bootstrap found no
// authorization files, the generated blueprint contained no module permissions, and Authentik
// never created the module's groups.
//
// Nothing errored. Containers were healthy, logs were clean, login succeeded and issued a
// perfectly valid token — carrying no module claims, so the menu entry and every page behind it
// silently did not exist. Structural tests on the compose file catch that specific cause; this
// one catches the symptom whatever the cause, which is the point.
//
// Opt-in via RUN_STACK_E2E=1, like the other stack E2E specs.
//
// HOSTAPP_FRONTEND_URL must be the ROUTED entry point (Traefik), not the host_app frontend
// container's own port. `/remotes/<slug>/*` is served by the proxy, so against the container port
// the manifest request falls through to the SPA's index.html — a 200 that is not JSON — module
// federation cannot load the remote, and the menu entry is legitimately absent. That looks
// exactly like the authorization outage this spec exists to catch, and is not it.

const here = path.dirname(fileURLToPath(import.meta.url))
const HOSTAPP_URL = process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3000'
const SLUG = process.env.MODULE_SLUG ?? 'template'
const shouldRun = process.env.RUN_STACK_E2E === '1'

/** The access_token the app itself received, from the captured session. */
function accessToken(): string {
  const file = path.join(here, '..', 'auth', '.auth', `${DEFAULT_PERSONA}.json`)
  const captured = JSON.parse(fs.readFileSync(file, 'utf8'))
  return JSON.parse(captured.session.value).access_token as string
}

/**
 * The permission set host_app resolves for the logged-in persona.
 *
 * This replaces decoding the access token. The token is thin — identity and tenant ids
 * only — so any assertion made against its contents is asserting a contract that was removed. `/me`
 * is where permissions live, and it is the same source the frontend itself reads, so this asserts
 * exactly the value the code under test will see.
 */
async function resolvedPermissions(page: import('@playwright/test').Page): Promise<string[]> {
  const response = await page.request.get(`${HOSTAPP_URL}/api/me`, {
    headers: { Authorization: `Bearer ${accessToken()}` },
  })
  expect(response.status(), `GET /api/me: ${response.status()}`).toBe(200)
  const body = await response.json()
  return (body.permissions ?? []) as string[]
}

test.describe('a logged-in user receives this module\'s permissions', () => {
  test.skip(!shouldRun, 'stack E2E is opt-in: set RUN_STACK_E2E=1')

  test('the resolved permission set carries at least one entry for this module', async ({
    page,
  }) => {
    // Resolved by host_app, NOT decoded from the token. The token is thin since the thin-token change: it
    // carries identity and tenant ids and no permissions at all, so the old version of this test —
    // which searched the JWT for the module slug — asserted a contract that no longer exists. It
    // had been skipped since before the change, so it never said so.
    const granted = await resolvedPermissions(page)
    expect(
      granted.some((p) => p.toLowerCase().startsWith(`${SLUG.toLowerCase()}.`)),
      `no permission for "${SLUG}" in ${JSON.stringify(granted)}. The user can log in but the ` +
        `module is invisible to them. Check that the module's authorization.yaml was seeded: ` +
        `\`./authz.sh seed --module ${SLUG}\` reports what it applied, and Admin → System ` +
        `messages records what it deliberately did not.`,
    ).toBe(true)
  })

  test('the user is granted menu access rather than merely naming the module', async ({ page }) => {
    const granted = (await resolvedPermissions(page)).map((p) => p.toLowerCase())
    // `<slug>.<resource>:menu_access` is what the shell consults when deciding to render the entry.
    expect(
      granted.some((p) => p.startsWith(`${SLUG.toLowerCase()}.`) && p.endsWith(':menu_access')),
      `the user holds permissions for "${SLUG}" but no menu access: ${JSON.stringify(granted)}`,
    ).toBe(true)
  })

  test('the shell renders the module menu entry', async ({ page }) => {
    await page.goto(HOSTAPP_URL, { waitUntil: 'networkidle' })
    // Matched on the link target rather than its label: the sidebar hides entry text when
    // collapsed, and the display name is deployer-configurable, but the route is the contract.
    const entry = page.locator(`nav a[href*="/${SLUG}"]`).first()
    await expect(
      entry,
      `the shell rendered no menu link to "/${SLUG}" — the symptom a user reports as ` +
        `"the module is gone". If the token claims above passed, the permissions arrived and the ` +
        `problem is in the shell's menu rendering rather than in authorization.`,
    ).toBeAttached({ timeout: 15_000 })
  })
})
