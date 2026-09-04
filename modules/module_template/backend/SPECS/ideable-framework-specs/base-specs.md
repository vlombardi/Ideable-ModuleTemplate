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

- Build Docker image: `docker build --no-cache -t <slug>.backend:${IMAGE_TAG} ./SOURCES/  # never :latest — see Runtime image below`
- Produces Docker image only; no DIST folder.

## Runtime image (mandatory constraints on the code)

The backend runs on **`gcr.io/distroless/python3-debian12:nonroot`** as **uid 65532**, with
`read_only: true` and a `tmpfs` at `/tmp` (the non-root image work). These are constraints on what the application
may do, not deployment trivia:

| Constraint | Consequence for the code |
|---|---|
| No shell (`sh`, `bash`) | never `subprocess` a shell utility, never `shell=True`. Compose `command:` and healthchecks must be **exec form** — nothing expands a string form. |
| No package manager | every dependency ships in `requirements.txt` and is installed at build time. Nothing can be added at runtime. |
| Read-only root filesystem | `/tmp` is the only writable path. Any cache, scratch file or generated asset goes there (`tempfile.gettempdir()`). |
| uid 65532, non-root | a file the backend must read needs to be readable by that uid — e.g. the Authentik credential at `/shared/hostapp-api-token`, mode `440`, group `65532` via `HOSTAPP_API_TOKEN_GID`. |
| `ENTRYPOINT []` | the distroless base sets `ENTRYPOINT ["/usr/bin/python3.11"]`, which would turn every `CMD` into *arguments to python*. The Dockerfile resets it. |
| No locale data | `alembic.ini` must be **pure ASCII** — Alembic reads it with `encoding="locale"`, and `locale.getencoding()` ignores Python's UTF-8 mode (PEP 686). |

Debugging a running backend therefore uses `docker exec <c> python -c …`, not a shell. The recipes are
in `docs/RUNBOOK.md` § *Debugging a container that has no shell*; for an interactive session, build the
Dockerfile's `builder` stage, which keeps a full Debian userland without shipping one.

**Images carry an immutable tag.** Never `latest`: `${IMAGE_TAG}` is the commit the build came from
(`-dirty` when the working tree was not clean), recorded in `deployment_root/.env.config` so
`./start.sh` restarts exactly the deployed build and a rollback is one edited line. See
`rules/general-guidelines.md` § *Docker image naming convention*.

**Configuration fails closed on a blank value, not only a missing one.** Every required field in
`config.py` is covered by a blank check, because `docker compose` substitutes an empty string for any
variable it cannot resolve. Adding a `Field(...)` without adding it to the validator reopens the gap.

### Environment the backend reads (mandatory to keep in step)

Every `os.getenv` in the backend is one of three kinds, and the kind decides where it is written down:

- **Deployment tunables** — documented in the module's `.env.config.example` **and** passed by the
  service's `environment:` block. Both halves are required: a variable documented but not passed is a
  trap, because setting it changes nothing and nothing says so.
- **Secrets** — `.env.secrets.example` only, never `.env.config`.
- **Container-internal constants** — `APP_HOST` (the bind address, default `0.0.0.0`) and
  `MODULES_ROOT` (default `/modules`). These are **not** deployment knobs: `MODULES_ROOT` must match
  the volume mount that puts the module configs there, so changing one without the other breaks the
  seed and the e2e-account loader. They are recorded here rather than in `.env.config.example`
  precisely so nobody is invited to tune them.

## Service

- FastAPI backend for the example `template` remote module.
- Service exposes CRUD endpoints for the example `<entity>` entity.

## Authentication

- Validate Bearer JWTs using Authentik JWKS.
- Reject requests with invalid or missing tokens.

### JWKS cache and the JWT hot path (mandatory)

Token validation sits on every authenticated request, so its cache is a correctness concern as
much as a performance one:

- **TTL, never an untimed cache.** The JWKS is held in an explicit module-level cache with a TTL
  from `AUTHENTIK_JWKS_TTL_SECONDS` (default `600`). An untimed `@lru_cache` makes a routine
  provider key rotation a permanent `401 JWT signing key not found` until every container is
  restarted — a silent, non-self-healing outage.
- **Cache key objects, not the JSON.** RSA key objects are built at fetch time and indexed by
  `kid`; a request must never call `RSAAlgorithm.from_jwk(...)` on its own path.
- **Refresh on miss, exactly once.** An unknown `kid` forces a single JWKS refresh, guarded by a
  lock (concurrent misses collapse into one fetch) and rate-limited to one forced refresh per 30
  seconds, before the request is rejected. This is what makes a key rotation self-healing.
- **Bounded retry, retryable error.** The fetch retries 3 times with exponential backoff (≤2s of
  sleeping in total). When the provider stays unreachable the response is
  **`503` with a `Retry-After` header** — never a bare `500`, which tells clients and load
  balancers nothing about retrying.
- **One validation per request.** The app-level audit dependency runs before route dependencies:
  it validates the token once and stores the claims on `request.state.claims`; `get_claims` (and
  any per-route auth dependency) reads that state and only validates itself when the state is
  absent. Two validations per request means two RS256 verifications on a single-core backend.
- **Never cache whole tokens** keyed by the token string: unbounded memory, and permissions that
  keep working past the token's `exp`.
- Every JWKS refresh is logged at `INFO` (key count and outcome), and its freshness is surfaced in
  `/ready` (see § *Diagnostic probes*): `jwks`, `jwks_keys`, `jwks_fetched_at`,
  `jwks_last_outcome`, and `jwks_last_error` when the last attempt failed.
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

## List endpoints: pagination and totals (mandatory)

Every list endpoint follows this contract. It is a framework contract, not an Items one: the shared
`useServerTableState` hook in `reusable.ui` consumes exactly this response shape, so a module whose
backend answers differently gets a table that mispages.

**Page size is capped.** `MAX_PAGE_SIZE` (default **200**) bounds `limit`. The router declares it as
`Query(..., le=crud.MAX_PAGE_SIZE)` so an over-large request is a 422 rather than a table scan, and
`crud` re-checks it because the cap is a data-access invariant, not a routing one. An unbounded
`limit` lets one request ask for the whole table.

**`total` may be an estimate, and the response says which.** An exact `COUNT(*)` is a second full
pass over the same rows the page already selected. Above `EXACT_COUNT_THRESHOLD` matching rows
(default **50,000**, judged from the planner's estimate) the planner's estimate is returned instead
and **`total_is_exact` is `false`**. Below it the count is exact and `total_is_exact` is `true`.
A client that renders "N results" must read `total_is_exact` — reporting an estimate as exact is the
kind of quiet wrongness this field exists to prevent.

**Cursor (keyset) pagination is offered alongside offset.** `OFFSET` makes Postgres read and discard
`skip` rows, so deep pages degrade linearly: measured on 1,000,000 rows, offset 900,000 took **89 ms**
and the cursor **0.115 ms**. A list response therefore carries **`next_after_id`**, and passing it
back as `after_id` seeks directly.

**A cursor is refused when it would be wrong.** `after_id` is only meaningful against a stable,
unique ordering, so combining it with `sort_by != "id"` is **rejected** rather than silently returning
the wrong rows. Jumping to an arbitrary page still uses offset — a cursor can only step.

**Substring filters need trigram indexes.** `ILIKE '%…%'` cannot use a btree index. Any column
exposed as a substring filter must have a `gin_trgm_ops` index, added by a migration (see
`database/SPECS/ideable-framework-specs/schema-workflow.md`).

> **Configuration note.** `MAX_PAGE_SIZE` and `EXACT_COUNT_THRESHOLD` are read with `os.getenv` and
> have the defaults above, but the module's `docker-compose.yml` does not currently pass either into
> the container, so a deployment gets the code defaults. Exposing them follows the usual pattern — a
> slugged `<SLUG>_MAX_PAGE_SIZE` in the module `.env.config`, mapped in the service's `environment:`
> block — and is tracked in `kanban/todo/deferred-items-from-the-19-task-epic.md`.

## Observability (mandatory)

- **Every log line is JSON — including the libraries'.** The formatter is installed on the **root**
  handler and uvicorn's own handlers are cleared (`app/logging_config.py`). A formatter attached
  only to the application logger leaves uvicorn access lines and SQLAlchemy warnings as plain
  text, and a stream that is mostly JSON cannot be parsed as data at all. Minimum fields:
  `timestamp`, `level`, `logger`, `message`, `module_slug`, plus `request_id`, `actor`, `path`,
  `method` inside a request and `status_code`, `duration_ms` on the access line.
- **`X-Request-ID` in, bound, and back out.** The correlation middleware reuses an inbound header
  (so an id survives module-to-module calls) or generates one, binds it to the log context for the
  request, and echoes it in the response. **Traefik has no built-in request-id generator**: the id
  originates at the backend when the edge does not supply one. Do not claim edge-generated ids in
  documentation unless a Traefik plugin is actually deployed.
- **The formatter is dependency-free and replaceable.** `structlog` would buy per-call key-value
  logging and structured tracebacks at the cost of `ProcessorFormatter` bridging for library
  records; if that trade becomes worth it, `logging_config.py` is the only file to change.
- **`/metrics` is internal-only.** It is exposed by the instrumentator but **no Traefik router rule
  matches it**, so it stays on the Docker network. Publishing it hands out endpoint inventory,
  traffic volumes and error rates. Probes and the scrape are excluded from the latency histogram.
- **Module-specific collectors are mandatory, not optional extras**: `db_pool_connections_in_use` /
  `_overflow` against `db_pool_capacity` (the pool-sizing ceiling), `jwks_cache_age_seconds` (the JWT hot-path work —
  unbounded growth means refresh is failing), `audit_trail_errors_total` (the audit-correctness work — any increase
  means the audit trail is unreadable). A metrics scrape must never fail a request: collectors read
  live state defensively and degrade to a missing sample.

SLIs, their objectives and alert thresholds live in `docs/RUNBOOK.md` § *Observability and SLOs*.

## Audit trail correctness (mandatory)

The audit trail is a compliance artefact, so two properties matter more than availability:

- **The reference instant is persisted, never derived from the process.** `module_runtime_meta`
  holds one `system_epoch` row, written by the bootstrap with `INSERT … ON CONFLICT DO NOTHING`;
  `get_system_startup_at()` reads it once and caches it. A process-level `datetime.now()` gives
  each uvicorn worker its own value, so the same record reports **different creation timestamps
  to different users**, and every redeploy changes them. When the row cannot be read the backend
  logs a `WARNING` and falls back to the process instant — announced, never assumed.
- **A database fault on the audit path is an error, not an empty history.**
  `build_transaction_map`, `build_transaction_actor_map` and the version query log at `ERROR`
  with a stack trace and raise `AuditUnavailableError`, answered as **`503` + `Retry-After`**.
  Returning `{}` / `[]` made "this record never changed" and "we could not read the change
  record" indistinguishable — the difference an auditor asks about, and the one monitoring needs.
  Rolling back before raising keeps the session usable.
- **An unattributed commit inside a request is logged at `WARNING`.** The audit dependency records
  the request path in a ContextVar; when a versioned transaction commits with no actor while that
  path is set, `ActorPlugin` warns and names the path. Outside a request (bootstrap, shell,
  background job) the `system` actor is correct and nothing is logged.

The DDL lives in a **migration** — the model is the schema and only Alembic writes it, so there is
no second copy to keep in sync. `test_datamodel_source_sync.py` now checks the generated
`database/SPECS/schema.sql` against the tables `app/models.py` declares. The bootstrap registers
its own `script_key` (`<slug>_runtime_meta_v1`) for the DATA it seeds, so a second run is a no-op.

## Connection pool and concurrency (mandatory)

The backend runs **multiple uvicorn workers** (`BACKEND_WORKERS`, default 2) — a single process
uses a single core no matter how many the host has. Workers are separate processes that share
nothing, which drives everything below.

| Setting | Env var | Default | Why |
|---|---|---|---|
| Pool size | `DB_POOL_SIZE` | 10 | SQLAlchemy's silent default is 5 |
| Overflow | `DB_MAX_OVERFLOW` | 10 | Burst headroom above the pool |
| Pool timeout | `DB_POOL_TIMEOUT` | 10s | Wait for a connection before giving up (default was 30s) |
| Recycle | `DB_POOL_RECYCLE` | 1800s | Drop connections before an idle reaper does |
| Connect timeout | `DB_CONNECT_TIMEOUT` | 5s | Bound the TCP/auth handshake |
| Statement timeout | `DB_STATEMENT_TIMEOUT_MS` | 15000 | No query runs forever |
| Write rate limit | `RATE_LIMIT_WRITES_PER_MINUTE` | 120 | Per identity, per worker; 0 disables |

Mandatory rules:

- **`pool_pre_ping=True`.** After a database restart or failover, pooled connections are stale;
  without the pre-ping check each one fails a user request before being discarded.
- **`application_name=<slug>-backend` in `connect_args`**, so a module's connections are
  identifiable in `pg_stat_activity` — this is what makes the connection count auditable:
  `SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE '%-backend'`.
- **Pool exhaustion is a `503` with `Retry-After`**, never a `500`. SQLAlchemy's `TimeoutError`
  gets a dedicated exception handler; a saturated pool is a capacity signal a client and a load
  balancer can act on, not a server fault.
- **The AnyIO threadpool is sized to `pool_size + max_overflow`.** Endpoints are sync `def`, so
  they run in that threadpool; more threads than connections only moves the queue out of the
  database, where it is measurable, into an invisible one.
- **Import-time schema work is wrapped in a Postgres advisory lock** (`schema_lock()`). With N
  workers, `Base.metadata.create_all()` — and on host_app the sequence and plan-user syncs — runs
  N times concurrently and races. One worker does the work; the rest wait. This is a stopgap:
  Alembic migrations replace it.
- **The readiness probe keeps its own pool-less engine** (see § *Diagnostic probes*). A probe must
  never queue behind application traffic or consume the pool's last connection.

### Connection arithmetic (check before raising `BACKEND_WORKERS`)

```
backend connections = BACKEND_WORKERS × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
                    = 2 × (10 + 10) = 40 per backend
```

Each module's database must satisfy
`Σ(its backends) + bootstrap + any other consumer ≤ max_connections` (Postgres default: 100).
host_app's `database` also serves Authentik (server + worker) and the bootstrap job;
`template-database` serves this module's backend and bootstrap. At the defaults both fit with
headroom. **Doubling `BACKEND_WORKERS` doubles the connection count** — raise `max_connections` on
the database service, or lower `DB_POOL_SIZE`, in the same change.

### Rate limiting is per worker

The limiter's counters live in the worker process, so the effective ceiling is
`BACKEND_WORKERS × RATE_LIMIT_WRITES_PER_MINUTE`. Set the value with that multiplication in mind;
an exact global limit needs a store shared between workers, which the stack does not have yet.
It applies to `POST`/`PUT`/`PATCH`/`DELETE` only, keyed by the authenticated identity (falling
back to the peer address), and is enforced as an **app-level dependency registered after the
audit-actor dependency** — never as middleware, which runs before dependencies and would only ever
see the peer address.

## Diagnostic probes (mandatory)

Every module backend MUST expose three probes at the **application root** (never under `/api`),
so orchestration can tell "the process is alive" from "the process can serve traffic":

| Probe | Path | Semantics | Response |
|---|---|---|---|
| Liveness | `GET /health` | The process responds. **No I/O** — never touches the DB or the network. | `200 {"status": "ok"}` |
| Readiness | `GET /ready` | The process can serve traffic: DB reachable **and** JWKS usable. | `200 {"database": "ok", "jwks": "ok"\|"not_cached", "jwks_keys": <n>, "jwks_fetched_at": <iso8601\|null>, "jwks_last_outcome": "never"\|"ok"\|"error"}`, or `503` with the same body plus `"degraded": [<component>, …]` |
| Startup | `GET /startup` | Boot (migrations / bootstrap) has completed. | `200 {"status": "started"}`, or `503 {"status": "starting"}` before completion |

Mandatory rules:

- All three are **unauthenticated** and declared `include_in_schema=False`.
- They MUST NOT pass through the audit-actor dependency: JWT validation on a 10-second probe is
  pure waste. The global dependency skips them by path (see `shared-backend-bug-avoider.md`
  § *Audit Trail: Actor must be set before every mutating commit*).
- The readiness DB check runs `SELECT 1` on a **dedicated pool-less engine** with an explicit
  connect and statement timeout (≤ 2s), so a probe can never consume the last connection of the
  application pool nor hang past the probe interval.
- The readiness JWKS check reads the **cache state only** and MUST NOT force a remote fetch. The
  JWKS is fetched lazily on the first token validation, so an empty cache reports `not_cached`
  and is **not** a fault — only a missing `AUTHENTIK_JWKS_URL` (`unconfigured`) is degraded.
  A backend that reported 503 until the cache warmed would never become healthy before the first
  login, and would block every service gated on it by `condition: service_healthy`.
- `/startup` is backed by an in-memory flag set by the **last** startup handler.

Compose contract for these probes:

- The backend service's `healthcheck` targets **`/ready`** (not `/health`), with
  `interval: 10s`, `timeout: 5s`, `retries: 5`, `start_period: 30s`.
- The frontend service declares a `healthcheck` (`wget --spider http://127.0.0.1:80`) and depends
  on the backend with the long form `condition: service_healthy` — start ordering alone is not
  enough, since a started-but-unready backend still fails the frontend's first calls.


---

## Statelessness: the audit, and the rule it produces

A replica must be interchangeable, or scaling out silently changes behaviour instead of adding
capacity. Every piece of in-process state in a module backend was enumerated for the horizontal-scale work; this is the
outcome, and the rule that follows it.

| In-process state | Scope | Verdict |
|---|---|---|
| `audit._system_startup_at` | per process, lazily **read from the database** (`module_runtime_meta.system_epoch`) | **Safe.** It is a cache of a persisted value, so every replica converges on the same instant. It was a per-process value once, and that made the audit trail report a different creation timestamp for the same record depending on which worker answered. |
| `auth._jwks_cache` (RSA keys) | per process | **Safe, and intentionally per-replica.** Each replica fetches the JWKS independently and refreshes on an unknown `kid`, so a key rotation self-heals everywhere without coordination. The cost is N fetches instead of one, which is why `/metrics` exposes its state (the observability work). |
| `audit._current_user`, `audit._request_path` (`ContextVar`) | per **request** | **Safe.** A ContextVar set inside a request never outlives it. The actor dependency must stay `async def` for that to hold — see the shared bug-avoider. |
| `crud` GUCs (`app.tenant_ids`, `app.cross_tenant_read`) | per **transaction** (`set_config(…, true)`) | **Safe, and that is the point.** Transaction-local means nothing leaks to the next request that borrows a pooled connection — which is also why a post-commit read has to re-publish it. |
| `metadata.create_all()` | — | **Gone** (the move to Alembic migrations). Every replica running DDL at startup is a race by construction; Alembic runs once, in a one-shot job, before any replica serves traffic. |
| Session state / login state | — | **None.** Authorization is resolved per request from host_app's tables (the privileged-access work), so a replica holds nothing about a user. Verified: a token minted while three replicas were up kept working after the replica that served its first request was killed — no re-login. |

**Rule for a derived module.** Anything that must be identical across replicas goes in the database,
not in a module-level variable — `module_runtime_meta` exists for exactly this. Per-request state uses
a `ContextVar`. A per-process cache is acceptable only when every replica can derive the same value
independently, and then it must be observable on `/metrics`; a cache whose value differs per replica
and *matters* is a bug that only appears once someone scales out, which is the worst time to find it.
