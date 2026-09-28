---
name: ideable-define-specs
description: Decide and write the SPECS target for one or more modules/sub-modules — the specifications step (step 1) of the development process, and the dev-cycle's `Specs` node
---
# General Guidelines
If the user asks to define specs without specifying a module, always work on all the enabled modules (see `modules/enabled.md`).
When defining specs for a module, cover all the sub-modules of the module, no partial coverage.

# Workflow: Define Specs

This workflow guides a coding agent through the **specifications step (step 1)** of the
development process: deciding, writing and updating `SPECS/` files **before** any source is
written or changed. It drives the dev-cycle's `Specs` node — the node `Implementing` (step 2,
`ideable-implement-specs`) codes against and loops back to when it meets a gap the spec does not
yet settle.

**`Specs` has direct spec-write authority.** Defining the target for a sub-set's things IS this
node's job, not a proposal to someone else's — unlike `ideable-spec-driven-edit`'s general
propose-and-ask rule for spec changes, which does not apply here (see that skill's § 4). A
genuine ambiguity only the maintainer can settle — a business rule nothing written down decides,
two specs that actually contradict each other, a scope call the plan never took — still goes to
`Asking human direction`: this authority is for **deciding the target**, not for **guessing** a
decision that belongs to a human.

## Prerequisites

Before starting, verify:
1. `modules/enabled.md` — identify which modules are enabled. Only work on enabled modules.
2. Each module's dependency declaration in `modules/<MODULE>/module.json` (`provides` / `dependsOn`, with `kinds`) — the machine-readable inter-module contract resolved providers-first by `scripts/dev/common/module_deps.py`; inspect the resolved graph with `scripts/runtime/status.sh --deps`. The human-readable `modules/<MODULE>/SPECS/dependencies.md` records pinned library versions (checked to exist by `scripts/dev/common/validate_modules.sh`). Canonical contract: `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md` §5.1.
3. `rules/general-guidelines.md` — re-read the mandatory project rules before writing any spec.

## Step 1 — Determine scope

Ask the user (or infer from context) which of the following is being worked on:
- A specific sub-module (e.g. `host_app/backend`)
- An entire module (e.g. `host_app`, all its sub-modules)
- All enabled modules

Process modules and sub-modules in **dependency (providers-first) order**, exactly as
`ideable-implement-specs` does (the order `scripts/dev/common/module_deps.py` produces).

## Step 2 — Read what already exists

For each sub-module in scope, read in order:
1. `modules/<MODULE>/SPECS/base-specs.md` — module-level general specs
2. Any framework-owned spec files referenced from `base-specs.md` under an `ideable-framework-specs/` folder (e.g. `auth-specs.md`, `module-integration-specs.md`, `shared-ui-specs.md`)
3. Sub-module-level `base-specs.md` if present
4. Sub-module-level framework-owned spec files referenced from the sub-module's `base-specs.md`
5. `general_bug_avoider.md` and `datamodel_related_bug_avoider.md` if present — a spec gap is
   often already named there as a known pitfall

Note explicit constraints, forbidden patterns, required interfaces and data models before
deciding anything.

## Step 3 — Audit existing SOURCES

Read the sub-module's `SOURCES/` folder (if it exists) to see what already stands, so a spec
decision is made against the real starting point rather than an assumed one — the same audit
`ideable-implement-specs` used to do at this point, still necessary here because the target has
to account for what exists.

## Step 4 — Create or resume the implementation plan

**On a fresh run** (this is the first thing driving the plan), create the **implementation
plan** — the human-readable status artifact this and the downstream skills keep current. Format,
status-symbol legend, naming, location and active-plan resolution are defined **once** in
`rules/implementation-plan.md`; read it and follow it exactly (do not restate it here).

1. Create the plan file in `implementation-plans/` using the naming convention in that rule
   (`<date> - <time> - <description> (<state>).md`, timestamp = now, state = `NotStarted`). Do
   **not** create the plan branch by hand — the `Branching` node does it. Once the plan file is
   complete (through step 3 below), make it the active plan and drive it:
   ```bash
   ./scripts/dev/common/dev-cycle.sh start <description>       # creates its `ACTIVE PLAN` link
   ./scripts/dev/common/dev-cycle.sh run --auto-advance 2      # Branching, then Specs
   ```
   `run` advances `NotStarted → Branching` (nothing to do), performs `Branching` (creates and
   checks out `plan/<description>`, starts sub-set 1) and leaves the plan at `Specs` — where this
   skill's own work continues.
2. Write **Purpose** (a few sentences on what this run sets out to do), **General design** (only
   the durable, cross-cutting design assumptions — a short "Nothing beyond the sub-sets' own
   scope" line when there are none), and the **Overall view** chapter (**Created at**/**Last
   updated** = now, **Current step** = `Not started (…)`, every sub-set row `—`, the canonical
   dev-cycle Mermaid graph highlighted on `NotStarted`).
3. Fill the **Sub-sets summary** with the things to implement, one row per
   thing, divided into sub-set sub-tables per `rules/implementation-plan.md` § *Sub-sets* (sized
   as large as one green test run can certify, not as small as a sentence can describe). The
   columns are the ones that rule §4 defines: `Specs | Impl | BE test | FE test | Cfg test | Fw test | Docs`. Start `Specs`, `Impl` and `Docs` at 🔲, and set each test column to 🔲 or ➖ depending on whether the thing has a part that kind of suite can exercise.
4. Write the **Status summary**, the **Detailed summary** (organized per sub-set, sub-task tables
   where a thing decomposes), and the **Repos updates summary table** (`Implementation` =
   `Not started`, `Tests` = `0 passed / 0 failed / 0 pending`, `Commit` = `Not committed`).

**On a resumed run** (`Implementing` looped back here with a spec gap), read the spec-gap record
it left (`<!-- dev-cycle:spec-gap -->` in the plan) instead of starting over — it names exactly
what was found missing.

Record every **decision this node took that the plan did not already contain** — including "the
spec now says X" whenever that was a genuine choice among options the existing specs left open —
as a row in the executing sub-set's own **Decisions table**, `It # | Node | Premises | Question |
Answer | Who | Consequences`, `Who` = `agent`, per `rules/implementation-plan.md` §
*Detailed summary*.

**This step performs the `Specs` node; it never advances the plan.**
`./scripts/dev/common/dev-cycle.sh run` is the only advance, and there is no `set`: one command writes the graph, `Current step`, the executing sub-set and its accrued time — highlight **your own** node and stop.

## Step 5 — Define or update the spec files

This is the node's actual deliverable. For every thing in scope for the executing sub-set:

1. **Decide the target.** Where the existing spec chain (Step 2) already settles it, there is
   nothing to do here — move on. Where it does not — an interface not yet written down, a data
   model not yet decided, a contract left implicit — **write it down**, directly, in the right
   spec file: framework-owned `ideable-framework-specs/` first when the gap is a framework
   contract, otherwise the module-specific spec. This is the one place in the whole cycle a spec
   is edited without first proposing the change and waiting for confirmation.
2. **Do not write source code here.** This step produces `SPECS/` changes only; `Implementing`
   reads the result and writes `SOURCES/` from it. A spec written to describe code that does not
   exist yet is normal and expected — that is what step 2 of the process is *for*.
3. **A decision only the maintainer can take is still not guessed.** A business rule nothing
   existing settles, two specs that genuinely contradict each other, a scope call the plan never
   made — record it as a decision row with NO answer (`record_decision(..., asked=True)`) and run
   the router: it parks the plan at `Asking human direction`, and the time spent waiting is accrued
   to the `Ask` column. Do not pick one and proceed, and do not put the question anywhere the
   router cannot see it — a question asked in place is charged to the node that asked it, which is
   why a plan can read `Ask —` after a dozen of them. This is the same decision-authority rule as
   everywhere else in the project; what changed is that *routine* spec-definition work no longer
   routes through it.
4. Keep the plan's per-thing paragraphs and any durable design note (§ *Detailed summary* —
   `#### Design note`) current as you decide each target.
5. **Drive the `Specs` cell for every thing you write a target for**: 🔲→🔄 while writing it, and
   🔄→✅ once it is written. The node's deliverable IS the written target — the later steps of the
   iteration (`Implementing`, `Testing`, `Documenting`) implement, prove and describe it, and
   `Documenting` does not touch this column: a written-and-tested spec is documentation to align,
   not a target to re-verify.

## Step 6 — Report

Summarise what was decided, listing:
- Spec files created or changed, and for each, what was decided and why
- The path of the implementation plan (created or resumed), and its current Status summary
- Any open questions or deferred items that require a human decision
- Whether this run started fresh or resumed from an `Implementing`-raised spec gap, and (if
  resumed) which gap it closed
