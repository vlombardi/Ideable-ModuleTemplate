/**
 * The `sub_items` standard entity page.
 *
 * `sub_items` is an association entity (it is reached from `TemplateItems.tsx`'s association
 * view, `items -> sub_items`), but `shared-ui-widgets-specs.md` § *Main entities definition*
 * gives every datamodel entity — main and association alike — a standard page by default. This
 * page is that default: a plain `StandardEntityPage` mount, same as `TemplateItems.tsx`, wired to
 * its own menu item and route. The association-view wiring inside `TemplateItems.tsx` is
 * untouched — this page is ADDITIONAL, not a replacement for it.
 *
 * `sub_items` itself has one association level below it — `sub_item_notes` — so this page also
 * carries that one association tab, the same way `TemplateItems.tsx` carries the `sub_items` tab.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  EntitySelector,
  StandardEntityPage,
  type AssociationTab,
  type ColumnDef,
  type DetailField,
  type PageResult,
  type VersionPage,
} from '@ideable/ui'
import { useTranslation } from '../hooks/useTranslation'
import { entityTransport, EntityTransportError, historyQueryParams } from '../services/entityTransport'
import { fetchPermissions, type PermissionOutcome } from '../services/permissions'
import '../index.css'

/** The `sub_items` entity's read shape (`app/entities/sub_items.py`). */
interface SubItem {
  id: number
  item_fk: number
  name: string
  description: string | null
  item_name: string | null
}

/** The `sub_item_notes` entity's read shape (`app/entities/sub_item_notes.py`) — the one
 *  association level `sub_items` has below it. */
interface SubItemNote {
  id: number
  sub_item_fk: number
  name: string
  description: string | null
  sub_item_name: string | null
}

/** The `items` entity's read shape, as narrowly as this page needs it — `item_fk`'s Entity
 *  Selector picks from this entity's own table. */
interface TemplateItem {
  id: number
  name: string
  description: string | null
}

const PERMISSION_FAILURE_MESSAGE: Record<PermissionOutcome, string> = {
  ok: 'common.notAuthorized',
  'session-expired': 'common.sessionExpired',
  unavailable: 'common.permissionsUnavailable',
}

function isPermissionFailure(error: Error): boolean {
  return error instanceof EntityTransportError && (error.status === 401 || error.status === 403)
}

export default function TemplateSubItems() {
  const { t } = useTranslation()

  // Same UNDETERMINED-vs-denied contract `TemplateItems.tsx` documents: `null` means host_app has
  // not answered yet, an empty set means it answered and this user holds nothing.
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

  const canEdit = permissions?.has('template.sub_items:edit') ?? false
  const canEditSubItemNotes = permissions?.has('template.sub_item_notes:edit') ?? false

  const columns = useMemo<ColumnDef<SubItem, unknown>[]>(() => [
    { accessorKey: 'id', header: t('templateSubItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateSubItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateSubItems.columns.description'), enableSorting: true },
    { accessorKey: 'item_name', header: t('templateSubItems.columns.itemName'), enableSorting: false },
  ], [t])

  const labelFor = useMemo(() => {
    const labels: Record<string, string> = {
      id: t('templateSubItems.columns.id'),
      name: t('templateSubItems.columns.name'),
      description: t('templateSubItems.columns.description'),
      item_fk: t('templateSubItems.columns.itemFk'),
      item_name: t('templateSubItems.columns.itemName'),
    }
    return (field: string) => labels[field] ?? field
  }, [t])

  const detailExcluded = useMemo<Record<string, string>>(
    () => ({ tenant_id: 'the module\'s tenant-scoping column; the page works within the active tenant, so it is not shown' }),
    [],
  )

  const detailFields = useMemo<DetailField<SubItem>[]>(() => [
    { name: 'id', label: t('templateSubItems.columns.id') },
    { name: 'name', label: t('templateSubItems.columns.name'), isName: true },
    { name: 'description', label: t('templateSubItems.columns.description') },
    { name: 'item_fk', label: t('templateSubItems.columns.itemFk') },
    { name: 'item_name', label: t('templateSubItems.columns.itemName') },
  ], [t])

  // The Entity Selector's own modal table — `item_fk`'s picker, per `shared-ui-widgets-specs.md`
  // § *Form FK association selection (normative)*. Same three columns `TemplateItems.tsx` itself
  // shows on the `items` master table, so picking from this modal shows what that page would.
  const itemSelectColumns = useMemo<ColumnDef<TemplateItem, unknown>[]>(() => [
    { accessorKey: 'id', header: t('templateItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateItems.columns.description'), enableSorting: true },
  ], [t])

  const itemLabelFor = useMemo(() => {
    const labels: Record<string, string> = {
      id: t('templateItems.columns.id'),
      name: t('templateItems.columns.name'),
      description: t('templateItems.columns.description'),
    }
    return (field: string) => labels[field] ?? field
  }, [t])

  const subItemNoteColumns: ColumnDef<SubItemNote, unknown>[] = [
    { accessorKey: 'id', header: t('templateSubItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateSubItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateSubItems.columns.description'), enableSorting: true },
  ]

  // The one association level `sub_items` has: `sub_item_notes`, the same tab
  // `TemplateItems.tsx` already carries for `sub_items -> sub_item_notes` inside its own Full
  // perspective — this is that same level, offered again here because the selection now starts
  // one hop closer (a `sub_items` row instead of an `items` row).
  const subItemNotesTab = useMemo<AssociationTab<SubItemNote>[]>(() => [{
    id: 'sub_item_notes',
    label: t('templateSubItems.subItemNotes.tab'),
    singular: t('templateSubItems.subItemNotes.singular'),
    depth: {
      columns: subItemNoteColumns,
      baseParams: (chain) => ({ sub_item_fk: chain[0]?.id }),
      query: (params) => entityTransport.get('/sub_item_notes', params) as Promise<PageResult<SubItemNote>>,
      count: (chain) =>
        entityTransport
          .get('/sub_item_notes', { sub_item_fk: chain[0]?.id, limit: 1 })
          .then((page) => (page as PageResult<SubItemNote>).total),
      label: (row) => row.name,
      formFields: [
        { name: 'name', label: t('templateSubItems.columns.name'), required: true },
        { name: 'description', label: t('templateSubItems.columns.description') },
      ],
      create: async (values, chain) => {
        await entityTransport.post!('/sub_item_notes', { ...values, sub_item_fk: chain[0]?.id })
      },
      unlink: async (row) => {
        await entityTransport.delete!(`/sub_item_notes/${row.id}`)
      },
      update: async (row, values) => {
        await entityTransport.put!(`/sub_item_notes/${row.id}`, values)
      },
      canWrite: canEditSubItemNotes,
      createLabel: t('templateSubItems.subItemNotes.create'),
      createSubmitLabel: t('common.create'),
      saveLabel: t('common.save'),
      unlinkLabel: t('templateSubItems.subItemNotes.unlink'),
    },
    full: {
      columns: subItemNoteColumns,
      baseParams: (chain) => ({ sub_item_fk: chain[0]?.id }),
      query: (params) => entityTransport.get('/sub_item_notes', params) as Promise<PageResult<SubItemNote>>,
      label: (row) => row.name,
    },
  }], [subItemNoteColumns, t, canEditSubItemNotes])

  if (permissions === null) return <p className="ideable:text-sm">{t('common.loading')}</p>

  return (
    <div className="ideable-scope">
      <StandardEntityPage<SubItem>
        entityKey="sub_items"
        transport={entityTransport}
        title={t('templateSubItems.title')}
        entityLabel={t('templateSubItems.entity')}
        columns={columns}
        labelFor={labelFor}
        canEdit={canEdit}
        createLabel={t('templateSubItems.createItem')}
        createSubmitLabel={t('common.create')}
        editLabel={t('common.edit')}
        deleteLabel={t('common.delete')}
        saveLabel={t('common.save')}
        deleteConfirmMessage={t('templateSubItems.confirmDelete')}
        cancelLabel={t('common.cancel')}
        formFields={[
          { name: 'name', label: t('templateSubItems.columns.name'), required: true },
          { name: 'description', label: t('templateSubItems.columns.description') },
          {
            name: 'item_fk',
            label: t('templateSubItems.columns.itemFk'),
            required: true,
            render: (value, setValue) => (
              <EntitySelector<TemplateItem>
                entityKey="items"
                transport={entityTransport}
                value={value as string | number | null}
                onChange={setValue}
                columns={itemSelectColumns}
                labelFor={itemLabelFor}
                displayName={(row) => row.name}
                title={t('templateSubItems.selectItem')}
                selectLabel={t('common.select')}
              />
            ),
          },
        ]}
        detailFields={detailFields}
        detailExcluded={detailExcluded}
        rowLabel={(row) => row.name}
        associations={subItemNotesTab}
        auditColumns={['id', 'name', 'item_fk', 'timestamp', 'actor', 'actor_id']}
        historyLabel={t('templateSubItems.history')}
        fetchHistoryPage={(rowId, params) =>
          entityTransport.get(`/sub_items/${rowId}/history`, historyQueryParams(params)) as Promise<VersionPage>
        }
        renderError={(error) => (
          <p className="ideable:text-sm">
            {isPermissionFailure(error)
              ? t(PERMISSION_FAILURE_MESSAGE[permissionOutcome])
              : t('templateSubItems.loadFailed')}
          </p>
        )}
      />
    </div>
  )
}
