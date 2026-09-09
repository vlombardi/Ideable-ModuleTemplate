import { test, expect } from '../auth/session-fixture'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PERSONA } from '../auth/personas'

// The "My access" page must show EXACTLY what `/api/me` returns — not a copy of it that drifts.
//
// The page exists because the token no longer carries authorization data, so a user can no longer
// answer "what am I allowed to do" by decoding the JWT in session storage, and `/api/me` cannot be
// opened in the address bar because it needs a Bearer token. This page is the replacement, and its
// JSON block is described to the user as the endpoint's response, verbatim.
//
// It was not. The block listed five fields chosen by hand, so when `tenant_ids` was added to the
// endpoint the page kept rendering, kept looking complete, and silently omitted one of the two
// halves of the authorization decision — the half that produces `403 No tenant scope`, which is
// exactly the failure a user opens this page to understand.
//
// A static test can assert the page serialises `me` rather than a literal. Only this one can assert
// that what the browser actually renders equals what the API actually returns, which is the claim
// the page makes to the person reading it.
//
// Opt-in via RUN_STACK_E2E=1, like the other stack E2E specs.

const here = path.dirname(fileURLToPath(import.meta.url))
const HOSTAPP_URL = process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3000'
const shouldRun = process.env.RUN_STACK_E2E === '1'

/** The access_token the app itself received, from the captured session. */
function accessToken(): string {
  const file = path.join(here, '..', 'auth', '.auth', `${DEFAULT_PERSONA}.json`)
  const captured = JSON.parse(fs.readFileSync(file, 'utf8'))
  return JSON.parse(captured.session.value).access_token as string
}

async function apiMe(page: import('@playwright/test').Page): Promise<Record<string, unknown>> {
  const response = await page.request.get(`${HOSTAPP_URL}/api/me`, {
    headers: { Authorization: `Bearer ${accessToken()}` },
  })
  expect(response.status(), `GET /api/me: ${response.status()}`).toBe(200)
  return (await response.json()) as Record<string, unknown>
}

async function renderedJson(page: import('@playwright/test').Page): Promise<Record<string, unknown>> {
  await page.goto(`${HOSTAPP_URL}/my-access`, { waitUntil: 'networkidle' })
  const block = page.locator('pre').first()
  await expect(
    block,
    'the My access page rendered no JSON block. It is the only way a user can see their own ' +
      'authorization now that the token carries none of it.',
  ).toBeAttached({ timeout: 15_000 })
  return JSON.parse((await block.innerText()).trim()) as Record<string, unknown>
}

test.describe('the My access page shows what /api/me returns', () => {
  test.skip(!shouldRun, 'stack E2E is opt-in: set RUN_STACK_E2E=1')

  test('the rendered JSON is the /api/me response', async ({ page }) => {
    const fromApi = await apiMe(page)
    const fromPage = await renderedJson(page)

    // Compared as parsed objects, so key order and indentation do not matter — only the DATA, which
    // is what the page promises the reader.
    expect(
      fromPage,
      'the page shows something other than the /api/me response. It tells the reader this JSON is ' +
        'that response verbatim, so any difference is the page lying to the person trying to ' +
        'understand why they were denied.',
    ).toEqual(fromApi)
  })

  test('every field the endpoint returns reaches the page', async ({ page }) => {
    // Stated separately from the equality above because it is the failure that actually happened,
    // and it is the one worth naming in the report: a field present in the API and absent from the
    // page. Equality catches it too, but says "objects differ" rather than "tenant_ids is missing".
    const fromApi = await apiMe(page)
    const fromPage = await renderedJson(page)

    const missing = Object.keys(fromApi).filter((key) => !(key in fromPage))
    expect(
      missing,
      `/api/me returns ${JSON.stringify(missing)} and the page does not show it. A page whose ` +
        `stated purpose is "everything the application uses to decide what you may do" must not ` +
        `curate that list by hand — serialise the payload.`,
    ).toEqual([])
  })

  test('the tenant scope is visible as a card, not only inside the JSON', async ({ page }) => {
    const tenantIds = ((await apiMe(page)).tenant_ids ?? []) as string[]
    test.skip(tenantIds.length === 0, 'the persona holds no tenant, so there is no tag to find')

    await page.goto(`${HOSTAPP_URL}/my-access`, { waitUntil: 'networkidle' })
    // Searched OUTSIDE the JSON block: the raw payload is already asserted above, and finding the
    // tag there would pass even if no card were rendered at all.
    const wholePage = await page.locator('body').innerText()
    const rawBlock = await page.locator('pre').first().innerText()
    const cardsOnly = wholePage.split(rawBlock).join(' ')

    for (const tag of tenantIds) {
      const id = /[(]([0-9]+)[)]$/.exec(tag)?.[1] ?? tag
      expect(
        cardsOnly.includes(tag) || cardsOnly.includes(id),
        `the tenant ${tag} appears only in the raw JSON. Permissions say what may be done and ` +
          `tenants say to whose data; a reader scanning the cards sees half the answer.`,
      ).toBe(true)
    }
  })
})
