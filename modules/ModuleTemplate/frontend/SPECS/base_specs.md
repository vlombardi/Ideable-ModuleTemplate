# IMPORTANT: Read This First

**This file (`base-specs.md`) is the MANDATORY starting point for any coding agent action on this module's frontend.**

Before implementing, modifying, or troubleshooting any frontend component, you MUST:
1. Read `rules/general-guidelines.md`, then
2. Read this entire file, then
3. Read `module-specs.md`, then any other further referenced specs files.
4. Read `shared-ui-specs.md` for shared remote-mode, authorization, and menu generation rules.
5. Read `shared-ui-widgets-specs.md` for widget-level behavior and layout rules (tables, modals, dropdowns, etc.).

Following the order above, if two rules conflict at the same level, the above order defines the priority logic (i.e., rule in previous point wins, e.g., rule in point 1 wins over rule in point 2, and so on).


## Specification Files Chain

| File | Status | Purpose |
|---|---|---|
| `shared-ui-specs.md` | **MANDATORY** | Shared cross-module UI contract |
| `shared-ui-widgets-specs.md` | **MANDATORY** | Shared widget-level behaviour |
| `module-ui-specs.md` | **MANDATORY** | This module's entity/menu/route specs |

> **Deployment Rules**: Per `rules/general-guidelines.md` lines 98-115:
> - No `build:` sections in docker-compose
> - Docker images must be pre-built before deployment
> - No `SOURCES/` path references in docker-compose

## Build

- Build Docker image: `docker build --no-cache -t ${APP_SLUG}/frontend:latest --build-arg VITE_${APP_SLUG_UPPER}_API_URL=${VITE_${APP_SLUG_UPPER}_API_URL} ./SOURCES/`
- Produces Docker image only; no DIST folder.
- **Note**: `${APP_SLUG}` and `${APP_SLUG_UPPER}` are placeholders. Read the actual slug from `module.json` `slug` field.

## Technology

- Build tool: Rsbuild.
- Module Federation role: remote (`name: ${APP_SLUG}` — read from `module.json` `slug`).
- `rsbuild.config.ts` must expose `./moduleManifest`.
- Output and dev asset prefix must be `/remotes/${APP_SLUG}/`.

## Module Identity Reference (Source of Truth: `module.json`)

All module-specific values below use `${APP_SLUG}` placeholder.
Read the actual value from `module.json` in this module's root:
- `slug` → used for CSS prefix, MF name, URLs, permissions namespace
- `name` → used for display names

## Module Manifest

- `src/moduleManifest.ts` must export the remote module contract used by HostApp.
- **Example contract baseline**: this file uses the `template` slug as the reference example for HostApp-integrated remote modules.
- This module implements, as example baseline:
  - `slug: ${APP_SLUG}` (from `module.json`)
  - Menu items are HostApp absolute paths including module base path (for example `/${APP_SLUG}/items`)
  - Route descriptors are module-local (for example `/dashboard`, `/items`) and HostApp applies `basePath`
  - One menu item and one route are required for each main entity derived from `database/SPECS/datamodel.sql`
  - Menu item contract fields are required: `name`, `href`, `icon`, optional `order`
  - Permissions in `${APP_SLUG}.items.*` namespace (general pattern: `${APP_SLUG}.${entity}.*`)

## Authentication and session handling

- Remote modules must rely on HostApp-managed authentication and session renewal.
- Do not configure an independent OIDC login flow inside the remote module.
- Do not use iframe-based silent renew.
- Do not call `signinSilent()` or `signinRedirect()` from the remote module to recover an expired session.
- Treat HostApp as the source of truth for authentication state, token renewal, and login redirects.
- Use the access token provided by HostApp for authenticated API calls.
- If an API request fails with `401`, surface an authenticated-session-expired state to the host rather than trying to re-authenticate on its own.

## Dirty form / navigation guard

- Any page that allows editing or creating data must track whether there are unsaved changes.
- When the user attempts to leave an edit context with unsaved changes, the UI must prompt before losing work.
- For in-app navigation, show a confirmation dialog that offers save, discard, or cancel.
- For browser refresh or tab close, register a `beforeunload` fallback so the browser warns the user that unsaved changes exist.

## Standalone Menu Definition Contract

- The module `config/` folder must include `menu_definition.json` for standalone runtime navigation (module running outside HostApp integration).
- `menu_definition.json` must contain a top-level `menu_definition` array.
- Each `menu_definition` item must contain:
  - `menu_item_code`
  - `menu_item_name`
  - `icon`
  - optional `routing` (omitted for container-only nodes)
  - `sub_items` array with the same recursive item structure

Verification URLs (deployed environment, using `${APP_SLUG}` from `module.json`):
- `https://<host>/module-registry.json`
  - Must include `${APP_SLUG}` with entry `/remotes/${APP_SLUG}/mf-manifest.json`.
- `https://<host>/remotes/${APP_SLUG}/mf-manifest.json`
  - Must be reachable and must include exposed module `./moduleManifest`.

## CSS Isolation

- Tailwind prefix must be `${APP_SLUG}-` (slug from `module.json`).
- Utility classes must follow prefix usage consistently across remote pages/components.
- Module visual tokens must inherit HostApp design tokens by default when running inside HostApp.
- Module must expose module-scoped override tokens so the module can override inherited values when needed without changing HostApp global tokens.

## Canonical Compatibility Role

- **ModuleTemplate is the canonical, always-updated compatibility reference** for developers building HostApp-integrated remote modules.
- Module developers should be able to rely on ModuleTemplate alone to discover required integration patterns for routing, auth, widgets, and L&F behavior.
- ModuleTemplate specs and implementation must be kept aligned with the HostApp integration rules described in the shared specs/docs (e.g., in `<module_slug>/SPECS/base-specs.md` and all other ) in the same change cycle whenever integration rules evolve.
- ModuleTemplate specs and implementation must be kept aligned with the HostApp integration rules described in the shared specs/docs (e.g., in `<module_slug>/<SUB-MODULE-NAME>/SPECS/base-specs.md` and all other  ) in the same change cycle whenever integration rules evolve.
- ModuleTemplate frontend is the L&F source of truth for reusable remote-module UI patterns.

## L&F parity validation requirements

The following checks are mandatory before releasing ModuleTemplate updates:

1. Automated parity contract checks:
   - `modules/ModuleTemplate/frontend/TESTS/test_template_items_table_contract.py`
   - `modules/ModuleTemplate/frontend/TESTS/test_lf_parity_contract.py`
2. Visual snapshot parity checks (Playwright):
   - `modules/ModuleTemplate/frontend/TESTS/playwright/tests/lf-parity.spec.ts`

Recommended runner from repository root:

```bash
./scripts/check_moduletemplate_lf_parity.sh
```

## Remote L&F Modes

- Default mode (mandatory): ModuleTemplate pages inherit HostApp visual tokens.
- Override mode (optional): module-specific L&F is allowed only through module-scoped token overrides and selectors.
- Module frontend code must never alter HostApp global selectors (`html`, `body`, universal `*`) when running as a remote.

