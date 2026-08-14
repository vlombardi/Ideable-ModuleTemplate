import * as React from "react"
import { cn } from "../lib/utils"

/**
 * Canonical entity-table row action button for @ideable/ui.
 *
 * One source of truth for the look & feel of the per-row action icons (view / edit /
 * delete / history / …) so every table — host_app, module_template, and every remote
 * module — renders them identically: a rounded-square, bordered icon button with a
 * hover-accent fill. Pages MUST use this instead of hand-rolling `<button>`/`<Button>`
 * markup in their `actions` column, which previously drifted per module.
 *
 * - `variant="default"` — neutral bordered square, hover fills with the accent colour.
 * - `variant="danger"`  — destructive action (delete), rendered with the theme's
 *   destructive colour and a filled hover.
 */
export interface RowActionButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /**
   * Icon component to render (sized to the button automatically). Typed as
   * `React.ElementType` rather than lucide's `LucideIcon` on purpose: consumers
   * import lucide-react from their own install, which is a nominally distinct type
   * from @ideable/ui's copy — a structural element type accepts either without a
   * cast, and also accepts a plain inline-SVG component.
   */
  icon: React.ElementType
  variant?: "default" | "danger"
}

export const RowActionButton = React.forwardRef<HTMLButtonElement, RowActionButtonProps>(
  ({ icon: Icon, variant = "default", className, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(
        "ideable:inline-flex ideable:h-8 ideable:w-8 ideable:items-center ideable:justify-center ideable:rounded-md ideable:border ideable:bg-background ideable:text-sm ideable:transition-colors ideable:focus-visible:outline-none ideable:focus-visible:ring-2 ideable:focus-visible:ring-ring ideable:focus-visible:ring-offset-2 ideable:disabled:pointer-events-none ideable:disabled:opacity-50",
        variant === "danger"
          ? "ideable:border-destructive/40 ideable:text-destructive ideable:hover:bg-destructive ideable:hover:text-destructive-foreground"
          : "ideable:hover:bg-accent ideable:hover:text-accent-foreground",
        className,
      )}
      {...props}
    >
      <Icon className="ideable:h-4 ideable:w-4" aria-hidden="true" />
    </button>
  ),
)
RowActionButton.displayName = "RowActionButton"

/**
 * Row-action container: lays out one or more {@link RowActionButton}s consistently
 * (right-aligned, evenly gapped). Use it as the cell content of the `actions` column.
 */
export function RowActions({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "ideable:flex ideable:items-center ideable:justify-end ideable:gap-1",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
