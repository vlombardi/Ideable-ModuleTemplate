import { useState, useMemo, useEffect } from 'react'
import {
  templateItemsService,
  TemplateItem,
  TemplateItemCreate,
  TemplateItemUpdate,
  TemplateItemsQuery,
} from '../services/templateItems'
import { ServerDataTable, ColumnDef } from '../components/ServerDataTable'
import '../index.css'

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

export default function TemplateItems() {
  const [isEditMode, setIsEditMode] = useState(false)
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
  const [showAuditData, setShowAuditData] = useState(false)
  const [formData, setFormData] = useState<TemplateItemCreate>({ name: '', description: '' })

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
    fetchItems(query)
  }, [query])

  useEffect(() => {
    const readEditMode = () => {
      setIsEditMode(window.localStorage.getItem('hostapp.edit_mode') === 'true')
    }

    const handleModeChanged = (event: Event) => {
      const customEvent = event as CustomEvent<{ isEditMode?: boolean }>
      if (typeof customEvent.detail?.isEditMode === 'boolean') {
        setIsEditMode(customEvent.detail.isEditMode)
        return
      }
      readEditMode()
    }

    readEditMode()
    window.addEventListener('hostapp:edit-mode-changed', handleModeChanged)
    window.addEventListener('storage', readEditMode)

    return () => {
      window.removeEventListener('hostapp:edit-mode-changed', handleModeChanged)
      window.removeEventListener('storage', readEditMode)
    }
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await templateItemsService.createItem(formData)
      setFormData({ name: '', description: '' })
      setIsCreating(false)
      await fetchItems(query)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create item')
    }
  }

  const handleUpdate = async (e: React.FormEvent, id: number) => {
    e.preventDefault()
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
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm('Are you sure you want to delete this item?')) return
    
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
    { id: 'name', header: 'Name', accessorKey: 'name', meta: { sortable: true } },
    { id: 'description', header: 'Description', accessorKey: 'description', meta: { sortable: true } },
    { 
      id: 'au_creation_timestamp', 
      header: 'Created At', 
      accessorKey: 'au_creation_timestamp',
      cell: ({ row }) => formatTimestamp(row.getValue('au_creation_timestamp') as string),
      meta: { sortable: true } 
    },
    { 
      id: 'au_last_update_timestamp', 
      header: 'Updated At', 
      accessorKey: 'au_last_update_timestamp',
      cell: ({ row }) => formatTimestamp(row.getValue('au_last_update_timestamp') as string),
      meta: { sortable: true } 
    },
    { id: 'au_created_by_user', header: 'Creator', accessorKey: 'au_created_by_user', meta: { sortable: true } },
    { id: 'au_last_updated_by_user', header: 'Updater', accessorKey: 'au_last_updated_by_user', meta: { sortable: true } },
    ...(isEditMode
      ? [
          {
            id: 'actions',
            header: 'Actions',
            cell: ({ row }: { row: { original: TemplateItem } }) => (
              <div className="template-flex template-items-center template-gap-2" onClick={(e) => e.stopPropagation()}>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    startEdit(row.original)
                  }}
                  className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 hover:template-bg-accent hover:template-text-accent-foreground template-h-8 template-w-8 template-p-0"
                >
                  <PencilIcon />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDelete(row.original.id)
                  }}
                  className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 hover:template-bg-accent hover:template-text-accent-foreground template-h-8 template-w-8 template-p-0"
                >
                  <TrashIcon />
                </button>
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
          <h1 className="template-text-2xl template-font-bold">Template Items</h1>
          <div className="template-text-muted-foreground">Loading...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="template-scope" data-lf="hostapp">
      <div className="template-space-y-4">
      <div className="template-flex template-items-center template-justify-between">
        <h1 className="template-text-3xl template-font-bold">Items</h1>
        {isEditMode && (
          <button
            onClick={() => setIsCreating(!isCreating)}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-bg-primary template-text-primary-foreground hover:template-bg-primary/90 template-h-10 template-px-4 template-py-2"
          >
            <span className="template-mr-2"><PlusIcon /></span>
            {isCreating ? 'Cancel' : 'Create Item'}
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
          <h2 className="template-text-lg template-font-semibold">Create New Item</h2>
          <div>
            <label className="template-block template-text-sm template-font-medium template-mb-1">
              Name *
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
              Description
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
              Create
            </button>
            <button
              type="button"
              onClick={() => {
                setIsCreating(false)
                setFormData({ name: '', description: '' })
              }}
              className="template-px-4 template-py-2 template-border template-rounded-md"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {isEditMode && isEditing && (
        <form onSubmit={(e) => handleUpdate(e, isEditing)} className="template-p-4 template-border template-rounded-md template-space-y-4">
          <h2 className="template-text-lg template-font-semibold">Edit Item</h2>
          <div>
            <label className="template-block template-text-sm template-font-medium template-mb-1">
              Name
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
              Description
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
              Update
            </button>
            <button
              type="button"
              onClick={() => {
                setIsEditing(null)
                setFormData({ name: '', description: '' })
              }}
              className="template-px-4 template-py-2 template-border template-rounded-md"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <ServerDataTable<TemplateItem>
        title="Items"
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
        showAuditColumns={showAuditData}
        onToggleAuditColumns={() => setShowAuditData(!showAuditData)}
      />
      </div>
    </div>
  )
}
