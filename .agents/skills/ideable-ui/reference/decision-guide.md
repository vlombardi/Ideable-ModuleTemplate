# Decision Guide — need → widget

Match what you're building to the framework widget. Then open its row in `widget-index.md`.

| I need to… | Use |
|---|---|
| Show a list/grid of entities with server-side pagination, sorting, filtering | `ServerDataTable` |
| Show a many-to-many association grid (link/unlink related entities) | `AssociationServerDataTable` (needs a `QueryClientProvider` ancestor) |
| Show per-object change history (field diffs + associate/disassociate) | `AuditTrailPopup` (gated by `audit_trail:view`) |
| Show a large movable/resizable modal (any big data popup) | `DraggableResizablePopup` (never Radix `Dialog` for this) |
| Warn before losing unsaved edits (navigation/close) | `UnsavedChangesDialog` + `useUnsavedChangesGuard` |
| Plot a numeric value over time (time-series entity: timestamp + numeric column) | `TimeSeriesChart` |
| Render an icon chosen by name (data-driven menus) | `DynamicIcon` |
| A button (action, submit, destructive, link, icon) | `Button` |
| A text field | `Input` (+ `Label`) |
| A boolean toggle in a form | `Checkbox` |
| A single-choice dropdown | `Select` |
| A tabbed panel | `Tabs` |
| A small confirmation/edit modal (a11y focus-trapped) | `Dialog` primitive |
| A context/actions menu | `DropdownMenu` |
| A hover hint | `Tooltip` (+ `TooltipProvider` at the root) |
| A bordered content container with header/title | `Card` |
| Manage table page/pageSize/sort/filter state | `useServerTableState` |
| Translate widget chrome (reactive to host language) | `useTranslation` (from `@ideable/ui`) |

Rules of thumb:
- **Entity list page** = `ServerDataTable` + a details/form card + (if versioned) an `AuditTrailPopup` action + (if it edits) `UnsavedChangesDialog`.
- **Time-series entity page** (timestamp + numeric column) MUST also render a `TimeSeriesChart`.
- If nothing fits, it may be a genuinely new reusable widget → see SKILL.md § Extending the widget library. If it's a one-off, build it in the page (not the library).
