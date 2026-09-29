**IMPORTANT**: define here module-specific backend specifications.

For the framework-wide audit trail contract (versioning, history endpoints, association
versioning, actor injection, frontend rendering rules) see:
`modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md`

---

## Audit Trail — Module-Specific Configuration

Every entity model in this module must opt in to SQLAlchemy-Continuum versioning by default.
Association tables linking versioned entities must also apply `Versioned`.

**Versioned entities for the `template` baseline module:**
- `template_items` — main entity, full field-change versioning
- Any association tables linking `template_items` to other versioned entities

To opt out of versioning for a specific model:

```python
class SomeTransientModel(Base):
    __versioned__ = {'exclude': True}
    ...
```

**Permission used for all `/history` endpoints in this module:**
`require_permission('template.audit_trail:view')` — the fully-qualified
`<module_slug>.<resource>:<action>` form (see `general_bug_avoider.md` and the framework
`ideable-framework-specs/shared-backend-bug-avoider.md` § *Authorization*). A bare
`audit_trail:view` never matches the runtime permission set and always 403s.

---

## Entity registry (`app/entities/`) — this module's entities

The framework contract — what a descriptor declares, what is served from it, and the hooks that
change one step without writing a router — is
`backend/SPECS/ideable-framework-specs/base-specs.md` § *Entities are declared, not written*. It is
not repeated here. What follows is what THIS module declares and where.

- `app/entities/items.py` registers `template_items` under the key `items`, with its schemas, the
  bare permission resource `items`, and an empty eager-load plan.
- `app/main.py` calls `entities.mount_entity_routers(app, prefix='/api')`, which serves every
  registered entity. No per-entity router is written; `app/routers/` holds none.
- The endpoints are built by `ideable_api.router`, and the descriptor, the registry
  (`register_entity`, `get_entity_descriptor`, `all_entity_descriptors`, `freeze_registry`,
  `is_registry_frozen`) and the descriptor-driven query core (`list_entity`, `get_entity_row`,
  `create_entity_row`, `update_entity_row`, `delete_entity_row`) by `ideable_api.entities` — all of
  it the SHARED framework package (`reusable.api/README.md`), not this module's. Those wrappers are
  thin covers over the model-parameterised functions in `ideable_api.query` (which `app/crud.py`
  re-exports), closed over a descriptor rather than a bare model so the eager-load plan and the
  hooks apply on every call path.
- `app/entities/__init__.py` is this module's own: it re-exports the framework's names, imports the
  module's descriptor submodules, calls `freeze_registry()`, and builds the `Platform` that tells
  the generated endpoints how THIS backend opens a session, checks a permission, resolves a tenant
  scope and reads its audit trail.

- **Registered at import, frozen after startup.** `app/entities/__init__.py` imports every
  descriptor submodule and calls `freeze_registry()` once, at the bottom of the file — the module
  decides when it has finished declaring, so the framework package freezes nothing itself. A
  `register_entity()` call afterwards raises — there is no path back to an unfrozen registry in one
  process, by design (`implementation-plans/... an-entity-is-served-by-the-framework-unless-it-says-otherwise ...`,
  design note "where the genericity is allowed to live", rule 1).
- **`crud.list_entities` / `crud.get_entity` gained an `options` parameter**: a sequence of
  `sqlalchemy.orm` loader options (`joinedload`, `selectinload`, `load_only`, …), applied via
  `.options(*options)`. The descriptor-driven wrappers above always pass `descriptor.eager_load`
  here — there is no call path that skips it. `items` declares an empty plan today (`TemplateItem`
  has no relationships); the N+1 guard that FAILS a descriptor which omits a needed one is sub-set
  4's job, not this one's.
- **`TenantScope` lives in `app/tenancy.py`, and nothing else does.** The module holds the plain
  dataclass and imports no web framework, so `crud.py` and the registry can import it without
  pulling in FastAPI — which is what makes `backend/TESTS`' in-process layer possible at all (see
  `TESTS/README.md`). `app/auth.py` imports and re-exports the name, so `from .auth import
  TenantScope` resolves too; new code should import from `app.tenancy`.

- **The registry's two suites are FRAMEWORK contracts, force-synced into every module.**
  `backend/TESTS/test_entity_registry.py` and `backend/TESTS/test_entity_query_mechanics.py` name no
  entity: they ask the registry what this module declares and hold the contract against each entity,
  discovering the columns they need from that entity's own create schema. The same file holds the
  contract for a declared ASSOCIATION — the descriptor's validation, the freeze, the narrowing and
  the hook order — over stand-in models, so a module that declares no link table is covered too. A
  module that adds an entity or an association gets it covered without editing either file, and must
  not edit them — they arrive from the template
  (`SPECS/ideable-framework-specs/infrastructure-file-list.md` § *Shared framework tests*).
  `backend/TESTS/test_bespoke_baseline.py` is deliberately NOT one of them: it guards a frozen copy
  of this module's own pre-registry `items` query, kept only until sub-set 4's benchmark has used it.

## Diagnostic probes — module-specific values

The probe contract (`/health` liveness, `/ready` readiness, `/startup` startup — unauthenticated,
`include_in_schema=False`, exempt from the audit-actor dependency) is framework-wide and defined
in `ideable-framework-specs/base-specs.md` § *Diagnostic probes*. For this module:

- The probes are served by `template-backend` on internal port `8002`; through Traefik they are
  reachable under `/module/template/…` like any other root path of this backend.
- The `template-backend` healthcheck targets `/ready`; `template-frontend` carries its own
  `wget --spider` healthcheck and depends on the backend with `condition: service_healthy`.
- Readiness components reported by this module: `database` (the `TEMPLATE_ENTITIES_DB_*` database,
  checked with `SELECT 1` on the dedicated probe engine) and `jwks` (`AUTHENTIK_JWKS_URL` cache
  state, never fetched by the probe).
- The probe timeout is the module constant `PROBE_TIMEOUT_SECONDS = 2` in `app/database.py` — it
  is deliberately **not** an env var: the value is bounded by the 10s healthcheck interval, not by
  deployment.
