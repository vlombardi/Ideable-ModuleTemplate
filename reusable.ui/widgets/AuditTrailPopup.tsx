import { useState, useEffect, useCallback, useMemo } from "react"
import { Link, Unlink } from "lucide-react"
import DraggableResizablePopup from "./DraggableResizablePopup"
import { ServerDataTable } from "./ServerDataTable"
import type { ColumnDef } from "@tanstack/react-table"
import { useTranslation } from "../hooks/useTranslation"

const OPERATION_LABEL_KEYS: Record<number, string> = {
  0: "auditTrail.opInsert",
  1: "auditTrail.opUpdate",
  2: "auditTrail.opDelete",
  3: "auditTrail.opAssociate",
  4: "auditTrail.opDisassociate",
}

const OPERATION_STYLES: Record<number, string> = {
  0: "ideable:bg-green-100 ideable:text-green-800",
  1: "ideable:bg-blue-100 ideable:text-blue-800",
  2: "ideable:bg-red-100 ideable:text-red-800",
  3: "ideable:bg-purple-100 ideable:text-purple-800",
  4: "ideable:bg-amber-100 ideable:text-amber-800",
}

export interface VersionRecord {
  transaction_id: number
  operation_type: number
  timestamp?: string | null
  actor?: string | null
  actor_id?: number | null
  [key: string]: unknown
}

export interface VersionPage {
  items: VersionRecord[]
  total: number
  page: number
  size: number
  pages: number
}

export interface AuditPageParams {
  skip: number
  limit: number
  sort_by?: string
  sort_order?: "asc" | "desc"
  /** Column filters keyed by server field (actor / operation_type / timestamp). The
   *  fetcher serialises non-empty values as query params; the history endpoint applies
   *  case-insensitive substring matches. */
  filters?: Record<string, string>
}

interface AuditTab {
  label: string
  columns: string[]
  fetchPage: (params: AuditPageParams) => Promise<VersionPage>
}

interface AuditTrailPopupProps {
  open: boolean
  onClose: () => void
  entityLabel: string
  tabs: AuditTab[]
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-"
  if (typeof value === "boolean") return value ? "true" : "false"
  if (value instanceof Date) return value.toLocaleString()
  return String(value)
}

function formatTimestamp(value: unknown): string {
  if (!value) return "-"
  const date = value instanceof Date ? value : new Date(String(value))
  if (isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function formatHeader(col: string, t: (key: string) => string): string {
  const auditHeaderMap: Record<string, string> = {
    timestamp: t("table.columns.createdAt"),
    actor: t("table.columns.creator"),
  }
  if (auditHeaderMap[col]) return auditHeaderMap[col]
  return col
    .replace(/_fk$/, "")
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ")
}

function computeDiffs(
  current: VersionRecord,
  previous: VersionRecord | undefined,
  columns: string[],
  t: (key: string, vars?: Record<string, string>) => string,
): string[] {
  // Association-change rows show the peer entity info instead of field diffs
  if (current.operation_type === 3 || current.operation_type === 4) {
    const peerLabel = formatValue(current.peer_entity_label)
    const peerType = formatValue(current.peer_entity_type)
    const assocName = formatValue(current.association_name)
    const parts: string[] = []
    if (assocName && assocName !== "-") parts.push(t("auditTrail.assocLabel", { name: assocName }))
    if (peerType && peerType !== "-") parts.push(t("auditTrail.assocType", { type: peerType }))
    if (peerLabel && peerLabel !== "-") parts.push(t("auditTrail.assocEntity", { label: peerLabel }))
    return parts.length ? parts : [current.operation_type === 3 ? t("auditTrail.associated") : t("auditTrail.disassociated")]
  }

  const diffs: string[] = []
  const skipKeys = new Set([
    "transaction_id",
    "operation_type",
    "end_transaction_id",
    "timestamp",
    "actor",
    "actor_id",
    "event",
    "client_ip",
    "user_agent",
    "request_method",
    "request_path",
    "association_name",
    "peer_entity_type",
    "peer_entity_id",
    "peer_entity_label",
  ])

  if (!previous) {
    if (current.operation_type === 0) {
      for (const col of columns) {
        if (skipKeys.has(col)) continue
        const val = formatValue(current[col])
        if (val !== "-") diffs.push(`${formatHeader(col, t)}: ${val}`)
      }
      return diffs.length ? diffs : [t("auditTrail.created")]
    }
    return ["—"]
  }

  if (current.operation_type === 2) {
    return [t("auditTrail.deleted")]
  }

  for (const col of columns) {
    if (skipKeys.has(col)) continue
    const cur = current[col]
    const prev = previous[col]
    if (cur !== prev) {
      diffs.push(`${formatHeader(col, t)}: ${formatValue(prev)} → ${formatValue(cur)}`)
    }
  }

  return diffs.length ? diffs : [t("auditTrail.noVisibleChanges")]
}

function getActor(v: VersionRecord): string {
  const actor = v.actor
  if (!actor) return "—"
  const actorId = v.actor_id
  if (actorId !== null && actorId !== undefined) return `${actor}(${actorId})`
  return String(actor)
}

function getEventAction(v: VersionRecord): string | null {
  const evt = v.event
  return evt && typeof evt === "string" ? evt : null
}

function AssociationIcon({ operationType }: { operationType: number }) {
  if (operationType === 3) {
    return <Link className="ideable:h-3 ideable:w-3" />
  }
  if (operationType === 4) {
    return <Unlink className="ideable:h-3 ideable:w-3" />
  }
  return null
}

const DEFAULT_PAGE_SIZE = 20

function AuditTable({ columns, fetchPage }: { columns: string[]; fetchPage: (params: AuditPageParams) => Promise<VersionPage> }) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<VersionRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [sortBy, setSortBy] = useState<string>("timestamp")
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc")
  // Column filters keyed by ServerDataTable column id (when / who / operation).
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ServerDataTable column id → server field, for both sort and filter.
  const SERVER_FIELD: Record<string, string> = { when: "timestamp", who: "actor", operation: "operation_type" }

  const load = useCallback(
    async (p: number, ps: number, sb: string, so: "asc" | "desc", flt: Record<string, string>) => {
      setLoading(true)
      setError(null)
      try {
        const serverFilters: Record<string, string> = {}
        for (const [colId, val] of Object.entries(flt)) {
          const field = SERVER_FIELD[colId]
          if (field && val && val.trim() !== "") serverFilters[field] = val
        }
        const result = await fetchPage({
          skip: (p - 1) * ps,
          limit: ps,
          sort_by: sb,
          sort_order: so,
          filters: serverFilters,
        })
        setVersions(result.items)
        setTotal(result.total)
      } catch (e) {
        setError(e instanceof Error ? e.message : t("table.errorLoading"))
      } finally {
        setLoading(false)
      }
    },
    [fetchPage, t],
  )

  useEffect(() => {
    load(page, pageSize, sortBy, sortOrder, filters)
  }, [load, page, pageSize, sortBy, sortOrder, filters])

  const handleSortChange = (columnId: string, dir: "asc" | "desc" | null) => {
    const field = SERVER_FIELD[columnId]
    if (!field || !dir) {
      setSortBy("timestamp"); setSortOrder("desc")
    } else {
      setSortBy(field); setSortOrder(dir)
    }
    setPage(1)
  }

  const handleFilterChange = (columnId: string, value: string) => {
    setFilters((prev) => {
      const next = { ...prev }
      if (value && value.trim() !== "") next[columnId] = value
      else delete next[columnId]
      return next
    })
    setPage(1)
  }

  // Precompute each row's diffs (needs the neighbouring field-version) + operation metadata,
  // and give every row a stable `id` for ServerDataTable.
  type AuditRow = VersionRecord & {
    id: string
    __diffs: string[]
    __eventAction: string | null
    __isAssociation: boolean
  }
  const rows: AuditRow[] = useMemo(
    () =>
      versions.map((v, idx) => {
        let previous: VersionRecord | undefined = undefined
        for (let i = idx + 1; i < versions.length; i++) {
          if (versions[i].operation_type !== 3 && versions[i].operation_type !== 4) {
            previous = versions[i]
            break
          }
        }
        return {
          ...v,
          id: `${v.transaction_id}-${idx}`,
          __diffs: computeDiffs(v, previous, columns, t),
          __eventAction: getEventAction(v),
          __isAssociation: v.operation_type === 3 || v.operation_type === 4,
        }
      }),
    [versions, columns, t],
  )

  const auditColumns: ColumnDef<AuditRow, unknown>[] = useMemo(
    () => [
      {
        id: "when", accessorKey: "timestamp", header: t("auditTrail.colWhen"),
        cell: ({ row }) => <span className="ideable:whitespace-nowrap">{formatTimestamp(row.original.timestamp)}</span>,
        meta: { sortable: true },
      },
      {
        id: "who", accessorKey: "actor", header: t("auditTrail.colWho"),
        cell: ({ row }) => <span className="ideable:whitespace-nowrap">{getActor(row.original)}</span>,
        meta: { sortable: true },
      },
      {
        id: "operation", accessorKey: "operation_type", header: t("auditTrail.colOp"),
        cell: ({ row }) => {
          const v = row.original
          return (
            <>
              <span
                className={[
                  "ideable:inline-flex ideable:items-center ideable:gap-1 ideable:rounded-full ideable:px-2 ideable:py-0.5 ideable:text-xs ideable:font-medium",
                  OPERATION_STYLES[v.operation_type] ?? "ideable:bg-slate-100 ideable:text-slate-800",
                ].join(" ")}
              >
                {v.__isAssociation && <AssociationIcon operationType={v.operation_type} />}
                {OPERATION_LABEL_KEYS[v.operation_type] ? t(OPERATION_LABEL_KEYS[v.operation_type]) : String(v.operation_type)}
              </span>
              {v.__eventAction &&
                v.__eventAction !== "model_created" &&
                v.__eventAction !== "model_updated" &&
                v.__eventAction !== "model_deleted" && (
                  <span className="ideable:block ideable:text-[10px] ideable:text-muted-foreground ideable:mt-0.5">
                    {v.__eventAction}
                  </span>
                )}
            </>
          )
        },
        meta: { sortable: true },
      },
      {
        id: "changes", header: t("auditTrail.colWhat"),
        cell: ({ row }) => (
          <ul className="ideable:space-y-0.5">
            {row.original.__diffs.map((d, dIdx) => (
              <li key={dIdx} className="ideable:text-xs">{d}</li>
            ))}
          </ul>
        ),
        meta: { sortable: false, filterable: false },
      },
    ],
    [t],
  )

  if (error) {
    return (
      <p className="ideable:text-sm ideable:text-red-600 ideable:py-4 ideable:text-center">{error}</p>
    )
  }

  if (loading && rows.length === 0) {
    return (
      <p className="ideable:text-sm ideable:text-muted-foreground ideable:py-4 ideable:text-center">
        {t("common.loading")}
      </p>
    )
  }

  // The audit table is the shared ServerDataTable (column resize, sort, filter, pagination,
  // dark-mode surface). Filters on When/Who/Op map to the history endpoint's
  // actor/operation_type/timestamp query params; the Changes column is not filterable.
  return (
    <ServerDataTable<AuditRow>
      columns={auditColumns}
      data={rows}
      total={total}
      page={page}
      pageSize={pageSize}
      onPageChange={setPage}
      onPageSizeChange={(s) => { setPageSize(s); setPage(1) }}
      onSortChange={handleSortChange}
      filters={filters}
      onFilterChange={handleFilterChange}
    />
  )
}

export function AuditTrailPopup({ open, onClose, entityLabel, tabs }: AuditTrailPopupProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(tabs[0]?.label ?? "")

  if (!open) return null

  return (
    <DraggableResizablePopup
      title={t("auditTrail.title", { entity: entityLabel })}
      onClose={onClose}
      initialWidth={1000}
      initialHeight={600}
      // Large data popup: do NOT dismiss on outside click (avoids accidental loss
      // of scroll position / place). Consistent across host_app and remotes.
      closeOnBackdrop={false}
    >
      <div className="ideable:mb-4 ideable:flex ideable:gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.label}
            onClick={() => setActiveTab(tab.label)}
            className={`ideable:px-4 ideable:py-2 ideable:rounded-md ideable:text-sm ideable:font-medium ${
              activeTab === tab.label
                ? "ideable:bg-primary ideable:text-primary-foreground"
                : "ideable:border ideable:bg-background ideable:hover:bg-accent"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) =>
        tab.label === activeTab ? (
          <AuditTable key={tab.label} columns={tab.columns} fetchPage={tab.fetchPage} />
        ) : null,
      )}
    </DraggableResizablePopup>
  )
}
