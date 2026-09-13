import type { RowData } from '@tanstack/react-table'

// Framework augmentation so `ServerDataTable` column defs can carry per-column
// UI metadata (`meta: { sortable, filterable, type }`) with proper typing.
// Imported for its side-effect (type-only) by ServerDataTable so any consumer of
// the widget or the re-exported ColumnDef type picks it up.
declare module '@tanstack/react-table' {
  interface ColumnMeta<TData extends RowData, TValue> {
    sortable?: boolean
    filterable?: boolean
    type?: 'text' | 'boolean' | 'number'
    filterType?: string
  }
}
