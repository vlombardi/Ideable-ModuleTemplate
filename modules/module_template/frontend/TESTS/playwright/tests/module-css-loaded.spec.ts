import { test, expect } from '../auth/session-fixture'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Verifies the CSS loading contract end-to-end: when host_app mounts a remote module, the
// module's compiled stylesheet is actually loaded — via the moduleManifest side-effect import
// (§1, MF runtime injects assets.css) and/or host_app's defensive injector (§2.2). Without
// it the module renders unstyled inside host_app. Generic + force-synced (uses MODULE_SLUG).

const here = path.dirname(fileURLToPath(import.meta.url))
// tests → playwright → TESTS → frontend, then SOURCES/src/moduleManifest.ts
const MANIFEST = path.join(here, '..', '..', '..', 'SOURCES', 'src', 'moduleManifest.ts')

const HOSTAPP_URL = process.env.HOSTAPP_FRONTEND_URL ?? 'http://localhost:3000'
const SLUG = process.env.MODULE_SLUG ?? 'template'

// Derive the module's first page route from its OWN moduleManifest (menu hrefs are
// host-absolute routes) instead of hardcoding an entity path — so the SAME spec works for
// module_template (Items) and any remote (SRA: companies, assets, …) with zero per-module edits.
function firstModuleRoute(): string {
  const src = fs.readFileSync(MANIFEST, 'utf8')
  const hrefs = [...src.matchAll(/href:\s*['"]([^'"]+)['"]/g)].map((m) => m[1])
  return hrefs[0] ?? `/${SLUG}`
}

test.describe('remote module CSS loads inside host_app', () => {
  // Opt-in: needs a running authenticated host_app + module stack (seeded session). Without
  // RUN_STACK_E2E the default (stack-free) phase skips it. See testing-guidelines.md § UI tests.
  test.skip(
    !process.env.RUN_STACK_E2E,
    'requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  test('the mounted module ships its compiled stylesheet', async ({ page }) => {
    await page.goto(`${HOSTAPP_URL}${firstModuleRoute()}`, { waitUntil: 'networkidle' })

    // The module actually mounted (not the login / no-active-profile gate).
    await expect(page).not.toHaveURL(/\/no-active-role|\/if\/flow\//)
    await expect(page.getByRole('table').or(page.getByRole('heading')).first()).toBeVisible()

    // A stylesheet served from the module's remote (/remotes/<slug>/…css) must be present —
    // injected by the MF runtime (§1) or host_app's loader (§2.2). Poll: injection may occur
    // shortly after mount.
    const moduleCss = page.locator(`link[rel="stylesheet"][href*="/remotes/${SLUG}/"]`)
    await expect
      .poll(() => moduleCss.count(), {
        message: `no /remotes/${SLUG}/ stylesheet loaded — module would render unstyled in host_app`,
        timeout: 10_000,
      })
      .toBeGreaterThan(0)
  })
})
