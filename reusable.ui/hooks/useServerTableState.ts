import { useMemo, useState } from "react"

export function useServerTableState(options?: { defaultPageSize?: number }) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(options?.defaultPageSize ?? 50)
  const [sortColumn, setSortColumn] = useState<string>("")
  const [sortDirection, setSortDirection] = useState<"asc" | "desc" | null>(null)
  const [filters, setFilters] = useState<Record<string, string>>({})

  const queryParams = useMemo(() => {
    return {
      skip: (page - 1) * pageSize,
      limit: pageSize,
      ...(sortColumn && sortDirection ? { sort_by: sortColumn, sort_order: sortDirection } : {}),
    }
  }, [page, pageSize, sortColumn, sortDirection])

  const onSortChange = (columnId: string, direction: "asc" | "desc" | null) => {
    setSortColumn(columnId)
    setSortDirection(direction)
    setPage(1)
  }

  const onFilterChange = (columnId: string, value: string) => {
    setFilters(prev => {
      const next = { ...prev }
      if (value === "" || value === "all") {
        delete next[columnId]
      } else {
        next[columnId] = value
      }
      return next
    })
    setPage(1)
  }

  const onPageSizeChange = (size: number) => {
    setPageSize(size)
    setPage(1)
  }

  return {
    page,
    pageSize,
    sortColumn,
    sortDirection,
    filters,
    setPage,
    setPageSize: onPageSizeChange,
    setSortColumn,
    setSortDirection,
    setFilters,
    queryParams,
    onSortChange,
    onFilterChange,
  }
}
