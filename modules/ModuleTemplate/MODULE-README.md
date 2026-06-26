# ModuleTemplate

**Reference blueprint for HostApp-compatible remote modules.**

ModuleTemplate is the canonical example for building Ideable modules. It demonstrates complete integration patterns: Module Federation frontend remotes, authenticated FastAPI backend, PostgreSQL database, and HostApp integration.

---

## Architecture Overview

ModuleTemplate relationships:
- **Template Repo**: Bare scaffold exported via `push-updates-to-ModuleTemplate-repo.sh`
- **Master Repo**: Full development environment with HostApp + all modules
- **Custom Modules**: Created via `module-init.sh`, synced via `sync-template-updates.sh`

All specs use generic `${APP_SLUG}` placeholder resolved from `module.json`.

---

## Core Concepts

### Host/Remote Split

- **HostApp**: Owns shell UI (header, menu, route guards, layout), loads remotes dynamically via MF 2.0
- **ModuleTemplate (remote)**: Contributes pages, routes, menu metadata via `./moduleManifest` export

### Key Integration Points

| Component | Host Side | Remote Side |
|-----------|-----------|-------------|
| Menu | `config/modules_menu_mapping.json` | `config/menu_definition.json` |
| Registry | `public/module-registry.json` | `src/moduleManifest.ts` |
| Backend | Traefik strips `/module/<slug>` | FastAPI handles `/api/*` |
| Auth | Authentik JWT claims drive authorization | Validates JWT via JWKS |

### Identity Resolution

All specs use `${APP_SLUG}` as the project-wide prefix and `${MODULE_SLUG}` as the module-local suffix. The deployed ecosystem resolves these values from the project and module environments before generating the merged compose file:

```json
{
  "slug": "digital_shelter",
  "displayName": "Digital Shelter",
  "cssPrefix": "digital_shelter-"
}
```

This makes specs **generic and reusable** across any module without string substitution.

---

## Creating a New Module

### Step 1: Initialize from Template

```bash
./scripts/module_only/module-init.sh <NewModuleName>
```

What it does:
1. Copies `modules/ModuleTemplate/` to `modules/<NewModuleName>/`
2. Updates `module.json` with new slug/name
3. Substitutes entity names in source files (e.g., `TemplateItems` → `YourEntity`)
4. Creates `.env` with correct prefixes
5. Adds module to `modules/enabled.md`

### Step 2: Define Data Model

Edit the shared framework specs first, then module-specific specs:

```
SPECS/ideable-framework-specs/base-specs.md       # Framework-wide contract and build/deploy rules
SPECS/ideable-framework-specs/auth-specs.md       # Framework-wide authentication and authorization contract
SPECS/ideable-framework-specs/module-integration-specs.md # Framework integration contract with HostApp
config/authorization.yaml                        # Module-specific Authentik authorization config
database/SPECS/datamodel.sql                     # Entity schema specification
```

The module bootstrap process consumes `config/authorization.yaml` directly as the sole source of truth for module-specific authorization.
HostApp owns the initial app-wide authorization bootstrap in `modules/HostApp/config/authorization.yaml`.
Shared framework contracts live in the `ideable-framework-specs/` folders under the module root, backend, database, and frontend trees; those files are the shared baseline and must stay synchronized across HostApp, ModuleTemplate, and derived modules.

General split rule:

- HostApp bootstrap starts with the minimal authorization data required to use the app.
- Each module bootstrap provisions its own authorization data to Authentik when the module is bootstrapped.
- When the composed app needs additional framework-level authorization data, update the relevant shared spec file inside the corresponding `ideable-framework-specs/` folder.
- When a module needs additional module-specific authorization data, update that module's own spec files and authorization config.

### Step 3: Implement with Agent Workflows

Execute in sequence:

```
@[/ImplementSpecs]   # SPECS -> SOURCES (frontend/backend/database)
@[/Build&Deploy]     # SOURCES -> DIST -> deployment_root/
@[/Tests&Fix]        # Run all tests, fix failures
```

### Step 4: Deploy

```bash
./redeploy.sh
```

Interactive prompts:
- Wipe volumes? (default: **no**)
- Start containers? (default: **yes**)

After building images and deploying artifacts, `redeploy.sh` automatically regenerates the merged `deployment_root/.env` and `deployment_root/docker-compose.yml` from the per-module files before starting the stack.

### Runtime customization in `deployment_root/`

After deployment, operators can customize a module without rebuilding images by editing the mounted files under `deployment_root/modules/<YourModule>/`.

Examples:

- `deployment_root/modules/<YourModule>/config/authorization.yaml` — update the module’s authorization config, then rerun deployment/bootstrap so Authentik reconciles permissions, roles, profiles, and menu claims.
- `deployment_root/modules/<YourModule>/config/menu_definition.json` — change the remote menu tree and visibility structure.
- `deployment_root/modules/<YourModule>/config/*.png` or other runtime-mounted branding assets — customize module-specific logos or illustrations when the module exposes them through `config/`.
- `deployment_root/modules/<YourModule>/.env` — adjust module-local runtime settings such as API URLs or ports.

All runtime-mounted config files are read by the deployed containers, so changes take effect on the next bootstrap/restart cycle described by the relevant specs.

---

## Syncing Template Updates

When ModuleTemplate evolves, sync updates:

```bash
# Check available updates
./scripts/module_only/sync-template-updates.sh --list-changes

# Sync specific file
./scripts/module_only/sync-template-updates.sh --file scripts/module-init.sh

# Sync all infrastructure + shared SPECS
./scripts/module_only/sync-template-updates.sh
```

SPECS use generic `${APP_SLUG}` placeholders, so they work unchanged in any module. The sync script also keeps `.env.example` files in sync and backfills only missing keys into the matching `.env` files without overwriting existing values.

The synced infrastructure surface also includes the repository-root `AGENTS.md`, the `rules/` folder, and the repo-root module-project wrappers (`start.sh`, `stop.sh`, `status.sh`, `redeploy.sh`, `update_backend.sh`, `update_frontend.sh`) when they are exported from the maintainer repository. In the exported template repo, the long-form docs are renamed to `IDEABLE-README.md` and `MODULE-README.md`, and placeholder `README.md` files remain at the repo root and module root for template users to customize.

---

## Pushing Template Updates (Maintainers)

Export ModuleTemplate to standalone repo:

```bash
./scripts/master_only/push-updates-to-ModuleTemplate-repo.sh
```

Pushes `modules/ModuleTemplate/` + shared infrastructure to `Ideable-ModuleTemplate.git`.

---

## Development Workflow Sequence

Starting from scratch with new datamodel:

1. **Create module**: `./scripts/module_only/module-init.sh MyModule`
2. **Write datamodel**: `database/SPECS/datamodel.sql` + seed SQL
3. **Generate sources**: `@[/ImplementSpecs]` - agent reads SPECS, writes SOURCES
4. **Build & deploy**: `@[/Build&Deploy]` - builds Docker images locally, compiles to DIST, copies to deployment_root
5. **Test**: `@[/Tests&Fix]` - runs all module tests
6. **Deploy**: `./redeploy.sh` - interactive deployment with optional start

If you want to publish any built images to a registry, run `scripts/common/push_module_images_to_registry.sh` after the build step and pass the module names plus the tag you want to publish. The push script tags and pushes existing images; it does not rebuild them.

Repeat 3-6 iteratively as specs evolve.

---

## Configuration Reference

### Module Identity and Build Variables

| Variable | Purpose |
|----------|---------|
| `APP_SLUG` | Project-wide slug used as the main runtime prefix |
| `MODULE_SLUG` | Module-local slug used as the runtime sub-prefix |
| `APP_NAME` | Human-readable name resolved from `module.json` |
| `<SLUG>_BACKEND_PORT` | FastAPI port |
| `<SLUG>_FRONTEND_PORT` | Nginx/MF port |
| `VITE_<SLUG_UPPER>_API_URL` | Frontend API URL |

### Module Manifest Contract

```typescript
export const moduleManifest = {
  slug: '${APP_SLUG}',
  menuItems: [{ name: 'Items', href: '/${APP_SLUG}/items', icon: 'Package' }],
  routes: [{ path: '/items', component: () => import('./pages/Items') }],
  permissions: ['${APP_SLUG}.items.read', '${APP_SLUG}.items.write']
};
```

### Menu Definition Contract

Remote modules define their menu structure in `config/menu_definition.json`:

```json
{
  "menu_definition": [
    {
      "menu_item_code": "MODULE_CODE",
      "menu_item_name": "Display Name",
      "icon": "IconName",
      "routing": "/path",
      "is_collapsible": false,
      "authorization_claim": "TEMPLATE.ITEMS",
      "sub_items": []
    }
  ]
}
```

**Fields:**
- `menu_item_code` (required) — stable node identifier used by HostApp mapping
- `menu_item_name` (required) — display label
- `icon` (required) — Lucide icon name
- `routing` (optional) — URL path for the page; omit for container items that only group sub-items
- `is_collapsible` (optional, default `false`) — When `true`, the menu item is collapsible, hiding all sub-items behind an expand/collapse control; when `false`/absent, sub-items are always visible
- `authorization_claim` (optional, string) — When defined, only users whose validated Authentik JWT includes the required claim can see this menu item and its entire sub-tree; when absent, all users can see it
- `sub_items` (required) — Recursive array with the same structure

**HostApp** maps remote menu definitions to the main navigation via `config/modules_menu_mapping.json`, which references items by `module_menu_item_code_path` (e.g., `"TEMPLATE.ITEMS"`).

When HostApp is the runtime shell, a mapping path may start with an existing HostApp menu code to nest the module menu under that branch.

- Example: `"ADMIN.MYMENU"` renders the module node `MYMENU` under HostApp `Admin`.
- HostApp renders nested mapped menu trees up to four levels deep total.

**Runtime note**: branding assets and the HostApp home page are configured by the host shell at runtime via the favicon file pointed to by `AUTHENTIK_LOGIN_FAVICON_FILE` inside `modules/HostApp/config/`, `modules/HostApp/config/login_bg.svg`, and `modules/HostApp/config/home.html`; ModuleTemplate only defines menu/routing/permission content for the remote area.

### API Authentication Contract

- API endpoints validate Authentik JWT Bearer tokens.
- Swagger UI exposes an `Authorize` button through OAuth2 Authorization Code + PKCE.
- The Swagger OAuth2 callback for this module is `/module/template/api/docs/oauth2-redirect` when deployed under HostApp.
- Derived remote modules must keep the same pattern, replacing `template` with their own module slug in the callback path.

### Remote module authorization checklist

If you are building a derived remote module, keep authorization simple:

1. **Validate the bearer token with Authentik JWKS.**
   - Reject requests with missing, invalid, or expired JWTs.

2. **Use token claims as the only runtime source of truth.**
   - Read permissions from `<module_slug>.permissions`.
   - Read menu visibility from `<module_slug>.permissions` using `<resource>:menu_access` entries.
   - Read tenant scoping from `hostapp.tenant_ids`.

3. **Do not re-implement authorization in the database.**
   - Do not rely on local RBAC tables.
   - Do not query HostApp to decide whether a user can act.

4. **Make UI visibility follow the token.**
   - Hide menus when the matching `<resource>:menu_access` permission is missing from `*.permissions`.
   - Hide or disable buttons and table action icons when the matching `*.permissions` claim is missing.
   - Use the same claim set for view/edit mode toggles.

5. **Treat profile switching as token refresh.**
   - When the active profile changes, the next token must carry the new claims.
   - Re-read the token-derived claims after refresh; do not calculate permissions locally.

6. **Define permissions declaratively.**
   - Keep permission names in `config/authorization.yaml`.
   - Let the Authentik bootstrap pipeline turn those declarations into claims.

---

## Quick Commands

```bash
# Scaffold new module
./scripts/module_only/module-init.sh MyModule

# Check template updates
./scripts/module_only/sync-template-updates.sh --list-changes

# Sync updates
./scripts/module_only/sync-template-updates.sh

# Push template (maintainers)
./scripts/master_only/push-updates-to-ModuleTemplate-repo.sh

# Deploy with prompts
./redeploy.sh
```

Agent workflows:
- `@[/ImplementSpecs]` - SPECS to SOURCES
- `@[/Build&Deploy]` - Build and deploy
- `@[/Tests&Fix]` - Run tests

---

## Audit Trail

ModuleTemplate ships with a built-in audit trail for all entities, powered by **SQLAlchemy-Continuum**.

### How it works

- Every model that inherits from `Versioned` (in `app/models.py`) gets a companion `<table>_version`
  table auto-created by the ORM. Each write operation (INSERT / UPDATE / DELETE) is recorded.
- The actor (authenticated username) is injected into `TransactionMeta` via `app/audit.py` before
  each commit.

### Access control

A single permission `audit_trail:view` is required to access history endpoints. It is declared in
`config/authorization.yaml` and emitted in `<module_slug>.permissions` inside the JWT.

### History endpoints

```
GET /items/{item_id}/history   # requires audit_trail:view in template.permissions
```

### UI entry point

An **Audit Trail** icon action (`History`) appears in the action column of the Items table page
when the authenticated user has `audit_trail:view`. Clicking opens the Audit Trail Popup
(framework contract: `frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`).

### Dependencies

- `sqlalchemy-continuum==1.4.2` (see `SPECS/dependencies.md`)
- `alembic==1.13.1`

### Implementation guide for new audited entities

When adding a new versioned entity or a page that exposes history, follow the framework contract in `SPECS/ideable-framework-specs/base-specs.md`, `SPECS/ideable-framework-specs/auth-specs.md`, and `frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`:

1. Make the model inherit from `Versioned` so SQLAlchemy-Continuum creates the version table automatically.
2. Ensure mutating requests set the current authenticated user before commit so the actor is recorded in `TransactionMeta`.
3. Expose a read-only `GET /<entity>/{entity_id}/history` endpoint guarded by `audit_trail:view`.
4. Add an audit trail action icon in the table action column and hide it when `audit_trail:view` is absent.
5. Open the shared Audit Trail Popup from the action icon and load the history through the module service layer.
6. Keep the legacy per-page audit toggle out of new implementations; audit visibility is permission-driven only.

### New backend files

- `app/audit.py` — context variable and SQLAlchemy before-commit listener for actor injection.

## Related Documentation

- `frontend/SPECS/ideable-framework-specs/base_specs.md` - Frontend build, MF, CSS
- `backend/SPECS/ideable-framework-specs/base_specs.md` - FastAPI, auth
- `database/SPECS/ideable-framework-specs/base-specs.md` - Schema design
- `SPECS/ideable-framework-specs/base-specs.md` - Framework contract and build/deploy rules
- `SPECS/ideable-framework-specs/auth-specs.md` - Framework authentication and authorization contract
- `SPECS/ideable-framework-specs/module-integration-specs.md` - Framework integration contract
- `SPECS/dependencies.md` - Libraries

## Unsaved changes guard

Module developers who need to protect create/edit flows from accidental loss of work should start here:

- `frontend/SPECS/shared-ui-specs.md` - canonical guard contract and usage rules
- `frontend/SPECS/shared-ui-widgets-specs.md` - shared dialog/widget contract
- `frontend/SOURCES/src/hooks/useUnsavedChangesGuard.ts` - reusable guard hook
- `frontend/SOURCES/src/components/UnsavedChangesDialog.tsx` - shared confirmation dialog

Use this facility for any page, drawer, or modal that can lose unsaved changes when the user cancels, refreshes, or closes the tab.
