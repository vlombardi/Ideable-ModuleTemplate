import type { Browser } from '@playwright/test'
import { PERSONAS, hasCreds } from './personas'

// A captured authenticated session: Playwright storageState (cookies + localStorage)
// plus the oidc-client-ts User blob, which lives in sessionStorage (storageState does
// NOT persist sessionStorage) and is what react-oidc-context + the module remote read.
export interface CapturedSession {
  storageState: unknown
  session: { key: string; value: string } | null
}

// Capture WHATEVER oidc.user:* entry the app persisted. The key derives from the
// *frontend's build-time* OIDC authority/client, which can differ from this test env
// (e.g. a module's repo env says `sra` but the deployed host_app shell uses `ideable`).
// Scanning — like the remote's own getCurrentAccessToken — makes the harness robust to
// that, instead of requiring an env-derived key to match.
const FIND_OIDC_USER = () => {
  for (let i = 0; i < window.sessionStorage.length; i += 1) {
    const k = window.sessionStorage.key(i)
    if (!k || !k.startsWith('oidc.user:')) continue
    const v = window.sessionStorage.getItem(k)
    try {
      if (v && JSON.parse(v).access_token) return { key: k, value: v }
    } catch {
      /* not JSON */
    }
  }
  return null
}

async function submit(page: import('@playwright/test').Page): Promise<void> {
  // Authentik renders every stage's controls in the DOM at once, so click the *visible*
  // primary button (Enter does not submit the password stage). Fall back to a visible
  // submit button, then Enter.
  const primary = page
    .locator('button:visible', { hasText: /continue|log ?in|sign ?in|next/i })
    .first()
  if (await primary.count()) {
    await primary.click()
    return
  }
  const submitBtn = page.locator("button[type='submit']:visible").first()
  if (await submitBtn.count()) {
    await submitBtn.click()
    return
  }
  await page.keyboard.press('Enter')
}

/**
 * Log in as a persona by driving the real Authentik login flow, and capture the
 * authenticated session. The host_app frontend auto-redirects to Authentik on load
 * (auth.signinRedirect), so we just navigate and complete the identification +
 * password stages.
 */
export async function loginAndCapture(
  browser: Browser,
  baseURL: string,
  personaName: string,
): Promise<CapturedSession> {
  const persona = PERSONAS[personaName]
  if (!hasCreds(persona)) {
    throw new Error(`[auth] persona '${personaName}' is missing username/password`)
  }
  const context = await browser.newContext({ ignoreHTTPSErrors: true })
  const page = await context.newPage()
  try {
    await page.goto(`${baseURL}/`, { waitUntil: 'domcontentloaded' })

    // Identification stage (Authentik `uidField`). Authentik renders every stage's
    // inputs in the DOM at once, so we must target the *visible* field of each stage —
    // otherwise `input[type=password]` matches a hidden pre-stage input. If no visible
    // identifier appears, we may already be authenticated → skip to capture.
    const uid = page
      .locator("input#ak-identifier-input, input[name='uidField']:visible")
      .first()
    const onLoginForm = await uid
      .waitFor({ state: 'visible', timeout: 20_000 })
      .then(() => true)
      .catch(() => false)
    if (onLoginForm) {
      await uid.fill(persona.username)
      await submit(page)
      // Wait for the password *stage* input by its Authentik id — NOT a broader
      // `input[type=password]` match, which would resolve to a hidden pre-stage input
      // still in the DOM and never advance the flow.
      const pw = page.locator('input#ak-stage-password-input').first()
      await pw.waitFor({ state: 'visible', timeout: 15_000 })
      await pw.fill(persona.password)
      await submit(page)
      // Leave the Authentik flow (redirect chain: flow → /authorize → /auth/callback → app).
      await page.waitForURL((u) => !u.toString().includes('/if/flow/'), { timeout: 30_000 }).catch(() => {})
    }

    // Wait for react-oidc to persist SOME oidc.user:* token, then capture it verbatim.
    await page.waitForFunction(FIND_OIDC_USER, undefined, { timeout: 30_000 }).catch(() => {})
    const session = await page.evaluate(FIND_OIDC_USER)
    if (process.env.E2E_DEBUG) {
      const keys = await page.evaluate(() => Object.keys(window.sessionStorage))
      console.error(`[login-debug] onLoginForm=${onLoginForm} url=${page.url()}`)
      console.error(`[login-debug] sessionStorage keys=${JSON.stringify(keys)} captured=${!!session}`)
    }
    const storageState = await context.storageState()
    return { storageState, session }
  } finally {
    await context.close()
  }
}
