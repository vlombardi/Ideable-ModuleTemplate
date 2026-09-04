**IMPORTANT**: define here module specific **database** specifications.

The framework contract — how the schema is authored, migrated and rendered — is
`ideable-framework-specs/schema-workflow.md`, and it is the authority. Read it first. This file is
for what is true of **this module's** data and nothing else.

---

## The schema, in one line

**The model is the schema, and only Alembic writes it.** `backend/SOURCES/app/models.py` is the
authored definition, `backend/SOURCES/alembic/versions/` applies it, and `SPECS/schema.sql` is a
generated rendering kept for reading. There is no `datamodel.sql`; DDL written into an init script is
executed by nothing on a database that has already been bootstrapped.

## Entities this module declares

| Table | Kind | Versioned | Tenant-scoped | Notes |
|---|---|:--:|:--:|---|
| `<entity>` | main | yes | yes | the example entity; business fields only, no inline `au_*` columns |

**Main vs association.** A *main* entity is a standalone business table and gets a menu item and a
route. An *association* entity is a pure join table and must not produce a top-level menu item.
Classify from the models, not from a filename.

## What every entity here must carry

- `__versioned__: dict = {}` — audit trail is on by default in this module. Opt out only with
  `__versioned__ = {'exclude': True}` and a reason.
- `__tenant_scoped__` — mandatory, and checked at build time by
  `scripts/common/check_tenancy_markers.py`. `True` means the rows are partitioned by tenant and the
  gate then insists `tenant_id` exists.
- **Tenant-leading indexes.** `tenant_id` comes first in every composite index, or a query touches
  every tenant's rows and filters afterwards.
- **A trigram index for any column exposed as a substring filter.** `ILIKE '%term%'` has a leading
  wildcard, which no B-tree can serve.

## Seed data

`SPECS/seed.sql` (materialised to `SOURCES/initdb/seed.sql`) carries **data only** — never DDL. It
runs on every deploy, so every statement is idempotent (`ON CONFLICT DO NOTHING`,
`WHERE NOT EXISTS`). A one-time block guards itself with its own `script_key` in
`module_bootstrap_execution`; never reuse or bump an existing key to force a re-run.

## Runtime database target

This module uses one entities database, configured through `<SLUG>_ENTITIES_DB_*`. When that target
resolves to host_app's, the module's own database container is not instantiated. The container's
volume must persist across stop/start and redeploy unless the operator removes it.
