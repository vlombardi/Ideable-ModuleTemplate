import { test, expect } from '../auth/session-fixture'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Generic, force-syncable authenticated E2E: discovers the module's entity pages from
// its OWN moduleManifest.ts (every menu `href` is a host-absolute route) and verifies
// each loads for a logged-in persona — not the login redirect, not the "No Active
// Profile" gate — and renders real content (a data table or a heading). Because it
// derives everything from the module under test, the SAME spec works for module_template
// (Items) and any remote (SRA: companies, assets, …) with zero per-module edits.
//
// Opt-in via RUN_STACK_E2E=1 (+ stack URL + persona creds). See testing-guidelines.md.

const here = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.env.HOSTAPP_FRONTEND_URL ?? process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3001'
// tests → playwright → TESTS → frontend, then SOURCES/src/moduleManifest.ts
const MANIFEST = path.join(here, '..', '..', '..', 'SOURCES', 'src', 'moduleManifest.ts')

function entityRoutes(): string[] {
  const src = fs.readFileSync(MANIFEST, 'utf8')
  // Menu hrefs are host-absolute routes to the module's pages (flat or nested groups).
  const hrefs = [...src.matchAll(/href:\s*['"]([^'"]+)['"]/g)].map((m) => m[1])
  return Array.from(new Set(hrefs))
}

const ROUTES = entityRoutes()

test.describe('Module entity pages load authenticated (live stack)', () => {
  test.skip(
    !process.env.RUN_STACK_E2E,
    'Requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  test('manifest declares at least one entity page', () => {
    expect(ROUTES.length, 'moduleManifest.ts must declare menu hrefs').toBeGreaterThan(0)
  })

  for (const route of ROUTES) {
    test(`page ${route} renders authenticated`, async ({ page }) => {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' })

      // Not bounced to the login flow or the missing-profile gate.
      expect(page.url(), 'should not redirect to the no-active-profile gate').not.toContain(
        '/no-active-role',
      )
      expect(page.url(), 'should not redirect to the Authentik login flow').not.toContain(
        '/if/flow/',
      )

      // Rendered real content: a data table (entity list pages) or at least a heading
      // (wizard/dashboard pages). Either proves the authenticated route mounted.
      await expect(
        page.getByRole('table').or(page.getByRole('heading')).first(),
      ).toBeVisible({ timeout: 20_000 })
    })
  }
})
