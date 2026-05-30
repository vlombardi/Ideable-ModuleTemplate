import { useState, useEffect, useMemo, useRef, ReactNode } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Eye,
  EyeOff,
} from 'lucide-react'

const SortNeutralIcon = ArrowUpDown
const SortAscIcon = ArrowUp
const SortDescIcon = ArrowDown
const ChevronLeftIcon = ChevronLeft
const ChevronRightIcon = ChevronRight
const ChevronsLeftIcon = ChevronsLeft
const ChevronsRightIcon = ChevronsRight
const EyeIcon = Eye
const EyeOffIcon = EyeOff

export interface ColumnDef<TData> {
  id: string
  header: string
  accessorKey?: string
  cell?: (props: { row: { original: TData; getValue: (key: string) => unknown } }) => ReactNode
  meta?: {
    type?: 'text' | 'boolean'
    sortable?: boolean
    filterable?: boolean
  }
}

interface ServerDataTableProps<TData extends { id: number | string }> {
  columns: ColumnDef<TData>[]
  data: TData[]
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  onSortChange?: (columnId: string, direction: 'asc' | 'desc' | null) => void
  onFilterChange?: (columnId: string, value: string) => void
  filters?: Record<string, string>
  onRowClick?: (row: TData) => void
  selectedRow?: TData | null
  title?: string
  showAuditColumns?: boolean
  onToggleAuditColumns?: () => void
  actions?: ReactNode
}

const formatColumnHeader = (columnId: string): string => {
  const auditMapping: Record<string, string> = {
    'au_creation_timestamp': 'Created At',
    'au_last_update_timestamp': 'Updated At',
    'au_created_by_user': 'Creator',
    'au_last_updated_by_user': 'Updater',
  }
  
  if (auditMapping[columnId]) {
    return auditMapping[columnId]
  }

  let formatted = columnId.replace(/_fk$/, '')
  formatted = formatted
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
  
  return formatted
}

const isNarrowIdOrFkColumn = (columnId: string): boolean => {
  return columnId === 'id' || columnId.endsWith('_fk')
}

const getNarrowColumnClassName = (columnId: string): string => {
  if (!isNarrowIdOrFkColumn(columnId)) return ''
  return 'template-w-[90px] template-max-w-[90px] template-whitespace-nowrap template-overflow-hidden'
}

const getNarrowColumnAlignClassName = (columnId: string): string => {
  if (!isNarrowIdOrFkColumn(columnId)) return ''
  return 'template-text-right'
}

const abbreviateHeaderLabel = (label: string): string => {
  const wordMap: Record<string, string> = {
    Assignment: 'Ass.',
    Profile: 'Prof.',
    Description: 'Desc.',
    Permission: 'Perm.',
    Created: 'Cr.',
    Updated: 'Upd.',
    Creator: 'Crt.',
    Updater: 'Upd.',
    Timestamp: 'Ts.',
  }

  return label
    .split(' ')
    .filter(Boolean)
    .map((word) => {
      if (wordMap[word]) return wordMap[word]
      if (word.length <= 4) return word
      return `${word.slice(0, 4)}.`
    })
    .join(' ')
}

export function ServerDataTable<TData extends { id: number | string }>({
  columns,
  data,
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  onSortChange,
  onFilterChange,
  filters = {},
  onRowClick,
  selectedRow,
  title,
  showAuditColumns = false,
  onToggleAuditColumns,
  actions,
}: ServerDataTableProps<TData>) {
  const [sorting, setSorting] = useState<{ id: string; desc: boolean } | null>(null)
  const [localFilters, setLocalFilters] = useState<Record<string, string>>({})
  const tableRef = useRef<HTMLDivElement>(null)
  const filterTimeoutRef = useRef<number | null>(null)

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // Filter columns based on showAuditColumns
  const visibleColumns = useMemo(() => {
    const auditColumns = ['au_creation_timestamp', 'au_last_update_timestamp', 'au_created_by_user', 'au_last_updated_by_user']
    return columns.filter((col) => {
      if (auditColumns.includes(col.id)) {
        return showAuditColumns
      }
      return true
    })
  }, [columns, showAuditColumns])

  // Handle sorting
  const handleSort = (columnId: string) => {
    if (!onSortChange) return

    const meta = columns.find(c => c.id === columnId)?.meta
    if (meta?.sortable === false) return

    let newSorting: { id: string; desc: boolean } | null = null

    if (!sorting || sorting.id !== columnId) {
      newSorting = { id: columnId, desc: false }
    } else if (!sorting.desc) {
      newSorting = { id: columnId, desc: true }
    } else {
      newSorting = null
    }

    setSorting(newSorting)
    onSortChange(columnId, newSorting ? (newSorting.desc ? 'desc' : 'asc') : null)
  }

  // Handle filter changes with debounce
  const handleFilterChange = (columnId: string, value: string) => {
    setLocalFilters(prev => {
      const newFilters = { ...prev }
      if (value === '' || value === 'all') {
        delete newFilters[columnId]
      } else {
        newFilters[columnId] = value
      }
      return newFilters
    })

    if (filterTimeoutRef.current) {
      window.clearTimeout(filterTimeoutRef.current)
    }

    filterTimeoutRef.current = window.setTimeout(() => {
      if (onFilterChange) {
        onFilterChange(columnId, value === 'all' ? '' : value)
      }
    }, 500)
  }

  // Sync local filters with parent filters
  useEffect(() => {
    setLocalFilters(filters)
  }, [filters])

  // Handle click outside to deselect
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node
      if (tableRef.current && !tableRef.current.contains(target)) {
        if (onRowClick && selectedRow) {
          // Don't deselect, just keep current
        }
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onRowClick, selectedRow])

  // Get filter type
  const getFilterType = (column: ColumnDef<TData>): 'text' | 'boolean' | 'none' => {
    if (column.id === 'actions') return 'none'
    const meta = column.meta
    if (meta?.filterable === false) return 'none'
    if (meta?.type === 'boolean') return 'boolean'
    return 'text'
  }

  return (
    <div className="template-space-y-4" ref={tableRef}>
      {(title || actions) && (
        <div className="template-flex template-items-center template-justify-between">
          {title && <h2 className="template-text-2xl template-font-bold">{title}</h2>}
          <div className="template-flex template-items-center template-gap-2">{actions}</div>
        </div>
      )}

      <div className="template-flex template-items-center template-justify-between template-gap-2">
        <div className="template-flex template-items-center template-gap-2">
          <span className="template-text-sm template-text-muted-foreground">Rows per page:</span>
          <select
            value={pageSize.toString()}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            className="template-h-9 template-w-[100px] template-rounded-md template-border template-bg-background template-px-2"
          >
            {[10, 20, 50, 100, 200, 500].map((size) => (
              <option key={size} value={size.toString()}>
                {size}
              </option>
            ))}
          </select>
        </div>

        {onToggleAuditColumns && (
          <button
            onClick={onToggleAuditColumns}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-border template-border-input template-bg-background hover:template-bg-accent hover:template-text-accent-foreground template-h-9 template-px-3"
          >
            {showAuditColumns ? <EyeOffIcon className="template-h-4 template-w-4" /> : <EyeIcon className="template-h-4 template-w-4" />}
            <span className="template-ml-2">{showAuditColumns ? 'Hide' : 'Show'} Audit Data</span>
          </button>
        )}
      </div>

      <div className="template-relative template-overflow-auto template-rounded-md template-border">
        <table className="template-w-full">
          <thead className="template-sticky template-top-0 template-z-10 template-border-b template-bg-background">
            <tr className="template-border-b">
              {visibleColumns.map((column) => {
                const columnId = column.id
                const isSortable = column.meta?.sortable !== false && columnId !== 'actions'
                const isNarrow = isNarrowIdOrFkColumn(columnId)
                const isSorted = sorting?.id === columnId ? sorting : null
                const fullHeaderLabel = column.header || formatColumnHeader(columnId)
                const headerLabel = isNarrow ? abbreviateHeaderLabel(fullHeaderLabel) : fullHeaderLabel

                return (
                  <th
                    key={`${column.id}-header`}
                    className={`template-h-12 template-px-4 template-text-left template-align-middle template-font-medium template-text-muted-foreground ${getNarrowColumnClassName(columnId)} ${getNarrowColumnAlignClassName(columnId)}`}
                  >
                    <div className="template-flex template-min-w-0 template-items-center template-gap-2">
                      {isSortable ? (
                        <button
                          className={`template-h-8 template-p-0 template-font-medium template-text-sm template-min-w-0 template-inline-flex template-items-center ${isNarrow ? 'template-w-full template-justify-end' : 'template-justify-start'}`}
                          onClick={() => handleSort(column.id)}
                        >
                          <span title={fullHeaderLabel}>{headerLabel}</span>
                          {isSorted ? (
                            isSorted.desc ? (
                              <SortDescIcon className="template-ml-2 template-h-4 template-w-4" />
                            ) : (
                              <SortAscIcon className="template-ml-2 template-h-4 template-w-4" />
                            )
                          ) : (
                            <SortNeutralIcon className="template-ml-2 template-h-4 template-w-4" />
                          )}
                        </button>
                      ) : (
                        <div className={`template-h-8 template-flex template-items-center template-text-sm template-min-w-0 ${isNarrow ? 'template-w-full template-justify-end' : 'template-justify-start'}`}>
                          <span title={fullHeaderLabel}>{headerLabel}</span>
                        </div>
                      )}
                    </div>
                  </th>
                )
              })}
            </tr>
            <tr className="template-border-b">
              {visibleColumns.map((column) => {
                const columnId = column.id
                const filterType = getFilterType(column)

                return (
                  <th
                    key={`${column.id}-filter`}
                    className={`template-h-10 template-px-4 ${getNarrowColumnClassName(columnId)} ${getNarrowColumnAlignClassName(columnId)}`}
                  >
                    {filterType === 'text' && (
                      <input
                        type="text"
                        placeholder="Filter..."
                        value={localFilters[column.id] || ''}
                        onChange={(e) => handleFilterChange(column.id, e.target.value)}
                        className={`template-h-8 template-w-full template-rounded-md template-border template-bg-background template-text-sm ${isNarrowIdOrFkColumn(columnId) ? 'template-px-2' : 'template-px-3'}`}
                      />
                    )}
                    {filterType === 'boolean' && (
                      <select
                        value={localFilters[column.id] || 'all'}
                        onChange={(e) => handleFilterChange(column.id, e.target.value)}
                        className={`template-h-8 template-w-full template-rounded-md template-border template-bg-background ${isNarrowIdOrFkColumn(columnId) ? 'template-px-2' : 'template-px-3'}`}
                      >
                        <option value="all">All</option>
                        <option value="true">True</option>
                        <option value="false">False</option>
                      </select>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {data.length > 0 ? (
              data.map((row) => (
                <tr
                  key={row.id}
                  className={`template-cursor-pointer template-border-b template-transition-colors hover:template-bg-muted/50 ${
                    selectedRow && selectedRow.id === row.id ? 'template-bg-muted' : ''
                  }`}
                  onClick={() => onRowClick?.(row)}
                >
                  {visibleColumns.map((column) => {
                    const isNarrow = isNarrowIdOrFkColumn(column.id)
                    const value = column.accessorKey ? (row as Record<string, unknown>)[column.accessorKey] : null

                    return (
                      <td
                        key={`${row.id}-${column.id}`}
                        className={`template-p-2 template-align-middle ${getNarrowColumnClassName(column.id)} ${getNarrowColumnAlignClassName(column.id)} ${isNarrow ? 'template-whitespace-nowrap' : ''}`}
                      >
                        {column.cell
                          ? column.cell({ row: { original: row, getValue: (key: string) => (row as Record<string, unknown>)[key] } })
                          : (value as ReactNode) || '-'}
                      </td>
                    )
                  })}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={visibleColumns.length} className="template-h-24 template-text-center template-text-muted-foreground">
                  No results.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer with pagination */}
      <div className="template-flex template-items-center template-justify-between template-border-t template-bg-background template-py-2">
        <div className="template-text-sm template-text-muted-foreground">
          Showing {data.length > 0 ? ((page - 1) * pageSize) + 1 : 0} to {Math.min(page * pageSize, total)} of {total} results
        </div>
        <div className="template-flex template-items-center template-gap-2">
          <button
            onClick={() => onPageChange(1)}
            disabled={page === 1}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-border template-border-input template-bg-background hover:template-bg-accent hover:template-text-accent-foreground template-h-9 template-px-3"
          >
            <ChevronsLeftIcon className="template-h-4 template-w-4" />
          </button>
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page === 1}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-border template-border-input template-bg-background hover:template-bg-accent hover:template-text-accent-foreground template-h-9 template-px-3"
          >
            <ChevronLeftIcon className="template-h-4 template-w-4" />
          </button>
          <div className="template-text-sm template-font-medium">Page {page} of {totalPages}</div>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page === totalPages}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-border template-border-input template-bg-background hover:template-bg-accent hover:template-text-accent-foreground template-h-9 template-px-3"
          >
            <ChevronRightIcon className="template-h-4 template-w-4" />
          </button>
          <button
            onClick={() => onPageChange(totalPages)}
            disabled={page === totalPages}
            className="template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium template-ring-offset-background template-transition-colors focus-visible:template-outline-none focus-visible:template-ring-2 focus-visible:template-ring-ring focus-visible:template-ring-offset-2 disabled:template-pointer-events-none disabled:template-opacity-50 template-border template-border-input template-bg-background hover:template-bg-accent hover:template-text-accent-foreground template-h-9 template-px-3"
          >
            <ChevronsRightIcon className="template-h-4 template-w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
