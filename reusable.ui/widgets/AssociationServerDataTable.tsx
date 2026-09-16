import { useEffect, useMemo } from "react"
import { useTranslation } from "../hooks/useTranslation"
import { useQuery } from "@tanstack/react-query"
import { ColumnDef } from "@tanstack/react-table"
import { ServerDataTable } from "./ServerDataTable"
import { useServerTableState } from "../hooks/useServerTableState"

type PageResult<T> = {
  items: T[]
  total: number
  page: number
  size: number
  pages: number
}

/**
 * `id` is `string | number` because association rows are addressed by a COMPOSITE id —
 * `<left_fk>__<right_fk>` — while plain entities carry a numeric primary key. The widget itself
 * never reads `TData["id"]`, so the constraint only ever existed to describe the data; describing
 * it as `number` made every association table a type error.
 *
 * Those errors were invisible: the build transpiles without typechecking, so the failed generic
 * silently poisoned the surrounding JSX and TypeScript then reported the identifiers used only
 * there as "declared but never read" — 20 errors in Permissions.tsx from this one line.
 */
export function AssociationServerDataTable<TData extends { id: string | number }>(props: {
  title: string
  columns: ColumnDef<TData, any>[]
  enabled: boolean
  queryKeyBase: any[]
  queryFn: (params: Record<string, any>) => Promise<PageResult<TData>>
  baseParams?: Record<string, any>
  defaultPageSize?: number
  isEditMode?: boolean
  selectedRow?: TData | null
  onRowSelect?: (row: TData | null) => void
  onTotalChange?: (total: number) => void
  onItemsChange?: (items: TData[]) => void
}) {
  const {
    title,
    columns,
    enabled,
    queryKeyBase,
    queryFn,
    baseParams,
    defaultPageSize,
    isEditMode,
    selectedRow,
    onRowSelect,
    onTotalChange,
    onItemsChange,
  } = props

  const { t } = useTranslation()
  const tableState = useServerTableState({ defaultPageSize })

  const inferFkFilterKeyFromDotted = (dottedKey: string): string | null => {
    const prefix = dottedKey.split(".")[0]
    const map: Record<string, string> = {
      user: "user_fk",
      profile: "profile_fk",
      role: "role_fk",
      permission: "permission_fk",
    }
    return map[prefix] ?? null
  }

  const extractSingleIdToken = (value: string): { id: string; remainingText: string } | null => {
    const matches = value.match(/\(\d+\)/g) || []
    if (matches.length !== 1) return null

    const id = matches[0].slice(1, -1)
    const remainingText = value.replace(matches[0], "").trim()
    return { id, remainingText }
  }

  const apiFilterParams = useMemo(() => {
    const dotted: Record<string, string> = {}
    const plain: Record<string, string> = {}

    for (const [key, value] of Object.entries(tableState.filters)) {
      if (key.includes(".")) {
        const fkKey = inferFkFilterKeyFromDotted(key)
        const parsed = extractSingleIdToken(value)

        if (fkKey && parsed) {
          plain[fkKey] = parsed.id
          if (parsed.remainingText) {
            dotted[key] = parsed.remainingText
          }
          continue
        }

        dotted[key] = value
      } else {
        plain[key] = value
      }
    }

    return {
      plain,
      dottedJson: Object.keys(dotted).length > 0 ? JSON.stringify(dotted) : undefined,
    }
  }, [tableState.filters])

  const mergedParams = useMemo(() => {
    return {
      ...(baseParams || {}),
      ...tableState.queryParams,
      ...apiFilterParams.plain,
      ...(apiFilterParams.dottedJson ? { filters: apiFilterParams.dottedJson } : {}),
    }
  }, [baseParams, tableState.queryParams, apiFilterParams])

  const queryKey = useMemo(() => {
    return [...queryKeyBase, mergedParams]
  }, [queryKeyBase, mergedParams])

  const { data, isError, error, isFetching } = useQuery({
    queryKey,
    queryFn: () => queryFn(mergedParams),
    enabled,
    placeholderData: (previousData) => previousData,
  })

  useEffect(() => {
    if (data) {
      onTotalChange?.(data.total)
      onItemsChange?.(data.items)
    }
  }, [data, onItemsChange, onTotalChange])

  return (
    <div className="ideable:space-y-2">
      {isError && (
        <div className="ideable:text-sm ideable:text-destructive">
          {error instanceof Error ? error.message : t('table.errorLoading')}
        </div>
      )}
      <div className="ideable:relative">
        {isFetching && (
          <div className="ideable:absolute ideable:inset-0 ideable:z-10 ideable:flex ideable:items-center ideable:justify-center ideable:bg-background/50 ideable:pointer-events-none">
            <div className="ideable:text-sm ideable:text-muted-foreground">{t('table.updating')}</div>
          </div>
        )}
        <ServerDataTable<TData>
          columns={columns}
          data={data?.items || []}
          total={data?.total || 0}
          page={tableState.page}
          pageSize={tableState.pageSize}
          onPageChange={tableState.setPage}
          onPageSizeChange={tableState.setPageSize}
          onSortChange={tableState.onSortChange}
          onFilterChange={tableState.onFilterChange}
          filters={tableState.filters}
          onRowSelect={onRowSelect}
          selectedRow={selectedRow}
          isEditMode={!!isEditMode}
          title={title}
        />
      </div>
    </div>
  )
}
