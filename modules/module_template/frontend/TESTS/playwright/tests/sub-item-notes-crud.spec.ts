import { test, expect } from '../auth/session-fixture'
import { request as pwRequest, type APIRequestContext, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PERSONA } from '../auth/personas'
import { parseEntityGraph } from '../lib/entity-graph'
import { newRunMarker, ownedBy } from '../lib/run-marker'

// Full-CRUD, data-driven E2E for module_template's `sub_item_notes` entity — the standard page it
// got per `shared-ui-widgets-specs.md` § *Main entities definition* (an association entity gets
// its own page IN ADDITION TO appearing inside its parent's association view; this suite exercises
// the standalone page). Copied from the reference `items-crud.spec.ts`; see
// `rules/testing-guidelines.md` § "CRUD E2E tests".
//
// FK-ordering (rules/testing-guidelines.md § "Foreign-key ordering"): the chain is
// `template_items -> sub_items -> sub_item_notes` (`sub_item_notes.sub_item_fk`). Leaf-first
// create: item, then sub-item, then the note(s) this suite exercises. Root-first delete: notes
// first, then the sub-item, then the item — derived from the module's own
// `database/SPECS/schema.sql` via `parseEntityGraph`, never hand-typed.

const here = path.dirname(fileURLToPath(import.meta.url))
const TEMPLATE_URL =
  process.env.HOSTAPP_FRONTEND_URL ?? process.env.TEMPLATE_FRONTEND_URL ?? 'http://localhost:3001'
const SLUG = process.env.MODULE_SLUG ?? 'template'
const API_ITEMS = `${TEMPLATE_URL}/module/${SLUG}/api/items`
const API_SUB_ITEMS = `${TEMPLATE_URL}/module/${SLUG}/api/sub_items`
const API_SUB_ITEM_NOTES = `${TEMPLATE_URL}/module/${SLUG}/api/sub_item_notes`

const RUN = newRunMarker()

const CLEANUP_PAGE_SIZE = 100
const PARENT_ITEM_NAME = `${RUN} SubItemNotesParent`
const PARENT_SUB_ITEM_NAME = `${RUN} SubItemNotesParentSubItem`
const NOTE_A = `${RUN} Alpha`
const NOTE_A_DESCRIPTION = `${RUN} description for Alpha`
const NOTE_A_EDITED = `${RUN} Alpha (edited)`
const NOTE_B = `${RUN} Beta`
const NOTE_UI = `${RUN} UiCreated`

function bearerFromSession(): string {
  const file = path.join(here, '..', 'auth', '.auth', `${DEFAULT_PERSONA}.json`)
  const captured = JSON.parse(fs.readFileSync(file, 'utf8'))
  return JSON.parse(captured.session.value).access_token as string
}

/** The FK-aware create/delete order for this suite's three-level chain, from the module's own
 *  schema — never hand-typed. */
function fkOrder(): { createOrder: string[]; deleteOrder: string[] } {
  const schemaPath = path.join(here, '..', '..', '..', '..', 'database', 'SPECS', 'schema.sql')
  const graph = parseEntityGraph(fs.readFileSync(schemaPath, 'utf8'))
  const createOrder = graph.createOrder.filter(
    (e) => e === 'template_items' || e === 'sub_items' || e === 'sub_item_notes',
  )
  return { createOrder, deleteOrder: [...createOrder].reverse() }
}

async function gotoSubItemNotes(page: Page, opts: { editMode?: boolean } = {}): Promise<void> {
  await page.goto(`${TEMPLATE_URL}/${SLUG}/sub_item_notes`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('table')).toBeVisible()
  if (opts.editMode) {
    await page.evaluate(() => {
      window.localStorage.setItem('hostapp.edit_mode', 'true')
      window.dispatchEvent(
        new CustomEvent('hostapp:edit-mode-changed', { detail: { isEditMode: true } }),
      )
    })
    await expect(page.getByRole('button', { name: 'Create Sub-Item Note' })).toBeVisible({ timeout: 10_000 })
  }
}

/** Type into the Name column filter (columns: id, name, description, sub_item_name) and wait for
 *  the debounced (500ms) server round-trip. */
async function filterByName(page: Page, value: string): Promise<void> {
  const nameFilter = page.getByPlaceholder('Filter...').nth(1)
  await nameFilter.fill('')
  await nameFilter.fill(value)
  await page.waitForTimeout(900)
}

/** Type into the Description column filter (columns: id, name, description, sub_item_name) and
 *  wait for the debounced round-trip — proves `description` is actually filterable server-side
 *  (`SubItemNote.__filterable__` + its trigram index), not just present as a column. */
async function filterByDescription(page: Page, value: string): Promise<void> {
  const descriptionFilter = page.getByPlaceholder('Filter...').nth(2)
  await descriptionFilter.fill('')
  await descriptionFilter.fill(value)
  await page.waitForTimeout(900)
}

/** Click the edit form's Save button and confirm it actually submitted (the form closes) before
 *  moving on — retrying the click itself if it doesn't.
 *
 *  This page's Save click has been observed to occasionally not register at all under Playwright's
 *  automated click (no request, no error, dialog stays open) immediately after this exact sequence
 *  (reload -> filter -> wait -> open edit -> click Save), while the identical sequence performed by
 *  hand always works — confirmed by manual reproduction, twice, against a live deployment. The cause
 *  is Playwright-specific (a native, capturing listener attached directly to the button via CDP
 *  never fired either, ruling out an app-level cause), not an application defect, so this retries the
 *  click rather than changing app code. A genuine regression still fails loudly: this throws if the
 *  form never closes after several attempts. */
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

test.describe.serial('module_template Sub-Item Notes — CRUD (authenticated, live stack)', () => {
  test.skip(
    !process.env.RUN_STACK_E2E,
    'CRUD E2E requires a running authenticated stack; set RUN_STACK_E2E=1',
  )

  test('the module schema orders template_items, sub_items, then sub_item_notes', () => {
    const { createOrder, deleteOrder } = fkOrder()
    expect(createOrder).toEqual(['template_items', 'sub_items', 'sub_item_notes'])
    expect(deleteOrder).toEqual(['sub_item_notes', 'sub_items', 'template_items'])
  })

  let api: APIRequestContext
  let parentItemId: number
  let parentSubItemId: number

  test.beforeAll(async () => {
    api = await pwRequest.newContext({
      ignoreHTTPSErrors: true,
      extraHTTPHeaders: { Authorization: `Bearer ${bearerFromSession()}` },
    })
    // Leaf-first create, two levels up: the item, then the sub-item this run's notes
    // FK-reference.
    const itemRes = await api.post(API_ITEMS, {
      data: { name: PARENT_ITEM_NAME, description: 'parent for sub-item-notes e2e' },
    })
    const itemBody = await itemRes.json().catch(() => ({}))
    expect(itemRes.status(), JSON.stringify(itemBody)).toBe(201)
    parentItemId = itemBody.id

    const subItemRes = await api.post(API_SUB_ITEMS, {
      data: { name: PARENT_SUB_ITEM_NAME, description: 'parent for sub-item-notes e2e', item_fk: parentItemId },
    })
    const subItemBody = await subItemRes.json().catch(() => ({}))
    expect(subItemRes.status(), JSON.stringify(subItemBody)).toBe(201)
    parentSubItemId = subItemBody.id
  })

  test.afterAll(async () => {
    // Root-first delete would violate the FK, so this walks the chain from the leaf up: every
    // `sub_item_notes` row this run created, then the parent sub-item, then the parent item.
    // Every response is checked — see items-crud.spec.ts's afterAll for why an unchecked
    // cleanup is the one defect this pattern exists to prevent.
    try {
      const doomed: number[] = []
      for (let skip = 0; ; skip += CLEANUP_PAGE_SIZE) {
        const res = await api.get(API_SUB_ITEM_NOTES, {
          params: { skip: String(skip), limit: String(CLEANUP_PAGE_SIZE) },
        })
        if (!res.ok()) {
          throw new Error(
            `cleanup could not list sub_item_notes: ${res.status()} ${await res.text()} -- rows ` +
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
        const del = await api.delete(`${API_SUB_ITEM_NOTES}/${id}`)
        if (!del.ok()) leaked.push(`${id} (${del.status()})`)
      }
      if (leaked.length) {
        throw new Error(`cleanup could not delete sub_item_note(s) ${leaked.join(', ')} named ${RUN}*`)
      }

      if (parentSubItemId !== undefined) {
        const delSubItem = await api.delete(`${API_SUB_ITEMS}/${parentSubItemId}`)
        if (!delSubItem.ok()) {
          throw new Error(
            `cleanup could not delete parent sub-item ${parentSubItemId} (${delSubItem.status()})`,
          )
        }
      }
      if (parentItemId !== undefined) {
        const delItem = await api.delete(`${API_ITEMS}/${parentItemId}`)
        if (!delItem.ok()) {
          throw new Error(`cleanup could not delete parent item ${parentItemId} (${delItem.status()})`)
        }
      }
    } finally {
      await api.dispose()
    }
  })

  test('CREATE (API): POST /sub_item_notes returns 201 with the created note', async () => {
    for (const [name, description] of [
      [NOTE_A, NOTE_A_DESCRIPTION],
      [NOTE_B, 'created by e2e'],
    ] as const) {
      const res = await api.post(API_SUB_ITEM_NOTES, {
        data: { name, description, sub_item_fk: parentSubItemId },
      })
      const body = await res.json().catch(() => ({}))
      expect(res.status(), JSON.stringify(body)).toBe(201)
      expect(body).toMatchObject({ name, sub_item_fk: parentSubItemId })
      expect(typeof body.id).toBe('number')
    }
  })

  test('READ: the API-created notes are displayed in the UI table', async ({ page }) => {
    await gotoSubItemNotes(page)
    await filterByName(page, NOTE_A)
    await expect(page.getByRole('cell', { name: NOTE_A, exact: true })).toBeVisible()
  })

  test('FILTER: the Name filter narrows the table to the matching row', async ({ page }) => {
    await gotoSubItemNotes(page)
    await filterByName(page, NOTE_B)
    const rows = page.locator('table tbody tr')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(NOTE_B)
  })

  test('FILTER: the Description filter narrows the table to the matching row', async ({ page }) => {
    await gotoSubItemNotes(page)
    await filterByDescription(page, NOTE_A_DESCRIPTION)
    const rows = page.locator('table tbody tr')
    await expect(rows).toHaveCount(1)
    await expect(rows.first()).toContainText(NOTE_A)
  })

  test('CREATE (UI): the create form adds a new row shown in the table', async ({ page }) => {
    await gotoSubItemNotes(page, { editMode: true })
    await page.getByRole('button', { name: 'Create Sub-Item Note' }).click()
    const form = page.locator('form')
    await form.locator('input[type="text"]').first().fill(NOTE_UI)

    // `sub_item_fk` is picked by name through the Entity Selector modal
    // (`shared-ui-widgets-specs.md` § "Form FK association selection (normative)"), never typed
    // as a raw id: open it, filter the `sub_items` selection table down to the parent this run
    // created, and click its row.
    await form.getByRole('button', { name: 'Select', exact: true }).click()
    const subItemModal = page.locator('[data-entity-selector="sub_items"]')
    await expect(subItemModal).toBeVisible()
    await subItemModal.getByPlaceholder('Filter...').nth(1).fill(PARENT_SUB_ITEM_NAME)
    await page.waitForTimeout(900)
    await subItemModal.getByRole('cell', { name: PARENT_SUB_ITEM_NAME, exact: true }).click()
    await expect(subItemModal).toBeHidden()

    await page.getByRole('button', { name: 'Create', exact: true }).click()
    await filterByName(page, NOTE_UI)
    await expect(page.getByRole('cell', { name: NOTE_UI, exact: true })).toBeVisible()
  })

  test('UPDATE (UI): editing a row updates its value in the table', async ({ page }) => {
    await gotoSubItemNotes(page, { editMode: true })
    await filterByName(page, NOTE_A)
    const row = page.locator('table tbody tr', { hasText: NOTE_A }).first()
    // Action buttons are SVG-only: history (0), pencil/edit (1), trash/delete (2).
    await row.locator('td').last().locator('button').nth(1).click()
    const form = page.locator('form')
    await form.locator('input[type="text"]').first().fill(NOTE_A_EDITED)
    await clickSaveAndWaitForClose(page)
    await filterByName(page, NOTE_A_EDITED)
    await expect(page.getByRole('cell', { name: NOTE_A_EDITED, exact: true })).toBeVisible()
  })

  test('DELETE (UI): deleting a row removes it from the table', async ({ page }) => {
    await gotoSubItemNotes(page, { editMode: true })
    await filterByName(page, NOTE_B)
    const row = page.locator('table tbody tr', { hasText: NOTE_B }).first()
    page.on('dialog', (d) => d.accept()) // native confirm()
    await row.locator('td').last().locator('button').last().click() // trash = last action
    await filterByName(page, NOTE_B)
    await expect(page.locator('table tbody tr', { hasText: NOTE_B })).toHaveCount(0)
  })

  test('a sub-item with a note still attached refuses deletion (the FK, not just test ordering)', async () => {
    const noteRes = await api.post(API_SUB_ITEM_NOTES, {
      data: { name: `${RUN} StillAttached`, description: 'blocks sub-item delete', sub_item_fk: parentSubItemId },
    })
    expect(noteRes.status()).toBe(201)
    const noteBody = await noteRes.json()

    const delRes = await api.delete(`${API_SUB_ITEMS}/${parentSubItemId}`)
    // 409, not merely "not 204": a crash (500) also fails to delete, and must not pass as a refusal.
    expect(delRes.status(), 'a sub-item with a note still pointing at it is refused as a conflict').toBe(409)
    expect((await delRes.json()).detail, 'the refusal names what blocks it').toContain('sub_item_notes')

    // Clean up the extra note so `afterAll` finds the parent sub-item still deletable, leaf-first.
    const cleanup = await api.delete(`${API_SUB_ITEM_NOTES}/${noteBody.id}`)
    expect(cleanup.status()).toBe(204)
  })
})
