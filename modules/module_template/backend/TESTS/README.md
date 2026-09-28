# module_template Backend Tests

## MF 2.0 UI Composition (General Concepts)

module_template backend is part of a remote module composed into host_app at runtime via MF 2.0.

- host_app owns shell UI and shared auth context.
- module_template provides module-specific pages and API behavior.
- Backend integration must preserve JWT validation and Authentik claim-based permission checks.

These tests verify the remote backend remains compatible in a composed host_app + remotes runtime.

## Compatible Module Creation (from `module_template`)

For new modules cloned from `module_template`, backend onboarding should include:

1. Copy template module folder and rename module identity (slug, env vars, permissions).
2. Update specs (`SPECS`) before backend implementation changes.
3. Keep permission namespace `<slug>.<resource>:<action>`.
4. Keep JWKS validation and host_app permission-context integration (host_app resolves
   permissions and tenant scope from its own tables via `/api/me`; the module never reads either
   from token claims — see `SPECS/module-specs.md` § *Backend Authentication and Authorization*).
5. Run full build/deploy/start flow and execute integration tests against containers.

Reference workflow docs:
- `IDEABLE-README.md` (repo root)
- `modules/host_app/README.md`
- `modules/module_template/MODULE-README.md`

This directory contains the backend test suite for module_template: three layers, described below,
covering the deployed API, the query core against a live database with no HTTP involved, and pure
logic with no database at all.

## Three layers, and each test belongs to exactly one

A test's SUBJECT decides its layer — not convenience, and not "whatever already imports easily."
Getting this wrong in either direction has a cost: a mechanics test standing in for a contract test
misses everything only HTTP actually exercises (auth, routing, serialization); a contract test
standing in for a mechanics test cannot see the SQL a change actually emits.

### 1. API integration — the default, and the majority

**What it is for:** the CONTRACT a caller can rely on — status codes, payload shapes, permissions,
tenancy, pagination metadata. This is the layer that catches what only the deployed system can
show: a compose wiring mistake, a migration that did not run, an env var the container never
received, a permission that 403s because the namespace is wrong end to end.

**What it may import:** `requests`, and nothing from `app.*` — a test at this layer that reaches
into source code has drifted into layer 2 and belongs there instead.

**What it runs against:** the deployed API endpoints (running in Docker containers) — real
compose, real migrations, real containers, exactly as a caller reaches them through Traefik in
production. Never source code directly.

**Named examples:** `test_items.py` (CRUD + auth for `template_items`), `test_tenant_isolation.py`
and `test_tenancy_contract_names.py` (the isolation suite and its stack-free naming-contract
companion), `test_history_pagination.py`, `test_health_endpoints.py`, `test_jwt_hotpath.py`,
`test_observability.py`, `test_pool_resilience.py`, `test_audit_consistency.py`,
`test_migrations.py`, `test_items_pagination_perf.py`. `conftest.py` provides this layer's shared
fixtures (`api_base_url`, `auth_token`/`auth_headers`, the service-account token mint and profile
grant).

### 2. In-process (mechanics) — additive, never a substitute

**What it is for:** what a contract test cannot observe from outside — the SQL a query actually
compiles to, whether a keyset cursor really seeks instead of skipping at depth, whether an
eager-load plan is honoured (the N+1 question), whether a statement carries bound parameters or
embedded literals. These are properties of the QUERY, not of the response shape, and an API test
can pass with every one of them wrong.

**What it may import:** `app.*` directly — `app.crud`, `app.entities`, `app.models`,
`app.database`, `app.tenancy` — and `ideable_api.*`, the shared framework package those first two
re-export (`reusable.api/README.md`), reached through the tracked `SOURCES/.ideable-api` symlink.
NO FastAPI anywhere in the chain. That boundary is deliberate and enforced by where `TenantScope`
lives (`ideable_api.tenancy`, not any module's `auth.py` — see its module docstring) precisely so
this layer never needs an HTTP framework installed. A check that reads one of those files as TEXT
takes its path from `framework_sources.py` rather than writing its own.
`requirements-dev.txt` states the same boundary from the tooling side: it installs SQLAlchemy,
SQLAlchemy-Continuum and pydantic so this layer type-checks and runs, and deliberately does not
install FastAPI.

**What it runs against:** the deployed database — the SAME `<slug>-database` a real backend talks
to, migrated the same way, through the restricted `<SLUG>_APP_DB_USER` role (never the owning
role), so Row-Level Security is exercised exactly as it is in production. Only the HTTP layer is
absent: no router, no `TestClient`, no request. `conftest.py`'s `app_module` fixture is what opens
this — it puts `backend/SOURCES` on `sys.path`, resolves the database connection (tool-container
service DNS or the published loopback port, mirroring `_grant_profile`'s host_app connection), and
imports the query core.

**Named examples:** `test_entity_registry.py` (the registry contract — validated at import, frozen
after startup — for every declared entity AND every declared association, the latter over stand-in
models; needs the database connection only because importing `app.database` builds a real `Engine`,
not because any query runs), `test_entity_query_mechanics.py` (the generic list/
get/create/update/delete core, tenant scoping, keyset pagination, the eager-load plan), and
`test_bespoke_baseline.py` (the frozen pre-registry baseline in `benchmark/bespoke_baseline.py`
still behaves correctly against the live schema).

**Additive, never a substitute — this is the rule that keeps the layer honest.** A behaviour
reachable over HTTP must have its own API-layer test regardless of what this layer also covers; if
a mechanics test is the ONLY test of something a caller can call, that something is missing its
contract test. `items`' generic CRUD is covered both ways today: `test_items.py` at the API layer,
`test_entity_query_mechanics.py` at this one — and that duplication is intentional, not
redundant, because the two layers answer different questions.

### 3. Stack-free — logic that needs neither an API nor a database

**What it is for:** pure functions and static structure — parsing, filtering, naming contracts,
DDL-generation code — where a database or a running server would be scaffolding, not subject.

**What it may import:** `app.*` modules that need no live connection to be exercised (most are
loaded via `importlib.util.spec_from_file_location` precisely so nothing else in the package needs
to import cleanly), or nothing from `app.*` at all — several of these read source files as text and
assert on structure.

**What it runs against:** nothing external. These run in the CI gate where there is no database and
no deployed stack.

**Named examples:** `test_framework_ops_and_rewriter.py` (the Alembic Rewriter and framework DDL
operations, driven with a synthetic `CreateTableOp`), `test_audit_filters.py` (`app.audit`'s pure
in-memory history filter, loaded standalone), `test_audit_retention.py` and
`test_audit_retention_is_observable.py` (partitioning/retention DDL read as text from the
migrations and `scripts/runtime/audit-retention.sh`), `test_auth_permissions_payload.py` (asserts
on `auth.py`'s source: permissions resolved via host_app, never from claims).

## Test Structure

- `conftest.py` — shared fixtures for all three layers: the API layer's `api_base_url` /
  `auth_token` / `auth_headers`; the in-process layer's `app_module` / `db_session` /
  `tenant_scope_factory`.
- `test_*.py` — one file per behaviour under test, in whichever layer above its subject belongs to.
- `benchmark/` — sub-set 4's benchmark suite and the frozen pre-registry baseline
  (`bespoke_baseline.py`) it measures against; see that module's docstring.

## Running Tests

**The sanctioned way is `scripts/dev/common/run_enabled_tests.sh`** (directly, or via the
`ideable-test-and-fix` skill) — see `rules/testing-guidelines.md` § *How tests must be run*. It is
the only path that writes the `TEST_REPORTS/` artifacts maintainers rely on, and a direct `pytest`
invocation refuses to run without `IDEABLE_TEST_RUNNER=1` (or the explicit, unrecorded
`IDEABLE_UNRECORDED_RUN=1` escape hatch for local iteration).

Layer 1 (API integration) needs the module's containers running in `deployment_root/`:

```bash
export TEMPLATE_API_URL=http://localhost:8002/module/template/api
export TEST_AUTH_TOKEN=<valid_jwt_token>  # optional — conftest mints one otherwise
```

Layers 2 and 3 need no running backend container — layer 2 needs the deployed DATABASE (see
`conftest.py`'s `app_module` fixture for the connection it resolves), layer 3 needs nothing beyond
the Python environment `requirements-dev.txt` describes.

## Authentication

Layer 1 only. `conftest.py`'s `auth_token` fixture mints a service-account token through Authentik
and grants it this module's permissions in host_app's database — it FAILS rather than skips when it
cannot, per `rules/testing-guidelines.md` § *A skip is explained, never just counted*.
`TEST_AUTH_TOKEN` overrides it when set.

## Coverage by layer

- **Layer 1 (API):** health, CRUD + auth + tenancy for `template_items`, JWT hot-path, audit-trail
  history pagination and filtering, observability, connection-pool resilience, migrations.
- **Layer 2 (in-process):** the entity-registry contract, the generic query core's tenant scoping,
  whitelisting, pagination and eager-load enforcement, and the frozen bespoke baseline sub-set 4
  benchmarks against.
- **Layer 3 (stack-free):** the Alembic Rewriter and framework DDL operations, the audit history
  filter, retention/partitioning DDL, and the permission-resolution source contract.

## Permissions

The Layer 1 tests verify that endpoints require specific permissions:
- `items:view` — for listing/reading items
- `items:edit` — for creating, updating, and deleting items
