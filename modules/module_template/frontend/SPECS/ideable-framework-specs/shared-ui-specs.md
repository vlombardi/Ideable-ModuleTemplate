> **NOTE**: This file should not be changed since its content is inherited from the Ideable Framework module_template and is updated via the `sync-template-updates.sh` script. For module-specific frontend specifications, use the `module-ui-specs.md` file.

---

# Shared UI Specs

This module can be executed as a Module Federation 2.0:
- Master (optional - if present, it will provide the UI elements like Header, Menu, Footer)
- Remote (required - it will provide the UI pages that will be rendered inside the host_app content area)

## Remote mode
When it is executed as a Remote, the host_app is the Master and in this case, this module will not render any general UI element such as the Header, the Menu, the Footer, or other general UI elements.
Nonetheless, this module defines its own UI pages that will be invoked by specific host_app menu items and rendered inside the host_app content area.

In order to provide a homogeneous and consistent user experience, this module must build its UI from the shared **`@ideable/ui`** widget library (`reusable.ui/`) — the single source of truth for UI, Look & Feel, and widget definitions — and use the same visual tokens (colors, radii, typography scale) as host_app.
This purpose is achieved by importing the shared widgets/primitives from `@ideable/ui` and its styles once (`@import "@ideable/ui/styles"`). The canonical design tokens are defined once in `@ideable/ui` (`reusable.ui/styles/base-tokens.css`) and inherited by both host_app and this module — neither redefines them. host_app and this module do **not** provide their own copies of the shared widgets or the palette.
Whenever a CSS class should be overridden, it should be done by defining a new class with the same name but with a more specific selector (e.g., by prefixing it with the module's CSS prefix) — but rebrand by overriding token *values* (`data-lf="module"` tokens, or the runtime `config/theme-override.css`), never class names.

## Framework CSS Classes Reference

For a comprehensive reference of the framework's semantic CSS class tokens (owned by `@ideable/ui`), see:
`framework-css-classes-reference.md`

This document provides:
- Complete list of the semantic class tokens organized by category (colors, typography, spacing, layout, sizing, borders, effects, interactive states, animations, accessibility) — shared widgets author them with the neutral `ideable:` prefix; substitute your own prefix for your own markup
- Component-specific class combinations for Button, Input, Card, Dialog, Select, Tabs, Tooltip
- The canonical design-token source (`reusable.ui/styles/base-tokens.css`) and the `data-lf` parity/branding model
- Usage and override patterns, including the runtime `config/theme-override.css` rebranding path

Remote-mode L&F contract:
- Default behavior must match the shared `@ideable/ui` L&F and widget interaction patterns (host_app uses the same library, so parity is automatic).
- Module-specific L&F customizations are opt-in, done by overriding token *values* (never class names), and must be scoped to the module root only.
- Remote pages must not mutate host_app global selectors (`html`, `body`, universal `*`).

### Authentication and session handling

When executed as a Remote, this module must rely on host_app-managed authentication and session renewal.

Rules:
- Do not configure an independent OIDC login flow inside the remote module.
- Do not use iframe-based silent renew.
- Do not call `signinSilent()` or `signinRedirect()` from the remote module to recover an expired session.
- Treat host_app as the source of truth for authentication state, token renewal, and login redirects.
- Use the access token provided by host_app for authenticated API calls.
- If an API request fails with `401`, surface an authenticated-session-expired state to the host rather than trying to re-authenticate on its own.

Discoverability contract for module developers:
- `modules/module_template/frontend/SPECS/` is the canonical source to learn required host_app-compatible frontend patterns.
- `shared-ui-widgets-specs.md` defines widget-level behavior and layout rules.
- `SOURCES/` code in module_template must stay aligned with these specs and acts as copy-ready reference implementation.

### Menu rendering and is_collapsible

The host_app sidebar renders menu items from `modules_menu_mapping.json`. The merge logic preserves **all** fields from each module's mapping entries — no fields are dropped or defaulted.

Key fields affecting rendering:
- `is_collapsible` (boolean, default `false`): when `true`, the host_app renders a collapsible button with visible sub-items. When `false` or absent, the item is not collapsible and all sub-items are always visible. If this field is lost during merge, the menu item may be resolved but render incorrectly (e.g., invisible or non-collapsible).
- `authorization_claim` (string): gates menu visibility on the permission set `/api/me` returns — never on the token, which carries no authorization data. When present, only users holding the exact permission can see the item and its sub-tree.
- `routing` (string): the URL path the menu item navigates to.
- `icon` (string): the lucide-react icon name to display.

When an explicit `modules/host_app/config/modules_menu_mapping.json` exists, it is the complete merged menu — it must include entries for **all** enabled modules, not just host_app menus.

## Dirty form / navigation guard

Remote module pages that edit or create data must use the shared unsaved-changes guard so the same behavior is available in every host_app-compatible module.

Canonical implementation — consumed from the shared `@ideable/ui` library (do not fork locally):
- `useUnsavedChangesGuard` hook — `import { useUnsavedChangesGuard } from '@ideable/ui'`
- `UnsavedChangesDialog` widget — `import { UnsavedChangesDialog } from '@ideable/ui'`

Hook contract:
- `useUnsavedChangesGuard({ dirty, enabled? })` is the preferred entry point.
- The hook returns prompt state and guarded action helpers for cancel/save flows.
- The hook must always register a `beforeunload` fallback when the page is dirty and enabled.
- `useUnsavedChangesGuard(boolean)` remains supported for backward compatibility, but new pages should use the options object.

Guarded action contract:
- `requestGuardedAction({ onDiscard, onSave?, onKeepEditing? })` opens the shared confirmation dialog when dirty.
- `onDiscard` must reset or close the current edit context.
- `onSave` must save the pending form state and then close the edit context.
- `onKeepEditing` must simply dismiss the prompt and keep the current edit state active.

Discoverability for module developers:
- Use the guard for any form, drawer, modal, or inline edit flow where closing the page would lose unsaved work.
- Reuse the shared dialog labels from `common.unsavedChangesTitle`, `common.unsavedChangesMessage`, `common.save`, `common.discard`, and `common.keepEditing`.
- module_template pages should serve as the reference implementation for new remote modules.

## Master mode
Master mode requirements apply only when the module is explicitly configured to run as a standalone master; otherwise they are out of scope.

In order to allow the execution of this module as a Master, the following UI elements should be implemented:
- Header
- Menu
- Footer


## Authorization
The authorization pattern logic implemented by a module relies on the concept of `Permission`. A Permission is defined in terms of:
- `Resource`: defining on the object on which the authorization should be granted for a user. A Resource can be for example a table in the database, a file, a directory, etc. 
- `Action`: defining which action should be granted for a user on a specific resource. An Action can be for example `read`, `write`, `delete`, etc.

When a Permission is not explicitly granted to a user, the user should not be able to access it in any way.

When a module is executed as a Remote
- the authorization system is provided by the host_app and is transparent to this module
- Permissions are associated to Roles, Roles are associated with Profiles, and Profiles are associated with Users. 

When a module is executed as a Master, the authorization system should be implemented by the module following at least the Permission pattern, that in one way or another (directly or indirectly) must allow associating Permissions with Users.

---

## Authoritative source for entities

- The authoritative source for a module's entities is its `backend/SOURCES/app/models.py`, rendered
  for reading in `database/SPECS/schema.sql`.
- Menu generation must be derived from that datamodel (not from hardcoded frontend lists).

## Main entity definition

A datamodel table is a **main entity** when all the following are true:
- it is a business table from the module datamodel
- it is not a pure association/join table
- it is not a child-only table that exists exclusively under a parent context

A datamodel table is a **pure association/join table** if:
- it primarily represents links between other entities (typically only FK columns plus optional audit/metadata)
- it does not represent a standalone business object page

## Required menu generation contract

For each main entity in the datamodel:
- create exactly one menu item in `moduleManifest.menuItems`
- create exactly one route descriptor in `moduleManifest.routes`
- ensure menu item and route resolve to the same page
- create a corresponding page component for that entity and if not specified otherwise, use the same patterns used for the host_app main entities about how they are displayed in the UI, i.e., create a table with the entity's data and a form to add/edit/delete the entity's data.
- create an entry in the `menu_definition.json` file

`menuItems[]` entries must provide:
- `name`
- `href`
- `icon`
- optional `order`

`routes[]` entries must provide:
- `path`
- lazy `component` loader

## Path and ordering rules

- `menuItems[].href` must be a host_app absolute path including module base path (example: `/template/items`).
- `routes[].path` must be module-local and must not include base path (example: `/items`).
- Menu items must be sorted by `order` ascending, then by `name` ascending when `order` is equal or missing.

---

## Internationalization (i18n)

### Language hook

- Remote modules must read the active language from `localStorage.getItem('hostapp.language')` on mount and update reactively by listening to the `hostapp:language-changed` `CustomEvent` on `window`.
- The `useTranslation()` hook in `src/hooks/useTranslation.ts` implements this contract and must not be modified to break it. That module also carries the module's one call to `registerModuleMessages` (§ *Who owns which string*): it is the file every page goes through, so dropping the call would leave the module's overrides never taking effect — silently, since the widgets keep rendering the library's strings.
- Supported languages: `en` (English) and `it` (Italian). Both must always be kept in sync.

### Language files

- All user-visible strings must be defined in `src/i18n/en.json` and `src/i18n/it.json`.
- There must be one key per managed language; new keys added to `en.json` must always have a corresponding translation in `it.json` in the same change.
- Keys use a namespaced dot-notation structure (e.g. `table.rowsPerPage`, `templateItems.createItem`).

### i18n Coverage — mandatory for all components

- **Every user-visible string in every component must go through `t()`** — including shared components like `ServerDataTable`. Strings must never be hardcoded in JSX.
- Page components must call `useTranslation()` and use `t()` for all button labels, dialog titles, column headers, inline labels, and status messages.
- Shared components that render text (e.g. `ServerDataTable`) must call `useTranslation()` internally.
- Column headers defined in page files must use `t()` — never hardcoded strings like `header: "Full Name"`.
- Audit access is an action gated by the `audit_trail:view` permission, labelled with `table.viewAuditTrail`.

### Who owns which string

- **The library owns the strings of its own widgets.** `reusable.ui/i18n/en.json` and `it.json` define every `table.*`, `chart.*`, `auditTrail.*` and `common.*` string an `@ideable/ui` widget renders, and the widget resolves them through the library's own `useTranslation`. **A module renders a complete, translated table while holding none of those keys** — so a module must never copy a library string it does not mean to change: an identical copy overrides nothing today and pins the library's wording the day the library improves it.
- **A module's bundle must carry every key the module's OWN code passes to `t()`**, and that is the whole of what it must carry. The module's hook reads the module bundle alone and has no library fallback, so a key its pages ask for and it does not hold renders as the key itself. `table.viewAuditTrail` is the standing case: the page owns the audit-trail action and passes the label **into** the shared table.
- **A module overrides a widget string by including that key in its own bundle.** Inclusion **is** the override — nothing is declared per key, and there is no registry of overridable strings. The module's `useTranslation` registers its bundles with the library once, at import time (`registerModuleMessages` from `@ideable/ui`), and the shared hook then consults the module's bundle before its own, in the active language and in the English fallback alike.
- **A key is held, or dropped, in every language at once — so whether a copy overrides anything is judged across all of them.** `en.json` and `it.json` carry the same keys (§ *Language files*, enforced by `test_lang_files_have_identical_keys`), which makes holding a widget key a decision about the **key**, never about one language's value. A module that overrides `table.rowsPerPage` in Italian holds it in English too, at the library's own wording: that English row is required by key parity and is not a copy anyone may remove. A key therefore overrides nothing only when, in **every** supported language, the library carries it and the module's value is byte-identical — and where the library carries no such key at all, the module's string is the only one there is.

### i18n contract test

- `modules/module_template/frontend/TESTS/test_i18n_contract.py` verifies i18n coverage and must pass before releasing updates. It requires the keys the module's own code resolves, and **reports** — never forbids — two distinct things:
  - `test_module_overrides_of_library_strings_are_reported` names, **per language**, every library string the module overrides and what it became. *This key changes the library's Italian string* is a fact about Italian.
  - `test_keys_that_override_nothing_in_any_language_are_reported` names, in **one list for all languages**, the keys copied verbatim in every one of them. Those, and only those, can actually be deleted: each can go from every language file at once, leaving key parity intact and no override behind. Keys the module's own code resolves are excluded whatever their value, because the module's hook has no library fallback.
