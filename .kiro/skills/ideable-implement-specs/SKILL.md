---
name: ideable-implement-specs
description: Implement or update SOURCES from SPECS for one or more modules/sub-modules
---
# General Guidelines
If the user asks to implement specs without specifying a module, always implement all the enabled modules (see `modules/enabled.md`).
When implementing specs for a module, implement all the sub-modules of the module, no partial implementations.

# Workflow: Implement Specs → Sources

This workflow guides a coding agent through the **coding step (step 2)** of the development process: reading specification files and producing or updating source files in `SOURCES/` folders. It is intentionally structured to maximise consistency, even though the output is not fully deterministic.

## Prerequisites

Before starting, verify:
1. `modules/enabled.md` — identify which modules are enabled. Only work on enabled modules.
2. Each module's `dependencies.md` (e.g. `modules/<MODULE>/dependencies.md`) — verify dependency versions and processing prerequisites.
3. `rules/general-guidelines.md` — re-read the mandatory project rules before writing any code.

## Step 1 — Determine scope

Ask the user (or infer from context) which of the following is being implemented:
- A specific sub-module (e.g. `host_app/backend`)
- An entire module (e.g. `host_app`, all its sub-modules)
- All enabled modules

Process sub-modules in dependency order as defined by the `depends_on` relationships in the module's `docker-compose.yml`.

## Step 2 — Read specifications

For each sub-module in scope, read in order:
1. `modules/<MODULE>/SPECS/base-specs.md` — module-level general specs
2. Any framework-owned spec files referenced from `base-specs.md` that live under an `ideable-framework-specs/` folder (e.g. `auth-specs.md`, `module-integration-specs.md`, `shared-ui-specs.md`)
3. Sub-module-level `base-specs.md` if present (e.g. `modules/<MODULE>/<SUB-MODULE>/SPECS/base-specs.md`)
4. Sub-module-level framework-owned spec files referenced from the sub-module's `base-specs.md`
5. `general_bug_avoider.md` of the sub-module being worked on — mandatory, contains known bugs and required fixes
6. `datamodel_related_bug_avoider.md` of the sub-module being worked on, if present

Note any explicit constraints, forbidden patterns, required interfaces, and data models before writing a single line of code.

## Step 3 — Audit existing SOURCES

Before creating or modifying files, read the existing contents of the sub-module's `SOURCES/` folder (if it exists) to understand:
- What is already implemented
- What is missing or inconsistent with the specs
- What must not be changed (e.g. stable interfaces used by other sub-modules)

## Step 4 — Implement

Apply the following rules strictly while writing or modifying source files:

- **Dockerfiles**: if the sub-module requires a Docker image, place its `Dockerfile` only inside `SOURCES/`. Never place it in `DIST/` or the sub-module root.
- **No deployment logic in SOURCES**: `SOURCES/` must contain only source code and the `Dockerfile`. It must never reference `deployment_root/`, `DIST/`, or any path outside the sub-module.
- **Respect the general guidelines**: follow all rules in `rules/general-guidelines.md`, in the related  module-specific rules and sub-module-specific rules in `SPECS/`.
- **Respect existing interfaces**: do not change API contracts, database schemas, or environment variable names that other sub-modules depend on without explicit instruction.
- **Update specs if needed**: if during implementation a spec is found to be incomplete, ambiguous, or incorrect, stop and update the relevant spec file before continuing. If the gap affects a framework-owned contract, update the corresponding `ideable-framework-specs/` file first; otherwise update the module-specific spec. Do not silently deviate from specs. **MANDATORY**: do not change any code if a spec is found to be incomplete, ambiguous, or incorrect. In case, ask the user for clarification.
- Do not implement fallbacks or workarounds, only implement the requested sepcs assuming all pre-conditions are met. If some pre-condition is not met (e.g., different schema, different or missing data or configuration), ask the user to meet the pre-condition first. 
- Do not ever silently implement fallbacks by hardcoding missing data or silently modifying database schemas, just notify what is missing or different from what is expected.

## Step 5 — Verify consistency

After implementing, verify:
1. All files referenced by the `Dockerfile` (if present) exist in `SOURCES/`.
2. All environment variables used in source code are documented in `modules/<MODULE>/.env.example`.
3. Any new port exposed by a service is reflected in the module's `docker-compose.yml` (ports are discovered dynamically via `scripts/runtime/list-exposed-ports.sh`).
4. Any new dependency (library, image) is added to the module's `SPECS/dependencies.md`.
5. The `SPECS/base-specs.md` inside modules and sub-modules, together with any referenced `ideable-framework-specs/` files, accurately reflect what was implemented. In case of any discrepancy, ask the user for clarification.

## Step 6 — Verify test coverage

For every new or changed implementation, verify that a corresponding test exists inside the relevant `TESTS/` folder. This step is about **ensuring tests are present and up to date**, not executing them — test execution happens separately at development process step 7.

- If a test for the new/changed behaviour does not exist, create it now.
- If an existing test no longer matches the updated implementation, update it.
- Do NOT run the tests here. Simply ensure the test files are correct and committed alongside the source changes.

**Frontend UI / E2E tests (Playwright).** A module gets the generic force-synced suites
for free (`entity-pages` + `crud-endpoints` discover the module's pages/resources), so do
not hand-write those. For each CRUD entity, additionally ensure a **CRUD E2E suite** per
`rules/testing-guidelines.md` § *CRUD E2E tests* (create via API → read/update/delete via
UI, assert real data, clean up). When entities have **foreign-key dependencies**, the
generated CRUD tests MUST be **dependency-ordered**:
1. Build the **entity dependency tree** with the shared helper
   `frontend/TESTS/playwright/lib/entity-graph.ts` — `parseEntityGraph(datamodelSql)`
   parses the `FOREIGN KEY … REFERENCES` clauses and returns `createOrder` (leaf-first)
   and per-entity `parents`. Do not hand-roll the parsing/topological sort.
2. **Create in `createOrder` (leaves → root)**, valorizing each child's FK fields with the
   id returned when its parent was created — so FK-bearing entities are actually created,
   not skipped.
3. **Delete in reverse (`createOrder` reversed, root → leaves)** to respect FK constraints.
Copy `modules/module_template/frontend/TESTS/playwright/tests/items-crud.spec.ts` as the
per-entity reference and apply the ordering above for FK-bearing entities.

**Entity scoping — cover exactly THIS module's entities (do NOT ask the user).** The
per-entity CRUD suites, and the module's `tests/` folder in general, must contain a suite
for **every entity, and only the entities, defined in this module's own datamodel**
(`database/SOURCES/initdb/datamodel.sql`). The template ships `tests/items-crud.spec.ts`
(and any other `*-crud.spec.ts`) as a **reference example** for the template's `items`
entity — it is NOT force-synced and is NOT part of a real module's suite. Therefore, when
implementing specs for a module derived from the template:
1. **Generate one CRUD suite per entity in this module's datamodel**, named after the
   entity (e.g. `company-crud.spec.ts`, `asset-crud.spec.ts`), ordered by the FK
   dependency tree above.
2. **Delete any template example CRUD spec whose entity does not exist in this module** —
   most notably `tests/items-crud.spec.ts` when the module has no `items` entity. Do **not**
   adapt it in place, do **not** leave it, and do **not** ask the user how to handle it:
   removing the template's items tests and shipping only this module's entity suites **is**
   the defined path. (The generic force-synced `entity-pages` + `crud-endpoints` specs stay
   — they self-discover this module's own pages/resources.)

## Step 7 — Report

Summarise what was created or modified, listing:
- Files added or changed in `SOURCES/`
- New tests added in `TESTS/`
- Any open questions or deferred items that require human decision
