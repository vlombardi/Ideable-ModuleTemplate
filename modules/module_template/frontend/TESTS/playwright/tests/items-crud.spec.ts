import { test, expect } from '../auth/session-fixture'
import { request as pwRequest, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Full-CRUD, data-driven E2E for the module_template Items entity, against a live
// authenticated stack (persona `standard` = sadmin). Data is CREATED through the
// backend API (which also exercises the create endpoint + auth), then Read / Update /
// Delete are verified THROUGH THE UI, asserting the table reflects the real data —
// not just "a table exists". Opt-in via RUN_STACK_E2E.
//
// This spec is the reference template every CRUD entity should copy (see
// rules/testing-guidelines.md § "CRUD E2E tests per entity").

const here = path.dirname(fileURLToPath(import.meta.url))
const TEMPLATE_URL = process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3001'
const SLUG = process.env.MODULE_SLUG ?? 'template'
const API_ITEMS = `${TEMPLATE_URL}/module/${SLUG}/api/items`

// Unique per-run marker so the suite is deterministic + repeatable regardless of
// whatever data already lives in the DB, and so cleanup can find exactly its rows.
const RUN = `E2E-${Date.now().toString(36)}`
const ITEM_A = `${RUN} Alpha`
const ITEM_A_EDITED = `${RUN} Alpha (edited)`
const ITEM_B = `${RUN} Beta`
const ITEM_UI = `${RUN} UiCreated`

/** The Bearer token the app itself uses — the access_token from the captured session. */
function bearerFromSession(): string {
  const file = path.join(here, '..', 'auth', '.auth', 'standard.json')
  const captured = JSON.parse(fs.readFileSync(file, 'utf8'))
  return JSON.parse(captured.session.value).access_token as string
}

async function gotoItems(page: Page, opts: { editMode?: boolean } = {}): Promise<void> {
  await page.goto(`${TEMPLATE_URL}/${SLUG}/items`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('table')).toBeVisible()
  if (opts.editMode) {
    // Create/Edit/Delete controls only render in edit mode (+ items:edit). host_app owns
    // the mode and defaults to view, so flip it at runtime the way the shell does:
    // set the flag AND fire the event TemplateItems listens for.
    await page.evaluate(() => {
      window.localStorage.setItem('hostapp.edit_mode', 'true')
      window.dispatchEvent(
        new CustomEvent('hostapp:edit-mode-changed', { detail: { isEditMode: true } }),
      )
    })
    await expect(page.getByRole('button', { name: 'Create Item' })).toBeVisible({ timeout: 10_000 })
  }
}

/** Type into the Name column filter and wait for the debounced (500ms) server round-trip. */
async function filterByName(page: Page, value: string): Promise<void> {
  const nameFilter = page.getByPlaceholder('Filter...').nth(1) // columns: id, name, description
  await nameFilter.fill('')
  await nameFilter.fill(value)
  await page.waitForTimeout(900)
}

test.describe.serial('module_template Items — CRUD (authenticated, live stack)', () => {
  test.skip(
    !process.env.RUN_STACK_E2E,
    'CRUD E2E requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  let api: APIRequestContext

  test.beforeAll(async () => {
    api = await pwRequest.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Authorization: `Bearer ${bearerFromSession()}` },
    })
  })

  test.afterAll(async () => {
    // Repeatable: delete everything this run created (match by the unique RUN marker).
    const res = await api.get(API_ITEMS, { params: { limit: '500' } })
    if (res.ok()) {
      const body = await res.json()
      for (const it of body.items ?? []) {
        if (typeof it.name === 'string' && it.name.startsWith(RUN)) {
          await api.delete(`${API_ITEMS}/${it.id}`).catch(() => undefined)
        }
      }
    }
    await api.dispose()
  })

  test('CREATE (API): POST /items returns 201 with the created item', async () => {
    for (const name of [ITEM_A, ITEM_B]) {
      const res = await api.post(API_ITEMS, { data: { name, description: 'created by e2e' } })
      const body = await res.json().catch(() => ({}))
      expect(res.status(), JSON.stringify(body)).toBe(201)
      expect(body).toMatchObject({ name })
      expect(typeof body.id).toBe('number')
    }
  })

  test('READ: the API-created items are displayed in the UI table', async ({ page }) => {
    await gotoItems(page)
    await filterByName(page, ITEM_A)
    await expect(page.getByRole('cell', { name: ITEM_A, exact: true })).toBeVisible()
  })

  test('FILTER: the Name filter narrows the table to the matching row', async ({ page }) => {
    await gotoItems(page)
    await filterByName(page, ITEM_B)
    const rows = page.locator('table tbody tr')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(ITEM_B)
  })

  test('CREATE (UI): the create form adds a new row shown in the table', async ({ page }) => {
    await gotoItems(page, { editMode: true })
    await page.getByRole('button', { name: 'Create Item' }).click()
    const form = page.locator('form')
    await form.locator('input[type="text"]').first().fill(ITEM_UI)
    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await filterByName(page, ITEM_UI)
    await expect(page.getByRole('cell', { name: ITEM_UI, exact: true })).toBeVisible()
  })

  test('UPDATE (UI): editing a row updates its value in the table', async ({ page }) => {
    await gotoItems(page, { editMode: true })
    await filterByName(page, ITEM_A)
    const row = page.locator('table tbody tr', { hasText: ITEM_A }).first()
    // Action buttons are SVG-only: history (0), pencil/edit (1), trash/delete (2).
    await row.locator('td').last().locator('button').nth(1).click()
    const form = page.locator('form')
    await form.locator('input[type="text"]').first().fill(ITEM_A_EDITED)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await filterByName(page, ITEM_A_EDITED)
    await expect(page.getByRole('cell', { name: ITEM_A_EDITED, exact: true })).toBeVisible()
  })

  test('DELETE (UI): deleting a row removes it from the table', async ({ page }) => {
    await gotoItems(page, { editMode: true })
    await filterByName(page, ITEM_B)
    const row = page.locator('table tbody tr', { hasText: ITEM_B }).first()
    page.on('dialog', (d) => d.accept()) // native confirm()
    await row.locator('td').last().locator('button').last().click() // trash = last action
    await filterByName(page, ITEM_B)
    await expect(page.locator('table tbody tr', { hasText: ITEM_B })).toHaveCount(0)
  })
})
