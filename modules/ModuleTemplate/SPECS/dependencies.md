# ModuleTemplate Dependencies

This file is the single source of truth for all dependencies and component versions of the ModuleTemplate module and its sub-modules.

**⚠️ MANDATORY**: Update this file immediately whenever a dependency is added, removed, or its version changes.

---

## Inter-Module Dependencies

| Depends on | Reason |
|------------|--------|
| HostApp | Authentication/authorization context via Authentik JWT claims, project-scoped Docker network `ideable_network` (namespaced per deployment) |

**Provides to other modules**: *(none — this is a remote leaf module)*

---

## Sub-Module: frontend

**Technology**: React + TypeScript + Rsbuild + Module Federation 2.0 (Remote)

| Component | Version | Purpose |
|-----------|---------|---------|
| Node.js | 20.x | Build runtime |
| React | 19.2.7 | UI library |
| React DOM | 19.2.7 | React renderer |
| TypeScript | 5.6.3 | Type system |
| Rsbuild | 2.1.2 | Build tool (Rspack-based) |
| @module-federation/rsbuild-plugin | 2.6.0 | Module Federation 2.0 remote |
| React Router DOM | 7.18.1 | Routing |
| TailwindCSS | 4.3.2 | CSS framework |
| @tailwindcss/postcss | 4.3.2 | Tailwind v4 PostCSS plugin |
| class-variance-authority | 0.7.1 | CSS utilities |
| clsx | 2.1.1 | Class name utility |
| tailwind-merge | 3.6.0 | Tailwind class merger |
| Lucide React | 1.23.0 | Icons |

**Dev Dependencies**:
- @types/react: 19.2.17
- @types/react-dom: 19.2.3
- @rsbuild/core: 2.1.2
- @rsbuild/plugin-react: 2.1.0
- PostCSS: 8.5.16

**Dockerfile Base**: `node:20-alpine` (build), `nginx:alpine` (runtime)  
See `frontend/SOURCES/package.json` for the complete pinned list.

---

## Sub-Module: backend

**Technology**: FastAPI (Python)

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.11-slim | Base runtime |
| FastAPI | 0.109.0 | Web framework |
| Uvicorn | 0.27.0 | ASGI server |
| psycopg2-binary | 2.9.9 | PostgreSQL adapter |
| SQLAlchemy | 2.0.25 | ORM |
| Pydantic | 2.5.3 | Data validation |
| pydantic-settings | 2.1.0 | Settings management |
| python-jose | 3.3.0 | JWT tokens |
| pyjwt | 2.8.0 | JWT library |
| cryptography | 42.0.0 | Cryptographic recipes |
| requests | 2.31.0 | HTTP library |
| python-multipart | 0.0.6 | Form data parsing |
| sqlalchemy-continuum | 1.4.2 | ORM-level row versioning (audit trail) |
| alembic | 1.13.1 | DB schema migrations |

**Dockerfile Base**: `python:3.11-slim`  
See `backend/SOURCES/requirements.txt` for the complete pinned list.

---

## Sub-Module: database

**Technology**: PostgreSQL

| Component | Version | Purpose |
|-----------|---------|---------|
| postgres | 16-alpine | Module-local relational database |
