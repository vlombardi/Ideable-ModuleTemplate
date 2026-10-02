import { test, expect } from '../auth/session-fixture'
import { request as pwRequest, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PERSONA } from '../auth/personas'
import { parseEntityGraph } from '../lib/entity-graph'
import { newRunMarker, ownedBy } from '../lib/run-marker'

// Full-CRUD, data-driven E2E for module_template's `sub_items` entity — the standard page it
// got per `shared-ui-widgets-specs.md` § *Main entities definition* (an association entity gets
// its own page IN ADDITION TO appearing inside `items`'s association view; this suite exercises
// the standalone page, not that association view). Copied from the reference
// `items-crud.spec.ts`; see `rules/testing-guidelines.md` § "CRUD E2E tests".
//
// FK-ordering (rules/testing-guidelines.md § "Foreign-key ordering"): `sub_items` has one
// in-scope parent, `template_items` (`item_fk`). The parent row is created FIRST (leaf-first
// create) and deleted LAST (root-first delete), after every `sub_items` row this run created —
// derived from the module's own `database/SPECS/schema.sql` via `parseEntityGraph`, never
// hand-typed, so the order stays correct if the graph grows a new in-between entity.

const here = path.dirname(fileURLToPath(import.meta.url))
const TEMPLATE_URL =
  process.env.HOSTAPP_FRONTEND_URL ?? process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3001'
const SLUG = process.env.MODULE_SLUG ?? 'template'
const API_ITEMS = `${TEMPLATE_URL}/module/${SLUG}/api/items`
const API_SUB_ITEMS = `${TEMPLATE_URL}/module/${SLUG}/api/sub_items`

const RUN = newRunMarker()

// Page size afterAll walks the table in — must not exceed the API's MAX_PAGE_SIZE (200), or the
// listing is rejected with 422 and cleanup deletes nothing. See items-crud.spec.ts's afterAll.
const CLEANUP_PAGE_SIZE = 100
const PARENT_ITEM_NAME = `${RUN} SubItemsParent`
const SUB_A = `${RUN} Alpha`
const SUB_A_DESCRIPTION = `${RUN} description for Alpha`
const SUB_A_EDITED = `${RUN} Alpha (edited)`
const SUB_B = `${RUN} Beta`
const SUB_UI = `${RUN} UiCreated`

function bearerFromSession(): string {
  const file = path.join(here, '..', 'auth', '.auth', `${DEFAULT_PERSONA}.json`)
  const captured = JSON.parse(fs.readFileSync(file, 'utf8'))
  return JSON.parse(captured.session.value).access_token as string
}

/** The FK-aware create/delete order for this suite's two entities, from the module's own schema
 *  — never hand-typed. */
function fkOrder(): { createOrder: string[]; deleteOrder: string[] } {
  const schemaPath = path.join(here, '..', '..', '..', '..', 'database', 'SPECS', 'schema.sql')
  const graph = parseEntityGraph(fs.readFileSync(schemaPath, 'utf8'))
  const createOrder = graph.createOrder.filter((e) => e === 'template_items' || e === 'sub_items')
  return { createOrder, deleteOrder: [...createOrder].reverse() }
}

async function gotoSubItems(page: Page, opts: { editMode?: boolean } = {}): Promise<void> {
  await page.goto(`${TEMPLATE_URL}/${SLUG}/sub_items`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('table')).toBeVisible()
  if (opts.editMode) {
    await page.evaluate(() => {
      window.localStorage.setItem('hostapp.edit_mode', 'true')
      window.dispatchEvent(
        new CustomEvent('hostapp:edit-mode-changed', { detail: { isEditMode: true } }),
      )
    })
    await expect(page.getByRole('button', { name: 'Create Sub-Item' })).toBeVisible({ timeout: 10_000 })
  }
}

/** Type into the Name column filter (columns: id, name, description, item_name) and wait for the
 *  debounced (500ms) server round-trip. */
async function filterByName(page: Page, value: string): Promise<void> {
  const nameFilter = page.getByPlaceholder('Filter...').nth(1)
  await nameFilter.fill('')
  await nameFilter.fill(value)
  await page.waitForTimeout(900)
}

/** Type into the Description column filter (columns: id, name, description, item_name) and wait
 *  for the debounced round-trip — proves `description` is actually filterable server-side
 *  (`SubItem.__filterable__` + its trigram index), not just present as a column. */
async function filterByDescription(page: Page, value: string): Promise<void> {
  const descriptionFilter = page.getByPlaceholder('Filter...').nth(2)
  await descriptionFilter.fill('')
  await descriptionFilter.fill(value)
  await page.waitForTimeout(900)
}

/** Click the edit form's Save button and confirm it actually submitted (the form closes) before
 *  moving on — retrying the click itself if it doesn't. See `sub-item-notes-crud.spec.ts`'s own
 *  copy of this helper for why: this exact click has been observed to occasionally not register
 *  under Playwright's automated click, confirmed to be a Playwright-specific artifact (not an app
 *  defect) by manual reproduction of the identical sequence against a live deployment. */
async function clickSaveAndWaitForClose(page: Page): Promise<void> {
  const saveButton = page.getByRole('button', { name: 'Save', exact: true })
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await saveButton.click()
    const closed = await saveButton
      .waitFor({ state: 'detached', timeout: 2_000 })
      .then(() => true)
      .catch(() => false)
    if (closed) return
  }
  throw new Error('Save click never closed the edit form after 5 attempts')
}

test.describe.serial('module_template Sub-Items — CRUD (authenticated, live stack)', () => {
  test.skip(
    !process.env.RUN_STACK_E2E,
    'CRUD E2E requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  test('the module schema orders template_items before sub_items', () => {
    const { createOrder, deleteOrder } = fkOrder()
    expect(createOrder).toEqual(['template_items', 'sub_items'])
    expect(deleteOrder).toEqual(['sub_items', 'template_items'])
  })

  let api: APIRequestContext
  let parentItemId: number

  test.beforeAll(async () => {
    api = await pwRequest.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Authorization: `Bearer ${bearerFromSession()}` },
    })
    // Leaf-first create: the parent `items` row this run's `sub_items` rows FK-reference.
    const res = await api.post(API_ITEMS, {
      data: { name: PARENT_ITEM_NAME, description: 'parent for sub-items e2e' },
    })
    const body = await res.json().catch(() => ({}))
    expect(res.status(), JSON.stringify(body)).toBe(201)
    parentItemId = body.id
  })

  test.afterAll(async () => {
    // Root-first delete would violate the FK, so children go first: every `sub_items` row this
    // run created, THEN the parent `items` row. Same checked-response discipline as
    // items-crud.spec.ts's afterAll (an unchecked cleanup that silently deletes nothing is the
    // one this repo already fixed once).
    try {
      const doomed: number[] = []
      for (let skip = 0; ; skip += CLEANUP_PAGE_SIZE) {
        const res = await api.get(API_SUB_ITEMS, {
          params: { skip: String(skip), limit: String(CLEANUP_PAGE_SIZE) },
        })
        if (!res.ok()) {
          throw new Error(
            `cleanup could not list sub_items: ${res.status()} ${await res.text()} -- rows ` +
              `named ${RUN}* are still in the database`,
          )
        }
        const items: Array<{ id: number; name?: unknown }> = (await res.json()).items ?? []
        for (const it of items) {
          if (ownedBy(RUN, it.name)) doomed.push(it.id)
        }
        if (items.length < CLEANUP_PAGE_SIZE) break
      }

      const leaked: string[] = []
      for (const id of doomed) {
        const del = await api.delete(`${API_SUB_ITEMS}/${id}`)
        if (!del.ok()) leaked.push(`${id} (${del.status()})`)
      }
      if (leaked.length) {
        throw new Error(`cleanup could not delete sub_item(s) ${leaked.join(', ')} named ${RUN}*`)
      }

      if (parentItemId !== undefined) {
        const delParent = await api.delete(`${API_ITEMS}/${parentItemId}`)
        if (!delParent.ok()) {
          throw new Error(
            `cleanup could not delete parent item ${parentItemId} (${delParent.status()})`,
          )
        }
      }
    } finally {
      await api.dispose()
    }
  })

  test('CREATE (API): POST /sub_items returns 201 with the created sub-item', async () => {
    for (const [name, description] of [
      [SUB_A, SUB_A_DESCRIPTION],
      [SUB_B, 'created by e2e'],
    ] as const) {
      const res = await api.post(API_SUB_ITEMS, {
        data: { name, description, item_fk: parentItemId },
      })
      const body = await res.json().catch(() => ({}))
      expect(res.status(), JSON.stringify(body)).toBe(201)
      expect(body).toMatchObject({ name, item_fk: parentItemId })
      expect(typeof body.id).toBe('number')
    }
  })

  test('READ: the API-created sub-items are displayed in the UI table', async ({ page }) => {
    await gotoSubItems(page)
    await filterByName(page, SUB_A)
    await expect(page.getByRole('cell', { name: SUB_A, exact: true })).toBeVisible()
  })

  test('FILTER: the Name filter narrows the table to the matching row', async ({ page }) => {
    await gotoSubItems(page)
    await filterByName(page, SUB_B)
    const rows = page.locator('table tbody tr')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(SUB_B)
  })

  test('FILTER: the Description filter narrows the table to the matching row', async ({ page }) => {
    await gotoSubItems(page)
    await filterByDescription(page, SUB_A_DESCRIPTION)
    const rows = page.locator('table tbody tr')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(SUB_A)
  })

  test('CREATE (UI): the create form adds a new row shown in the table', async ({ page }) => {
    await gotoSubItems(page, { editMode: true })
    await page.getByRole('button', { name: 'Create Sub-Item' }).click()
    const form = page.locator('form')
    await form.locator('input[type="text"]').first().fill(SUB_UI)

    // `item_fk` is picked by name through the Entity Selector modal
    // (`shared-ui-widgets-specs.md` § "Form FK association selection (normative)"), never typed
    // as a raw id: open it, filter the `items` selection table down to the parent this run
    // created, and click its row.
    await form.getByRole('button', { name: 'Select', exact: true }).click()
    const itemModal = page.locator('[data-entity-selector="items"]')
    await expect(itemModal).toBeVisible()
    await itemModal.getByPlaceholder('Filter...').nth(1).fill(PARENT_ITEM_NAME)
    await page.waitForTimeout(900)
    await itemModal.getByRole('cell', { name: PARENT_ITEM_NAME, exact: true }).click()
    await expect(itemModal).toBeHidden()

    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await filterByName(page, SUB_UI)
    await expect(page.getByRole('cell', { name: SUB_UI, exact: true })).toBeVisible()
  })

  test('UPDATE (UI): editing a row updates its value in the table', async ({ page }) => {
    await gotoSubItems(page, { editMode: true })
    await filterByName(page, SUB_A)
    const row = page.locator('table tbody tr', { hasText: SUB_A }).first()
    // Action buttons are SVG-only: history (0), pencil/edit (1), trash/delete (2).
    await row.locator('td').last().locator('button').nth(1).click()
    const form = page.locator('form')
    await form.locator('input[type="text"]').first().fill(SUB_A_EDITED)
    await clickSaveAndWaitForClose(page)
    await filterByName(page, SUB_A_EDITED)
    await expect(page.getByRole('cell', { name: SUB_A_EDITED, exact: true })).toBeVisible()
  })

  test('DELETE (UI): deleting a row removes it from the table', async ({ page }) => {
    await gotoSubItems(page, { editMode: true })
    await filterByName(page, SUB_B)
    const row = page.locator('table tbody tr', { hasText: SUB_B }).first()
    page.on('dialog', (d) => d.accept()) // native confirm()
    await row.locator('td').last().locator('button').last().click() // trash = last action
    await filterByName(page, SUB_B)
    await expect(page.locator('table tbody tr', { hasText: SUB_B })).toHaveCount(0)
  })

  test('a parent with a sub-item still attached refuses deletion (the FK, not just test ordering)', async () => {
    const subRes = await api.post(API_SUB_ITEMS, {
      data: { name: `${RUN} StillAttached`, description: 'blocks parent delete', item_fk: parentItemId },
    })
    expect(subRes.status()).toBe(201)
    const subBody = await subRes.json()

    const delRes = await api.delete(`${API_ITEMS}/${parentItemId}`)
    // 409, not merely "not 204": a crash (500) also fails to delete, and must not pass as a refusal.
    expect(delRes.status(), 'an item with a sub_item still pointing at it is refused as a conflict').toBe(409)
    expect((await delRes.json()).detail, 'the refusal names what blocks it').toContain('sub_items')

    // Clean up the extra sub_item so `afterAll` finds the parent item still deletable, leaf-first.
    const cleanup = await api.delete(`${API_SUB_ITEMS}/${subBody.id}`)
    expect(cleanup.status()).toBe(204)
  })
})
