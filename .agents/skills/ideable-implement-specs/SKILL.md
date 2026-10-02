---
name: ideable-implement-specs
description: Implement or update SOURCES from an already-settled SPECS for one or more modules/sub-modules
---
# General Guidelines
If the user asks to implement specs without specifying a module, always implement all the enabled modules (see `modules/enabled.md`).
When implementing specs for a module, implement all the sub-modules of the module, no partial implementations.

# Workflow: Implement Specs → Sources

This workflow guides a coding agent through the **coding step (step 2)** of the development
process: reading specification files and producing or updating source files in `SOURCES/`
folders. It drives the dev-cycle's `Implementing` node, which always follows `Specs`
(`ideable-define-specs`, step 1) — the spec target is already decided by the time this skill
runs. **This skill has no spec-write authority.** If the spec does not settle something this
step needs, it does not propose a change and does not edit the spec itself — see Step 4b.

## Prerequisites

Before starting, verify:
1. `modules/enabled.md` — identify which modules are enabled. Only work on enabled modules.
2. Each module's dependency declaration in `modules/<MODULE>/module.json` (`provides` / `dependsOn`, with `kinds`) — the machine-readable inter-module contract resolved providers-first by `scripts/dev/common/module_deps.py`; inspect the resolved graph with `scripts/runtime/status.sh --deps`. The human-readable `modules/<MODULE>/SPECS/dependencies.md` records pinned library versions (checked to exist by `scripts/dev/common/validate_modules.sh`). Canonical contract: `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md` §5.1.
3. `rules/general-guidelines.md` — re-read the mandatory project rules before writing any code.

## Step 1 — Determine scope

Ask the user (or infer from context) which of the following is being implemented:
- A specific sub-module (e.g. `host_app/backend`)
- An entire module (e.g. `host_app`, all its sub-modules)
- All enabled modules

Process modules and sub-modules in **dependency (providers-first) order** as resolved from the `dependsOn`/`provides` declarations in each `module.json` (the order `scripts/dev/common/module_deps.py` produces and `scripts/runtime/status.sh --deps` prints — host_app first, then dependents). Within a module, sub-modules follow the `depends_on` relationships in the module's `docker-compose.yml`.

## Step 1b — Compute the incremental work-set

Do **not** blindly re-derive every spec each run. Compute which specs actually need work — a
spec needs work when **it changed** or **a spec it (transitively) references changed**:

```bash
scripts/dev/common/spec_workset.py            # default: working tree vs HEAD
scripts/dev/common/spec_workset.py --base <ref>   # e.g. the last-implemented commit
scripts/dev/common/spec_workset.py --force    # full run — every spec (self-healing)
```

The script rebuilds the spec **reference graph fresh** each run (never trust a cached list),
uses **git as the change oracle**, and prints `CHANGED ∪ transitive-DEPENDENTS` as the
work-set plus the SKIPPED specs.

Rules for using it (a **cache hint, never the source of truth**):
- **`Done ⇐ contract tests pass`** — never "the skill finished". Correctness is established by
  `ideable-test-and-fix`, not by hash/graph equality.
- Even for **skipped** specs, their contract tests are still re-run in the test step — the skip
  saves *implementation*, not *verification* — so a silent drift still surfaces.
- Run `--force` **periodically / in CI** so a full self-healing pass can never be locked out.
- Per-spec status vocabulary (a derived view, reported not hand-edited): `Todo` (never
  implemented), `Doing` (selected this run; always re-selected if a run is interrupted — never
  trusted as complete), `Done` (implemented **and** contract tests pass), `Drifted` (spec
  unchanged but SOURCES changed out-of-band → re-select), `Failing` (tests fail → not Done).

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

## Step 4 — Keep the plan updated

The implementation plan was **created by `ideable-define-specs`** at `NotStarted`, and the
router has already advanced it through `Branching` and `Specs` to `Implementing` by the time this
skill runs — this step never creates a plan (see `rules/implementation-plan.md` §
*Active plan resolution*: only `ideable-define-specs` and `ideable-bugfixing-and-changes` may).

As you implement (Step 5), drive the plan's `Impl` column (🔲→🔄→✅) and the Repos
`Implementation` cell — per `rules/implementation-plan.md`. Record every **decision this node
took that the plan did not already contain** (an implementation choice among options the spec
left open, a thing deliberately deferred) as a row in the executing sub-set's own **Decisions
table** — `It # | Node | Premises | Question | Answer | Who | Consequences`, `Who` = `agent` — per
`rules/implementation-plan.md` § *Detailed summary*. An agent's memory is never something the
next node may rely on: the router resumes the session across the nodes of one sub-set, but a
session can be gone and the sub-set after this one starts a fresh agent on purpose.

**This step performs the `Implementing` node; it never advances the plan.**
`./scripts/dev/common/dev-cycle.sh run` is the only advance, and there is no `set`: one command writes the graph, `Current step`, the executing sub-set and its accrued time — highlight **your own** node and stop there.

## Step 4b — A spec gap routes to `Specs`, never to a proposal or a question

If the spec this step is coding against does not settle something needed — an interface not
written down, a data model choice not made, a contract left implicit — **do not** edit the spec,
**do not** propose a change and wait, and **do not** stop-and-ask the maintainer for the spec's
content (that authority now belongs to `Specs`, not to a question put here). Instead:

1. Stop coding the thing that met the gap.
2. Call `record_spec_gap(text, reason, subset=<executing sub-set>)` (`scripts/dev/common/dev_cycle.py`) — or, if driving the plan by hand, write the same `<!-- dev-cycle:spec-gap -->` block yourself, naming exactly what is missing.
3. Leave the plan at `Implementing`; `./scripts/dev/common/dev-cycle.sh run` reads the marker and routes back to `Specs` instead of `BuildDeploy`.

A genuine decision only the maintainer can take — one `Specs` itself could not resolve either — is
raised the same way as everywhere else: record it as a decision row with NO answer
(`record_decision(..., asked=True)`) and run the router, which parks the plan at
`Asking human direction` so the wait is accrued to `Ask` rather than to this node. What is different
is that an ordinary spec gap is `Specs`'s to close, not a question this step asks or a change it
proposes.

## Step 5 — Implement

Apply the following rules strictly while writing or modifying source files. As you complete
each thing from the plan's Main table, update its `Impl` cell (🔄 while working, ✅ when the
source is written) and refresh the plan's Status summary — per `rules/implementation-plan.md`.

- **Dockerfiles**: if the sub-module requires a Docker image, place its `Dockerfile` only inside `SOURCES/`. Never place it in `DIST/` or the sub-module root.
- **No deployment logic in SOURCES**: `SOURCES/` must contain only source code and the `Dockerfile`. It must never reference `deployment_root/`, `DIST/`, or any path outside the sub-module.
- **Respect the general guidelines**: follow all rules in `rules/general-guidelines.md`, in the related  module-specific rules and sub-module-specific rules in `SPECS/`.
- **Respect existing interfaces**: do not change API contracts, database schemas, or environment variable names that other sub-modules depend on without explicit instruction.
- **Follow the `ideable-spec-driven-edit` discipline for every edit** — it is the single
  rulebook for safe changes and applies in full here, **except** § 4 (*Specs are
  propose-don't-edit*): that clause's authority now belongs to `Specs`, and this step follows
  Step 4b above instead. Everything else applies as written: **no fallbacks/workarounds**
  (implement only the requested specs assuming preconditions are met; if a precondition is unmet
  — missing or different schema/data/config — ask the user to meet it first) and **no
  hardcoding** missing data or silent schema changes (surface what is missing/different). Read
  `ideable-spec-driven-edit` and honour it.

## Step 6 — Verify consistency

After implementing, verify:
1. All files referenced by the `Dockerfile` (if present) exist in `SOURCES/`.
2. All environment variables used in source code are documented in `modules/<MODULE>/.env.example`.
3. Any new port exposed by a service is reflected in the module's `docker-compose.yml` (ports are discovered dynamically via `scripts/runtime/list-exposed-ports.sh`).
4. Any new dependency is declared in the right place: a new **inter-module** dependency as a `dependsOn` edge (with the correct `kinds`) in `modules/<MODULE>/module.json`, and any new **library/image** version in `modules/<MODULE>/SPECS/dependencies.md`. Run `scripts/dev/common/validate_modules.sh` — it validates the `module.json` schema, resolves the graph, and emits the `provides`-vs-reality and drift lints.
5. What was implemented still matches `SPECS/base-specs.md` and any referenced `ideable-framework-specs/` files. A mismatch found here that is a genuine spec gap goes through Step 4b, not a direct edit.

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
   `frontend/TESTS/playwright/lib/entity-graph.ts` — `parseEntityGraph(sql)` — given `database/SPECS/schema.sql` —
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
(`database/SPECS/schema.sql`). The template ships `tests/items-crud.spec.ts`
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
- The path of the implementation plan, and its current Status summary
- Any spec gap raised (Step 4b) and whether it was closed by a `Specs` pass yet
- Any open questions or deferred items that require human decision
