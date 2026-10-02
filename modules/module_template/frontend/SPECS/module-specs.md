# Module-Specific UI Specs

This file contains frontend specifications that are specific to **this module's** entities and business rules. The shared cross-module UI contract (entity definition, menu generation, path rules, i18n, L&F, widgets, auth/session handling) is defined in `shared-ui-specs.md` and `shared-ui-widgets-specs.md`.

- Remote modules must rely on host_app-managed authentication and session renewal; they must not introduce their own OIDC login or silent-renew recovery flow.
- Any standalone menu grouping used by this module for administrative pages must be rendered as a collapsible parent menu.
- Collapsible parents must start collapsed by default, auto-expand on matching routes, and preserve a user's explicit collapsed state until the user reopens them.

---

## Minimum expected result for current datamodel

Given the current schema (`database/SPECS/schema.sql`, generated from `app/models.py`), the
datamodel currently defines three entities:
- `template_items` — main entity
- `sub_items` — association entity, reached from `template_items`'s association view
- `sub_item_notes` — association entity, reached from `sub_items`'s association view, and from
  `template_items`'s own association view one level deeper (Depth: the selected sub-item's notes;
  Full: every note reachable from the selected item, via `GET /items/{id}/sub_item_notes`)

Per `shared-ui-widgets-specs.md` § *Main entities definition*, every entity gets a standard page
by default, opt-out only. None of the three is opted out here, so this module must expose:
- one menu item and one `StandardEntityPage` route for `template_items` (for example `Items`)
- one menu item and one `StandardEntityPage` route for `sub_items` (for example `Sub-Items`)
- one menu item and one `StandardEntityPage` route for `sub_item_notes` (for example
  `Sub-Item Notes`)

`sub_items` and `sub_item_notes` keep appearing inside `template_items`'s (respectively
`sub_items`'s) association view exactly as before — their own page is additional, not a
replacement for that. `template_items`'s own association view carries both levels: `sub_items`
at the first hop, `sub_item_notes` one hop below it — a maintainer visiting Items can descend
straight to a sub-item's notes without first opening the Sub-Items page.

### Entity page opt-outs

None currently. A future entity added to this module's datamodel gets a standard page by default;
list it here, with the reason, the moment a maintainer decides it should have none (or a
non-standard one) instead.
