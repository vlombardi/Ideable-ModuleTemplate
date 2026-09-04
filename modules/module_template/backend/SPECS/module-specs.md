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
