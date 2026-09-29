import { useCallback, useEffect, useMemo, useState } from "react"
import { useServerTableState, type ServerTableOptions } from "./useServerTableState"

/**
 * What the backend says is QUERYABLE about an entity — `GET <api>/entities/{key}`.
 *
 * Deliberately carries no labels and no renderers. The backend owns what can be filtered, sorted
 * and paged because it is the side that enforces it; the page owns how a column is labelled and
 * drawn because a label needs translating and a cell may need arbitrary React. A payload carrying
 * both would be two sources of truth for one of them.
 */
export interface EntityDescriptor {
  key: string
  permission_resource: string
  filterable: string[]
  sortable: string[]
  versioned: boolean
  /** True when the backend mounts no create/update/delete route for this entity at all — e.g.
   *  host_app's `permissions`, sourced only from a module's authorization.yaml catalog. A page
   *  reads this to decide whether to offer a create/edit/delete affordance at all. */
  read_only: boolean
  max_page_size: number
  fields: string[]
}

export interface EntityPage<Row> {
  items: Row[]
  total: number
  total_is_exact?: boolean
  next_after_id?: number | null
}

/**
 * The one thing a consumer must supply: how to reach ITS module's API.
 *
 * Four verbs, because a table that can only read is half a page. Auth, the base URL and the error
 * mapping stay on the module's side of this interface — `@ideable/ui` must not know how a module
 * authenticates or where its API lives.
 */
export interface EntityTransport {
  /** GET `path` with `params`, returning parsed JSON. Throws on a non-2xx response. */
  get: (path: string, params?: Record<string, unknown>) => Promise<unknown>
  post?: (path: string, body: unknown) => Promise<unknown>
  put?: (path: string, body: unknown) => Promise<unknown>
  delete?: (path: string) => Promise<void>
}

export interface UseEntityQueryOptions extends ServerTableOptions {
  /** Skip fetching until true — for a table inside a popup that has not been opened yet. */
  enabled?: boolean
  /**
   * Fixed query params merged into every request, invisible to the table's own filter row.
   *
   * For a DETAIL table scoped to a parent — `sub_items` under the selected `items` row — the
   * scoping value (`item_fk`) is the CALLER's to fix, not the viewer's to type: it must reach
   * every request the same way paging and sort do, and it must never appear as an editable filter
   * a viewer could clear. Merged UNDER `debouncedFilters` so a column that is both base-scoped and
   * independently filterable still lets the viewer narrow further within the fixed scope.
   */
  baseParams?: Record<string, unknown>
}

export interface UseEntityQueryResult<Row> {
  descriptor: EntityDescriptor | null
  rows: Row[]
  total: number
  loading: boolean
  error: Error | null
  /** Re-fetch the current page — after a create, update or delete. */
  refresh: () => void
  table: ReturnType<typeof useServerTableState>
}

/**
 * Everything a table needs to show one entity: its descriptor, a page of rows, and the
 * page/sort/filter state that produced them.
 *
 * ENTITY-AGNOSTIC BY CONSTRUCTION. It is given a key and a transport, never a typed service — so
 * one hook serves every entity a module declares, and a module that adds an entity writes no
 * fetching code at all. `useServerTableState` still owns the paging, sorting and filter debounce;
 * this adds the descriptor and the request.
 *
 * The descriptor is fetched once per key and the rows on every state change, because the first is
 * a property of the datamodel and the second is a property of the question being asked.
 */
export function useEntityQuery<Row = Record<string, unknown>>(
  entityKey: string,
  transport: EntityTransport,
  options?: UseEntityQueryOptions,
): UseEntityQueryResult<Row> {
  const table = useServerTableState(options)
  const [descriptor, setDescriptor] = useState<EntityDescriptor | null>(null)
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  const enabled = options?.enabled !== false
  const refresh = useCallback(() => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    transport
      .get(`/entities/${entityKey}`)
      .then((payload) => {
        if (!cancelled) setDescriptor(payload as EntityDescriptor)
      })
      .catch((cause) => {
        // A missing descriptor is not a transient error: the entity is not declared, or the caller
        // may not see it. Surfaced rather than retried, so a page says so instead of spinning.
        if (!cancelled) setError(cause instanceof Error ? cause : new Error(String(cause)))
      })
    return () => {
      cancelled = true
    }
  }, [entityKey, transport, enabled])

  // `useServerTableState.queryParams` carries paging and sort ONLY — a page that filters has
  // always merged its own filter values in. `useEntityQuery` does it here, once, so no consumer
  // can forget: measured 2026-09-18, the filter row rendered and typed into and narrowed nothing,
  // because the values never left the browser.
  //
  // DEBOUNCED, not raw: `filters` updates per keystroke and drives the inputs; `debouncedFilters`
  // is what a request should carry, or every character typed is a query.
  const { queryParams: pageParams, debouncedFilters } = table
  const baseParams = options?.baseParams
  const queryParams = useMemo(
    () => ({ ...pageParams, ...baseParams, ...debouncedFilters }),
    [pageParams, baseParams, debouncedFilters],
  )

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    setLoading(true)
    transport
      .get(`/${entityKey}`, queryParams as Record<string, unknown>)
      .then((payload) => {
        if (cancelled) return
        const page = payload as EntityPage<Row>
        setRows(page.items ?? [])
        setTotal(page.total ?? 0)
        setError(null)
      })
      .catch((cause) => {
        if (cancelled) return
        // The rows are cleared on failure deliberately: leaving the previous page on screen under
        // a new filter shows data that does not answer the question that was asked.
        setRows([])
        setTotal(0)
        setError(cause instanceof Error ? cause : new Error(String(cause)))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [entityKey, transport, queryParams, reloadToken, enabled])

  return useMemo(
    () => ({ descriptor, rows, total, loading, error, refresh, table }),
    [descriptor, rows, total, loading, error, refresh, table],
  )
}
