# @ideable/ui Widget Index

The registry of framework widgets. Each row points at the **source** (`reusable.ui/`), the **live example** (`module_template` `WidgetGallery.tsx` section), and the **canonical spec**. Import everything from `@ideable/ui` (barrel) or deep paths (`@ideable/ui/widgets/X`, `@ideable/ui/primitives/X`) for tightest tree-shaking.

Spec keys:
- **S1** = `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`
- **S2** = `modules/module_template/frontend/SPECS/ideable-framework-specs/framework-css-classes-reference.md`
- **S3** = `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md`

Gallery = `modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx`.

| Widget | Family | Import | Source | Gallery section | Spec |
|---|---|---|---|---|---|
| `ServerDataTable` | table | `@ideable/ui` | `reusable.ui/widgets/ServerDataTable.tsx` | "ServerDataTable" | S1 §Tables |
| `AssociationServerDataTable` | table (M2M) | `@ideable/ui` | `reusable.ui/widgets/AssociationServerDataTable.tsx` | — | S1 §Associated entities |
| `DataTable` (legacy client-side) | table | `@ideable/ui` | `reusable.ui/widgets/DataTable.tsx` | — | S1 §Tables |
| `AuditTrailPopup` | popup | `@ideable/ui` | `reusable.ui/widgets/AuditTrailPopup.tsx` | "Popups & dialogs" | S1 §DraggableResizablePopup + audit-trail-specs.md |
| `DraggableResizablePopup` | popup | `@ideable/ui` | `reusable.ui/widgets/DraggableResizablePopup.tsx` | "Popups & dialogs" | S1 §DraggableResizablePopup |
| `UnsavedChangesDialog` (+ `useUnsavedChangesGuard`) | dialog | `@ideable/ui` | `reusable.ui/widgets/UnsavedChangesDialog.tsx`, `reusable.ui/hooks/useUnsavedChangesGuard.ts` | "Popups & dialogs" | S1 §UnsavedChangesDialog, S3 §Dirty form guard |
| `TimeSeriesChart` | chart | `@ideable/ui` | `reusable.ui/widgets/TimeSeriesChart.tsx` | "TimeSeriesChart" | S1 §Charts + host ui-specs (time-series entities) |
| `DynamicIcon` | icon | `@ideable/ui` | `reusable.ui/widgets/DynamicIcon.tsx` | "DynamicIcon" | S3 §Menu (icon field) |
| `Button` (+ `buttonVariants`) | primitive | `@ideable/ui` | `reusable.ui/primitives/button.tsx` | "Buttons" | S2 §Button |
| `Input` | primitive | `@ideable/ui` | `reusable.ui/primitives/input.tsx` | "Form inputs" | S2 §Input |
| `Checkbox` | primitive/toggle | `@ideable/ui` | `reusable.ui/primitives/checkbox.tsx` | "Form inputs" | S2 |
| `Label` | primitive | `@ideable/ui` | `reusable.ui/primitives/label.tsx` | "Form inputs" | S2 |
| `Select` (+ parts) | primitive | `@ideable/ui` | `reusable.ui/primitives/select.tsx` | "Form inputs" | S2 §Select |
| `Tabs` (+ parts) | primitive | `@ideable/ui` | `reusable.ui/primitives/tabs.tsx` | "Tabs & Tooltip" | S2 §Tabs |
| `Tooltip` (+ parts, `TooltipProvider`) | primitive | `@ideable/ui` | `reusable.ui/primitives/tooltip.tsx` | "Tabs & Tooltip" | S2 §Tooltip |
| `Card` (+ parts) | primitive | `@ideable/ui` | `reusable.ui/primitives/card.tsx` | (wraps every section) | S2 §Card |
| `Dialog` (+ parts) | primitive | `@ideable/ui` | `reusable.ui/primitives/dialog.tsx` | (used by UnsavedChangesDialog) | S2 §Dialog |
| `DropdownMenu` (+ parts) | primitive | `@ideable/ui` | `reusable.ui/primitives/dropdown-menu.tsx` | — | S2 |
| `useServerTableState` | hook | `@ideable/ui` | `reusable.ui/hooks/useServerTableState.ts` | (paired with tables) | S1 §Tables |
| `useTranslation` | hook | `@ideable/ui` | `reusable.ui/hooks/useTranslation.ts` | (widget i18n) | S3 §i18n |

## Notes

- `ServerDataTable` uses `@tanstack/react-table` `ColumnDef` (re-exported from `@ideable/ui`); per-column UI meta (`{sortable, filterable, type, filterType}`) is typed via the augmentation in `reusable.ui/widgets/react-table-meta.ts`. Header must be a **string** (function headers are ignored) — pass `header: t('...')`.
- `AssociationServerDataTable` (M2M grids) uses `@tanstack/react-query` (a shared MF singleton) — the consuming app must provide a `QueryClientProvider` ancestor. Prefer `ServerDataTable` for plain lists; use `AssociationServerDataTable` for link/unlink association grids. `DataTable` is the legacy client-side table — prefer `ServerDataTable` for new work.
- Adding a widget: see SKILL.md § Extending the widget library.
