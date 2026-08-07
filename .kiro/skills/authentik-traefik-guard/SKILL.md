---
name: authentik-traefik-guard
description: >
  Use this skill when setting up, configuring, or debugging authentication and
  authorization for containerized services using Authentik as Identity Provider
  and Traefik v3 as reverse proxy. Covers: Docker Compose wiring for authentik
  server + worker, Traefik v3 static/dynamic config, forwardAuth middleware
  setup (single-app and domain-level), embedded outpost vs standalone proxy
  outpost, protecting FastAPI backend routes (JWT header validation via
  X-authentik-jwt), protecting React frontend with session-based redirect,
  TLS via Let's Encrypt ACME, Docker networks isolation, secrets management,
  and common pitfalls (redirect loops, outpost version mismatch, UTC timezone
  constraint). Activate when user asks about: "protect my API with authentik",
  "traefik forwardAuth", "authentik outpost docker compose", "SSO for fastapi
  and react", "authentik proxy provider", "X-authentik headers", "authentik
  embedded outpost".
---

# Skill: authentik-traefik-guard

> ⚠️ **PROJECT RULES OVERRIDE** — When working inside this project, `rules/general-guidelines.md` takes precedence over any pattern shown in this skill. In particular:
> - **Never add `build:` sections** to any `docker-compose.yml` — all images must be pre-built.
> - **Never place a `Dockerfile` outside `SOURCES/`** — it must live at `modules/<MODULE>/<SUB_MODULE>/SOURCES/Dockerfile`.
> - The directory structure shown in this skill is a generic reference; adapt it to the project's `modules/<MODULE>/<SUB_MODULE>/SOURCES/` layout.

## Purpose

Generate production-ready Docker Compose configurations and application code
to protect a **FastAPI backend** and a **React frontend** using:

- **Authentik** (≥ 2024.12 / current 2025.x) as Identity Provider
- **Traefik v3** as reverse proxy and TLS terminator
- **Forward Auth** (Proxy Provider) pattern — Traefik delegates auth to Authentik

## Sources (verified, official)

- Authentik Traefik integration: https://docs.goauthentik.io/add-secure-apps/providers/proxy/server_traefik/
- Authentik Docker Compose install: https://docs.goauthentik.io/install-config/install/docker-compose/
- Authentik Header Auth: https://docs.goauthentik.io/add-secure-apps/providers/proxy/header_authentication/
- Traefik Docker Compose setup: https://doc.traefik.io/traefik/setup/docker/
- Traefik EntryPoints reference: https://doc.traefik.io/traefik/reference/install-configuration/entrypoints/

---

## Architecture Overview

```
Internet
    │
    ▼
[Traefik v3]  ←── TLS termination, routing, forwardAuth middleware
    │
    ├─── /outpost.goauthentik.io/* ──► [Authentik Embedded Outpost :9000]
    │                                       │
    │                                  checks session/token
    │                                       │
    ├─── api.domain.com ──forwardAuth──► [FastAPI :8000]
    │                                   (reads X-authentik-* headers)
    │
    └─── app.domain.com ──forwardAuth──► [React :3000]
                                        (protected by session cookie)
```

**Key design decisions:**
1. **Embedded Outpost** (recommended over standalone proxy container) — available since Authentik 2021.8.1, requires no extra container
2. **Forward Auth (Single Application)** mode per service — enables per-app access policies
3. **Domain-level Forward Auth** optional as catch-all — simpler but no per-app policies
4. FastAPI uses `X-authentik-jwt` header to validate identity without calling Authentik again
5. React app relies on session cookie set by Authentik via Traefik redirect

---

## Step-by-Step Instructions

### 1. Prerequisites — Generate secrets

```bash
# Generate PostgreSQL password (max 99 chars per PostgreSQL limitation)
echo "PG_PASS=$(openssl rand -base64 36 | tr -d '\n')" >> .env

# Generate Authentik secret key
echo "AUTHENTIK_SECRET_KEY=$(openssl rand -base64 60 | tr -d '\n')" >> .env
```

> ⚠️ **NEVER** change `AUTHENTIK_SECRET_KEY` after first start — it encrypts stored data.
> ⚠️ **NEVER** mount `/etc/timezone` or `/etc/localtime` in authentik containers — breaks OAuth/SAML (official constraint from Authentik docs).

---

### 2. Docker Compose — Full Stack

```yaml
# docker-compose.yml
# Sources:
#   Authentik: https://docs.goauthentik.io/install-config/install/docker-compose/
#   Traefik v3: https://doc.traefik.io/traefik/setup/docker/

services:

  # ─────────────────────────────────────────────
  # TRAEFIK v3
  # ─────────────────────────────────────────────
  traefik:
    image: traefik:v3.3
    container_name: traefik
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    networks:
      - proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
      - ./traefik/dynamic:/dynamic:ro
    command:
      # Static config
      - "--api.dashboard=false"                          # disable dashboard in prod
      - "--providers.docker=true"
      - "--providers.docker.exposedByDefault=false"
      - "--providers.docker.network=proxy"
      - "--providers.file.directory=/dynamic"            # dynamic config folder

      # EntryPoints
      - "--entrypoints.web.address=:80"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      - "--entrypoints.web.http.redirections.entrypoint.permanent=true"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.websecure.http.tls=true"

      # ACME / Let's Encrypt
      - "--certificatesresolvers.le.acme.email=admin@domain.com"
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"
      - "--certificatesresolvers.le.acme.httpchallenge.entrypoint=web"
      - "--entrypoints.websecure.http.tls.certresolver=le"

      # Logging
      - "--log.level=WARNING"
      - "--accesslog=true"

  # ─────────────────────────────────────────────
  # AUTHENTIK — PostgreSQL
  # ─────────────────────────────────────────────
  authentik-postgresql:
    image: postgres:17-alpine
    container_name: authentik-postgresql
    restart: unless-stopped
    networks:
      - authentik-internal
    volumes:
      - authentik-postgres-data:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: ${PG_PASS}
      POSTGRES_USER: authentik
      POSTGRES_DB: authentik
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -d authentik -U authentik"]
      interval: 30s
      timeout: 5s
      retries: 5

  # ─────────────────────────────────────────────
  # AUTHENTIK — Server (includes embedded outpost)
  # ─────────────────────────────────────────────
  authentik-server:
    image: ghcr.io/goauthentik/server:2025.10.4   # pin to specific version
    container_name: authentik-server
    restart: unless-stopped
    command: server
    networks:
      - proxy
      - authentik-internal
    volumes:
      - ./authentik/media:/media
      - ./authentik/custom-templates:/templates
    environment:
      AUTHENTIK_POSTGRESQL__HOST: authentik-postgresql
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: ${PG_PASS}
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
      AUTHENTIK_ERROR_REPORTING__ENABLED: "false"
      # DO NOT set AUTHENTIK_LOG_LEVEL to suppress noise in prod
      # NOTE: Redis is NOT required since Authentik 2025.8 — do not add AUTHENTIK_REDIS__HOST
    depends_on:
      authentik-postgresql:
        condition: service_healthy
    labels:
      traefik.enable: "true"
      traefik.docker.network: "proxy"

      # Router: authentik UI + API
      traefik.http.routers.authentik.rule: "Host(`auth.domain.com`)"
      traefik.http.routers.authentik.entrypoints: "websecure"
      traefik.http.routers.authentik.tls.certresolver: "le"
      traefik.http.services.authentik.loadbalancer.server.port: "9000"

      # Router: outpost callback — MUST have higher priority
      # Required so Traefik routes /outpost.goauthentik.io/* back to authentik
      traefik.http.routers.authentik-outpost.rule: >
        HostRegexp(`{subdomain:[a-z0-9-]+}.domain.com`) &&
        PathPrefix(`/outpost.goauthentik.io/`)
      traefik.http.routers.authentik-outpost.entrypoints: "websecure"
      traefik.http.routers.authentik-outpost.priority: "15"

      # ForwardAuth middleware — used by protected services
      # Address points to embedded outpost inside authentik-server container
      traefik.http.middlewares.authentik-auth.forwardauth.address: >
        http://authentik-server:9000/outpost.goauthentik.io/auth/traefik
      traefik.http.middlewares.authentik-auth.forwardauth.trustForwardHeader: "true"
      traefik.http.middlewares.authentik-auth.forwardauth.authResponseHeaders: >
        X-authentik-username,
        X-authentik-groups,
        X-authentik-entitlements,
        X-authentik-email,
        X-authentik-name,
        X-authentik-uid,
        X-authentik-jwt,
        X-authentik-meta-jwks,
        X-authentik-meta-outpost,
        X-authentik-meta-provider,
        X-authentik-meta-app,
        X-authentik-meta-version

  # ─────────────────────────────────────────────
  # AUTHENTIK — Worker
  # ─────────────────────────────────────────────
  authentik-worker:
    image: ghcr.io/goauthentik/server:2025.10.4   # MUST match server version
    container_name: authentik-worker
    restart: unless-stopped
    command: worker
    networks:
      - authentik-internal
    volumes:
      - ./authentik/media:/media
      - ./authentik/custom-templates:/templates
      # Docker socket for automatic outpost management (optional, adds security risk)
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      AUTHENTIK_POSTGRESQL__HOST: authentik-postgresql
      AUTHENTIK_POSTGRESQL__USER: authentik
      AUTHENTIK_POSTGRESQL__NAME: authentik
      AUTHENTIK_POSTGRESQL__PASSWORD: ${PG_PASS}
      AUTHENTIK_SECRET_KEY: ${AUTHENTIK_SECRET_KEY}
    depends_on:
      authentik-postgresql:
        condition: service_healthy

  # ─────────────────────────────────────────────
  # FASTAPI BACKEND
  # ─────────────────────────────────────────────
  backend:
    build: ./backend
    container_name: backend
    restart: unless-stopped
    networks:
      - proxy
      - app-internal
    environment:
      DATABASE_URL: postgresql+asyncpg://appuser:${APP_DB_PASS}@postgres:5432/appdb
      AUTHENTIK_JWKS_URL: http://authentik-server:9000/application/o/<app-slug>/jwks/
    labels:
      traefik.enable: "true"
      traefik.docker.network: "proxy"
      traefik.http.routers.backend.rule: "Host(`api.domain.com`)"
      traefik.http.routers.backend.entrypoints: "websecure"
      traefik.http.routers.backend.tls.certresolver: "le"
      traefik.http.routers.backend.middlewares: "authentik-auth@docker"
      traefik.http.services.backend.loadbalancer.server.port: "8000"

  # ─────────────────────────────────────────────
  # REACT FRONTEND
  # ─────────────────────────────────────────────
  frontend:
    build: ./frontend
    container_name: frontend
    restart: unless-stopped
    networks:
      - proxy
    labels:
      traefik.enable: "true"
      traefik.docker.network: "proxy"
      traefik.http.routers.frontend.rule: "Host(`app.domain.com`)"
      traefik.http.routers.frontend.entrypoints: "websecure"
      traefik.http.routers.frontend.tls.certresolver: "le"
      traefik.http.routers.frontend.middlewares: "authentik-auth@docker"
      traefik.http.services.frontend.loadbalancer.server.port: "3000"

networks:
  proxy:
    external: false        # shared network for Traefik ↔ services
  authentik-internal:
    internal: true         # Authentik ↔ PostgreSQL, NOT reachable from outside
  app-internal:
    internal: true         # Backend ↔ app database

volumes:
  authentik-postgres-data:
```

---

### 3. Authentik Admin Setup (after first boot)

```
# Initial setup URL — trailing slash is REQUIRED
http://<host>:9000/if/flow/initial-setup/
```

Then in the Admin UI (`https://auth.domain.com/if/admin/`):

**For each app (FastAPI + React separately):**

1. **Applications → Create** → use the Wizard (default since 2025.2)
2. Provider type: **Proxy Provider**
3. Mode: **Forward auth (single application)** — enables per-app access policies
4. External Host: `https://api.domain.com` (or `https://app.domain.com`)
5. Authentication URL: auto-filled as `https://auth.domain.com`
6. **Outposts → Embedded Outpost → Edit** → select both applications → Save

> ⚠️ The embedded outpost version MUST match the authentik server version.
> Always upgrade outposts and server at the same time.

---

### 4. FastAPI — Read Authentik Headers

FastAPI receives `X-authentik-*` headers injected by Traefik after forwardAuth
succeeds. For API routes, also validate the JWT carried in `X-authentik-jwt`.

```python
# backend/app/auth/authentik.py
# Source pattern: https://docs.goauthentik.io/add-secure-apps/providers/proxy/header_authentication/

from fastapi import Depends, HTTPException, Request, status
from functools import lru_cache
from typing import Annotated
import httpx
from jose import JWTError, jwk, jwt
import json

AUTHENTIK_JWKS_URL = "http://authentik-server:9000/application/o/<app-slug>/jwks/"


@lru_cache(maxsize=1)
def _fetch_jwks() -> dict:
    """Fetch JWKS from Authentik (cached). Refresh on app restart."""
    resp = httpx.get(AUTHENTIK_JWKS_URL, timeout=5)
    resp.raise_for_status()
    return resp.json()


class AuthentikUser:
    """Parsed identity from Authentik forwardAuth headers."""
    def __init__(
        self,
        username: str,
        email: str,
        uid: str,
        groups: list[str],
        jwt_payload: dict | None = None,
    ):
        self.username = username
        self.email = email
        self.uid = uid
        self.groups = groups
        self.jwt_payload = jwt_payload or {}

    def has_group(self, group: str) -> bool:
        return group in self.groups


def get_current_user(request: Request) -> AuthentikUser:
    """
    Dependency: extracts and validates Authentik identity.

    Traefik injects X-authentik-* headers ONLY after forwardAuth succeeds.
    If a request reaches FastAPI without these headers, it means Traefik's
    forwardAuth middleware is misconfigured or bypassed — always treat as 401.
    """
    username = request.headers.get("X-authentik-username")
    email = request.headers.get("X-authentik-email", "")
    uid = request.headers.get("X-authentik-uid", "")
    groups_raw = request.headers.get("X-authentik-groups", "")
    jwt_token = request.headers.get("X-authentik-jwt", "")

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authentik identity headers. "
                   "Is Traefik forwardAuth middleware active?",
        )

    # Optional: validate JWT signature using Authentik's JWKS
    jwt_payload: dict = {}
    if jwt_token:
        try:
            jwks = _fetch_jwks()
            # jose library handles key selection from JWKS automatically
            jwt_payload = jwt.decode(
                jwt_token,
                jwks,
                algorithms=["RS256"],
                options={"verify_aud": False},  # adjust if you set audience
            )
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid JWT from Authentik: {e}",
            )

    groups = [g for g in groups_raw.split("|") if g] if groups_raw else []

    return AuthentikUser(
        username=username,
        email=email,
        uid=uid,
        groups=groups,
        jwt_payload=jwt_payload,
    )


# Type alias for cleaner route signatures
CurrentUser = Annotated[AuthentikUser, Depends(get_current_user)]


def require_group(group_name: str):
    """Factory: returns a dependency that enforces group membership."""
    def _check(user: CurrentUser) -> AuthentikUser:
        if not user.has_group(group_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Group '{group_name}' required.",
            )
        return user
    return Depends(_check)
```

```python
# backend/app/main.py — usage example
from fastapi import FastAPI
from app.auth.authentik import CurrentUser, require_group

app = FastAPI()

@app.get("/api/me")
async def get_me(user: CurrentUser):
    return {
        "username": user.username,
        "email": user.email,
        "groups": user.groups,
    }

@app.get("/api/admin/dashboard")
async def admin_dashboard(user: AuthentikUser = require_group("authentik-admins")):
    return {"message": f"Welcome admin {user.username}"}
```

---

### 5. React Frontend — Pass Auth Headers to API

The React app runs behind the same forwardAuth middleware. After Authentik
redirects and sets the session cookie, the browser is granted access.

To call the FastAPI backend from React, pass the JWT token from Authentik:

```typescript
// frontend/src/api/client.ts
// The JWT is injected by Authentik in the X-authentik-jwt response header.
// React can read it from a dedicated /auth/me proxy endpoint.

const API_BASE = import.meta.env.VITE_API_URL ?? "https://api.domain.com";

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",  // send session cookie for same-domain setups
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (res.status === 401) {
    // Authentik session expired — redirect to login
    window.location.href = "/outpost.goauthentik.io/start";
    throw new Error("Unauthenticated");
  }

  if (!res.ok) {
    throw new Error(`API error ${res.status}`);
  }

  return res.json() as Promise<T>;
}
```

---

### 6. Traefik Dynamic Config (optional but recommended for production)

```yaml
# traefik/dynamic/middlewares.yml
# Loaded automatically by providers.file.directory setting

http:
  middlewares:
    # Security headers — apply to all services
    security-headers:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        forceSTSHeader: true
        contentTypeNosniff: true
        browserXssFilter: true
        referrerPolicy: "strict-origin-when-cross-origin"
        permissionsPolicy: "camera=(), microphone=(), geolocation=()"

    # Rate limiting — protect API from abuse
    api-ratelimit:
      rateLimit:
        average: 100
        burst: 50
```

Apply to backend router by updating its label:
```yaml
traefik.http.routers.backend.middlewares: "authentik-auth@docker,security-headers@file,api-ratelimit@file"
```

---

## Constraints and Critical Rules

1. **Version pinning**: Always use a specific image tag like `:2025.10.4`, never `:latest` (deprecated after 2025.2 per official release notes)
2. **Outpost/server version parity**: Worker, server, and outpost MUST be the same version — upgrade them simultaneously
3. **Timezone**: NEVER mount `/etc/timezone` or `/etc/localtime` in any authentik container — causes OAuth/SAML failures
4. **PostgreSQL password**: Max 99 characters (PostgreSQL protocol limitation)
5. **Secret key immutability**: `AUTHENTIK_SECRET_KEY` must not change after first start
6. **Redis removed**: Since Authentik 2025.8, Redis is no longer required — do NOT add `AUTHENTIK_REDIS__HOST` to the environment at all (not even as an empty string)
7. **Network isolation**: Keep `authentik-internal` network as `internal: true` — PostgreSQL must NOT be reachable from Traefik or the internet
8. **Header trust**: FastAPI MUST verify that `X-authentik-username` is present — if missing, the request bypassed forwardAuth and must be rejected as 401
9. **Priority routing**: The `/outpost.goauthentik.io/` router MUST have `priority: 15` (higher than default `10`) to take precedence over wildcard rules
10. **Initial setup URL trailing slash**: `http://host:9000/if/flow/initial-setup/` — missing trailing slash returns 404

---

## Common Pitfalls and Fixes

| Symptom | Root Cause | Fix |
|---|---|---|
| Infinite redirect loop | Outpost route missing or wrong priority | Set `priority: 15` on outpost router |
| `oidc: id token issued by different provider` | `AUTHENTIK_HOST` mismatch between internal and browser URL | Set `AUTHENTIK_HOST` to the public URL; remove `AUTHENTIK_HOST_BROWSER` |
| Blank page after login | Session cookie domain mismatch | Ensure all services share same root domain (e.g., `domain.com`) |
| 404 on `/if/flow/initial-setup` | Missing trailing slash | Always use `http://host:9000/if/flow/initial-setup/` |
| Outpost not connecting | Version mismatch server ↔ outpost | Pin both to same exact version tag |
| `X-authentik-username` missing in FastAPI | Middleware not applied or wrong reference | Check label uses `authentik-auth@docker` (note: `@docker` suffix when defined via labels) |
| PostgreSQL auth failure after password change | PG container uses password only on first init | `docker exec` into container and reset with `ALTER USER` |

---

## Directory Structure to Generate

```
project/
├── docker-compose.yml
├── .env                          # PG_PASS, AUTHENTIK_SECRET_KEY, APP_DB_PASS
├── letsencrypt/                  # Traefik ACME storage (created by Traefik)
├── traefik/
│   └── dynamic/
│       └── middlewares.yml       # Security headers, rate limiting
├── authentik/
│   ├── media/                    # Authentik media files
│   └── custom-templates/         # Optional Authentik custom templates
├── backend/
│   ├── Dockerfile
│   └── app/
│       ├── main.py
│       └── auth/
│           └── authentik.py      # Header extraction + JWT validation
└── frontend/
    ├── Dockerfile
    └── src/
        └── api/
            └── client.ts         # Auth-aware fetch wrapper
```
