# IMPORTANT: Read This First

**This file (`base-specs.md`) is the MANDATORY starting point for any coding agent action on this module's database.**

Before implementing, modifying, or troubleshooting any database component, you MUST:
1. Read `rules/general-guidelines.md`, then
2. Read this entire file, then
3. Read `module-specs.md`, then any other further referenced specs files.

## Normative precedence

If rules overlap, apply them in this order:
1. This file (`base-specs.md`)
2. `module-specs.md`
3. any other specs file eventually references in `module-specs.md`

If two rules conflict at the same level, the above order defines the priority logic (i.e., rule in previous point wins, e.g., rule in point 1 wins over rule in point 2, and so on).

---

# module_template Database Specs

## Authoritative datamodel

**The model is the schema, and only Alembic writes it.** `backend/SOURCES/app/models.py` is the one
authored definition; migrations under `backend/SOURCES/alembic/versions/` apply it; and
`database/SPECS/schema.sql` is a **generated rendering** of the result, kept for reading and review.
The full procedure — design → model → migration → verify, with `scripts/dev/schema.sh` — is in
`schema-workflow.md` beside this file, which is the authority for anything schema-related.

**There is no `datamodel.sql`.** The bootstrap does not mount one
(`database/TESTS/test_bootstrap_compose_contract.py` asserts it is absent), so DDL written there is
executed by nothing. It is retired because a SQL file and the ORM declaring the same tables are two
owners of one schema, and idempotent DDL hides the drift between them: `CREATE TABLE IF NOT EXISTS`
creates but never alters, so four `au_*` columns lived in deployed databases that no file in the
repository declared. `schema-workflow.md` records that incident in full.

## Build and deployment source of init scripts

- Database init scripts used at runtime must exist under `<module>/database/SOURCES/initdb/`.
- Build step copies `SOURCES/initdb/*` to `database/DIST/initdb/` via `database/SPECS/build.sh`.
- Deployment step copies `database/DIST/initdb/` to
  `deployment_root/modules/<module>/database/initdb/`.
- Runtime compose mounts the deployed `./database/initdb/seed.sql`, never a `SPECS/` path — and
  never a `datamodel.sql`, which no longer exists.

## Adding a table to an existing deployment (mandatory)

A migration, not an init script. `SOURCES/initdb/` is applied **once** per database, gated on a
`script_key` in `module_bootstrap_execution`: on a database that has already been bootstrapped the
key is present and the file is skipped **in full, including anything just added to it**. That is
precisely why schema DDL moved to Alembic — a bootstrap that also created tables was a second owner
of the schema.

So:

1. Add or change the model in `backend/SOURCES/app/models.py`.
2. Generate the migration (`scripts/dev/schema.sh migration <module> -m "…"`) and read it before
   committing — autogenerate proposes, it does not decide.
3. Regenerate `database/SPECS/schema.sql` so the rendering matches
   (`scripts/dev/schema.sh schema-sql <module>`).

Seed **data** still belongs in `seed.sql`, and every statement there must be idempotent
(`ON CONFLICT DO NOTHING`, `WHERE NOT EXISTS`) because it runs on every deploy.

## Runtime DB targets

module_template must support one database target for module entities, configured through dedicated env vars in the example module_template setup:

- `<SLUG>_ENTITIES_DB_HOST`
- `<SLUG>_ENTITIES_DB_PORT`
- `<SLUG>_ENTITIES_DB_NAME`
- `<SLUG>_ENTITIES_DB_USER`
- `<SLUG>_ENTITIES_DB_PASSWORD`

Execution rules:

- The module's own entities live in its entities database; migrations run against that target.
- If the entities DB target resolves to the host_app DB target (`HOSTAPP_DB_*`), the `template-database` container must not be instantiated.
- When the module uses its dedicated entities database container, the database must be bootstrapped only on its first execution and its files must be persisted through the mounted volume so that state survives subsequent stop/start or redeploy cycles unless the user removes the volume.

## Entity classification rules (for frontend menu generation)

Use the module's models (rendered in `database/SPECS/schema.sql`) to classify entities as:
- **Main entities**: standalone business tables that must appear in module menu/pages.
- **Association entities**: pure join/link tables that must not create top-level menu items.

Current datamodel includes:
- `<entity>` as an example main entity.

Any future schema changes must keep this classification updated so frontend menu generation remains deterministic.

- `schema-workflow.md` — how a module's datamodel is designed and evolved: the one-owner rule (the model is the schema, only Alembic writes it), the design → model → migration → verify phases implemented by `scripts/dev/schema.sh`, baselines and squashing, and the expand → migrate → contract policy for rolling deploys. **Read it before changing any table.**
