# ModuleTemplate Database Specs

## Authoritative datamodel

- The authoritative schema source is `modules/ModuleTemplate/database/SPECS/datamodel.sql`.
- `datamodel.sql` is initially authored and maintained in `SPECS/` during the specifications step.
- During `/Specs2Sources`, the schema must be materialized to `modules/ModuleTemplate/database/SOURCES/initdb/datamodel.sql` for runtime initialization.

## Authoritative authorization model

- The authoritative RBAC seed source is `modules/ModuleTemplate/database/SPECS/authorization.sql`.
- `authorization.sql` must define module permissions, module roles, module profiles, and role/profile mappings in HostApp RBAC tables.
- `authorization.sql` must be idempotent (safe on repeated executions).
- During `/Specs2Sources`, authorization seed must be materialized to `modules/ModuleTemplate/database/SOURCES/initdb/authorization.sql`.

## Build and deployment source of init scripts

- Database init scripts used at runtime must exist under `modules/ModuleTemplate/database/SOURCES/initdb/`.
- Build step copies `SOURCES/initdb/*` to `database/DIST/initdb/` via `modules/ModuleTemplate/database/SPECS/build.sh`.
- Deployment step copies `database/DIST/initdb/` to `deployment_root/modules/ModuleTemplate/database/initdb/`.

## Runtime DB targets

ModuleTemplate must support two distinct database targets, each configured through dedicated env vars:

- **Entities DB target** (used by module entities and backend runtime):
  - `TEMPLATE_ENTITIES_DB_HOST`
  - `TEMPLATE_ENTITIES_DB_PORT`
  - `TEMPLATE_ENTITIES_DB_NAME`
  - `TEMPLATE_ENTITIES_DB_USER`
  - `TEMPLATE_ENTITIES_DB_PASSWORD`

- **Authorization DB target** (used only for RBAC seed execution):
  - `TEMPLATE_AUTH_DB_HOST`
  - `TEMPLATE_AUTH_DB_PORT`
  - `TEMPLATE_AUTH_DB_NAME`
  - `TEMPLATE_AUTH_DB_USER`
  - `TEMPLATE_AUTH_DB_PASSWORD`

Execution rules:

- On module startup, `authorization.sql` must be executed against the **authorization DB target**.
- `datamodel.sql` must be executed only for the ModuleTemplate entities schema lifecycle.
- If the entities DB target resolves to the HostApp DB target (`HOSTAPP_DB_*`), the `template-database` container must not be instantiated.

## Bootstrap execution contract

- `datamodel.sql` and `authorization.sql` must be executed only once during the first bootstrap execution (initial environment provisioning).
- Their execution must be orchestrated by a dedicated bootstrap container for the module.
- The bootstrap container must:
  - depend on HostApp authorization bootstrap completion (service dependency) before running module SQL bootstrap logic;
  - wait until both configured DB targets are healthy and accepting connections;
  - only then execute `datamodel.sql` against the entities DB target and `authorization.sql` against the authorization DB target.

Implementation-time mandatory check:

- Any implementation that modifies module bootstrap startup ordering must preserve or re-establish an explicit dependency from module bootstrap to HostApp authorization bootstrap completion, otherwise it is non-compliant with these specs.

## Entity classification rules (for frontend menu generation)

Use `datamodel.sql` to classify entities as:
- **Main entities**: standalone business tables that must appear in module menu/pages.
- **Association entities**: pure join/link tables that must not create top-level menu items.

Current datamodel includes:
- `template_items` as a main entity.

Any future schema changes must keep this classification updated so frontend menu generation remains deterministic.

## Entity-to-permission synchronization rule

- Every time a new main entity is added to `datamodel.sql`, a corresponding CRUD permission set must be added to `authorization.sql` with naming:
  - `<module_slug>.<entity>.read`
  - `<module_slug>.<entity>.create`
  - `<module_slug>.<entity>.update`
  - `<module_slug>.<entity>.delete`
- For example, adding entity `pincopallino` requires:
  - `template.pincopallino.read`
  - `template.pincopallino.create`
  - `template.pincopallino.update`
  - `template.pincopallino.delete`

