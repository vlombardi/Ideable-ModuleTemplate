import { Fragment, useState, useEffect, useMemo, useRef, useCallback } from "react"
import "./react-table-meta"
import { useTranslation } from "../hooks/useTranslation"
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  ColumnDef,
  SortingState,
  RowSelectionState,
} from "@tanstack/react-table"
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Trash2
} from "lucide-react"
import { Button } from "../primitives/button"
import { Input } from "../primitives/input"
import { Checkbox } from "../primitives/checkbox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../primitives/select"

const EMPTY_FILTERS: Record<string, string> = {}

interface ServerDataTableProps<TData> {
  columns: ColumnDef<TData, any>[]
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
  onRowSelect?: (row: TData | null) => void
  selectedRow?: TData | null
  isEditMode?: boolean
  onBulkDelete?: (rows: TData[]) => void
  title?: string
  /** Render the per-column filter row. Default true. Set false for read-only tables
   *  (e.g. the audit trail) whose data source has no server-side filtering. */
  showFilters?: boolean
}

export function ServerDataTable<TData extends { id: string | number }>({
  columns,
  data,
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  onSortChange,
  onFilterChange,
  filters = EMPTY_FILTERS,
  onRowClick,
  onRowSelect,
  selectedRow,
  isEditMode = false,
  onBulkDelete,
  title,
  showFilters = true,
}: ServerDataTableProps<TData>) {
  const { t } = useTranslation()
  const [sorting, setSorting] = useState<SortingState>([])
  const [localFilters, setLocalFilters] = useState<Record<string, string>>({})
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const tableRef = useRef<HTMLDivElement>(null)
  const filterTimeoutRef = useRef<number | null>(null)
  const prevIsEditModeRef = useRef<boolean>(isEditMode)

  const totalPages = Math.ceil(total / pageSize)

  // ── User-resizable columns ─────────────────────────────────────────────────
  // A visible divider sits on each column boundary: drag it to resize, double-click it to
  // auto-fit the column to its content (Excel-style). Widths are DOM-driven and kept per
  // columnId; a column with no explicit width keeps the default auto layout.
  const MIN_COL_WIDTH = 60
  const [colWidths, setColWidths] = useState<Record<string, number>>({})

  const colStyle = (columnId: string): React.CSSProperties | undefined => {
    const w = colWidths[columnId]
    return w ? { width: w, minWidth: w, maxWidth: w } : undefined
  }

  const startColumnResize = useCallback((e: React.MouseEvent, columnId: string) => {
    e.preventDefault()
    e.stopPropagation()
    const th = (e.currentTarget as HTMLElement).closest('th') as HTMLElement | null
    const startW = th ? th.getBoundingClientRect().width : (colWidths[columnId] ?? 120)
    const startX = e.clientX
    const onMove = (ev: MouseEvent) => {
      const w = Math.max(MIN_COL_WIDTH, Math.round(startW + (ev.clientX - startX)))
      setColWidths((prev) => ({ ...prev, [columnId]: w }))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [colWidths])

  const autofitColumn = useCallback((columnId: string) => {
    const root = tableRef.current
    if (!root || typeof document === 'undefined') return
    const esc = (window as any).CSS?.escape ? (window as any).CSS.escape(columnId) : columnId.replace(/"/g, '\\"')
    const cells = root.querySelectorAll<HTMLElement>(`[data-col="${esc}"]`)
    let max = MIN_COL_WIDTH
    cells.forEach((cell) => {
      const cs = window.getComputedStyle(cell)
      const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
      // scrollWidth captures the full content even when the column is currently clipped,
      // so the fitted width always shows the complete content.
      max = Math.max(max, Math.ceil(cell.scrollWidth + pad + 2))
    })
    setColWidths((prev) => ({ ...prev, [columnId]: max }))
  }, [])

  const getColumnId = (columnDef: ColumnDef<TData, any>) =>
    ((columnDef as any).accessorKey || (columnDef as any).id) as string | undefined

  const isNarrowIdOrFkColumn = (columnDef: ColumnDef<TData, any>) => {
    const columnId = getColumnId(columnDef)
    if (columnId === "id") return true
    // FK columns that render a resolved label via a custom `cell` (e.g. "Cluster 1 (1)")
    // must size to content — only raw-id FK columns get the narrow 90px treatment.
    return !!columnId && columnId.endsWith("_fk") && !(columnDef as any).cell
  }

  const getNarrowColumnClassName = (columnDef: ColumnDef<TData, any>) => {
    if (!isNarrowIdOrFkColumn(columnDef)) return ""
    return "ideable:w-[90px] ideable:max-w-[90px] ideable:whitespace-nowrap ideable:overflow-hidden"
  }

  const getNarrowColumnAlignClassName = (columnDef: ColumnDef<TData, any>) => {
    if (!isNarrowIdOrFkColumn(columnDef)) return ""
    return "ideable:text-right"
  }

  // Preserve row selection when isEditMode changes
  useEffect(() => {
    // Don't clear selection when mode changes
    prevIsEditModeRef.current = isEditMode
  }, [isEditMode])

  // Filter columns: suppress FK cols when a dotted-path talking column already exists
  const visibleColumns = useMemo(() => {
    const getColId = (col: ColumnDef<TData, any>) => {
      return ((col as any).accessorKey || (col as any).id) as string | undefined
    }

    const allIds = columns.map(getColId).filter(Boolean) as string[]
    const dottedPrefixes = new Set(allIds.filter((id) => id.includes(".")).map((id) => id.split(".")[0]))

    const fkToPrefix: Record<string, string> = {
      user_fk: "user",
      profile_fk: "profile",
      role_fk: "role",
      permission_fk: "permission",
    }

    return columns.filter((col) => {
      const id = getColId(col)
      if (!id) return true

      if (id.endsWith("_fk")) {
        const prefix = fkToPrefix[id]
        if (prefix && dottedPrefixes.has(prefix)) {
          return false
        }
      }

      return true
    })
  }, [columns])

  const table = useReactTable({
    data,
    columns: visibleColumns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    pageCount: totalPages,
    state: {
      sorting,
      rowSelection,
    },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getRowId: (row) => row.id.toString(),
    enableRowSelection: true,
    enableMultiRowSelection: true,
  })

  const onSortChangeRef = useRef(onSortChange)

  useEffect(() => {
    onSortChangeRef.current = onSortChange
  }, [onSortChange])

  // Handle sorting changes
  useEffect(() => {
    if (sorting.length > 0 && onSortChangeRef.current) {
      const sort = sorting[0]
      onSortChangeRef.current(sort.id, sort.desc ? 'desc' : 'asc')
    } else if (sorting.length === 0 && onSortChangeRef.current) {
      onSortChangeRef.current('', null)
    }
  }, [sorting])

  // Handle filter changes with debounce for text inputs
  const handleFilterChange = (columnId: string, value: string) => {
    // Update local state immediately for responsive UI
    setLocalFilters(prev => {
      const newFilters = { ...prev }
      if (value === '' || value === 'all') {
        delete newFilters[columnId]
      } else {
        newFilters[columnId] = value
      }
      return newFilters
    })

    // Clear existing timeout
    if (filterTimeoutRef.current) {
      clearTimeout(filterTimeoutRef.current)
    }

    // Set new timeout to call parent's onFilterChange after 500ms
    // Only call for the specific column that changed
    filterTimeoutRef.current = setTimeout(() => {
      if (onFilterChange) {
        onFilterChange(columnId, value)
      }
    }, 500)
  }

  // Sync local filters with parent filters when parent updates
  useEffect(() => {
    setLocalFilters(filters)
  }, [filters])

  // Handle click outside to deselect
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node
      const element = target as Element
      
      // Check if click is inside a dialog, dialog overlay, M2M section, tabs, or header buttons
      const isInsideDialog = element.closest('[role="dialog"]')
      const isInsideDialogOverlay = element.closest('[data-radix-dialog-overlay]')
      const isInsideM2MSection = element.closest('[data-m2m-section]')
      const isInsideTabs = element.closest('[role="tablist"]') || element.closest('[role="tab"]') || element.closest('[role="tabpanel"]')
      const isInsideHeader = element.closest('header')
      const isInsideSidebar = element.closest('[data-sidebar]')
      
      if (tableRef.current && !tableRef.current.contains(target) && !isInsideDialog && !isInsideDialogOverlay && !isInsideM2MSection && !isInsideTabs && !isInsideHeader && !isInsideSidebar) {
        setRowSelection({})
        if (onRowSelect) {
          onRowSelect(null)
        }
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [onRowSelect])

  // Get selected rows for bulk delete
  const selectedRows = table.getSelectedRowModel().rows.map(row => row.original)

  // Helper to format column headers
  const formatColumnHeader = (columnId: string): string => {
    // Audit columns
    const auditMapping: Record<string, string> = {
      'timestamp': t('table.columns.createdAt'),
      'actor': t('table.columns.creator'),
      // Defensive: legacy au_* columns kept in case any caller still passes them
      'au_creation_timestamp': t('table.columns.createdAt'),
      'au_last_update_timestamp': t('table.columns.updatedAt'),
      'au_created_by_user': t('table.columns.creator'),
      'au_last_updated_by_user': t('table.columns.updater'),
    }
    
    if (auditMapping[columnId]) {
      return auditMapping[columnId]
    }

    // Remove _fk suffix and format
    let formatted = columnId.replace(/_fk$/, '')
    
    // Replace underscores with spaces and capitalize
    formatted = formatted
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
    
    return formatted
  }

  const abbreviateHeaderLabel = (label: string): string => {
    const wordMap: Record<string, string> = {
      Assignment: "Ass.",
      Profile: "Prof.",
      Description: "Desc.",
      Permission: "Perm.",
      Created: "Cr.",
      Updated: "Upd.",
      Creator: "Crt.",
      Updater: "Upd.",
      Timestamp: "Ts.",
    }

    return label
      .split(" ")
      .filter(Boolean)
      .map((word) => {
        if (wordMap[word]) return wordMap[word]
        if (word.length <= 4) return word
        return `${word.slice(0, 4)}.`
      })
      .join(" ")
  }

  // Determine filter type for column
  const getFilterType = (column: ColumnDef<TData, any>): 'text' | 'boolean' | 'none' => {
    const id = (column as any).accessorKey || (column as any).id
    
    // Skip filter for special columns
    if (id === '__select__' || id === 'actions') {
      return 'none'
    }

    // Check if column is boolean type (you may need to enhance this based on your data)
    const meta = (column as any).meta
    if (meta?.filterable === false) {
      return 'none'
    }
    if (meta?.type === 'boolean') {
      return 'boolean'
    }

    return 'text'
  }

  return (
    <div className="ideable:space-y-4" ref={tableRef}>
      {/* Header with title and controls */}
      <div className="ideable:flex ideable:items-center ideable:justify-between">
        {title && <h2 className="ideable:text-2xl ideable:font-bold">{title}</h2>}
        <div className="ideable:flex ideable:items-center ideable:gap-2">
          {isEditMode && selectedRows.length > 0 && onBulkDelete && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                if (confirm(`Delete ${selectedRows.length} selected items?`)) {
                  onBulkDelete(selectedRows)
                  setRowSelection({})
                }
              }}
            >
              <Trash2 className="ideable:mr-2 ideable:h-4 ideable:w-4" />
              {t('table.deleteSelected', { count: selectedRows.length.toString() })}
            </Button>
          )}
        </div>
      </div>

      {/* Page size selector */}
      <div className="ideable:flex ideable:items-center ideable:justify-between ideable:gap-2">
        <div className="ideable:flex ideable:items-center ideable:gap-2">
        <span className="ideable:text-sm ideable:text-muted-foreground">{t('table.rowsPerPage')}</span>
        <Select
          value={pageSize.toString()}
          onValueChange={(value) => onPageSizeChange(Number(value))}
        >
          <SelectTrigger className="ideable:w-[100px]" aria-label={t('table.rowsPerPage')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[10, 20, 50, 100, 200, 500].map((size) => (
              <SelectItem key={size} value={size.toString()}>
                {size}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        </div>

      </div>

      {/* Table */}
      <div className="ideable:relative ideable:overflow-auto ideable:rounded-md ideable:border">
        <table className="ideable:w-full">
          <thead className="ideable:sticky ideable:top-0 ideable:z-10 ideable:border-b ideable:bg-background">
            {table.getHeaderGroups().map((headerGroup) => (
              <Fragment key={headerGroup.id}>
                {/* Header row with sorting */}
                <tr key={`${headerGroup.id}-header`} className="ideable:border-b">
                  {headerGroup.headers.map((header, headerIndex) => {
                    const columnId = header.column.id
                    const isLastColumn = headerIndex === headerGroup.headers.length - 1
                    const isSorted = sorting.find(s => s.id === columnId)
                    const meta = (header.column.columnDef as any)?.meta
                    const isSortable = meta?.sortable !== false && columnId !== '__select__' && columnId !== 'actions'
                    const isNarrow = isNarrowIdOrFkColumn(header.column.columnDef)

                    const headerDef = header.column.columnDef.header
                    const fullHeaderLabel = typeof headerDef === 'string' ? headerDef : formatColumnHeader(columnId)
                    const headerLabel = isNarrow ? abbreviateHeaderLabel(fullHeaderLabel) : fullHeaderLabel
                    
                    return (
                      <th
                        key={header.id}
                        data-col={columnId}
                        style={colStyle(columnId)}
                        className={`ideable:relative ideable:h-12 ideable:px-4 ideable:text-left ideable:align-middle ideable:font-medium ideable:text-muted-foreground ${getNarrowColumnClassName(header.column.columnDef)} ${getNarrowColumnAlignClassName(header.column.columnDef)}`}
                      >
                        {header.isPlaceholder ? null : (
                          <div className="ideable:flex ideable:min-w-0 ideable:items-center ideable:gap-2">
                            {columnId === '__select__' && isEditMode ? (
                              <Checkbox
                                checked={table.getIsAllPageRowsSelected()}
                                onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                              />
                            ) : isSortable ? (
                              <Button
                                variant="ghost"
                                className={`ideable:h-8 ideable:p-0 ideable:font-medium ideable:min-w-0 ${isNarrow ? "ideable:w-full ideable:justify-end" : "ideable:justify-start"}`}
                                onClick={() => {
                                  const currentSort = sorting.find(s => s.id === columnId)
                                  if (!currentSort) {
                                    setSorting([{ id: columnId, desc: false }])
                                  } else if (!currentSort.desc) {
                                    setSorting([{ id: columnId, desc: true }])
                                  } else {
                                    setSorting([])
                                  }
                                }}
                              >
                                <span title={fullHeaderLabel}>{headerLabel}</span>
                                {isSorted ? (
                                  isSorted.desc ? (
                                    <ArrowDown className="ideable:ml-2 ideable:h-4 ideable:w-4" />
                                  ) : (
                                    <ArrowUp className="ideable:ml-2 ideable:h-4 ideable:w-4" />
                                  )
                                ) : (
                                  <ArrowUpDown className="ideable:ml-2 ideable:h-4 ideable:w-4" />
                                )}
                              </Button>
                            ) : (
                              <div className={`ideable:h-8 ideable:flex ideable:items-center ideable:min-w-0 ${isNarrow ? "ideable:w-full ideable:justify-end" : "ideable:justify-start"}`}>
                                <span title={fullHeaderLabel}>{headerLabel}</span>
                              </div>
                            )}
                          </div>
                        )}
                        {/* Divider sits ON the column boundary (translate-x-1/2). Skip the
                            last column: it has no column to its right, and a protruding
                            handle would add a few px of horizontal overflow to the table. */}
                        {columnId !== '__select__' && !isLastColumn && (
                          <div
                            role="separator"
                            aria-orientation="vertical"
                            title={t('table.resizeColumn')}
                            onMouseDown={(e) => startColumnResize(e, columnId)}
                            onDoubleClick={(e) => { e.preventDefault(); e.stopPropagation(); autofitColumn(columnId) }}
                            onClick={(e) => e.stopPropagation()}
                            className="ideable:group ideable:absolute ideable:top-0 ideable:right-0 ideable:z-20 ideable:flex ideable:h-full ideable:w-[7px] ideable:translate-x-1/2 ideable:cursor-col-resize ideable:items-stretch ideable:justify-center ideable:touch-none"
                          >
                            <span className="ideable:w-px ideable:bg-border ideable:group-hover:w-[2px] ideable:group-hover:bg-primary" />
                          </div>
                        )}
                      </th>
                    )
                  })}
                </tr>
                {/* Filter row */}
                {showFilters && (
                <tr key={`${headerGroup.id}-filter`} className="ideable:border-b">
                  {headerGroup.headers.map((header) => {
                    const column = header.column
                    const columnId = column.id
                    const filterType = getFilterType(column.columnDef)

                    return (
                      <th
                        key={`${header.id}-filter`}
                        data-col={columnId}
                        style={colStyle(columnId)}
                        className={`ideable:h-12 ideable:px-4 ${getNarrowColumnClassName(column.columnDef)} ${getNarrowColumnAlignClassName(column.columnDef)}`}
                      >
                        {filterType === 'text' && (
                          <Input
                            placeholder={t('table.filterPlaceholder')}
                            value={localFilters[columnId] || ''}
                            onChange={(e) => handleFilterChange(columnId, e.target.value)}
                            className={`ideable:h-8 ${isNarrowIdOrFkColumn(column.columnDef) ? "ideable:px-2" : ""}`}
                          />
                        )}
                        {filterType === 'boolean' && (
                          <Select
                            value={localFilters[columnId] || 'all'}
                            onValueChange={(value) => {
                              if (value === 'all') {
                                handleFilterChange(columnId, '')
                              } else {
                                handleFilterChange(columnId, value)
                              }
                            }}
                          >
                            <SelectTrigger className={`ideable:h-8 ${isNarrowIdOrFkColumn(column.columnDef) ? "ideable:px-2" : ""}`} aria-label={t('table.filterColumn')}>
                              <SelectValue placeholder={t('table.all')} />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="all">{t('table.all')}</SelectItem>
                              <SelectItem value="true">{t('table.true')}</SelectItem>
                              <SelectItem value="false">{t('table.false')}</SelectItem>
                            </SelectContent>
                          </Select>
                        )}
                      </th>
                    )
                  })}
                </tr>
                )}
              </Fragment>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                  className={`ideable:cursor-pointer ideable:border-b ideable:transition-colors ideable:hover:bg-muted/50 ${
                    selectedRow && (selectedRow as any).id === row.original.id ? 'ideable:bg-muted' : ''
                  }`}
                  onClick={() => {
                    if (onRowClick) {
                      onRowClick(row.original)
                    }
                    if (onRowSelect) {
                      onRowSelect(row.original)
                    }
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      data-col={cell.column.id}
                      style={colStyle(cell.column.id)}
                      className={`ideable:p-2 ideable:align-middle ideable:overflow-hidden ${getNarrowColumnClassName(cell.column.columnDef)} ${getNarrowColumnAlignClassName(cell.column.columnDef)}`}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td
                  colSpan={visibleColumns.length}
                  className="ideable:h-24 ideable:text-center ideable:text-muted-foreground"
                >
                  {t('table.noResults')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Footer with pagination */}
      <div className="ideable:flex ideable:items-center ideable:justify-between ideable:border-t ideable:bg-background ideable:py-2">
        <div className="ideable:text-sm ideable:text-muted-foreground">
          {t('table.showing', {
            from: (data.length > 0 ? ((page - 1) * pageSize) + 1 : 0).toString(),
            to: Math.min(page * pageSize, total).toString(),
            total: total.toString(),
          })}
        </div>
        <div className="ideable:flex ideable:items-center ideable:gap-2">
          <Button
            variant="outline"
            size="sm"
            aria-label={t('table.firstPage')}
            onClick={() => onPageChange(1)}
            disabled={page === 1}
          >
            <ChevronsLeft className="ideable:h-4 ideable:w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            aria-label={t('table.previousPage')}
            onClick={() => onPageChange(page - 1)}
            disabled={page === 1}
          >
            <ChevronLeft className="ideable:h-4 ideable:w-4" />
          </Button>
          <div className="ideable:text-sm ideable:font-medium">
            {t('table.page', { page: page.toString(), total: totalPages.toString() })}
          </div>
          <Button
            variant="outline"
            size="sm"
            aria-label={t('table.nextPage')}
            onClick={() => onPageChange(page + 1)}
            disabled={page === totalPages}
          >
            <ChevronRight className="ideable:h-4 ideable:w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            aria-label={t('table.lastPage')}
            onClick={() => onPageChange(totalPages)}
            disabled={page === totalPages}
          >
            <ChevronsRight className="ideable:h-4 ideable:w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
