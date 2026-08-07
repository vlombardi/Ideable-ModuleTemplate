import { Fragment, useState, useEffect, useMemo, useRef } from "react"
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
}

export function ServerDataTable<TData extends { id: number }>({
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
}: ServerDataTableProps<TData>) {
  const { t } = useTranslation()
  const [sorting, setSorting] = useState<SortingState>([])
  const [localFilters, setLocalFilters] = useState<Record<string, string>>({})
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const tableRef = useRef<HTMLDivElement>(null)
  const filterTimeoutRef = useRef<number | null>(null)
  const prevIsEditModeRef = useRef<boolean>(isEditMode)

  const totalPages = Math.ceil(total / pageSize)

  const isNarrowIdOrFkColumn = (columnId: string) => {
    return columnId === "id" || columnId.endsWith("_fk")
  }

  const getNarrowColumnClassName = (columnId: string) => {
    if (!isNarrowIdOrFkColumn(columnId)) return ""
    return "ideable:w-[90px] ideable:max-w-[90px] ideable:whitespace-nowrap ideable:overflow-hidden"
  }

  const getNarrowColumnAlignClassName = (columnId: string) => {
    if (!isNarrowIdOrFkColumn(columnId)) return ""
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
                  {headerGroup.headers.map((header) => {
                    const columnId = header.column.id
                    const isSorted = sorting.find(s => s.id === columnId)
                    const meta = (header.column.columnDef as any)?.meta
                    const isSortable = meta?.sortable !== false && columnId !== '__select__' && columnId !== 'actions'
                    const isNarrow = isNarrowIdOrFkColumn(columnId)

                    const headerDef = header.column.columnDef.header
                    const fullHeaderLabel = typeof headerDef === 'string' ? headerDef : formatColumnHeader(columnId)
                    const headerLabel = isNarrow ? abbreviateHeaderLabel(fullHeaderLabel) : fullHeaderLabel
                    
                    return (
                      <th
                        key={header.id}
                        className={`ideable:h-12 ideable:px-4 ideable:text-left ideable:align-middle ideable:font-medium ideable:text-muted-foreground ${getNarrowColumnClassName(columnId)} ${getNarrowColumnAlignClassName(columnId)}`}
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
                      </th>
                    )
                  })}
                </tr>
                {/* Filter row */}
                <tr key={`${headerGroup.id}-filter`} className="ideable:border-b">
                  {headerGroup.headers.map((header) => {
                    const column = header.column
                    const columnId = column.id
                    const filterType = getFilterType(column.columnDef)

                    return (
                      <th
                        key={`${header.id}-filter`}
                        className={`ideable:h-12 ideable:px-4 ${getNarrowColumnClassName(columnId)} ${getNarrowColumnAlignClassName(columnId)}`}
                      >
                        {filterType === 'text' && (
                          <Input
                            placeholder={t('table.filterPlaceholder')}
                            value={localFilters[columnId] || ''}
                            onChange={(e) => handleFilterChange(columnId, e.target.value)}
                            className={`ideable:h-8 ${isNarrowIdOrFkColumn(columnId) ? "ideable:px-2" : ""}`}
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
                            <SelectTrigger className={`ideable:h-8 ${isNarrowIdOrFkColumn(columnId) ? "ideable:px-2" : ""}`} aria-label={t('table.filterColumn')}>
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
                      className={`ideable:p-2 ideable:align-middle ${getNarrowColumnClassName(cell.column.id)} ${getNarrowColumnAlignClassName(cell.column.id)}`}
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
