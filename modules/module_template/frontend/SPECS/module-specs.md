# Module-Specific UI Specs

This file contains frontend specifications that are specific to **this module's** entities and business rules. The shared cross-module UI contract (entity definition, menu generation, path rules, i18n, L&F, widgets, auth/session handling) is defined in `shared-ui-specs.md` and `shared-ui-widgets-specs.md`.

- Remote modules must rely on host_app-managed authentication and session renewal; they must not introduce their own OIDC login or silent-renew recovery flow.
- Any standalone menu grouping used by this module for administrative pages must be rendered as a collapsible parent menu.
- Collapsible parents must start collapsed by default, auto-expand on matching routes, and preserve a user's explicit collapsed state until the user reopens them.

---

## Minimum expected result for current datamodel

Given current `datamodel.sql`, the main entity set includes:
- `template_items`

Therefore this module must expose at least:
- one menu item for `template_items` (for example `Items`)
- one corresponding route page for that entity
