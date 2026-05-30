---
name: ImplementSpecs
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
- A specific sub-module (e.g. `HostApp/backend`)
- An entire module (e.g. `HostApp`, all its sub-modules)
- All enabled modules

Process sub-modules in dependency order as defined by the `depends_on` relationships in the module's `docker-compose.yml`.

## Step 2 — Read specifications

For each sub-module in scope, read in order:
1. `modules/<MODULE>/SPECS/base-specs.md` — module-level general specs
2. Any spec files referenced from `base-specs.md` (e.g. `security.md`, `openapi.yaml`, `auth-specs.md`)
3. Sub-module-level `base-specs.md` if present (e.g. `modules/<MODULE>/<SUB-MODULE>/SPECS/base-specs.md`)
4. Sub-module-level spec files referenced from the sub-module's `base-specs.md`
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
- **Update specs if needed**: if during implementation a spec is found to be incomplete, ambiguous, or incorrect, stop and update the relevant spec file before continuing. Do not silently deviate from specs. **MANDATORY**: do not change any code if a spec is found to be incomplete, ambiguous, or incorrect. In case, ask the user for clarification.

## Step 5 — Verify consistency

After implementing, verify:
1. All files referenced by the `Dockerfile` (if present) exist in `SOURCES/`.
2. All environment variables used in source code are documented in `modules/<MODULE>/.env.example`.
3. Any new port exposed by a service is reflected in the module's `docker-compose.yml` (ports are discovered dynamically via `scripts/runtime/list-exposed-ports.sh`).
4. Any new dependency (library, image) is added to the module's `SPECS/dependencies.md`.
5. The `SPECS/base-specs.md` inside modules and sub-modules accurately reflects what was implemented. In case of any discrepancy, ask the user for clarification.

## Step 6 — Verify test coverage

For every new or changed implementation, verify that a corresponding test exists inside the relevant `TESTS/` folder. This step is about **ensuring tests are present and up to date**, not executing them — test execution happens separately at development process step 7.

- If a test for the new/changed behaviour does not exist, create it now.
- If an existing test no longer matches the updated implementation, update it.
- Do NOT run the tests here. Simply ensure the test files are correct and committed alongside the source changes.

## Step 7 — Report

Summarise what was created or modified, listing:
- Files added or changed in `SOURCES/`
- New tests added in `TESTS/`
- Any open questions or deferred items that require human decision
