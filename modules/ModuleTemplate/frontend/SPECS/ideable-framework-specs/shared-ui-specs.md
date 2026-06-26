> **NOTE**: This file should not be changed since its content is inherited from the Ideable Framework ModuleTemplate and is updated via the `sync-template-updates.sh` script. For module-specific frontend specifications, use the `module-ui-specs.md` file.

---

# Shared UI Specs

This module can be executed as a Module Federation 2.0:
- Master (optional - if present, it will provide the UI elements like Header, Menu, Footer)
- Remote (required - it will provide the UI pages that will be rendered inside the HostApp content area)

## Remote mode
When it is executed as a Remote, the HostApp is the Master and in this case, this module will not render any general UI element such as the Header, the Menu, the Footer, or other general UI elements.
Nonetheless, this module defines its own UI pages that will be invoked by specific HostApp menu items and rendered inside the HostApp content area.

In order to provide a homogeneous and consistent user experience, this module should follow the same UI patterns used by the HostApp, and use the same visual tokens (colors, radii, typography scale) as the HostApp.
This purpose is achieved by adopting the same `shared-ui-widgets-specs.md` specification file and by referencing the same CSS classes, whose actual definition will be available in the execution context of the HostApp.
Whenever a CSS class should be overridden, it should be done by defining a new class with the same name but with a more specific selector (e.g., by prefixing it with the module's CSS prefix).

Remote-mode L&F contract:
- Default behavior must match HostApp L&F and widget interaction patterns.
- Module-specific L&F customizations are opt-in and must be scoped to the module root only.
- Remote pages must not mutate HostApp global selectors (`html`, `body`, universal `*`).

### Authentication and session handling

When executed as a Remote, this module must rely on HostApp-managed authentication and session renewal.

Rules:
- Do not configure an independent OIDC login flow inside the remote module.
- Do not use iframe-based silent renew.
- Do not call `signinSilent()` or `signinRedirect()` from the remote module to recover an expired session.
- Treat HostApp as the source of truth for authentication state, token renewal, and login redirects.
- Use the access token provided by HostApp for authenticated API calls.
- If an API request fails with `401`, surface an authenticated-session-expired state to the host rather than trying to re-authenticate on its own.

Discoverability contract for module developers:
- `modules/ModuleTemplate/frontend/SPECS/` is the canonical source to learn required HostApp-compatible frontend patterns.
- `shared-ui-widgets-specs.md` defines widget-level behavior and layout rules.
- `SOURCES/` code in ModuleTemplate must stay aligned with these specs and acts as copy-ready reference implementation.

## Dirty form / navigation guard

Remote module pages that edit or create data must use the shared unsaved-changes guard so the same behavior is available in every HostApp-compatible module.

Canonical implementation:
- `modules/ModuleTemplate/frontend/SOURCES/src/hooks/useUnsavedChangesGuard.ts`
- `modules/ModuleTemplate/frontend/SOURCES/src/components/UnsavedChangesDialog.tsx`

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
- ModuleTemplate pages should serve as the reference implementation for new remote modules.

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
- the authorization system is provided by the HostApp and is transparent to this module
- Permissions are associated to Roles, Roles are associated with Profiles, and Profiles are associated with Users. 

When a module is executed as a Master, the authorization system should be implemented by the module following at least the Permission pattern, that in one way or another (directly or indirectly) must allow associating Permissions with Users.

---

## Authoritative source for entities

- The authoritative source for a module's entities is the module's `database/SPECS/datamodel.sql`.
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
- create a corresponding page component for that entity and if not specified otherwise, use the same patterns used for the HostApp main entities about how they are displayed in the UI, i.e., create a table with the entity's data and a form to add/edit/delete the entity's data.
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

- `menuItems[].href` must be a HostApp absolute path including module base path (example: `/template/items`).
- `routes[].path` must be module-local and must not include base path (example: `/items`).
- Menu items must be sorted by `order` ascending, then by `name` ascending when `order` is equal or missing.

---

## Internationalization (i18n)

### Language hook

- Remote modules must read the active language from `localStorage.getItem('hostapp.language')` on mount and update reactively by listening to the `hostapp:language-changed` `CustomEvent` on `window`.
- The `useTranslation()` hook in `src/hooks/useTranslation.ts` implements this contract and must not be modified to break it.
- Supported languages: `en` (English) and `it` (Italian). Both must always be kept in sync.

### Language files

- All user-visible strings must be defined in `src/i18n/en.json` and `src/i18n/it.json`.
- There must be one key per managed language; new keys added to `en.json` must always have a corresponding translation in `it.json` in the same change.
- Keys use a namespaced dot-notation structure (e.g. `table.rowsPerPage`, `templateItems.createItem`).

### i18n Coverage — mandatory for all components

- **Every user-visible string in every component must go through `t()`** — including shared components like `ServerDataTable`. Strings must never be hardcoded in JSX.
- Page components must call `useTranslation()` and use `t()` for all button labels, dialog titles, column headers, inline labels, and status messages.
- Shared components that render text (e.g. `ServerDataTable`) must call `useTranslation()` internally.
- The following table chrome strings must be covered by keys under the `table.*` namespace: `rowsPerPage`, `viewAuditTrail`, `filterPlaceholder`, `all`, `true`, `false`, `noResults`, `showing` (with `{{from}}`, `{{to}}`, `{{total}}` vars), `page` (with `{{page}}`, `{{total}}` vars), `deleteSelected` (with `{{count}}` var), `updating`, `errorLoading`, and `columns.{createdAt,updatedAt,creator,updater}`. Note: `showAuditData` and `hideAuditData` keys are removed; audit access is now an action gated by the `audit_trail:view` permission.
- Column headers defined in page files must use `t()` — never hardcoded strings like `header: "Full Name"`.

### i18n contract test

- `modules/ModuleTemplate/frontend/TESTS/test_i18n_contract.py` verifies i18n coverage and must pass before releasing updates.
