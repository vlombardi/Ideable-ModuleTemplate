import { useEffect, useState } from "react"
import type { ColumnDef } from "@tanstack/react-table"
import { Button } from "../primitives/button"
import DraggableResizablePopup from "./DraggableResizablePopup"
import { EntityTable } from "./EntityTable"
import type { EntityTransport } from "../hooks/useEntityQuery"

/**
 * The Entity Selector Pattern — `shared-ui-widgets-specs.md` § *Form FK association selection
 * (normative)*.
 *
 * A form field that holds a foreign key must never be a raw integer input or a plain dropdown:
 * the spec's own comparison table rejects both (no server-side paging, no full-column
 * filtering/sorting, does not scale past ~100 rows). This is the shared implementation, meant to
 * be plugged into an `EntityFormField`'s `render(value, setValue)` escape hatch — it does not
 * change `EntityFormField`'s own shape, and it is not itself a form field.
 *
 * The current value is shown as `<Name> (<ID>)`. A "Select" button opens a modal containing a
 * canonical `EntityTable` (server-side paging, sorting, per-column filtering — the same widget
 * `StandardEntityPage` itself uses, not a reimplementation of any of that). Clicking a row selects
 * it and closes the modal; the modal can also be dismissed (its own X only, no backdrop click —
 * same as every other framework popup) with no change to the field.
 *
 * The modal is the shared `DraggableResizablePopup` (centered, draggable, resizable, portal
 * rendered) — no bespoke modal chrome. Its content is wrapped in `role="dialog"`, which is both
 * correct modal semantics and what already exempts a click inside it from `ServerDataTable`'s
 * click-outside-deselects handler on whatever table sits behind it on the page.
 */
export interface EntitySelectorProps<Row extends { id: string | number }> {
  /** The entity key to select from, as declared in the module's registry — e.g. `items`. */
  entityKey: string
  /** How to reach the module's API — the same transport the page itself already uses. */
  transport: EntityTransport
  /** The current FK value (the referenced row's id). `''`/`null`/`undefined` means unset. */
  value: string | number | null | undefined
  /** Called with the newly selected row's id. */
  onChange: (id: string | number) => void
  /** Columns for the selection table — same shape `EntityTable`/`ServerDataTable` take. */
  columns: ColumnDef<Row, any>[]
  /** Field name -> column header, forwarded to `EntityTable`. */
  labelFor?: (field: string) => string
  /** The human-readable half of `<Name> (<ID>)`, for the current value and for a freshly
   *  selected row. */
  displayName: (row: Row) => string
  /** Modal title — already translated. */
  title: string
  /** The "Select" button's label — already translated. */
  selectLabel: string
  /** Shown when no value is selected yet. Defaults to an em dash. */
  placeholder?: string
  disabled?: boolean
}

export function EntitySelector<Row extends { id: string | number }>({
  entityKey,
  transport,
  value,
  onChange,
  columns,
  labelFor,
  displayName,
  title,
  selectLabel,
  placeholder = "—",
  disabled = false,
}: EntitySelectorProps<Row>) {
  const [open, setOpen] = useState(false)
  const [resolved, setResolved] = useState<Row | null>(null)
  const [loading, setLoading] = useState(false)

  const hasValue = value !== null && value !== undefined && value !== ""

  // Resolve the current value's display row. `EntityFormField.render` only ever receives the raw
  // field value (the id), never the whole row — so a name to show next to it is fetched here, the
  // same single-row GET every declared entity already mounts (`GET <api>/<entityKey>/<id>`), not a
  // workaround. Skipped when the already-resolved row is this same id (the row a selection in the
  // modal just supplied, or an unchanged value on re-render).
  useEffect(() => {
    if (!hasValue) {
      setResolved(null)
      return
    }
    if (resolved && String(resolved.id) === String(value)) return
    let cancelled = false
    setLoading(true)
    transport
      .get(`/${entityKey}/${value}`)
      .then((row) => {
        if (!cancelled) setResolved(row as Row)
      })
      .catch(() => {
        if (!cancelled) setResolved(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityKey, transport, value, hasValue])

  const displayText = !hasValue
    ? placeholder
    : loading && !resolved
      ? "…"
      : resolved
        ? `${displayName(resolved)} (${resolved.id})`
        : String(value)

  // Viewport-based cap, not a fixed pixel constant: `shared-ui-widgets-specs.md` § *Table-selection
  // dialogs* requires the dialog surface capped at 90% of the viewport width, and a viewport-based
  // maximum height.
  const viewportMaxWidth = typeof window !== "undefined" ? Math.round(window.innerWidth * 0.9) : 1200
  const viewportMaxHeight = typeof window !== "undefined" ? Math.round(window.innerHeight * 0.85) : 800

  return (
    <div className="ideable:flex ideable:items-center ideable:gap-2">
      <span data-testid="entity-selector-value" className="ideable:text-sm ideable:truncate">
        {displayText}
      </span>
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => setOpen(true)}>
        {selectLabel}
      </Button>

      {open && (
        <DraggableResizablePopup
          title={title}
          onClose={() => setOpen(false)}
          initialWidth={Math.min(1000, viewportMaxWidth)}
          initialHeight={Math.min(650, viewportMaxHeight)}
          maxWidth={viewportMaxWidth}
          maxHeight={viewportMaxHeight}
        >
          {/* `role="dialog"`: correct modal semantics, and it is also what already exempts a click
           *  in here from the click-outside-deselects handler of whatever `ServerDataTable` sits
           *  behind this popup on the page (the popup itself portals to `document.body`, a DOM
           *  sibling of the page rather than a descendant, so without this the background table
           *  would read a row click in here as "outside itself" and clear its own selection). */}
          <div role="dialog" aria-modal="true" data-entity-selector={entityKey}>
            <EntityTable<Row>
              entityKey={entityKey}
              transport={transport}
              columns={columns}
              labelFor={labelFor}
              onRowClick={(row) => {
                setResolved(row)
                onChange(row.id)
                setOpen(false)
              }}
            />
          </div>
        </DraggableResizablePopup>
      )}
    </div>
  )
}
