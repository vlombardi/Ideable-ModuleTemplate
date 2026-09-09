# UI Bug-Avoider Digest (mandatory)

Condensed from `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md` — read that file for full rationale. These are hard rules.

## Audit Trail Popup
- **Never dump raw version rows.** Compute field-level diffs: INSERT → initial non-empty values; UPDATE → only changed fields as `Field: old → new`; DELETE → "Deleted"; no visible change → "No visible changes".
- Skip internal metadata keys from diffs: `transaction_id`, `operation_type`, `end_transaction_id`, `au_*`, `event`, `client_ip`, `user_agent`, `request_method`, `request_path`.
- When computing `previous`, **skip synthetic association rows** (`ASSOCIATE`=3 / `DISASSOCIATE`=4) — walk forward to the nearest real field-version row, else you get a phantom "everything changed" diff.
- Association rows show `Link`/`Unlink` icons + association/peer info, not a field diff.
- The popup MUST use `DraggableResizablePopup` (centered/draggable/resizable, portal) — **never** Radix `Dialog` or a fixed-position div.
- Gate the audit action by the `audit_trail:view` claim; surface `401`/`403` states.

## Entity pages
- **Edit/delete action icons render only when edit mode is on** (`isEditEnabled && ...`). Don't rely on permission checks alone — the view/edit toggle is an explicit UX contract.
- **Do not show `au_*` audit columns** for entities that aren't versioned / lack per-object audit data (they'd be empty/misleading).

## i18n
- Every user-visible string goes through `t()` — never hardcoded in JSX. Widget chrome via `@ideable/ui` `useTranslation`; page strings via the module's `useTranslation`. Keep `en.json`/`it.json` in sync.

## Tokens / prefix / scope
- Shared widgets must render under an `.ideable-scope` ancestor (put it on `<body>` so Radix portals resolve tokens). Never style shared widgets with a module prefix; use `ideable:`.
- Never mutate host_app global selectors (`html`, `body`, universal `*`) from a remote; override only via module-prefixed selectors or `--ideable-module-*` token overrides.

## Charts
- Time-series entity pages (timestamp + numeric column) must render a `TimeSeriesChart` in addition to the table.
- Chart colors/gridlines/axis come from design tokens (automatic light/dark) — no `dark:` variants.
