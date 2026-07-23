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

- The authoritative schema source is `modules/module_template/database/SPECS/datamodel.sql` for the example module_template module.
- `datamodel.sql` is initially authored and maintained in `SPECS/` during the specifications step.
- During `/Specs2Sources`, the schema must be materialized to `modules/module_template/database/SOURCES/initdb/datamodel.sql` for runtime initialization.

## Build and deployment source of init scripts

- Database init scripts used at runtime must exist under `modules/module_template/database/SOURCES/initdb/`.
- Build step copies `SOURCES/initdb/*` to `database/DIST/initdb/` via `modules/module_template/database/SPECS/build.sh`.
- Deployment step copies `database/DIST/initdb/` to `deployment_root/modules/module_template/database/initdb/`.
- Runtime compose files must mount the deployed paths from `./database/initdb/datamodel.sql` and `./database/initdb/seed.sql`, never the `SPECS/` paths.

## Runtime DB targets

module_template must support one database target for module entities, configured through dedicated env vars in the example module_template setup:

- `TEMPLATE_ENTITIES_DB_HOST`
- `TEMPLATE_ENTITIES_DB_PORT`
- `TEMPLATE_ENTITIES_DB_NAME`
- `TEMPLATE_ENTITIES_DB_USER`
- `TEMPLATE_ENTITIES_DB_PASSWORD`

Execution rules:

- `datamodel.sql` must be executed only for the example module_template entities schema lifecycle.
- If the entities DB target resolves to the host_app DB target (`HOSTAPP_DB_*`), the `template-database` container must not be instantiated.
- When the module uses its dedicated entities database container, the database must be bootstrapped only on its first execution and its files must be persisted through the mounted volume so that state survives subsequent stop/start or redeploy cycles unless the user removes the volume.

## Entity classification rules (for frontend menu generation)

Use `datamodel.sql` to classify entities as:
- **Main entities**: standalone business tables that must appear in module menu/pages.
- **Association entities**: pure join/link tables that must not create top-level menu items.

Current datamodel includes:
- `template_items` as an example main entity.

Any future schema changes must keep this classification updated so frontend menu generation remains deterministic.
