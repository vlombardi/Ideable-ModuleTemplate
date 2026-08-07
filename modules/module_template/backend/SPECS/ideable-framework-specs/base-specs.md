# IMPORTANT: Read This First

**This file (`base-specs.md`) is the MANDATORY starting point for any coding agent action on this module's backend and business logic.**

Before implementing, modifying, or troubleshooting any backend component, you MUST:
1. Read `rules/general-guidelines.md`, then
2. Read this entire file, then
3. Read `module-specs.md`, then any other further referenced specs files.
4. For audit trail implementation, read
   `modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md` — it is the
   authoritative cross-cutting contract for versioning, history endpoints, association versioning,
   actor injection, and frontend rendering rules.
5. Read `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md`
   before writing or changing backend code — it contains mandatory rules including the
   prohibition of inline `au_*` columns on business tables (audit metadata belongs to
   SQLAlchemy-Continuum, not the base schema).

## Normative precedence

If rules overlap, apply them in this order:
1. This file (`base-specs.md`)
2. `module-specs.md`
3. any other specs file eventually references in `module-specs.md`

If two rules conflict at the same level, the above order defines the priority logic (i.e., rule in previous point wins, e.g., rule in point 1 wins over rule in point 2, and so on).

---

# module_template Backend Specs

## Build

- Build Docker image: `docker build --no-cache -t template.backend:latest ./SOURCES/`
- Produces Docker image only; no DIST folder.

## Service

- FastAPI backend for the example `template` remote module.
- Service exposes CRUD endpoints for the example `template_items` entity.

## Authentication

- Validate Bearer JWTs using Authentik JWKS.
- Reject requests with invalid or missing tokens.
- Swagger UI must expose an `Authorize` button using OAuth2 Authorization Code + PKCE.
- Swagger OAuth2 redirect callback must be `/module/template/api/docs/oauth2-redirect` when the module is deployed under host_app, and the same pattern must be preserved by derived remotes using their own module slug.

## Authorization

- Resolve authorization decisions from claims in the validated Authentik JWT.
- Enforce permission checks with `require_permission(...)` dependencies that operate on claims, not host_app RBAC lookups.
- Use the example permission namespace `items:*` for item CRUD operations (flat names inside `template.permissions`).

## Custom Claims

module_template may define module-specific Authentik claims for the example `template` module for:

- menu visibility
- route authorization
- item-level permissions
- tenant/company scoping

These claims must be emitted by Authentik and consumed directly after JWT verification.

## API Scope

- External API base path (through Traefik): `/module/template/api`.
- Internal backend API base path: `/api`.
- Example protected routes:
  - `GET /module/template/api/items` (`items:view`)
  - `POST /module/template/api/items` (`items:edit`)
  - `PUT /module/template/api/items/{item_id}` (`items:edit`)
  - `DELETE /module/template/api/items/{item_id}` (`items:edit`)
- Docs endpoint: `GET /module/template/api/docs`
- OAuth2 redirect endpoint: `GET /module/template/api/docs/oauth2-redirect`

