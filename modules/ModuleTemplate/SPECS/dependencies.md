# ModuleTemplate Dependencies

This file is the single source of truth for all dependencies and component versions of the ModuleTemplate module and its sub-modules.

**⚠️ MANDATORY**: Update this file immediately whenever a dependency is added, removed, or its version changes.

---

## Inter-Module Dependencies

| Depends on | Reason |
|------------|--------|
| HostApp | Authentication/authorization context (`GET /api/me`), shared Docker network `ideable_network` |

**Provides to other modules**: *(none — this is a remote leaf module)*

---

## Sub-Module: frontend

**Technology**: React + TypeScript + Rsbuild + Module Federation 2.0 (Remote)

| Component | Version | Purpose |
|-----------|---------|---------|
| Node.js | 18.x | Build runtime |
| React | 18.2.0 | UI library |
| React DOM | 18.2.0 | React renderer |
| TypeScript | 5.3.3 | Type system |
| Rsbuild | 1.0.1 | Build tool (Rspack-based) |
| @module-federation/rsbuild-plugin | 1.0.1 | Module Federation 2.0 remote |
| React Router DOM | 6.21.1 | Routing |
| Axios | 1.6.5 | HTTP client |
| @tanstack/react-query | 5.17.9 | Data fetching |
| TailwindCSS | 3.4.1 | CSS framework |
| Radix UI | 1.0+ | Headless UI components |
| class-variance-authority | 0.7.0 | CSS utilities |
| clsx | 2.1.0 | Class name utility |
| tailwind-merge | 2.2.0 | Tailwind class merger |
| Lucide React | 0.309.0 | Icons |

**Dev Dependencies**:
- @types/react: 18.2.48
- @types/react-dom: 18.2.18
- @rsbuild/core: 1.0.1
- @rsbuild/plugin-react: 1.0.1
- ESLint: 8.56.0
- PostCSS: 8.4.33
- Autoprefixer: 10.4.16

**Dockerfile Base**: `node:18-alpine` (build), `nginx:alpine` (runtime)  
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

**Dockerfile Base**: `python:3.11-slim`  
See `backend/SOURCES/requirements.txt` for the complete pinned list.

---

## Sub-Module: database

**Technology**: PostgreSQL

| Component | Version | Purpose |
|-----------|---------|---------|
| postgres | 16-alpine | Module-local relational database |
