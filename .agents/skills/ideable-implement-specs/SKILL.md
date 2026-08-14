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
2. Each module's dependency declaration in `modules/<MODULE>/module.json` (`provides` / `dependsOn`, with `kinds`) — the machine-readable inter-module contract resolved providers-first by `scripts/common/module_deps.py`; inspect the resolved graph with `scripts/runtime/status.sh --deps`. The human-readable `modules/<MODULE>/SPECS/dependencies.md` records pinned library versions (checked to exist by `scripts/common/validate_modules.sh`). Canonical contract: `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md` §5.1.
3. `rules/general-guidelines.md` — re-read the mandatory project rules before writing any code.

## Step 1 — Determine scope

Ask the user (or infer from context) which of the following is being implemented:
- A specific sub-module (e.g. `host_app/backend`)
- An entire module (e.g. `host_app`, all its sub-modules)
- All enabled modules

Process modules and sub-modules in **dependency (providers-first) order** as resolved from the `dependsOn`/`provides` declarations in each `module.json` (the order `scripts/common/module_deps.py` produces and `scripts/runtime/status.sh --deps` prints — host_app first, then dependents). Within a module, sub-modules follow the `depends_on` relationships in the module's `docker-compose.yml`.

## Step 1b — Compute the incremental work-set

Do **not** blindly re-derive every spec each run. Compute which specs actually need work — a
spec needs work when **it changed** or **a spec it (transitively) references changed**:

```bash
scripts/common/spec_workset.py            # default: working tree vs HEAD
scripts/common/spec_workset.py --base <ref>   # e.g. the last-implemented commit
scripts/common/spec_workset.py --force    # full run — every spec (self-healing)
```

The script rebuilds the spec **reference graph fresh** each run (never trust a cached list),
uses **git as the change oracle**, and prints `CHANGED ∪ transitive-DEPENDENTS` as the
work-set plus the SKIPPED specs.

Rules for using it (a **cache hint, never the source of truth**):
- **`Done ⇐ contract tests pass`** — never "the skill finished". Correctness is established by
  `ideable-test-and-fix`, not by hash/graph equality.
- **Report the work-set before writing anything**, and on ambiguity **stop and ask**.
- Even for **skipped** specs, their contract tests are still re-run in the test step — the skip
  saves *implementation*, not *verification* — so a silent drift still surfaces.
- Run `--force` **periodically / in CI** so a full self-healing pass can never be locked out.
- Per-spec status vocabulary (a derived view, reported not hand-edited): `Todo` (never
  implemented), `Doing` (selected this run; always re-selected if a run is interrupted — never
  trusted as complete), `Done` (implemented **and** contract tests pass), `Drifted` (spec
  unchanged but SOURCES changed out-of-band → re-select), `Failing` (tests fail → not Done),
  `Blocked` (missing precondition / ambiguity → stop and ask the human).

Then read specs and implement **only the work-set** (Steps 2–5), in dependency order.

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

## Step 4 — Create an implementation plan

Before writing any source, create an **implementation plan** — the human-readable status
artifact that this and the downstream skills keep current. Format, status-symbol legend,
naming, location, and active-plan resolution are defined **once** in
`rules/implementation-plan.md`; read it and follow it exactly (do not restate it here).

Concretely, at this step:
1. Create the plan file in `implementation-plans/` using the naming convention in that rule
   (`<date> - <time> - <description>.md`, timestamp = now). Then, per that rule's
   **Git integration**, create and check out the plan's branch —
   `git checkout -b plan/<description>` from the current branch — so all subsequent
   plan work lands on `plan/<description>`.
2. Write the **Purpose** chapter (a few sentences on what this run implements) and the
   **Overall view** chapter: **Created at** = now (`YYYY-MM-DD HH:MM`), **Last updated** = now,
   **Current step** = `Implementing (ideable-implement-specs)`, and the canonical dev-cycle
   Mermaid graph with the highlight on the `Implementing` node (the two `class` lines set so
   `Implementing` is the only `current` node).
3. Fill the **Main implementation summary table** with the things to implement, derived from
   the specs read in Step 2 and the audit in Step 3 — one row per thing, `Impl` = 🔲 (to do),
   and `BE test` / `FE test` = 🔲 or ➖ (`N/A`) depending on whether the thing has a
   backend / frontend part.
4. Write the **Status summary**, the **Detailed summary** (with sub-task tables where a thing
   decomposes), and the **Repos updates summary table** (`Implementation` = `Not started`,
   `Tests` = `0 passed / 0 failed / 0 pending`, `Commit` = `Not committed`).

Keep this plan updated as you implement in Step 5 (drive the `Impl` column 🔲→🔄→✅ and the
Repos `Implementation` cell). It is not a source of truth — correctness is established by
tests in the separate test step — it exists so a reader sees the real status at a glance.

## Step 5 — Implement

Apply the following rules strictly while writing or modifying source files. As you complete
each thing from the plan's Main table, update its `Impl` cell (🔄 while working, ✅ when the
source is written) and refresh the plan's Status summary — per `rules/implementation-plan.md`.

- **Dockerfiles**: if the sub-module requires a Docker image, place its `Dockerfile` only inside `SOURCES/`. Never place it in `DIST/` or the sub-module root.
- **No deployment logic in SOURCES**: `SOURCES/` must contain only source code and the `Dockerfile`. It must never reference `deployment_root/`, `DIST/`, or any path outside the sub-module.
- **Respect the general guidelines**: follow all rules in `rules/general-guidelines.md`, in the related  module-specific rules and sub-module-specific rules in `SPECS/`.
- **Respect existing interfaces**: do not change API contracts, database schemas, or environment variable names that other sub-modules depend on without explicit instruction.
- **Follow the `ideable-spec-driven-edit` discipline for every edit** — it is the single
  rulebook for safe changes and applies in full here: **no fallbacks/workarounds** (implement
  only the requested specs assuming preconditions are met; if a precondition is unmet — missing
  or different schema/data/config — ask the user to meet it first); **no hardcoding** missing
  data or silent schema changes (surface what is missing/different); and **propose-don't-edit
  specs with stop-and-ask** — if a spec is found incomplete, ambiguous, or incorrect, **do not
  change any code**; stop and ask the user, then update the spec (framework-owned
  `ideable-framework-specs/` first if it is a framework contract) only after confirmation. Read
  `ideable-spec-driven-edit` and honour it.

## Step 6 — Verify consistency

After implementing, verify:
1. All files referenced by the `Dockerfile` (if present) exist in `SOURCES/`.
2. All environment variables used in source code are documented in `modules/<MODULE>/.env.example`.
3. Any new port exposed by a service is reflected in the module's `docker-compose.yml` (ports are discovered dynamically via `scripts/runtime/list-exposed-ports.sh`).
4. Any new dependency is declared in the right place: a new **inter-module** dependency as a `dependsOn` edge (with the correct `kinds`) in `modules/<MODULE>/module.json`, and any new **library/image** version in `modules/<MODULE>/SPECS/dependencies.md`. Run `scripts/common/validate_modules.sh` — it validates the `module.json` schema, resolves the graph, and emits the `provides`-vs-reality and drift lints.
5. The `SPECS/base-specs.md` inside modules and sub-modules, together with any referenced `ideable-framework-specs/` files, accurately reflect what was implemented. In case of any discrepancy, ask the user for clarification.

## Step 7 — Verify test coverage

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

## Step 8 — Report

Summarise what was created or modified, listing:
- Files added or changed in `SOURCES/`
- New tests added in `TESTS/`
- The path of the implementation plan created in Step 4, and its current Status summary
- Any open questions or deferred items that require human decision
