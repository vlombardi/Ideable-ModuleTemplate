import { useState } from 'react'
import { Link, Unlink } from 'lucide-react'

const OPERATION_LABELS: Record<number, string> = {
  0: 'INSERT',
  1: 'UPDATE',
  2: 'DELETE',
  3: 'ASSOCIATE',
  4: 'DISASSOCIATE',
}

const OPERATION_STYLES: Record<number, string> = {
  0: 'template-bg-green-100 template-text-green-800',
  1: 'template-bg-blue-100 template-text-blue-800',
  2: 'template-bg-red-100 template-text-red-800',
  3: 'template-bg-purple-100 template-text-purple-800',
  4: 'template-bg-amber-100 template-text-amber-800',
}

export interface VersionRecord {
  transaction_id: number
  operation_type: number
  [key: string]: unknown
}

interface AuditTab {
  label: string
  versions: VersionRecord[]
  columns: string[]
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

function formatHeader(col: string): string {
  const auditHeaderMap: Record<string, string> = {
    au_creation_timestamp: 'Created At',
    au_last_update_timestamp: 'Updated At',
    au_created_by_user: 'Creator',
    au_last_updated_by_user: 'Updater',
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
  columns: string[]
): string[] {
  // Association-change rows show the peer entity info instead of field diffs
  if (current.operation_type === 3 || current.operation_type === 4) {
    const peerLabel = formatValue(current.peer_entity_label)
    const peerType = formatValue(current.peer_entity_type)
    const assocName = formatValue(current.association_name)
    const parts: string[] = []
    if (assocName && assocName !== '-') parts.push(`Association: ${assocName}`)
    if (peerType && peerType !== '-') parts.push(`Type: ${peerType}`)
    if (peerLabel && peerLabel !== '-') parts.push(`Entity: ${peerLabel}`)
    return parts.length ? parts : [current.operation_type === 3 ? 'Associated' : 'Disassociated']
  }

  const diffs: string[] = []
  const skipKeys = new Set([
    'transaction_id',
    'operation_type',
    'end_transaction_id',
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
        if (val !== '-') diffs.push(`${formatHeader(col)}: ${val}`)
      }
      return diffs.length ? diffs : ['Created']
    }
    return ['—']
  }

  if (current.operation_type === 2) {
    return ['Deleted']
  }

  for (const col of columns) {
    if (skipKeys.has(col)) continue
    const cur = current[col]
    const prev = previous[col]
    if (cur !== prev) {
      diffs.push(`${formatHeader(col)}: ${formatValue(prev)} → ${formatValue(cur)}`)
    }
  }

  return diffs.length ? diffs : ['No visible changes']
}

function getActor(v: VersionRecord): string {
  return formatValue(v.au_last_updated_by_user ?? v.au_created_by_user ?? '—')
}

function getEventAction(v: VersionRecord): string | null {
  const evt = v.event
  return evt && typeof evt === 'string' ? evt : null
}

function AssociationIcon({ operationType }: { operationType: number }) {
  if (operationType === 3) {
    return <Link className="template-h-3 template-w-3" />
  }
  if (operationType === 4) {
    return <Unlink className="template-h-3 template-w-3" />
  }
  return null
}

function AuditTable({ versions, columns }: { versions: VersionRecord[]; columns: string[] }) {
  if (versions.length === 0) {
    return (
      <p className="template-text-sm template-text-muted-foreground template-py-4 template-text-center">
        No results.
      </p>
    )
  }

  return (
    <div className="template-overflow-auto">
      <table className="template-w-full template-text-sm">
        <thead className="template-border-b">
          <tr>
            <th className="template-px-3 template-py-2 template-text-left template-font-medium">Op</th>
            <th className="template-px-3 template-py-2 template-text-left template-font-medium">When</th>
            <th className="template-px-3 template-py-2 template-text-left template-font-medium">Who</th>
            <th className="template-px-3 template-py-2 template-text-left template-font-medium">What Changed</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v, idx) => {
            // Find the nearest previous field-version row (skip synthetic association rows)
            let previous: VersionRecord | undefined = undefined
            for (let i = idx + 1; i < versions.length; i++) {
              if (versions[i].operation_type !== 3 && versions[i].operation_type !== 4) {
                previous = versions[i]
                break
              }
            }
            const diffs = computeDiffs(v, previous, columns)
            const eventAction = getEventAction(v)
            const isAssociation = v.operation_type === 3 || v.operation_type === 4
            return (
              <tr key={v.transaction_id} className="template-border-b">
                <td className="template-px-3 template-py-2 template-whitespace-nowrap">
                  <span
                    className={[
                      'template-inline-flex template-items-center template-gap-1 template-rounded-full template-px-2 template-py-0.5 template-text-xs template-font-medium',
                      OPERATION_STYLES[v.operation_type] ?? 'template-bg-slate-100 template-text-slate-800',
                    ].join(' ')}
                  >
                    {isAssociation && <AssociationIcon operationType={v.operation_type} />}
                    {OPERATION_LABELS[v.operation_type] ?? String(v.operation_type)}
                  </span>
                  {eventAction && eventAction !== 'model_created' && eventAction !== 'model_updated' && eventAction !== 'model_deleted' && (
                    <span className="template-block template-text-[10px] template-text-muted-foreground template-mt-0.5">
                      {eventAction}
                    </span>
                  )}
                </td>
                <td className="template-px-3 template-py-2 template-whitespace-nowrap">
                  {formatTimestamp(v.au_creation_timestamp ?? v.au_last_update_timestamp)}
                </td>
                <td className="template-px-3 template-py-2 template-whitespace-nowrap">
                  {getActor(v)}
                </td>
                <td className="template-px-3 template-py-2">
                  <ul className="template-space-y-0.5">
                    {diffs.map((d, dIdx) => (
                      <li key={dIdx} className="template-text-xs">{d}</li>
                    ))}
                  </ul>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function AuditTrailPopup({ open, onClose, entityLabel, tabs }: AuditTrailPopupProps) {
  const [activeTab, setActiveTab] = useState(tabs[0]?.label ?? '')

  if (!open) return null

  return (
    <div
      className="template-scope template-fixed template-inset-0 template-z-50 template-flex template-items-center template-justify-center"
      role="dialog"
      aria-modal="true"
    >
      {/* Overlay */}
      <div
        className="template-absolute template-inset-0 template-bg-black/50"
        onClick={onClose}
      />
      {/* Dialog panel */}
      <div className="template-relative template-bg-white template-rounded-lg template-shadow-xl template-w-[90vw] template-max-w-[90vw] template-max-h-[90vh] template-flex template-flex-col template-overflow-hidden">
        <div className="template-flex template-items-center template-justify-between template-border-b template-px-6 template-py-4">
          <h2 className="template-text-lg template-font-semibold">
            {entityLabel} — View Audit Trail
          </h2>
          <button
            onClick={onClose}
            className="template-text-muted-foreground hover:template-text-foreground"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <div className="template-flex-1 template-overflow-y-auto template-p-6">
          {/* Tab bar */}
          <div className="template-flex template-gap-2 template-mb-4">
            {tabs.map((tab) => (
              <button
                key={tab.label}
                onClick={() => setActiveTab(tab.label)}
                className={`template-px-4 template-py-2 template-rounded-md template-text-sm template-font-medium ${
                  activeTab === tab.label
                    ? 'template-bg-primary template-text-primary-foreground'
                    : 'template-border template-bg-background hover:template-bg-accent'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {/* Active tab content */}
          {tabs.map((tab) =>
            tab.label === activeTab ? (
              <AuditTable key={tab.label} versions={tab.versions} columns={tab.columns} />
            ) : null
          )}
        </div>
      </div>
    </div>
  )
}
