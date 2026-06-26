import { useState, useMemo, useEffect, useCallback, type FormEvent } from 'react'
import { useTranslation } from '../hooks/useTranslation'
import {
  templateItemsService,
  TemplateItem,
  TemplateItemCreate,
  TemplateItemUpdate,
  TemplateItemsQuery,
  TemplateItemVersion,
} from '../services/templateItems'
import { AuditTrailPopup, VersionRecord } from '../components/AuditTrailPopup'
import { ServerDataTable, ColumnDef } from '../components/ServerDataTable'
import { UnsavedChangesDialog } from '../components/UnsavedChangesDialog'
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard'
import { getCurrentAccessToken } from '../services/authToken'
import '../index.css'

const decodeJwtPayload = (token: string): Record<string, unknown> | null => {
  try {
    const payload = token.split('.')[1]
    if (!payload) return null
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
    return JSON.parse(atob(padded)) as Record<string, unknown>
  } catch {
    return null
  }
}

const collectPermissionClaims = (payload: Record<string, unknown> | null): Set<string> => {
  const claims = new Set<string>()
  if (!payload) return claims

  for (const [key, value] of Object.entries(payload)) {
    if (!(key === 'permissions' || key.endsWith('.permissions'))) continue
    if (!Array.isArray(value)) continue
    for (const entry of value) {
      if (typeof entry === 'string' && entry.trim()) {
        claims.add(entry.trim())
      }
    }
  }

  return claims
}

const PlusIcon = () => (
  <svg className="template-h-4 template-w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14" />
    <path d="M12 5v14" />
  </svg>
)

const PencilIcon = () => (
  <svg className="template-h-4 template-w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z" />
  </svg>
)

const TrashIcon = () => (
  <svg className="template-h-4 template-w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 6h18" />
    <path d="M8 6V4h8v2" />
    <path d="M19 6v14H5V6" />
    <path d="M10 11v6" />
    <path d="M14 11v6" />
  </svg>
)

const HistoryIcon = () => (
  <svg className="template-h-4 template-w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
    <path d="M3 3v5h5" />
    <path d="M12 7v5l4 2" />
  </svg>
)

export default function TemplateItems() {
  const { t } = useTranslation()
  const [isEditMode, setIsEditMode] = useState(false)
  const [accessToken, setAccessToken] = useState(() => getCurrentAccessToken())

  const permissions = useMemo(() => {
    return collectPermissionClaims(decodeJwtPayload(accessToken || ''))
  }, [accessToken])

  const canView = permissions.has('items:view')
  const canEdit = permissions.has('items:edit')
  const canViewAuditTrail = permissions.has('audit_trail:view')

  const isEditEnabled = isEditMode && canEdit

  const [items, setItems] = useState<TemplateItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [pages, setPages] = useState(1)
  const [sortBy, setSortBy] = useState<string>('')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc' | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [isEditing, setIsEditing] = useState<number | null>(null)
  const [auditPopupOpen, setAuditPopupOpen] = useState(false)
  const [auditHistory, setAuditHistory] = useState<TemplateItemVersion[]>([])
  const [formData, setFormData] = useState<TemplateItemCreate>({ name: '', description: '' })
  const hasUnsavedChanges = isCreating || isEditing !== null || formData.name.trim() !== '' || formData.description.trim() !== ''

  const unsavedChangesGuard = useUnsavedChangesGuard({ dirty: hasUnsavedChanges, enabled: isEditEnabled })

  const query = useMemo<TemplateItemsQuery>(() => {
    return {
      skip: (page - 1) * pageSize,
      limit: pageSize,
      ...(sortBy && sortOrder ? { sort_by: sortBy, sort_order: sortOrder } : {}),
      ...filters,
    }
  }, [filters, page, pageSize, sortBy, sortOrder])

  const fetchItems = async (nextQuery: TemplateItemsQuery = query) => {
    try {
      setLoading(true)
      setError(null)
      const data = await templateItemsService.listItems(nextQuery)
      setItems(data.items)
      setTotal(data.total)
      setPages(data.pages || 1)

      if (data.pages > 0 && page > data.pages) {
        setPage(data.pages)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load items')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!canView) {
      setLoading(false)
      setError(t('common.notAuthorized'))
      setItems([])
      setTotal(0)
      setPages(1)
      return
    }

    fetchItems(query)
  }, [canView, query, t])

  useEffect(() => {
    const readEditMode = () => {
      setIsEditMode(window.localStorage.getItem('hostapp.edit_mode') === 'true')
    }

    const readAccessToken = () => {
      setAccessToken(getCurrentAccessToken())
    }

    const handleModeChanged = (event: Event) => {
      const customEvent = event as CustomEvent<{ isEditMode?: boolean }>
      if (typeof customEvent.detail?.isEditMode === 'boolean') {
        setIsEditMode(customEvent.detail.isEditMode)
        return
      }
      readEditMode()
    }

    const handlePermissionsChanged = (event: Event) => {
      const customEvent = event as CustomEvent<{ permissions?: string[] }>
      if (customEvent.detail?.permissions) {
        readAccessToken()
        return
      }
      readAccessToken()
    }

    readEditMode()
    readAccessToken()
    window.addEventListener('hostapp:edit-mode-changed', handleModeChanged)
    window.addEventListener('hostapp:auth-token-changed', handlePermissionsChanged)
    window.addEventListener('storage', (e) => {
      if (e.key === 'hostapp.edit_mode') readEditMode()
    })

    return () => {
      window.removeEventListener('hostapp:edit-mode-changed', handleModeChanged)
      window.removeEventListener('hostapp:auth-token-changed', handlePermissionsChanged)
    }
  }, [])

  const submitCreate = useCallback(async () => {
    try {
      await templateItemsService.createItem(formData)
      setFormData({ name: '', description: '' })
      setIsCreating(false)
      await fetchItems(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create item')
    }
  }, [fetchItems, formData, query])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    await submitCreate()
  }

  const submitUpdate = useCallback(async (id: number) => {
    try {
      const updateData: TemplateItemUpdate = {}
      if (formData.name) updateData.name = formData.name
      if (formData.description) updateData.description = formData.description

      await templateItemsService.updateItem(id, updateData)
      setFormData({ name: '', description: '' })
      setIsEditing(null)
      await fetchItems(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update item')
    }
  }, [fetchItems, formData, query])

  const handleUpdate = async (e: React.FormEvent, id: number) => {
    e.preventDefault()
    await submitUpdate(id)
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('templateItems.deleteConfirm'))) return
    
    try {
      await templateItemsService.deleteItem(id)
      if (items.length === 1 && page > 1) {
        setPage((current) => Math.max(1, current - 1))
      } else {
        await fetchItems(query)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete item')
    }
  }

  const handleSortChange = (columnId: string, direction: 'asc' | 'desc' | null) => {
    setSortBy(direction ? columnId : '')
    setSortOrder(direction)
    setPage(1)
  }

  const handleFilterChange = (columnId: string, value: string) => {
    setFilters((previous) => {
      const next = { ...previous }
      if (value.trim() === '') {
        delete next[columnId]
      } else {
        next[columnId] = value
      }
      return next
    })
    setPage(1)
  }

  const startEdit = (item: TemplateItem) => {
    setFormData({
      name: item.name,
      description: item.description || ''
    })
    setIsEditing(item.id)
  }

  const resetFormState = useCallback(() => {
    setIsCreating(false)
    setIsEditing(null)
    setFormData({ name: '', description: '' })
  }, [])

  const openCreateForm = useCallback(() => {
    setIsEditing(null)
    setIsCreating(true)
    setFormData({ name: '', description: '' })
  }, [])

  const closeCurrentForm = useCallback(() => {
    resetFormState()
  }, [resetFormState])

  const requestCreateToggle = useCallback(() => {
    if (hasUnsavedChanges) {
      if (isCreating) {
        unsavedChangesGuard.requestGuardedAction({
          onDiscard: closeCurrentForm,
          onSave: submitCreate,
        })
        return
      }

      unsavedChangesGuard.requestGuardedAction({
        onDiscard: openCreateForm,
        onSave: async () => {
          if (isEditing !== null) {
            await submitUpdate(isEditing)
          }
          openCreateForm()
        },
      })
      return
    }

    if (isCreating) {
      closeCurrentForm()
      return
    }

    openCreateForm()
  }, [closeCurrentForm, hasUnsavedChanges, isCreating, isEditing, openCreateForm, submitCreate, submitUpdate])

  const requestCloseCurrentForm = useCallback(() => {
    if (hasUnsavedChanges) {
      unsavedChangesGuard.requestGuardedAction({
        onDiscard: closeCurrentForm,
        onSave: isCreating
          ? submitCreate
          : async () => {
              if (isEditing !== null) {
                await submitUpdate(isEditing)
              }
            },
      })
      return
    }

    closeCurrentForm()
  }, [closeCurrentForm, hasUnsavedChanges, isCreating, isEditing, submitCreate, submitUpdate, unsavedChangesGuard])

  const formatTimestamp = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
      return value
    }
    return date.toLocaleString()
  }

  // Define columns
  const columns: ColumnDef<TemplateItem>[] = [
    { id: 'id', header: 'ID', accessorKey: 'id', meta: { sortable: true } },
    { id: 'name', header: () => t('templateItems.name'), accessorKey: 'name', meta: { sortable: true } },
    { id: 'description', header: () => t('templateItems.description'), accessorKey: 'description', meta: { sortable: true } },
    ...((isEditEnabled || canViewAuditTrail)
      ? [
          {
            id: 'actions',
            header: () => t('common.actions'),
            cell: ({ row }: { row: { original: TemplateItem } }) => (
              <div className="template-flex template-items-center template-gap-2" onClick={(e) => e.stopPropagation()}>
                {canViewAuditTrail && (
                  <button
                    title={t('table.viewAuditTrail')}
                    onClick={(e) => {
                      e.stopPropagation()
                      setAuditHistory([])
                      templateItemsService.getHistory(row.original.id).then((h) => {
                        setAuditHistory(h)
                        setAuditPopupOpen(true)
                      })
                    }}
                    className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 hover:template-bg-accent hover:template-text-accent-foreground template-h-8 template-w-8 template-p-0"
                  >
                    <HistoryIcon />
                  </button>
                )}
                {isEditEnabled && canEdit && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      startEdit(row.original)
                    }}
                    className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 hover:template-bg-accent hover:template-text-accent-foreground template-h-8 template-w-8 template-p-0"
                  >
                    <PencilIcon />
                  </button>
                )}
                {isEditEnabled && canEdit && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(row.original.id)
                    }}
                    className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 hover:template-bg-accent hover:template-text-accent-foreground template-h-8 template-w-8 template-p-0"
                  >
                    <TrashIcon />
                  </button>
                )}
              </div>
            ),
            meta: { sortable: false, filterable: false },
          },
        ]
      : []),
  ]

  if (loading && items.length === 0) {
    return (
      <div className="template-scope" data-lf="hostapp">
        <div className="template-space-y-4">
          <h1 className="template-text-2xl template-font-bold">{t('templateItems.title')}</h1>
          <div className="template-text-muted-foreground">{t('common.loading')}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="template-scope" data-lf="hostapp">
      <div className="template-space-y-4">
      <div className="template-flex template-items-center template-justify-between">
        <h1 className="template-text-3xl template-font-bold">{t('templateItems.title')}</h1>
        {isEditEnabled && (
          <button
            onClick={requestCreateToggle}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-bg-primary template-text-primary-foreground hover:template-bg-primary/90 template-h-10 template-px-4 template-py-2"
          >
            <span className="template-mr-2"><PlusIcon /></span>
            {isCreating ? t('common.cancel') : t('templateItems.createItem')}
          </button>
        )}
      </div>

      {error && (
        <div className="template-p-4 template-bg-red-100 template-text-red-700 template-rounded-md">
          {error}
          <button onClick={() => setError(null)} className="template-ml-2 template-text-sm">
            Dismiss
          </button>
        </div>
      )}

      {isEditMode && isCreating && (
        <form onSubmit={handleCreate} className="template-p-4 template-border template-rounded-md template-space-y-4">
          <h2 className="template-text-lg template-font-semibold">{t('templateItems.createItem')}</h2>
          <div>
            <label className="template-block template-text-sm template-font-medium template-mb-1">
              {t('templateItems.name')} *
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="template-w-full template-px-3 template-py-2 template-border template-rounded-md"
              required
            />
          </div>
          <div>
            <label className="template-block template-text-sm template-font-medium template-mb-1">
              {t('templateItems.description')}
            </label>
            <textarea
              value={formData.description || ''}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="template-w-full template-px-3 template-py-2 template-border template-rounded-md"
              rows={3}
            />
          </div>
          <div className="template-flex template-gap-2">
            <button
              type="submit"
              className="template-px-4 template-py-2 template-bg-primary template-text-primary-foreground template-rounded-md"
            >
              {t('common.create')}
            </button>
            <button
              type="button"
              onClick={requestCloseCurrentForm}
              className="template-px-4 template-py-2 template-border template-rounded-md"
            >
              {t('common.cancel')}
            </button>
          </div>
        </form>
      )}

      {isEditMode && isEditing && (
        <form onSubmit={(e) => handleUpdate(e, isEditing)} className="template-p-4 template-border template-rounded-md template-space-y-4">
          <h2 className="template-text-lg template-font-semibold">{t('templateItems.editItem')}</h2>
          <div>
            <label className="template-block template-text-sm template-font-medium template-mb-1">
              {t('templateItems.name')}
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="template-w-full template-px-3 template-py-2 template-border template-rounded-md"
            />
          </div>
          <div>
            <label className="template-block template-text-sm template-font-medium template-mb-1">
              {t('templateItems.description')}
            </label>
            <textarea
              value={formData.description || ''}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="template-w-full template-px-3 template-py-2 template-border template-rounded-md"
              rows={3}
            />
          </div>
          <div className="template-flex template-gap-2">
            <button
              type="submit"
              className="template-px-4 template-py-2 template-bg-primary template-text-primary-foreground template-rounded-md"
            >
              {t('common.save')}
            </button>
            <button
              type="button"
              onClick={requestCloseCurrentForm}
              className="template-px-4 template-py-2 template-border template-rounded-md"
            >
              {t('common.cancel')}
            </button>
          </div>
        </form>
      )}

      <UnsavedChangesDialog
        open={unsavedChangesGuard.isPromptOpen}
        title={t('common.unsavedChangesTitle')}
        description={t('common.unsavedChangesMessage')}
        keepEditingLabel={t('common.keepEditing')}
        discardLabel={t('common.discard')}
        saveLabel={t('common.save')}
        onKeepEditing={unsavedChangesGuard.handleKeepEditing}
        onDiscard={unsavedChangesGuard.handleDiscard}
        onSave={unsavedChangesGuard.handleSave}
      />

      <ServerDataTable<TemplateItem>
        columns={columns}
        data={items}
        total={total}
        page={page}
        pageSize={pageSize}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size)
          setPage(1)
        }}
        onSortChange={handleSortChange}
        onFilterChange={handleFilterChange}
        filters={filters}
      />
      </div>

      {auditPopupOpen && (
        <AuditTrailPopup
          open={auditPopupOpen}
          onClose={() => { setAuditPopupOpen(false) }}
          entityLabel={t('templateItems.title')}
          tabs={[
            {
              label: t('templateItems.history'),
              versions: auditHistory as VersionRecord[],
              columns: ['id', 'name', 'description', 'au_creation_timestamp', 'au_last_update_timestamp', 'au_created_by_user', 'au_last_updated_by_user'],
            },
          ]}
        />
      )}
    </div>
  )
}
