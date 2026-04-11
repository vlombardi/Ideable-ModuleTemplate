# ModuleTemplate Backend Specs

> **Deployment Rules**: Per `rules/general-guidelines.md` lines 98-115:
> - No `build:` sections in docker-compose
> - Docker images must be pre-built before deployment
> - No `SOURCES/` path references in docker-compose

## Build

- Build Docker image: `docker build --no-cache -t template/backend:latest ./SOURCES/`
- Produces Docker image only; no DIST folder.

## Service

- FastAPI backend for `template` remote module.
- Service exposes CRUD endpoints for `template_items`.

## Authentication

- Validate Bearer JWTs using Authentik JWKS.
- Reject requests with invalid or missing tokens.

## Authorization

- Resolve effective user permissions by querying HostApp `GET /api/me`.
- Enforce permission checks with `require_permission(...)` dependencies.
- Use permission namespace `template.items.*` for item CRUD operations.

## API Scope

- External API base path (through Traefik): `/module/template/api`.
- Internal backend API base path: `/api`.
- Example protected routes:
  - `GET /module/template/api/items` (`template.items.read`)
  - `POST /module/template/api/items` (`template.items.create`)
  - `PUT /module/template/api/items/{item_id}` (`template.items.update`)
  - `DELETE /module/template/api/items/{item_id}` (`template.items.delete`)
