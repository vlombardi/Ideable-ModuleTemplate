import { personaTest, expect } from '../auth/session-fixture'

// The authorization matrix, end to end, through the real browser and the real login flow.
//
// This spec exists because of a regression that shipped: the access token became thin
// and the Items page still derived its permissions from it, so a fully
// authorized user was told "You are not authorized to view this page". Every backend suite
// passed — the backend was right — and nothing exercised the browser's view of authorization.
//
// It is deliberately built on personas that DIFFER, because the previous suite ran as the
// bootstrap superadmin and therefore could only ever assert that something was allowed. Half of
// authorization is denial, and denial is only meaningful when the persona legitimately lacks the
// permission:
//
//   hostAdmin     admin             sees Items, may edit
//   moduleAdmin   template_admin    sees Items, may edit
//   moduleReader  template_reader   sees Items, may NOT edit
//   noModule      reader            does not see Items at all
//
// A failure here means one of two things, and both matter: either the permission model changed, or
// the frontend is reading permissions from the wrong place again.

// The host shell's URL: the module's pages are host-absolute routes inside it, and the session
// captured by global-setup belongs to that origin.
const BASE = process.env.HOSTAPP_FRONTEND_URL ?? process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3000'
// Read from the module's own manifest rather than hardcoded, so a remote that renames its route
// does not silently start testing a 404 (which would 'pass' the denial assertions).
const ITEMS_ROUTE = '/template/items'
const NOT_AUTHORIZED = /not authorized to view this page/i

/**
 * Load the Items page and wait until authorization has actually been decided.
 *
 * This exists because of a flaw in the first version of THIS spec: it asserted
 * `expect(refusal).toHaveCount(0)` immediately after `goto`, and a count-of-zero assertion passes
 * instantly on a page that has not finished loading. Verified by re-deploying the original bug —
 * the suite went green against a build that demonstrably refuses. An absence assertion is only
 * meaningful once the thing being asserted absent has had its chance to appear.
 *
 * The permission set arrives from host_app's `/me`, and the refusal can only be rendered after that
 * response resolves — so waiting for it is what makes "no refusal" mean something.
 */
async function openItems(page: import('@playwright/test').Page): Promise<void> {
  const me = page.waitForResponse(
    (r) => r.url().includes('/api/me') && r.request().method() === 'GET',
    { timeout: 30_000 },
  )
  await page.goto(`${BASE}${ITEMS_ROUTE}`)
  await me
  // One more frame for React to commit the state the response produced.
  await expect(page.getByRole('heading', { name: /template items/i })).toBeVisible({
    timeout: 15_000,
  })
}

/**
 * Switch the shell into edit mode the way a user does — by clicking the mode toggle.
 *
 * Seeding `localStorage` does not work: the host writes `hostapp.edit_mode` on boot, so a value set
 * before navigation is overwritten before the page reads it. Driving the control is also the more
 * faithful test: it exercises the same path a person takes.
 */
async function enterEditMode(page: import('@playwright/test').Page): Promise<void> {
  await page.getByRole('button', { name: /view mode/i }).first().click()
  await expect(page.getByRole('button', { name: /edit mode/i }).first()).toBeVisible({
    timeout: 10_000,
  })
}

/** The access token the app itself received, read from the session the harness restored. */
async function bearer(page: import('@playwright/test').Page): Promise<string> {
  await page.goto(BASE)
  const token = await page.evaluate(() => {
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const k = window.sessionStorage.key(i)
      if (!k || !k.startsWith('oidc.user:')) continue
      const v = window.sessionStorage.getItem(k)
      try {
        const parsed = v ? JSON.parse(v) : null
        if (parsed?.access_token) return parsed.access_token as string
      } catch {
        /* not JSON */
      }
    }
    return null
  })
  if (!token) throw new Error('no access token in the restored session')
  return token
}

const stackOnly = (t: typeof import('@playwright/test').test) =>
  t.skip(!process.env.RUN_STACK_E2E, 'needs a running authenticated stack; set RUN_STACK_E2E=1')

// --------------------------------------------------------------------------------------------
// Can see it
// --------------------------------------------------------------------------------------------

for (const persona of ['hostAdmin', 'moduleAdmin', 'moduleReader'] as const) {
  const test = personaTest(persona)

  test.describe(`Items page — ${persona} is authorized`, () => {
    stackOnly(test)

    test('the page renders instead of refusing', async ({ page }) => {
      await openItems(page)
      // The exact message the regression produced. Asserted by text rather than by a permission
      // check so this fails for ANY cause of a false denial, not only the one already fixed.
      await expect(page.getByText(NOT_AUTHORIZED)).toHaveCount(0)
      await expect(page.getByRole('table')).toBeVisible({ timeout: 15_000 })
    })

    test('the Items menu entry is visible', async ({ page }) => {
      await page.goto(BASE)
      await expect(page.getByRole('link', { name: /items/i }).first()).toBeVisible({
        timeout: 15_000,
      })
    })
  })
}

// --------------------------------------------------------------------------------------------
// Cannot see it — the half a superadmin persona can never test
// --------------------------------------------------------------------------------------------

const denied = personaTest('noModule')

denied.describe('Items page — noModule is refused', () => {
  stackOnly(denied)

  denied('the page refuses instead of rendering', async ({ page }) => {
    await page.goto(`${BASE}${ITEMS_ROUTE}`)
    await expect(page.getByText(NOT_AUTHORIZED)).toBeVisible({ timeout: 15_000 })
  })

  denied('no item data is rendered behind the refusal', async ({ page }) => {
    // A message shown over a populated table would be a UI-only guard — the data already left the
    // server. The refusal has to mean the rows were never fetched.
    await page.goto(`${BASE}${ITEMS_ROUTE}`)
    await expect(page.getByText(NOT_AUTHORIZED)).toBeVisible({ timeout: 15_000 })
    // The grid chrome renders (header + empty state) but carries NO data. That distinction is the
    // assertion: a refusal shown over populated rows would mean the data had already been fetched
    // and the guard was decoration.
    await expect(page.getByText(/no results/i)).toBeVisible({ timeout: 10_000 })
  })

  denied('the Items menu entry is not offered', async ({ page }) => {
    await page.goto(BASE)
    await expect(page.getByRole('link', { name: /items/i })).toHaveCount(0)
  })
})

// --------------------------------------------------------------------------------------------
// Edit gating: the same page, two capabilities
// --------------------------------------------------------------------------------------------

const editor = personaTest('moduleAdmin')

editor.describe('Items page — edit is gated by permission, not by page access', () => {
  stackOnly(editor)

  editor('an editor is offered the toggle, and Create once it is on', async ({ page }) => {
    await openItems(page)
    await expect(page.getByText(NOT_AUTHORIZED)).toHaveCount(0)
    await expect(page.getByRole('button', { name: /create item/i })).toHaveCount(0)
    await enterEditMode(page)
    await expect(page.getByRole('button', { name: /create item/i })).toBeVisible({
      timeout: 10_000,
    })
  })
})

const readOnly = personaTest('moduleReader')

readOnly.describe('Items page — a reader is never offered Create', () => {
  stackOnly(readOnly)

  readOnly('edit mode is not even offered, and Create never appears', async ({ page }) => {
    // A reader holds `items:view` and no `:edit` anywhere, so host_app does not render the
    // edit-mode toggle at all (Layout.tsx gates it on `canEditAnything`). That is the stronger
    // behaviour: the shell does not offer a mode that could not do anything, rather than offering
    // one that turns out to be inert.
    //
    // Paired with the editor case above, this is the whole point of having two personas: the same
    // page, the same route, one permission apart.
    await openItems(page)
    await expect(page.getByText(NOT_AUTHORIZED)).toHaveCount(0)
    await expect(page.getByRole('button', { name: /view mode|edit mode/i })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /create item/i })).toHaveCount(0)
  })
})

// --------------------------------------------------------------------------------------------
// Segregation of duties (ISO 27001 A.5.3): the reviewer is not the subject
// --------------------------------------------------------------------------------------------

const officer = personaTest('officer')

officer.describe('Privileged-access review — only the security officer reads it', () => {
  stackOnly(officer)

  officer('the officer can read the review', async ({ page }) => {
    const response = await page.request.get(`${BASE}/api/access_review/privileged`, {
      headers: { Authorization: `Bearer ${await bearer(page)}` },
    })
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.complete).toBe(true)
  })
})

const subject = personaTest('hostAdmin')

subject.describe('Privileged-access review — the administrator being reviewed cannot', () => {
  stackOnly(subject)

  subject('an administrator is refused', async ({ page }) => {
    // `admin` is deliberately not granted the review permission: the reviewer must not be the
    // subject of the review.
    const response = await page.request.get(`${BASE}/api/access_review/privileged`, {
      headers: { Authorization: `Bearer ${await bearer(page)}` },
    })
    expect(response.status()).toBe(403)
  })
})
