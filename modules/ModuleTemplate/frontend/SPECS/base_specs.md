# ModuleTemplate Frontend Specs

> **Deployment Rules**: Per `rules/general-guidelines.md` lines 98-115:
> - No `build:` sections in docker-compose
> - Docker images must be pre-built before deployment
> - No `SOURCES/` path references in docker-compose

## Build

- Build Docker image: `docker build --no-cache -t template/frontend:latest --build-arg VITE_TEMPLATE_API_URL=${VITE_TEMPLATE_API_URL} ./SOURCES/`
- Produces Docker image only; no DIST folder.

## Technology

- Build tool: Rsbuild.
- Module Federation role: remote (`name: template`).
- `rsbuild.config.ts` must expose `./moduleManifest`.
- Output and dev asset prefix must be `/remotes/template/`.

## Module Manifest

- `src/moduleManifest.ts` must export the remote module contract used by HostApp.
- **Full contract specification**: See `modules/HostApp/SPECS/module-integration-specs.md` section "2) Remote Module Contract" for complete field definitions.
- This module implements:
  - `slug: template`
  - Menu items are HostApp absolute paths including module base path (for example `/template/items`)
  - Route descriptors are module-local (for example `/dashboard`, `/items`) and HostApp applies `basePath`
  - One menu item and one route are required for each main entity derived from `modules/ModuleTemplate/database/SPECS/datamodel.sql`
  - Menu item contract fields are required: `name`, `href`, `icon`, optional `order`
  - Permissions in `template.items.*` namespace

## Standalone Menu Definition Contract

- The module `config/` folder must include `menu_definition.json` for standalone runtime navigation (module running outside HostApp integration).
- `menu_definition.json` must contain a top-level `menu_definition` array.
- Each `menu_definition` item must contain:
  - `menu_item_code`
  - `menu_item_name`
  - `icon`
  - optional `routing` (omitted for container-only nodes)
  - `sub_items` array with the same recursive item structure

Verification URLs (deployed environment):
- `https://<host>/module-registry.json`
  - Must include `template` with entry `/remotes/template/mf-manifest.json`.
- `https://<host>/remotes/template/mf-manifest.json`
  - Must be reachable and must include exposed module `./moduleManifest`.

## CSS Isolation

- Tailwind prefix must be `template-`.
- Utility classes must follow prefix usage consistently across remote pages/components.
- ModuleTemplate visual tokens must inherit HostApp design tokens by default when running inside HostApp.
- ModuleTemplate must expose module-scoped override tokens so the module can override inherited values when needed without changing HostApp global tokens.

## Canonical Compatibility Role

- ModuleTemplate is the canonical, always-updated compatibility reference for developers building HostApp-integrated remote modules.
- ModuleTemplate specs and implementation must be kept aligned with `modules/HostApp/SPECS/module-integration-specs.md` in the same change cycle whenever integration rules evolve.
- Module developers should be able to rely on ModuleTemplate alone to discover required integration patterns for routing, auth, widgets, and L&F behavior.
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

- Default mode (mandatory): ModuleTemplate pages inherit HostApp visual tokens and interaction patterns.
- Override mode (optional): module-specific L&F is allowed only through module-scoped token overrides and selectors.
- Module frontend code must never alter HostApp global selectors (`html`, `body`, universal `*`) when running as a remote.

# ModuleTemplate Backend Specs

> **Deployment Rules**: Per `rules/general-guidelines.md` lines 98-115:
> - No `build:` sections in docker-compose
> - Docker images must be pre-built before deployment
> - No `SOURCES/` path references in docker-compose

## Build

- Build Docker image: `docker build --no-cache -t template/backend:latest ./SOURCES/`
- Produces Docker image only; no DIST folder.

## Authentication

- Validate Bearer JWTs using Authentik JWKS.
- Reject requests with invalid or missing tokens.

## Docs and Health Endpoint Convention

- Internal backend endpoints remain module-local: `/docs`, `/openapi.json`, `/health`.
- External routed endpoints are exposed by Traefik under `/module/template/*`.
- `https://<host>/module/template/api/docs` must render Swagger UI successfully behind strip-prefix routing.
