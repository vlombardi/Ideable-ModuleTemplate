# `@ideable/ui` — Ideable Framework Shared UI Widget Library

`@ideable/ui` (this `reusable.ui/` folder) is the Ideable framework's **single shared UI widget library** — data tables with server‑side pagination/sorting/filtering, popups, an audit‑trail viewer, charts, dialogs, and the full set of accessible form primitives. **host_app, module_template, and every remote module generated from it all consume the same widgets from here.**

If you're building a remote module, this is the library you use to build every UI surface — and the `ideable-ui` skill is your guide for doing it.

---

## Why use it (benefits)

- **Build UI faster.** A production‑grade table, audit popup, chart, or dialog is one import away — you don't reimplement (or maintain) any of them.
- **Consistent look & feel, for free.** Widgets resolve the canonical `@ideable/ui` design tokens — the same ones host_app uses — so your module looks native inside the host with zero styling work.
- **Accessibility built in.** The interactive primitives (dialog, select, dropdown, tabs, tooltip, checkbox) are Radix‑based — focus management, keyboard nav, and ARIA are handled for you.
- **You get upstream improvements.** Bug fixes and new widgets shipped by the framework arrive in your module through a single sync command — no manual copying, no drift.
- **Light images.** Heavy dependencies (charts, etc.) are pulled in only when you actually use a widget that needs them; unused widgets are tree‑shaken out of your built image.
- **Guided by a skill.** The `ideable-ui` skill maps "I need to show/collect X" → the right widget, points at a live example, and encodes the framework's mandatory UI rules.

---

## What's included

| Family | Widgets |
|---|---|
| Tables | `ServerDataTable` (server‑side page/sort/filter), `AssociationServerDataTable` (M2M link/unlink grids), `DataTable` (legacy client‑side) |
| Popups & dialogs | `DraggableResizablePopup`, `AuditTrailPopup` (field‑level history), `UnsavedChangesDialog` (+ `useUnsavedChangesGuard`) |
| Chart | `TimeSeriesChart` (numeric value over time) |
| Icon | `DynamicIcon` (render any lucide icon by name) |
| Primitives | `Button`, `Input`, `Label`, `Checkbox`, `Select`, `Tabs`, `Tooltip`, `Card`, `Dialog`, `DropdownMenu` |
| Hooks | `useTranslation`, `useServerTableState`, `useUnsavedChangesGuard` |

A **live, runnable gallery** of all of these (wired to the sample `template_items` entity) ships in `module_template`: `modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx`, reachable in dev under **Template → UI Examples**.

---

## How it fits together (30‑second model)

- `@ideable/ui` is a local package your frontend depends on via `"@ideable/ui": "file:../../../../reusable.ui"`.
- Your frontend imports the shared **precompiled** styles once: `@import "@ideable/ui/styles";` — this brings the `ideable:` design‑token layer that the widgets use.
- Your `<body>` carries `class="ideable-scope" data-lf="hostapp"` so the widgets resolve the design tokens (also through Radix portals).
- **CSS prefix rule:** your own pages/components use **your module's prefix** (`${APP_SLUG}:`, e.g. `template:`). Shared widgets use the neutral **`ideable:`** prefix internally — you never write `ideable:` in your own markup.

> A module generated from `Ideable-ModuleTemplate` comes **pre‑wired** with all of the above. You normally just import widgets and go.

---

## Guide 1 — Receive platform UI widget updates

Framework UI updates (new widgets, fixes, the refreshed `compiled.css`) reach your module through the standard template sync. `reusable.ui/` is part of the framework‑synced set.

From your module project root:

```bash
# 1. Preview what would change (safe, read‑only)
./scripts/module_only/sync-template-updates.sh --list-changes

# 2. Apply the updates (pulls the latest reusable.ui/, framework specs, and the ideable-ui skill)
./scripts/module_only/sync-template-updates.sh
#   …or review each change interactively:
./scripts/module_only/sync-template-updates.sh --selective

# 3. Rebuild the frontend so it picks up the new @ideable/ui version
cd modules/<YOUR_MODULE>/frontend/SOURCES
npm install            # refreshes the @ideable/ui file: link + any new deps
npm run build          # or ./redeploy.sh from the project root to build + deploy
```

Notes:
- `reusable.ui/` is **framework‑owned** — treat it as read‑only. Don't edit widgets locally; consume them. If you need a change or a new widget, request it from the Ideable maintainer so it ships to everyone (see *Extending* below).
- The shared `styles/compiled.css` is a tracked artifact and arrives ready to use — no build step on your side.

---

## Guide 2 — Adopt & use the widgets in your module

**Prerequisite:** your module was generated from `Ideable-ModuleTemplate`, so the wiring in *How it fits together* is already in place. (If you're wiring a frontend by hand, replicate `module_template`'s `frontend/SOURCES`: the `file:` dependency, the `@import "@ideable/ui/styles"`, and the `ideable-scope` body.)

**Step 1 — Import the widgets you need.**
```tsx
import {
  ServerDataTable,
  type ColumnDef,
  Button,
  AuditTrailPopup,
  UnsavedChangesDialog,
  useUnsavedChangesGuard,
} from '@ideable/ui'
```

**Step 2 — Write your page markup with YOUR module prefix.** Only the widgets use `ideable:`; your own layout uses `${APP_SLUG}:` (here `template:`). Wrap your page in your module scope; the widgets bring their own styling.
```tsx
<div className="template-scope template:space-y-4" data-lf="hostapp">
  <h1 className="template:text-2xl template:font-bold">{t('myEntity.title')}</h1>
  {isEditEnabled && <Button onClick={openCreate}>{t('myEntity.create')}</Button>}
  {/* widgets below */}
</div>
```

**Step 3 — Build a list with `ServerDataTable`.** Columns are `@tanstack/react-table` `ColumnDef` (re‑exported from `@ideable/ui`). Use **string** headers (function headers are ignored) and `meta` for per‑column behavior.
```tsx
const columns: ColumnDef<MyEntity>[] = [
  { id: 'id',   accessorKey: 'id',   header: t('myEntity.id'),   meta: { sortable: true } },
  { id: 'name', accessorKey: 'name', header: t('myEntity.name'), meta: { sortable: true } },
]

<ServerDataTable<MyEntity>
  columns={columns}
  data={items} total={total} page={page} pageSize={pageSize}
  onPageChange={setPage} onPageSizeChange={setPageSize}
  onSortChange={handleSort} onFilterChange={handleFilter} filters={filters}
/>
```

**Step 4 — Add the audit trail, unsaved‑changes guard, chart, etc.** Pass page‑specific labels already translated; the widget resolves its own chrome.
```tsx
<AuditTrailPopup open={open} onClose={close} entityLabel={t('myEntity.title')}
  tabs={[{ label: t('myEntity.history'), columns: [...], fetchPage: service.getHistoryPage }]} />
```

**Step 5 — i18n.** Your page strings come from **your module's** `useTranslation`; the widgets carry their own `table.*`/`auditTrail.*`/`chart.*` strings. Keep `en.json`/`it.json` in sync.

**Step 6 — When in doubt, use the skill.** Invoke **`/ideable-ui`** (see below). Copy the working pattern from the gallery: `modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx` and the real page `.../pages/TemplateItems.tsx`.

### Reference implementation to copy
- Full gallery of every widget: `modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx`
- A real entity page (table + form + audit + unsaved guard): `modules/module_template/frontend/SOURCES/src/pages/TemplateItems.tsx`

---

## The `ideable-ui` skill

An agent skill ships alongside this library (`.claude/skills/ideable-ui/`, also visible to Kiro/Devin). Invoke it with **`/ideable-ui`** whenever you (or an AI agent) build or change a UI element. It:
- maps your need → the right widget (`reference/decision-guide.md`),
- indexes each widget → its source + the live gallery section + the spec (`reference/widget-index.md`),
- states the conventions (prefix, tokens, scope, i18n, tree‑shaking) and the mandatory UI anti‑patterns.

It references **only** `reusable.ui/` and `module_template/` — so it works fully inside a remote project (where host_app has no sources).

---

## Branding (change the look, keep the widgets)

Rebrand by overriding **token values, never class names** — widgets reference token names, so a rebrand touches only values. The canonical values live once in `reusable.ui/styles/base-tokens.css` (`:root` + `.dark`); every consumer inherits them. Three paths, in increasing independence:

- **Match the surrounding app (default):** under `data-lf="hostapp"` widgets use the canonical tokens automatically — nothing to do.
- **Per‑module look (build‑time):** set the `--ideable-module-*` overrides and render under `data-lf="module"` (see `reusable.ui/styles/tokens.css`).
- **Runtime, no rebuild, no host_app access:** edit `config/theme-override.css` in the **deployed** folder (`deployment_root/modules/<your-module>/config/`). It is served `no-store` and loaded after the compiled bundle, so redefining `:root { --… }` / `.dark { --… }` there recolors your module and every widget live. Logos, favicon, and backgrounds are swapped by replacing files in that same `config/` folder. (Bundled icon glyphs need a rebuild.)

Full how-to (what to change at build time vs deploy time, by role): `modules/module_template/frontend/SPECS/ideable-framework-specs/look-and-feel-branding.md`.

---

## Extending / maintaining (Ideable maintainers)

New widgets and changes land here in the canonical Ideable repo and propagate to everyone via the sync flow. When you change a widget/primitive:
1. Edit under `reusable.ui/` (`widgets/`, `primitives/`, `styles/`, `hooks/`).
2. **Regenerate the precompiled CSS** (mandatory — Tailwind v4 allows only one prefix per build, so the `ideable:` layer must ship as static CSS): `npm run build:css` in `reusable.ui/`, then commit `styles/compiled.css`.
3. Add a demonstrating section to `module_template`'s `WidgetGallery.tsx` and a row to the skill's `widget-index.md`.
4. Propagate: push to `module_template`, then remotes sync (Guide 1).
