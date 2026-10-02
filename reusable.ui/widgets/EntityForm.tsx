import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Button } from "../primitives/button"
import { Input } from "../primitives/input"
import { Label } from "../primitives/label"
import { ImageField } from "./ImageField"

/**
 * A create/edit form for one declared entity, from a field list.
 *
 * Separately usable, like `EntityTable`: a page that needs its own layout renders this for the
 * ordinary fields and puts whatever it likes around them, instead of copying a form to change one
 * input. That is the property that keeps the escape hatch from being a fork.
 *
 * It renders the framework primitives (`Input`, `Label`, `Button`) and reinvents none of them.
 * What it adds is the part every entity form would otherwise repeat: field state, dirty tracking,
 * and the submit/cancel pair.
 *
 * DELIBERATELY NOT A SCHEMA-DRIVEN FORM. It takes the fields to render and how to label them; it
 * does not infer widgets from a JSON schema. Inference gets a date picker wrong, or a foreign key,
 * and the page cannot correct it without fighting the inference — so the caller says what it wants
 * and keeps the ability to say something else.
 */
export interface EntityFormField {
  name: string
  label: string
  /** `text` by default; `number` and `textarea` cover the rest of what a plain entity needs. */
  type?: "text" | "number" | "textarea" | "image"
  required?: boolean
  placeholder?: string
  /** Render this field yourself — a select over another entity, a date picker, anything. */
  render?: (
    value: unknown,
    setValue: (next: unknown) => void,
    /** Every field's current value, for a field derived from others (a composed full name). */
    values: Record<string, unknown>,
  ) => React.ReactNode
  /**
   * `type: "image"` only. Fetches the STORED image so the form can preview it; set by the page from the
   * row being edited (`StandardEntityPage`), omitted when there is none. `accept` narrows the chooser.
   */
  loadImage?: () => Promise<Blob>
  imageKey?: unknown
  accept?: string
}

export interface EntityFormProps {
  fields: EntityFormField[]
  /** The row being edited; omit for a create form. */
  value?: Record<string, unknown> | null
  onSubmit: (values: Record<string, unknown>) => void | Promise<void>
  onCancel?: () => void
  submitLabel: string
  cancelLabel?: string
  /** Disable everything — while a save is in flight, or without the edit permission. */
  disabled?: boolean
  /** Told whether anything has changed, so a page can wire its unsaved-changes guard. */
  onDirtyChange?: (dirty: boolean) => void
}

export function EntityForm({
  fields,
  value,
  onSubmit,
  onCancel,
  submitLabel,
  cancelLabel,
  disabled = false,
  onDirtyChange,
}: EntityFormProps) {
  const initial = useMemo(() => {
    const seed: Record<string, unknown> = {}
    for (const field of fields) seed[field.name] = value?.[field.name] ?? ""
    return seed
  }, [fields, value])

  const [values, setValues] = useState<Record<string, unknown>>(initial)

  // Re-seed when the row being edited changes — otherwise opening a second row shows the first.
  // Deliberately skipped on mount (the ref starts pointing at the same `initial` the state was
  // already seeded with): a `render` field that sets its own value from a mount-time effect (the
  // `item_fk` hidden-field pattern) has that effect and this one fire in the same commit, child
  // first — an unconditional `setValues(initial)` here would run second and overwrite it back to
  // "", which the API then rejects as a 422 the form couldn't explain to anyone reading its code.
  const seededInitial = useRef(initial)
  useEffect(() => {
    if (initial !== seededInitial.current) {
      seededInitial.current = initial
      setValues(initial)
    }
  }, [initial])

  const dirty = useMemo(
    () => fields.some((field) => (values[field.name] ?? "") !== (initial[field.name] ?? "")),
    [fields, values, initial],
  )
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange])

  const setValue = useCallback(
    (name: string, next: unknown) => setValues((current) => ({ ...current, [name]: next })),
    [],
  )

  // One stable callback per field name, cached for the component's lifetime — not recreated on
  // every render the way an inline `(next) => setValue(field.name, next)` in the `.map()` below
  // would be. A `render` field that sets its own value from a `useEffect` (a fixed value supplied
  // by the PAGE rather than typed by the viewer — `sub_item`'s `item_fk` is the worked example)
  // depends on that identity staying put: an unstable setter in the effect's dependency array
  // fires the effect every render, which calls the setter, which re-renders this form, which
  // creates a new setter — an infinite loop that froze the page rather than erroring, and was
  // only caught by a live-stack E2E test timing out.
  const fieldSetters = useRef(new Map<string, (next: unknown) => void>())
  const setterFor = useCallback(
    (name: string): ((next: unknown) => void) => {
      let setter = fieldSetters.current.get(name)
      if (!setter) {
        setter = (next: unknown) => setValue(name, next)
        fieldSetters.current.set(name, setter)
      }
      return setter
    },
    [setValue],
  )

  return (
    <form
      className="ideable:flex ideable:flex-col ideable:gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (!disabled) void onSubmit(values)
      }}
    >
      {fields.map((field) => (
        <div key={field.name} className="ideable:flex ideable:flex-col ideable:gap-2">
          <Label htmlFor={`entity-field-${field.name}`}>
            {field.label}
            {field.required ? " *" : ""}
          </Label>
          {field.render ? (
            field.render(values[field.name], setterFor(field.name), values)
          ) : field.type === "image" ? (
            <ImageField
              id={`entity-field-${field.name}`}
              label={field.label}
              value={values[field.name]}
              onChange={setterFor(field.name)}
              load={field.loadImage}
              cacheKey={field.imageKey}
              accept={field.accept}
              disabled={disabled}
            />
          ) : (
            <Input
              id={`entity-field-${field.name}`}
              type={field.type === "number" ? "number" : "text"}
              required={field.required}
              placeholder={field.placeholder}
              disabled={disabled}
              value={String(values[field.name] ?? "")}
              onChange={(event) => setValue(field.name, event.target.value)}
            />
          )}
        </div>
      ))}
      <div className="ideable:flex ideable:justify-end ideable:gap-2">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} disabled={disabled}>
            {cancelLabel ?? "Cancel"}
          </Button>
        )}
        <Button type="submit" disabled={disabled || !dirty}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}
