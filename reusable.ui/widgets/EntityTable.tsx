import { useMemo, type ReactNode } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import { ServerDataTable } from "./ServerDataTable"
import { useEntityQuery, type EntityTransport, type UseEntityQueryResult } from "../hooks/useEntityQuery"

/**
 * A server-side table for ONE declared entity, driven by its descriptor.
 *
 * Usable on its own — that is the point. `StandardEntityPage` composes it, and so can a page a
 * module writes itself, which is what keeps "custom page reusing standard elements" from meaning
 * copy-paste. A sealed page would have made the escape hatch a fork.
 *
 * It renders `ServerDataTable`; it does not reimplement one. What it adds is the wiring every
 * entity table would otherwise repeat: the descriptor fetch, the request, and the mapping from
 * the table's paging and sorting state onto the query the server expects.
 */
export interface EntityTableProps<Row extends { id: string | number }> {
  /** The entity key, as declared in the module's registry — `items`, `sub_item`, … */
  entityKey: string
  /** How to reach this module's API. */
  transport: EntityTransport
  /**
   * The columns to draw. Omit to render one column per field the descriptor reports, labelled by
   * `labelFor` — useful for a quick table, and deliberately not the recommended path: a real page
   * chooses its columns, their order and their cells.
   */
  columns?: ColumnDef<Row, any>[]
  /** Translate a field name into a column header. Defaults to the field name itself. */
  labelFor?: (field: string) => string
  /** Rendered above the table. */
  title?: string
  /** Rendered at the right end of the header row, beside the title. */
  headerActions?: ReactNode
  isEditMode?: boolean
  onRowClick?: (row: Row) => void
  onRowSelect?: (row: Row | null) => void
  selectedRow?: Row | null
  onBulkDelete?: (rows: Row[]) => void
  /** Don't fetch until true — for a table inside a popup that has not been opened. */
  enabled?: boolean
  /** Fixed query params merged into every request, invisible to the table's own filter row — see
   *  `useEntityQuery`'s `UseEntityQueryOptions.baseParams`. For a detail table scoped to a
   *  selected parent row, e.g. `{ item_fk: selected.id }`. */
  baseParams?: Record<string, unknown>
  /** Receives the query result, so a parent can refresh after a write or read the descriptor. */
  onReady?: (query: UseEntityQueryResult<Row>) => void
  defaultPageSize?: number
}

export function EntityTable<Row extends { id: string | number }>({
  entityKey,
  transport,
  columns,
  labelFor,
  title,
  headerActions,
  isEditMode,
  onRowClick,
  onRowSelect,
  selectedRow,
  onBulkDelete,
  enabled = true,
  onReady,
  defaultPageSize,
  baseParams,
}: EntityTableProps<Row>) {
  const query = useEntityQuery<Row>(entityKey, transport, { enabled, defaultPageSize, baseParams })
  const { descriptor, rows, total, table } = query

  // Reported after render rather than during, so a parent that calls `refresh()` in response
  // cannot re-enter this component mid-render.
  if (onReady) queueMicrotask(() => onReady(query))

  const resolved = useMemo<ColumnDef<Row, any>[]>(() => {
    if (columns) return columns
    const fields = descriptor?.fields ?? []
    return fields.map((field) => ({
      accessorKey: field,
      header: labelFor ? labelFor(field) : field,
      // Only what the server will accept: a column the whitelist does not name cannot be
      // filtered or sorted, and offering the control would produce a 422 on first use.
      enableSorting: descriptor?.sortable.includes(field) ?? false,
      enableColumnFilter: descriptor?.filterable.includes(field) ?? false,
    })) as ColumnDef<Row, any>[]
  }, [columns, descriptor, labelFor])

  return (
    <ServerDataTable<Row>
      columns={resolved}
      data={rows}
      total={total}
      page={table.page}
      pageSize={table.pageSize}
      onPageChange={table.setPage}
      // `setPageSize` is the hook's own handler, which already resets to page 1 — doing it here
      // too would be a second place that has to stay right.
      onPageSizeChange={table.setPageSize}
      onSortChange={table.onSortChange}
      onFilterChange={table.onFilterChange}
      filters={table.filters}
      onRowClick={onRowClick}
      onRowSelect={onRowSelect}
      selectedRow={selectedRow}
      isEditMode={isEditMode}
      onBulkDelete={onBulkDelete}
      title={title}
      headerActions={headerActions}
    />
  )
}
