---
name: ideable-bugfixing-and-changes
description: Use whenever a change or bugfix is needed in the Ideable project's sources or configuration. Entry point for both routes — a fast-lane change with no implementation plan, and the dev-cycle's Fixing node. Enforces a consistent, spec-driven process — check bug-avoiders first, implement safely on the codebase (never on running containers/deployment/DIST), no fallbacks or hardcoding, propose spec changes rather than editing specs unasked, and record fixes back into the specs/bug-avoiders.
category: bug-fixing
color: blue
displayName: Bug Fixing Expert
---

Use this skill for **any change or bugfix** in the Ideable project — a code fix, a configuration/env change, or resolving a reported bug. It keeps the spec-driven approach intact across iterations.

It serves **two routes**, and the maintainer chooses which:

- **Fast lane** — a simple change, no implementation plan, no PR. Tests and doc alignment still happen when they are needed.
- **Plan route** — the change belongs to an implementation plan; this skill is the dev-cycle's `Fixing` node and keeps the plan current.

## The Ideable project (context)

- Specification- and test-driven; divided into **modules and sub-modules**, each with its own `SPECS/` and `TESTS/`.
- **Framework-owned contracts** live in the `ideable-framework-specs/` folders under `SPECS/`, `backend/SPECS/`, `database/SPECS/`, and `frontend/SPECS/` — shared across host_app, module_template, and every remote; never edited in a remote project.
- **Module-specific contracts** are the remaining files under a module/sub-module `SPECS/` folder.
- Each relevant `SPECS/` folder may contain:
  - (mandatory) `base-specs.md` — the base specification for that scope;
  - (optional) `general_bug_avoider.md` — known bugs + how to avoid/fix them;
  - (optional) `<ASPECT>_bug_avoider.md` — bug-avoider for a specific aspect (e.g. `database_bug_avoider.md`, `ui_bug_avoider.md`, `api_bug_avoider.md`).

## First — plan or fast lane? The maintainer decides

**Assess and recommend. Do not decide.** `rules/general-guidelines.md`: decision authority belongs
to the human developer.

A plan is warranted by the **complexity of the change logic** — logic that needs a multi-step
approach and a planned test phase. It is *not* warranted by the number of files: a change deleting
1835 regenerable files can be one line of thought, and a twelve-line change to an authorization
check can need a plan.

State your recommendation with its reason, then **stop and ask**:

> Recommendation: fast lane — one predicate replaced in one check, single-step logic, covered by the
> existing suite. Plan instead?

Then honour the answer:

- **Fast lane** → continue below. **Create no plan.** Work on a short-lived branch.
- **Plan route** → hand off to the dev-cycle (`rules/implementation-plan.md`); a plan owns its
  `plan/<description>` branch. Return here when the router reaches `Fixing`.

Never enter either route on your own reading, and never create a plan the maintainer did not ask
for.

## Making the change — follow the `ideable-spec-driven-edit` discipline

This skill is the **entry point** for a change/bugfix (it establishes context, and keeps the
implementation plan current when one is active). The actual edit MUST follow the atomic **`ideable-spec-driven-edit`**
discipline — the single rulebook shared with `ideable-implement-specs` and
`ideable-test-and-fix`, so a fix here obeys the identical rails. Read that skill and honour it:

1. **Look first** — check the affected sub-module's `general_bug_avoider.md`, then any
   `<ASPECT>_bug_avoider.md`, then the `base-specs.md` chain, before diagnosing from scratch.
2. **Edit only on the codebase** (SOURCES/config), never running containers / `deployment_root`
   / `DIST/`; the change takes effect only after the next build/restart (e.g. `redeploy.sh`).
3. **No fallbacks, no hardcoding, no silent schema/spec deviation** — implement only the
   requested change; if a precondition is unmet, ask the user to meet it first.
4. **Specs are propose-don't-edit** — never change a spec without confirmation; stop-and-ask on
   ambiguity.
5. **Record the fix back** into the appropriate bug-avoider/spec (framework-owned
   `ideable-framework-specs/` first when it is a framework contract).

## Finishing a fast-lane change — tests and docs, each only if needed

Both are **measured, not guessed**, and doing them is the default. Skipping either is a claim, and a
claim needs the maintainer's assent.

**Does it need tests run?** Read the diff: anything outside `rules/`, `SPECS/` and loose `*.md`
changed behaviour. (Largely moot in practice — `.githooks/pre-push` refuses a push without a green
recorded run covering the pushed tree, so a fast-lane change reaches `main` only through one.)

- Needed → invoke **`ideable-test-and-fix`**. With no plan its plan bookkeeping self-skips.

**Does it need doc alignment?** For each path and identifier the diff touches, does any governing
document under `rules/` or `SPECS/` name it?

- Needed → invoke **`ideable-align-docs`**. With no plan its Step 5 self-skips, and its Step 6 docs
  gate still runs — that gate is the fast lane's one machine check on documentation.

**A skip is stated with its evidence and confirmed, never assumed:**

> No doc alignment: the diff touches only `scripts/TESTS/`, and no file under `rules/` or `SPECS/`
> names it. Confirm?

Either may legitimately be "no" — a test-only fix aligns no docs; a cosmetic spec correction needs
no new test. What may not happen is a silent skip. `ideable-align-docs` already holds the standard
this follows: *"`➖` is a claim like any other and must be true."*

**Landing it.** A fast-lane change needs no pull request (`rules/version-control.md` § *Git
Workflow*): commit on the short-lived branch and push to `main`. The two gates — the local pre-push
run and `gate.yml` — are the only review it gets, which is why neither is ever bypassed for it.

## Inside the dev-cycle — track the change in the implementation plan

**This section applies on the plan route only** (you were invoked at the `Fixing` node, or a plan is
active). On the fast lane there is no plan and nothing here applies — and **no plan is created**;
that is the maintainer's call, made at the gate above.

Keep the change visible in the **implementation plan** (format/legend/naming defined once in
`rules/implementation-plan.md`):

- Resolve the active plan (most-recently-modified `*.md` in `implementation-plans/`).
- If one exists, add a row per change/bugfix to the Main implementation summary table (or
  update the matching row) and drive its `Impl` cell (⬜→🔄→✅; 🛠️ while re-fixing after a
  failed test; ⛔ if it turns out not implementable). Refresh the Status summary.
- If **no** plan exists, the maintainer chose the fast lane: skip this section entirely. Do not
  create a plan. (This skill and `ideable-implement-specs` remain the only skills permitted to
  create one — on the maintainer's explicit instruction, never on their silence.)
- Set the Overall-view **Current step** to `Fixing (ideable-bugfixing-and-changes)`, move the
  graph highlight to the `Fixing` node (rewrite the two `class` lines), and refresh **Last
  updated**.
