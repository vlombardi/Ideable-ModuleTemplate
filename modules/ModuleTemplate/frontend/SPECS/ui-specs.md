# IMPORTANT: Read This First

**This file (`ui-specs.md`) is the MANDATORY starting point for any coding agent action on this module.**

Before implementing, modifying, or troubleshooting any UI component, you MUST:
1. Read this entire file.
2. Follow all references in the specification chain.
3. Read the `ui-widgets-specs.md` to understand how to implement specific UI Widgets (e.g., Tables, Modal dialogs, Dropdown list, etc.).

## Normative precedence

If rules overlap, apply them in this order:
1. This file (`ui-specs.md`)
2. `ui-widgets-specs.md`
3. Related `general_bug_avoider.md` rules for the touched scope

If two rules conflict at the same level, the more specific rule wins.

# General UI Specs
(HostApp UI specs vs Module UI specs)

This module can be executed as a Model Framework 2.0: 
- Master (optional - if present, it will provide the UI elements like Header, Menu, Footer)
- Remote (required - it will provide the UI pages that will be rendered inside the HostApp content area)

## Remote mode
When it is executed as a Remote, the HostApp is the Master and in this case, this module will not render any general UI element such as the Header, the Menu, the Footer, or other general UI elements.
Nonetheless, this module defines its own UI pages that will be invoked by specific HostApp menu items and rendered inside the HostApp content area.

In order to provide a homogeneous and consistent user experience, this module should follow the same UI patterns used by the HostApp, and use the same visual tokens (colors, radii, typography scale) as the HostApp.
This purpose is achieved by adopting the same `ui-widgets-specs.md` specification file and by referencing the same CSS classes, whose actual definition will be available in the execution context of the HostApp.
Whenever a CSS class should be overridden, it should be done by defining a new class with the same name but with a more specific selector (e.g., by prefixing it with `template-`).

Remote-mode L&F contract:
- Default behavior must match HostApp L&F and widget interaction patterns.
- Module-specific L&F customizations are opt-in and must be scoped to the module root only.
- Remote pages must not mutate HostApp global selectors (`html`, `body`, universal `*`).

Discoverability contract for module developers:
- `modules/ModuleTemplate/frontend/SPECS/` is the canonical source to learn required HostApp-compatible frontend patterns.
- `ui-widgets-specs.md` defines widget-level behavior and layout rules.
- `SOURCES/` code in ModuleTemplate must stay aligned with these specs and acts as copy-ready reference implementation.

## Master mode
Master mode requirements apply only when ModuleTemplate is explicitly configured to run as a standalone master; otherwise they are out of scope.

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

# Module-specific UI rules

## Authoritative source for entities

- The authoritative source for ModuleTemplate entities is `modules/ModuleTemplate/database/SPECS/datamodel.sql`.
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

## Explicit table requirements copied from HostApp

For each ModuleTemplate main-entity page table, apply the following HostApp table rules explicitly:

- Every column in the header must be sortable (click header label or icon).
- Sorting icon states must distinguish: active ascending, active descending, and not-sorted.
- For text columns, render a header text input for substring filtering.
- For boolean columns, render a header select filter with `All / True / False`.
- Boolean filter normalization must accept case-insensitive true-ish values (`true`, `t`, `1`, `yes`, `y`, `on`) and false-ish values (`false`, `f`, `0`, `no`, `n`, `off`); empty/missing means no filter.
- Use server-side pagination with:
  - elements-per-page control (above table, left)
  - footer controls (below table, right): first, previous, current page of total pages, next, last
- Render filters only for data columns. Do not render filter inputs for selection checkbox column (`__select__`) and actions column (`actions`).
- When a filter is cleared, omit that query parameter entirely from the API request (do not send empty-string values).

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

## Minimum expected result for current datamodel

Given current `datamodel.sql`, the main entity set includes:
- `template_items`

Therefore ModuleTemplate must expose at least:
- one menu item for `template_items` (for example `Items`)
- one corresponding route page for that entity
