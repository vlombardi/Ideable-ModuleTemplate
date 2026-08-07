# @ideable/ui Conventions

## Importing

- Import widgets/primitives/hooks from `@ideable/ui` (barrel) or deep paths (`@ideable/ui/widgets/ServerDataTable`, `@ideable/ui/primitives/button`) for the tightest tree-shaking.
- Import the shared styles **once** per consumer, in the consumer's root CSS: `@import "@ideable/ui/styles"`. This resolves (via the package `exports` + `file:` dependency) to the **precompiled, plain** `reusable.ui/styles/compiled.css` — the `ideable:` utility layer + design tokens + `.ideable-scope` cascade, already built, with **no `tailwindcss` re-import** and no preflight.
- **Why precompiled (critical):** Tailwind v4 honors only **one** prefix per compilation. If the shared styles re-imported `tailwindcss` with `prefix(ideable)`, it would **clobber the consumer's own `hostapp:`/`template:` layer** (total L&F loss). Shipping the `ideable:` layer as static CSS lets the consumer's single `@import "tailwindcss" prefix(<module>)` and the `ideable:` classes coexist.
- **Regenerating `compiled.css`:** whenever a widget/primitive adds or changes an `ideable:` class, run `npm run build:css` in `reusable.ui/` (it runs `tailwindcss -i styles/index.css -o styles/compiled.css`, scanning `widgets/` + `primitives/`) and commit the result. It is a tracked artifact so it syncs to remotes and is present in Docker builds (no Tailwind CLI needed at consume time).
- Resolution: `@ideable/ui` is a `file:` dependency; JS/CSS resolve via `node_modules`. Docker builds stage the package into the context (`SPECS/build.sh`) and `npm install --install-links`.

## CSS prefixes (two-prefix model)

- **Module-owned** components/pages use the **module's own** Tailwind prefix: `hostapp:` (host_app), `template:` / `${APP_SLUG}:` (remotes).
- **Shared `@ideable/ui`** widgets/primitives use the neutral **`ideable:`** prefix.
- The two layers coexist in one build. A page can mix: its own chrome in `template:`, the shared widgets it renders in `ideable:`.

## Design tokens & branding

- Tokens live in `reusable.ui/styles/tokens.css` as `--ideable-*` (single source of the palette; light + `.dark`).
- **Brand a project by overriding token VALUES, never class names.** Either redefine `--ideable-*`, or set `[data-lf='module']` overrides (`--ideable-module-*`). Widgets reference token names, so a rebrand touches only values.
- Inside host_app the tokens inherit host's runtime tokens (`.ideable-scope[data-lf='hostapp']` → `var(--primary)`, …) so shared widgets match host L&F automatically.

## The `.ideable-scope` wrapper (required for tokens)

- Shared widgets need an `.ideable-scope` ancestor so `--ideable-*` resolve.
- Consumers put `class="ideable-scope" data-lf="hostapp"` on `<body>` (so Radix **portals** — Dialog/Select/Tooltip/popups render to `document.body` — also resolve tokens). Page wrappers may add `ideable-scope` too.
- `DraggableResizablePopup` also self-scopes its portal.

## i18n split

- **Widget chrome** strings (`table.*`, `chart.*`, `auditTrail.*`, `common.*` used by widgets) belong to `@ideable/ui` and are resolved by the widget via `@ideable/ui`'s `useTranslation` (reads `localStorage['hostapp.language']` + the `hostapp:language-changed` event — works standalone and inside host).
- **Page-specific** strings belong to the module and are resolved by the **module's own** `useTranslation`. Pass page labels to widgets already translated (e.g. `ServerDataTable` column `header: t('templateItems.name')`).
- Keep `en.json`/`it.json` in sync in every i18n bundle.

## Tree-shaking & deps

- `@ideable/ui` is `sideEffects: false` (except CSS) with named exports → a consumer bundles only the widgets it imports. Heavy deps (Recharts, Radix, react-table) are pulled **only** when a widget that uses them is imported.
- Import `TimeSeriesChart`/Recharts **only** through code paths a module actually uses (e.g. the dev-only gallery) so Recharts is tree-shaken out of published images when unused (`WIDGET_EXAMPLES=false`).

## ServerDataTable specifics

- Columns are `@tanstack/react-table` `ColumnDef` (re-exported from `@ideable/ui`). Header must be a **string** (`header: t('...')`) — function headers are ignored.
- Per-column UI meta is `{ sortable?, filterable?, type?: 'text'|'boolean'|'number', filterType? }` (typed via the framework augmentation).
- Mutating action icons (edit/delete) render only when the page's edit mode is on (see bug-avoider digest).
