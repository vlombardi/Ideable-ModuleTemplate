import { chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loginAndCapture } from './login'
import { PERSONAS, hasCreds } from './personas'

const here = path.dirname(fileURLToPath(import.meta.url))
export const AUTH_DIR = path.join(here, '.auth')

// Playwright globalSetup. Only runs when RUN_STACK_E2E=1 (the opt-in for the
// live-stack authenticated suite). For each configured persona with credentials, it
// drives the real Authentik login once and saves the captured session to
// auth/.auth/<persona>.json for session-fixture to reuse. The default stack-free run
// (Widget Gallery) does no login.
export default async function globalSetup(): Promise<void> {
  if (!process.env.RUN_STACK_E2E) {
    console.log('[auth] RUN_STACK_E2E not set — skipping login; running stack-free suites only.')
    return
  }
  const baseURL = process.env.HOSTAPP_FRONTEND_URL ?? process.env.TEMPLATE_FRONTEND_URL
  if (!baseURL) {
    throw new Error('[auth] RUN_STACK_E2E=1 requires HOSTAPP_FRONTEND_URL / TEMPLATE_FRONTEND_URL')
  }
  fs.mkdirSync(AUTH_DIR, { recursive: true })

  const browser = await chromium.launch()
  try {
    let loggedIn = 0
    for (const [name, persona] of Object.entries(PERSONAS)) {
      if (!hasCreds(persona)) {
        console.log(`[auth] persona '${name}': no credentials configured — skipping`)
        continue
      }
      const captured = await loginAndCapture(browser, baseURL, name)
      if (!captured.session) {
        throw new Error(
          `[auth] persona '${name}' (${persona.username}): login did not yield a session token. ` +
            'Check the credentials and the Authentik login flow.',
        )
      }
      fs.writeFileSync(path.join(AUTH_DIR, `${name}.json`), JSON.stringify(captured))
      console.log(`[auth] logged in persona '${name}' as '${persona.username}'`)
      loggedIn += 1
    }
    if (loggedIn === 0) {
      throw new Error('[auth] RUN_STACK_E2E=1 but no persona had credentials (set E2E_STANDARD_* / SADMIN_*).')
    }
  } finally {
    await browser.close()
  }
}
