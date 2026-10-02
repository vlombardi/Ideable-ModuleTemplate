/**
 * The `sub_item_notes` standard entity page.
 *
 * `sub_item_notes` is an association entity, one level below `sub_items` (itself reached from
 * `items`) — it is already reachable through `TemplateItems.tsx`'s Full-perspective association
 * view and through `TemplateSubItems.tsx`'s own `sub_item_notes` tab. Per
 * `shared-ui-widgets-specs.md` § *Main entities definition*, every datamodel entity — main and
 * association alike — also gets its own standard page by default, opt-out only. This is that
 * page: a plain `StandardEntityPage` mount, same shape as `TemplateItems.tsx` and
 * `TemplateSubItems.tsx`. Neither association-view wiring is touched by this page's existence.
 *
 * `sub_item_notes` is the chain's leaf (nothing is FK-scoped to it in this module's datamodel), so
 * this page carries no `associations` prop — layout items 3-5 presuppose an entity with
 * associations, and there is none here.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  EntitySelector,
  StandardEntityPage,
  type ColumnDef,
  type DetailField,
  type VersionPage,
} from '@ideable/ui'
import { useTranslation } from '../hooks/useTranslation'
import { entityTransport, EntityTransportError, historyQueryParams } from '../services/entityTransport'
import { fetchPermissions, type PermissionOutcome } from '../services/permissions'
import '../index.css'

/** The `sub_item_notes` entity's read shape (`app/entities/sub_item_notes.py`). */
interface SubItemNote {
  id: number
  sub_item_fk: number
  name: string
  description: string | null
  sub_item_name: string | null
}

/** The `sub_items` entity's read shape, as narrowly as this page needs it — `sub_item_fk`'s
 *  Entity Selector picks from this entity's own table. */
interface SubItem {
  id: number
  item_fk: number
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

export default function TemplateSubItemNotes() {
  const { t } = useTranslation()

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

  const canEdit = permissions?.has('template.sub_item_notes:edit') ?? false

  const columns = useMemo<ColumnDef<SubItemNote, unknown>[]>(() => [
    { accessorKey: 'id', header: t('templateSubItemNotes.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateSubItemNotes.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateSubItemNotes.columns.description'), enableSorting: true },
    { accessorKey: 'sub_item_name', header: t('templateSubItemNotes.columns.subItemName'), enableSorting: false },
  ], [t])

  const labelFor = useMemo(() => {
    const labels: Record<string, string> = {
      id: t('templateSubItemNotes.columns.id'),
      name: t('templateSubItemNotes.columns.name'),
      description: t('templateSubItemNotes.columns.description'),
      sub_item_fk: t('templateSubItemNotes.columns.subItemFk'),
      sub_item_name: t('templateSubItemNotes.columns.subItemName'),
    }
    return (field: string) => labels[field] ?? field
  }, [t])

  // The Entity Selector's own modal table — `sub_item_fk`'s picker, per
  // `shared-ui-widgets-specs.md` § *Form FK association selection (normative)*. Same columns
  // `TemplateSubItems.tsx` itself shows on the `sub_items` master table.
  const subItemSelectColumns = useMemo<ColumnDef<SubItem, unknown>[]>(() => [
    { accessorKey: 'id', header: t('templateSubItems.columns.id'), enableSorting: true },
    { accessorKey: 'name', header: t('templateSubItems.columns.name'), enableSorting: true },
    { accessorKey: 'description', header: t('templateSubItems.columns.description'), enableSorting: true },
  ], [t])

  const subItemLabelFor = useMemo(() => {
    const labels: Record<string, string> = {
      id: t('templateSubItems.columns.id'),
      name: t('templateSubItems.columns.name'),
      description: t('templateSubItems.columns.description'),
    }
    return (field: string) => labels[field] ?? field
  }, [t])

  const detailExcluded = useMemo<Record<string, string>>(
    () => ({ tenant_id: 'the module\'s tenant-scoping column; the page works within the active tenant, so it is not shown' }),
    [],
  )

  const detailFields = useMemo<DetailField<SubItemNote>[]>(() => [
    { name: 'id', label: t('templateSubItemNotes.columns.id') },
    { name: 'name', label: t('templateSubItemNotes.columns.name'), isName: true },
    { name: 'description', label: t('templateSubItemNotes.columns.description') },
    { name: 'sub_item_fk', label: t('templateSubItemNotes.columns.subItemFk') },
    { name: 'sub_item_name', label: t('templateSubItemNotes.columns.subItemName') },
  ], [t])

  if (permissions === null) return <p className="ideable:text-sm">{t('common.loading')}</p>

  return (
    <div className="ideable-scope">
      <StandardEntityPage<SubItemNote>
        entityKey="sub_item_notes"
        transport={entityTransport}
        title={t('templateSubItemNotes.title')}
        columns={columns}
        labelFor={labelFor}
        canEdit={canEdit}
        createLabel={t('templateSubItemNotes.createItem')}
        createSubmitLabel={t('common.create')}
        editLabel={t('common.edit')}
        deleteLabel={t('common.delete')}
        saveLabel={t('common.save')}
        deleteConfirmMessage={t('templateSubItemNotes.confirmDelete')}
        cancelLabel={t('common.cancel')}
        formFields={[
          { name: 'name', label: t('templateSubItemNotes.columns.name'), required: true },
          { name: 'description', label: t('templateSubItemNotes.columns.description') },
          {
            name: 'sub_item_fk',
            label: t('templateSubItemNotes.columns.subItemFk'),
            required: true,
            render: (value, setValue) => (
              <EntitySelector<SubItem>
                entityKey="sub_items"
                transport={entityTransport}
                value={value as string | number | null}
                onChange={setValue}
                columns={subItemSelectColumns}
                labelFor={subItemLabelFor}
                displayName={(row) => row.name}
                title={t('templateSubItemNotes.selectSubItem')}
                selectLabel={t('common.select')}
              />
            ),
          },
        ]}
        detailFields={detailFields}
        detailExcluded={detailExcluded}
        rowLabel={(row) => row.name}
        auditColumns={['id', 'name', 'sub_item_fk', 'timestamp', 'actor', 'actor_id']}
        historyLabel={t('templateSubItemNotes.history')}
        fetchHistoryPage={(rowId, params) =>
          entityTransport.get(`/sub_item_notes/${rowId}/history`, historyQueryParams(params)) as Promise<VersionPage>
        }
        renderError={(error) => (
          <p className="ideable:text-sm">
            {isPermissionFailure(error)
              ? t(PERMISSION_FAILURE_MESSAGE[permissionOutcome])
              : t('templateSubItemNotes.loadFailed')}
          </p>
        )}
      />
    </div>
  )
}
