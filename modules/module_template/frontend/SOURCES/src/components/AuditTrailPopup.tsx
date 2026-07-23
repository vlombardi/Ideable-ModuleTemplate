import { useState, useEffect, useCallback } from 'react'
import { Link, Unlink } from 'lucide-react'
import DraggableResizablePopup from './DraggableResizablePopup'
import { useTranslation } from '../hooks/useTranslation'

const OPERATION_LABEL_KEYS: Record<number, string> = {
  0: 'auditTrail.opInsert',
  1: 'auditTrail.opUpdate',
  2: 'auditTrail.opDelete',
  3: 'auditTrail.opAssociate',
  4: 'auditTrail.opDisassociate',
}

const OPERATION_STYLES: Record<number, string> = {
  0: 'template:bg-green-100 template:text-green-800',
  1: 'template:bg-blue-100 template:text-blue-800',
  2: 'template:bg-red-100 template:text-red-800',
  3: 'template:bg-purple-100 template:text-purple-800',
  4: 'template:bg-amber-100 template:text-amber-800',
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
  sort_order?: 'asc' | 'desc'
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
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (value instanceof Date) return value.toLocaleString()
  return String(value)
}

function formatTimestamp(value: unknown): string {
  if (!value) return '-'
  const date = value instanceof Date ? value : new Date(String(value))
  if (isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function formatHeader(col: string, t: (key: string) => string): string {
  const auditHeaderMap: Record<string, string> = {
    au_creation_timestamp: t('table.columns.createdAt'),
    au_last_update_timestamp: t('table.columns.updatedAt'),
    au_created_by_user: t('table.columns.creator'),
    au_last_updated_by_user: t('table.columns.updater'),
    timestamp: t('table.columns.createdAt'),
    actor: t('table.columns.creator'),
  }
  if (auditHeaderMap[col]) return auditHeaderMap[col]
  return col
    .replace(/_fk$/, '')
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function computeDiffs(
  current: VersionRecord,
  previous: VersionRecord | undefined,
  columns: string[],
  t: (key: string, vars?: Record<string, string>) => string,
): string[] {
  if (current.operation_type === 3 || current.operation_type === 4) {
    const peerLabel = formatValue(current.peer_entity_label)
    const peerType = formatValue(current.peer_entity_type)
    const assocName = formatValue(current.association_name)
    const parts: string[] = []
    if (assocName && assocName !== '-') parts.push(t('auditTrail.assocLabel', { name: assocName }))
    if (peerType && peerType !== '-') parts.push(t('auditTrail.assocType', { type: peerType }))
    if (peerLabel && peerLabel !== '-') parts.push(t('auditTrail.assocEntity', { label: peerLabel }))
    return parts.length ? parts : [current.operation_type === 3 ? t('auditTrail.associated') : t('auditTrail.disassociated')]
  }

  const diffs: string[] = []
  const skipKeys = new Set([
    'transaction_id',
    'operation_type',
    'end_transaction_id',
    'timestamp',
    'actor',
    'actor_id',
    'au_creation_timestamp',
    'au_last_update_timestamp',
    'au_created_by_user',
    'au_last_updated_by_user',
    'event',
    'client_ip',
    'user_agent',
    'request_method',
    'request_path',
    'association_name',
    'peer_entity_type',
    'peer_entity_id',
    'peer_entity_label',
  ])

  if (!previous) {
    if (current.operation_type === 0) {
      for (const col of columns) {
        if (skipKeys.has(col)) continue
        const val = formatValue(current[col])
        if (val !== '-') diffs.push(`${formatHeader(col, t)}: ${val}`)
      }
      return diffs.length ? diffs : [t('auditTrail.created')]
    }
    return ['—']
  }

  if (current.operation_type === 2) {
    return [t('auditTrail.deleted')]
  }

  for (const col of columns) {
    if (skipKeys.has(col)) continue
    const cur = current[col]
    const prev = previous[col]
    if (cur !== prev) {
      diffs.push(`${formatHeader(col, t)}: ${formatValue(prev)} → ${formatValue(cur)}`)
    }
  }

  return diffs.length ? diffs : [t('auditTrail.noVisibleChanges')]
}

function getActor(v: VersionRecord): string {
  const actor = v.actor
  if (!actor) return '—'
  const actorId = v.actor_id
  if (actorId !== null && actorId !== undefined) return `${actor}(${actorId})`
  return String(actor)
}

function getEventAction(v: VersionRecord): string | null {
  const evt = v.event
  return evt && typeof evt === 'string' ? evt : null
}

function AssociationIcon({ operationType }: { operationType: number }) {
  if (operationType === 3) {
    return <Link className="template:h-3 template:w-3" />
  }
  if (operationType === 4) {
    return <Unlink className="template:h-3 template:w-3" />
  }
  return null
}

const DEFAULT_PAGE_SIZE = 20

function AuditTable({ columns, fetchPage }: { columns: string[]; fetchPage: (params: AuditPageParams) => Promise<VersionPage> }) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<VersionRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(DEFAULT_PAGE_SIZE)
  const [pages, setPages] = useState(1)
  const [sortBy, setSortBy] = useState<string>('timestamp')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (p: number, sb: string, so: 'asc' | 'desc') => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchPage({
        skip: (p - 1) * pageSize,
        limit: pageSize,
        sort_by: sb,
        sort_order: so,
      })
      setVersions(result.items)
      setTotal(result.total)
      setPages(result.pages || 1)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('table.errorLoading'))
    } finally {
      setLoading(false)
    }
  }, [fetchPage, pageSize, t])

  useEffect(() => {
    load(page, sortBy, sortOrder)
  }, [load, page, sortBy, sortOrder])

  const handleSort = (col: string) => {
    if (col === sortBy) {
      const next: 'asc' | 'desc' = sortOrder === 'desc' ? 'asc' : 'desc'
      setSortOrder(next)
    } else {
      setSortBy(col)
      setSortOrder('desc')
    }
    setPage(1)
  }

  const sortIcon = (col: string) => {
    if (col !== sortBy) return ' ↕'
    return sortOrder === 'asc' ? ' ↑' : ' ↓'
  }

  if (loading && versions.length === 0) {
    return (
      <p className="template:text-sm template:text-muted-foreground template:py-4 template:text-center">
        {t('common.loading')}
      </p>
    )
  }

  if (error) {
    return (
      <p className="template:text-sm template:text-red-600 template:py-4 template:text-center">{error}</p>
    )
  }

  if (versions.length === 0) {
    return (
      <p className="template:text-sm template:text-muted-foreground template:py-4 template:text-center">
        {t('auditTrail.noResults')}
      </p>
    )
  }

  return (
    <div className="template:flex template:flex-col template:gap-2">
      <div className="template:overflow-auto">
        <table className="template:w-full template:text-sm">
          <thead className="template:border-b">
            <tr>
              <th
                className="template:px-3 template:py-2 template:text-left template:font-medium template:cursor-pointer template:select-none"
                onClick={() => handleSort('operation_type')}
              >
                {t('auditTrail.colOp')}{sortIcon('operation_type')}
              </th>
              <th
                className="template:px-3 template:py-2 template:text-left template:font-medium template:cursor-pointer template:select-none"
                onClick={() => handleSort('timestamp')}
              >
                {t('auditTrail.colWhen')}{sortIcon('timestamp')}
              </th>
              <th
                className="template:px-3 template:py-2 template:text-left template:font-medium template:cursor-pointer template:select-none"
                onClick={() => handleSort('actor')}
              >
                {t('auditTrail.colWho')}{sortIcon('actor')}
              </th>
              <th className="template:px-3 template:py-2 template:text-left template:font-medium">
                {t('auditTrail.colWhat')}
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v, idx) => {
              let previous: VersionRecord | undefined = undefined
              for (let i = idx + 1; i < versions.length; i++) {
                if (versions[i].operation_type !== 3 && versions[i].operation_type !== 4) {
                  previous = versions[i]
                  break
                }
              }
              const diffs = computeDiffs(v, previous, columns, t)
              const eventAction = getEventAction(v)
              const isAssociation = v.operation_type === 3 || v.operation_type === 4
              return (
                <tr key={v.transaction_id} className="template:border-b">
                  <td className="template:px-3 template:py-2 template:whitespace-nowrap">
                    <span
                      className={[
                        'template:inline-flex template:items-center template:gap-1 template:rounded-full template:px-2 template:py-0.5 template:text-xs template:font-medium',
                        OPERATION_STYLES[v.operation_type] ?? 'template:bg-slate-100 template:text-slate-800',
                      ].join(' ')}
                    >
                      {isAssociation && <AssociationIcon operationType={v.operation_type} />}
                      {OPERATION_LABEL_KEYS[v.operation_type] ? t(OPERATION_LABEL_KEYS[v.operation_type]) : String(v.operation_type)}
                    </span>
                    {eventAction && eventAction !== 'model_created' && eventAction !== 'model_updated' && eventAction !== 'model_deleted' && (
                      <span className="template:block template:text-[10px] template:text-muted-foreground template:mt-0.5">
                        {eventAction}
                      </span>
                    )}
                  </td>
                  <td className="template:px-3 template:py-2 template:whitespace-nowrap">
                    {formatTimestamp(v.timestamp)}
                  </td>
                  <td className="template:px-3 template:py-2 template:whitespace-nowrap">
                    {getActor(v)}
                  </td>
                  <td className="template:px-3 template:py-2">
                    <ul className="template:space-y-0.5">
                      {diffs.map((d, dIdx) => (
                        <li key={dIdx} className="template:text-xs">{d}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="template:flex template:items-center template:justify-between template:text-sm template:pt-1">
        <span className="template:text-muted-foreground">
          {t('table.showing', { from: String(total === 0 ? 0 : (page - 1) * pageSize + 1), to: String(Math.min(page * pageSize, total)), total: String(total) })}
        </span>
        <div className="template:flex template:items-center template:gap-1">
          <button
            onClick={() => setPage(1)}
            disabled={page <= 1}
            className="template:px-2 template:py-1 template:border template:rounded-md disabled:template:opacity-50"
          >
            {'«'}
          </button>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="template:px-2 template:py-1 template:border template:rounded-md disabled:template:opacity-50"
          >
            {'‹'}
          </button>
          <span className="template:px-2">
            {t('table.page', { page: String(page), total: String(pages) })}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
            disabled={page >= pages}
            className="template:px-2 template:py-1 template:border template:rounded-md disabled:template:opacity-50"
          >
            {'›'}
          </button>
          <button
            onClick={() => setPage(pages)}
            disabled={page >= pages}
            className="template:px-2 template:py-1 template:border template:rounded-md disabled:template:opacity-50"
          >
            {'»'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function AuditTrailPopup({ open, onClose, entityLabel, tabs }: AuditTrailPopupProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState(tabs[0]?.label ?? '')

  if (!open) return null

  return (
    <DraggableResizablePopup
      title={t('auditTrail.title', { entity: entityLabel })}
      onClose={onClose}
      initialWidth={1000}
      initialHeight={600}
    >
      <div className="template:flex template:gap-2 template:mb-4">
        {tabs.map((tab) => (
          <button
            key={tab.label}
            onClick={() => setActiveTab(tab.label)}
            className={`template:px-4 template:py-2 template:rounded-md template:text-sm template:font-medium ${
              activeTab === tab.label
                ? 'template:bg-primary template:text-primary-foreground'
                : 'template:border template:bg-background template:hover:bg-accent'
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
