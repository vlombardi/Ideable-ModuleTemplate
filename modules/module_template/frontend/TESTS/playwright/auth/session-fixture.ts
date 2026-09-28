import { test as base, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PERSONA } from './personas'

const here = path.dirname(fileURLToPath(import.meta.url))
const AUTH_DIR = path.join(here, '.auth')

// Builds a `test` bound to a login persona (default: 'standard'). It reuses the
// session captured once by global-setup: the browser context is created from the
// persona's storageState (cookies + localStorage) AND the oidc-client-ts User blob is
// re-seeded into sessionStorage (which storageState can't carry) via an init script —
// so the app is authenticated as that real, profile-bearing user with no per-test login.
//
// Authenticated specs do: `const test = personaTest('standard')` (or another persona).
export function personaTest(personaName: string = DEFAULT_PERSONA) {
  return base.extend({
    context: async ({ browser }, use) => {
      const file = path.join(AUTH_DIR, `${personaName}.json`)
      let captured: { storageState?: unknown; session?: { key: string; value: string } | null } = {}
      try {
        captured = JSON.parse(fs.readFileSync(file, 'utf8'))
      } catch {
        // No captured session (e.g. a stack-free run where global-setup didn't log in).
        // Such specs are gated to skip via RUN_STACK_E2E, so a plain context is fine.
      }
      const context = await browser.newContext({
        storageState: (captured.storageState as any) ?? undefined,
        ignoreHTTPSErrors: true,
      })
      if (captured.session) {
        await context.addInitScript((s: { key: string; value: string }) => {
          try {
            window.sessionStorage.setItem(s.key, s.value)
          } catch {
            /* sessionStorage unavailable */
          }
        }, captured.session)
      }
      await use(context)
      await context.close()
    },
  })
}

export const test = personaTest(DEFAULT_PERSONA)
export { expect }
