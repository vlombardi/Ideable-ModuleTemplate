/**
 * The Items page: the worked example of using the standard page and the standard endpoints.
 *
 * This is what a module maintainer reads to learn how an entity is served. After the entity
 * registry, it is a forward: the entity key, the transport, translated labels, and nothing else.
 * `StandardEntityPage` comes from `@ideable/ui` and the endpoints are generated from the
 * descriptor in `app/entities/items.py`, so nothing here knows how a list is paged, how a filter
 * reaches SQL, or how the audit trail is fetched.
 *
 * It plays the role `WidgetGallery` plays for the widgets — the live demonstration that the
 * catalogue entry works — and it is deliberately the place the design fails first: if Items needs
 * one line the standard page cannot give it, the standard page is wrong, and that shows up in the
 * template rather than three modules later in somebody else's project.
 *
 * A module that needs something else points its menu item at its own component instead. The
 * endpoints stay mounted and this page stays importable, so that choice is reversible and costs
 * nothing in either direction.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  StandardEntityPage,
  type AssociationTab,
  type ColumnDef,
  type DetailField,
  type PageResult,
} from '@ideable/ui'
import { useTranslation } from '../hooks/useTranslation'
import { entityTransport, EntityTransportError } from '../services/entityTransport'
import { templateItemsService, type TemplateItem } from '../services/templateItems'
import { fetchPermissions, type PermissionOutcome } from '../services/permissions'
import '../index.css'

/** The `sub_items` entity's read shape (`app/entities/sub_items.py`) — no typed service needed,
 *  same as `TemplateItem`: `StandardEntityPage`/`EntityTable` fetch through `entityTransport`
 *  generically. */
interface SubItem {
  id: number
  item_fk: number
  name: string
  description: string | null
  item_name: string | null
}

/** The `sub_item_notes` entity's read shape (`app/entities/sub_item_notes.py`) — the chain's
 *  third level, one hop below `sub_items`. */
interface SubItemNote {
  id: number
  sub_item_fk: number
  name: string
  description: string | null
  sub_item_name: string | null
}

/** The full-perspective row shape for `/items/{id}/sub_item_notes`
 *  (`app/routers/item_traversal.py`, `schemas.ItemSubItemNotePath`) — every note reachable from the
 *  selected item, through its sub-items, carrying both parents' names as provenance. */
interface ItemSubItemNote extends SubItemNote {
  item_fk: number
  item_name: string | null
}

/**
 * What the page may say for each outcome of the permission fetch.
 *
 * Only `ok` is a statement about the USER — host_app answered and the permission is absent. The
 * other two are statements about the SYSTEM, and saying "you are not authorized" for either would
 * blame a person for an outage.
 */
const PERMISSION_FAILURE_MESSAGE: Record<PermissionOutcome, string> = {
  ok: 'common.notAuthorized',
  'session-expired': 'common.sessionExpired',
  unavailable: 'common.permissionsUnavailable',
}

function isPermissionFailure(error: Error): boolean {
  return error instanceof EntityTransportError && (error.status === 401 || error.status === 403)
}

export default function TemplateItems() {
  const { t } = useTranslation()

  // Resolved by host_app from its authorization tables: the access token is thin and carries no
  // permissions, so deriving them from it once hid this page from users who in fact had access.
  //
  // `null` is UNDETERMINED and is not `denied`. An empty set means host_app answered and this user
  // holds nothing; null means it has not answered yet, or could not. Collapsing the two shows a
  // refusal — or hides an action — on the strength of a request that never succeeded.
  const [permissions, setPermissions] = useState<Set<string> | null>(null)
  const [permissionOutcome, setPermissionOutcome] = useState<PermissionOutcome>('ok')

  useEffect(() => {
    let cancelled = false
    const load = () => {
      void fetchPermissions()
        .then((result) => {
          if (cancelled) return
          setPermissions(result.permissions)
          setPermissionOutcome(result.outcome)
        })
        .catch(() => {
          // A REJECTION MUST STILL RESOLVE THE UNDETERMINED STATE. Without this the page waits
          // forever on a request that already failed — measured: the heading never rendered, and
          // six specs failed on a page that was stuck rather than refusing or showing anything.
          //
          // An empty set with the `unavailable` outcome is the honest reading: nothing is known to
          // be permitted, and the reason is the system rather than the user, which is what decides
          // the message.
          if (cancelled) return
          setPermissions(new Set())
          setPermissionOutcome('unavailable')
        })
    }
    load()
    window.addEventListener('hostapp:auth-token-changed', load)
    return () => {
      cancelled = true
      window.removeEventListener('hostapp:auth-token-changed', load)
    }
  }, [])

  const canEdit = permissions?.has('template.items:edit') ?? false
  const canEditSubItems = permissions?.has('template.sub_items:edit') ?? false
  const canEditSubItemNotes = permissions?.has('template.sub_item_notes:edit') ?? false


  // Labels are the page's, not the library's: they need translating, and the backend descriptor
  // deliberately carries no copy. The column ORDER is the page's too.
  // The page chooses its columns, their order and what they show. The descriptor CAN supply a
  // default set, but it is the read schema's declaration order — here `name, description, id,
  // tenant_id` — which is neither what a reader expects nor what should be shown at all: tenant_id
  // is an internal scoping column. Choosing them is the documented path for a real page.
  const columns = useMemo<ColumnDef<TemplateItem, unknown>[]>(() => [
    { accessorKey: 'id', header: t('templateItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateItems.columns.description'), enableSorting: true },
  ], [t])

  const labelFor = useMemo(() => {
    const labels: Record<string, string> = {
      id: t('templateItems.columns.id'),
      name: t('templateItems.columns.name'),
      description: t('templateItems.columns.description'),
    }
    return (field: string) => labels[field] ?? field
  }, [t])

  const subItemColumns: ColumnDef<SubItem, unknown>[] = [
    { accessorKey: 'id', header: t('templateItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateItems.columns.description'), enableSorting: true },
  ]

  const subItemNoteColumns: ColumnDef<ItemSubItemNote, unknown>[] = [
    { accessorKey: 'id', header: t('templateItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateItems.columns.description'), enableSorting: true },
  ]

  // Full perspective's provenance column: a note reached this way can come from any sub-item, so
  // the table has to say which — same shape as `WidgetGallery.tsx`'s `galleryAssociations` second
  // level.
  const itemSubItemNoteColumns: ColumnDef<ItemSubItemNote, unknown>[] = [
    { accessorKey: 'sub_item_name', header: t('templateItems.subItemNotes.columns.subItem'), enableSorting: true },
    ...subItemNoteColumns,
  ]

  // The selected item's details card: every attribute the table does not show (the table already
  // shows id, name and description, so this is the same three — the card is where an entity whose
  // read schema carries MORE would put the rest, and `name` is marked the name for the header).
  const detailFields = useMemo<DetailField<TemplateItem>[]>(() => [
    { name: 'id', label: t('templateItems.columns.id') },
    { name: 'name', label: t('templateItems.columns.name'), isName: true },
    { name: 'description', label: t('templateItems.columns.description') },
  ], [t])

  // The chain's second level, `sub_item_notes` — `chain[1]` is the selected `sub_items` row, one
  // hop below the main `items` row at `chain[0]`. Depth is the selected sub-item's own notes, a
  // filter on `sub_item_fk`; Full is every note reachable from the selected ITEM, through
  // `/items/{id}/sub_item_notes` (`app/routers/item_traversal.py`), which is why only Full carries
  // the `sub_item_name` provenance column — a note reached that way can come from any sub-item.
  const subItemNotesTab = useMemo<AssociationTab<ItemSubItemNote>[]>(() => [{
    id: 'sub_item_notes',
    label: (chain) => t('templateItems.subItemNotes.tab', { name: chain[1]?.label ?? '' }),
    depth: {
      columns: subItemNoteColumns,
      baseParams: (chain) => ({ sub_item_fk: chain[1]?.id }),
      query: (params) => entityTransport.get('/sub_item_notes', params) as Promise<PageResult<ItemSubItemNote>>,
      count: (chain) =>
        entityTransport
          .get('/sub_item_notes', { sub_item_fk: chain[1]?.id, limit: 1 })
          .then((page) => (page as PageResult<ItemSubItemNote>).total),
      label: (row) => row.name,
      formFields: [
        { name: 'name', label: t('templateItems.columns.name'), required: true },
        { name: 'description', label: t('templateItems.columns.description') },
      ],
      create: async (values, chain) => {
        await entityTransport.post!('/sub_item_notes', { ...values, sub_item_fk: chain[1]?.id })
      },
      unlink: async (row) => {
        await entityTransport.delete!(`/sub_item_notes/${row.id}`)
      },
      update: async (row, values) => {
        await entityTransport.put!(`/sub_item_notes/${row.id}`, values)
      },
      canWrite: canEditSubItemNotes,
      createLabel: t('templateItems.subItemNotes.create'),
      createSubmitLabel: t('common.create'),
      saveLabel: t('common.save'),
      unlinkLabel: t('templateItems.subItemNotes.unlink'),
    },
    full: {
      columns: itemSubItemNoteColumns,
      query: (params, chain) =>
        entityTransport.get(`/items/${chain[0]?.id}/sub_item_notes`, params) as Promise<PageResult<ItemSubItemNote>>,
      count: (chain) =>
        entityTransport
          .get(`/items/${chain[0]?.id}/sub_item_notes`, { limit: 1 })
          .then((page) => (page as PageResult<ItemSubItemNote>).total),
      label: (row) => row.name,
    },
  }], [subItemNoteColumns, itemSubItemNoteColumns, t, canEditSubItemNotes])

  // The one association level this entity has: `sub_items`. `item_fk` is the level's own scope,
  // taken from the chain's main row rather than typed by the viewer, so a create never needs the
  // hidden-field trick the old `detail(row)` page used.
  const subItemsTab = useMemo<AssociationTab<SubItem>[]>(() => [{
    id: 'sub_items',
    label: (chain) => t('templateItems.subItems.tab', { name: chain[0]?.label ?? '' }),
    depth: {
      columns: subItemColumns,
      baseParams: (chain) => ({ item_fk: chain[0]?.id }),
      query: (params) => entityTransport.get('/sub_items', params) as Promise<PageResult<SubItem>>,
      count: (chain) =>
        entityTransport
          .get('/sub_items', { item_fk: chain[0]?.id, limit: 1 })
          .then((page) => (page as PageResult<SubItem>).total),
      label: (row) => row.name,
      formFields: [
        { name: 'name', label: t('templateItems.columns.name'), required: true },
        { name: 'description', label: t('templateItems.columns.description') },
      ],
      create: async (values, chain) => {
        // The affordance is only wired when the module's transport carries the verb; a module with
        // no `post` omits `create` and the page offers no add button at all.
        await entityTransport.post!('/sub_items', { ...values, item_fk: chain[0]?.id })
      },
      unlink: async (row) => {
        await entityTransport.delete!(`/sub_items/${row.id}`)
      },
      update: async (row, values) => {
        await entityTransport.put!(`/sub_items/${row.id}`, values)
      },
      canWrite: canEditSubItems,
      createLabel: t('templateItems.subItems.create'),
      createSubmitLabel: t('common.create'),
      saveLabel: t('common.save'),
      unlinkLabel: t('templateItems.subItems.unlink'),
    },
    full: {
      columns: subItemColumns,
      baseParams: (chain) => ({ item_fk: chain[0]?.id }),
      query: (params) => entityTransport.get('/sub_items', params) as Promise<PageResult<SubItem>>,
      label: (row) => row.name,
    },
  }], [subItemColumns, t, canEditSubItems])

  const associations = useMemo<AssociationTab<any>[]>(
    () => [...subItemsTab, ...subItemNotesTab],
    [subItemsTab, subItemNotesTab],
  )

  // Until host_app has answered, the page neither authorizes nor denies. Rendering a refusal on an
  // unanswered request blames the user for a pending call; rendering the table would show data the
  // caller may not be entitled to. Waiting is the only claim that is true at this moment.
  if (permissions === null) return <p className="ideable:text-sm">{t('common.loading')}</p>

  return (
    <div className="ideable-scope">
      <StandardEntityPage<TemplateItem>
        entityKey="items"
        transport={entityTransport}
        title={t('templateItems.title')}
        columns={columns}
        labelFor={labelFor}
        canEdit={canEdit}
        createLabel={t('templateItems.createItem')}
        createSubmitLabel={t('common.create')}
        editLabel={t('common.edit')}
        deleteLabel={t('common.delete')}
        saveLabel={t('common.save')}
        deleteConfirmMessage={t('templateItems.confirmDelete')}
        cancelLabel={t('common.cancel')}
        formFields={[
          { name: 'name', label: t('templateItems.columns.name'), required: true },
          { name: 'description', label: t('templateItems.columns.description') },
        ]}
        detailFields={detailFields}
        rowLabel={(row) => row.name}
        // The chain's association view: the visit-mode toggle, a breadcrumb tab per level, and
        // each level's table with its add/unlink affordances — `sub_items` at the first level,
        // `sub_item_notes` one hop below it.
        associations={associations}
        auditColumns={['id', 'name', 'description', 'timestamp', 'actor', 'actor_id']}
        historyLabel={t('templateItems.history')}
        fetchHistoryPage={(rowId, params) =>
          templateItemsService.getHistoryPage(Number(rowId), params)
        }
        // The refusal is the module's string, and it must replace the table rather than sit above
        // it: an empty grid behind a message says "there is nothing here", which is a different
        // claim from "you may not look".
        renderError={(error) => (
          <p className="ideable:text-sm">
            {isPermissionFailure(error)
              ? t(PERMISSION_FAILURE_MESSAGE[permissionOutcome])
              : t('templateItems.loadFailed')}
          </p>
        )}
      />
    </div>
  )
}
