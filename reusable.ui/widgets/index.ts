// @ideable/ui widget barrel. Prefer deep imports (`@ideable/ui/widgets/X`) in
// consumers for the tightest tree-shaking; the barrel is a convenience re-export
// (package is side-effect-free except CSS, so barrel imports still tree-shake).

// Chart
export { TimeSeriesChart } from './TimeSeriesChart'
export type {
  TimeSeriesChartProps,
  TimeSeriesPoint,
  TimeSeriesSeries,
} from './TimeSeriesChart'

// Data table (react-table based). ColumnDef is re-exported from react-table;
// its `meta` is augmented in ./react-table-meta (imported by ServerDataTable).
export { ServerDataTable } from './ServerDataTable'
export type { ColumnDef } from '@tanstack/react-table'
export { AssociationServerDataTable } from './AssociationServerDataTable'
export { DataTable } from './DataTable'

// Popups / dialogs
export { default as DraggableResizablePopup } from './DraggableResizablePopup'
export { AuditTrailPopup } from './AuditTrailPopup'
export type { VersionRecord, VersionPage, AuditPageParams } from './AuditTrailPopup'
export { UnsavedChangesDialog } from './UnsavedChangesDialog'

// Icon
export { DynamicIcon } from './DynamicIcon'
