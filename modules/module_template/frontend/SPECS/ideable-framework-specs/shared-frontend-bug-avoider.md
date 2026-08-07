# Shared Frontend Bug Avoider — Framework-Level Rules

These rules apply to every module's frontend. Module-specific `general_bug_avoider.md` files reference this file; do not duplicate these entries there.

---

## Audit Trail Popup: raw version tables are not useful

**Bug**: `AuditTrailPopup` displayed a raw table of all version fields (transaction_id, every column value). Users could not tell what changed between versions, and the table was too wide and hard to read.

**Fix**: Redesign the popup to show a focused timeline with four columns: **Op**, **When**, **Who**, **What Changed**. Compute per-field differences:
- **INSERT** → lists all initial non-empty field values
- **UPDATE** → shows only changed fields as `Field: old → new`
- **DELETE** → shows "Deleted"
- Updates with no visible changes → shows "No visible changes"

**Rule**: Audit trail popups must never dump raw version rows. They must compute and display field-level diffs so users can immediately see what changed. Skip internal metadata keys (`transaction_id`, `operation_type`, `end_transaction_id`, `au_*`, `event`, `client_ip`, `user_agent`, `request_method`, `request_path`) from diff computation.

---

## Entity pages: edit/delete action icons must be hidden in view mode

**Bug**: Entity pages showed edit and delete icons in the actions column even when `isEditEnabled` was `false` (view mode). Users could click them, though the underlying operations were still permission-gated.

**Fix**: Wrap action buttons with `isEditEnabled &&`:
```typescript
{isEditEnabled && canUpdate && (
  <Button variant="ghost" size="icon" onClick={...}>
    <Pencil className="<prefix>-h-4 <prefix>-w-4" />
  </Button>
)}
{isEditEnabled && canDelete && (
  <Button variant="ghost" size="icon" onClick={...}>
    <Trash2 className="<prefix>-h-4 <prefix>-w-4" />
  </Button>
)}
```

**Rule**: In entity pages with a view/edit mode toggle, all mutating action icons (edit, delete) must be conditionally rendered only when `isEditEnabled` is `true`. Do not rely solely on permission checks; the mode toggle is an explicit UX contract.

---

## Entity pages without audit trail must not show `au_*` columns

**Bug**: Some entity pages displayed `au_creation_timestamp`, `au_last_update_timestamp`, `au_created_by_user`, and `au_last_updated_by_user` columns even though the entity was static or externally managed and had no meaningful per-object audit trail data. These columns were always empty or misleading.

**Fix**: Remove all `au_*` column definitions from the affected table and remove the audit fields from the detail view panel.

**Rule**: Do not display `au_*` audit columns for entities that are not versioned or do not have a meaningful per-object audit trail. If an entity is static, externally managed, or otherwise lacks audit data, omit the audit fields from both table columns and detail views.

---

## Audit Trail Frontend: `computeDiffs` must skip synthetic association rows when finding `previous`

**Bug**: The audit popup rendered both Continuum field-change rows and synthetic association rows (`ASSOCIATE`/`DISASSOCIATE`) in the same list. `computeDiffs` took `previous = versions[idx + 1]`, which could be a synthetic row containing only association metadata. When comparing a real UPDATE version against a sparse synthetic row, every user field appeared different (the synthetic row had `undefined` for most fields), producing a phantom "all user data changed" diff.

**Fix**: Before calling `computeDiffs`, walk forward from `idx + 1` to find the nearest row whose `operation_type` is NOT `3` (`ASSOCIATE`) or `4` (`DISASSOCIATE`), and use that as `previous`.

**Rule**: When computing field-level diffs in an audit popup that mixes field-change rows with synthetic association rows, always locate the nearest actual field-version row as the comparison baseline. Never compare a Continuum version against a synthetic sparse row.

---

## Audit Trail Popup: must be centered, draggable, and resizable

**Bug**: The Audit Trail Popup was rendered using the Radix `Dialog` component or a custom fixed-position div that appeared offset to the right-bottom of the viewport instead of centered. The popup could not be dragged or resized, making it difficult to view large audit tables.

**Fix**: Replace all audit trail popup implementations with the shared `DraggableResizablePopup` component (`src/components/DraggableResizablePopup.tsx`). This component:
- Centers the popup in the viewport on open
- Provides a drag handle in the header for repositioning
- Provides a resize handle in the bottom-right corner for size adjustment
- Renders via `createPortal` into `document.body` to avoid clipping

**Rule**: Audit trail popups must never use Radix `Dialog` or custom fixed-position divs. They must always use `DraggableResizablePopup` to ensure consistent centering, drag, and resize behavior across host_app and all remote modules.
