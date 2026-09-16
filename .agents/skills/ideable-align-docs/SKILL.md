---
name: ideable-align-docs
description: Bring the specs and docs governing a change into line with what is now true — present tense only, no stale references. Drives the `Documenting` node of the dev-cycle, between a green `Testing` and `Committing`.
category: development
displayName: Align docs
---

# Workflow: Documenting — the specs and docs say what is, not what was

This skill drives the **`Documenting`** node of the dev-cycle (`rules/implementation-plan.md`
§ *Overall view*). It runs **after** a sub-set's tests are green and **before**
`ideable-commit-changes`, so the documentation changes are committed together with the code they
describe.

**Why it is a step and not a habit.** The plan that made the dev tools container the only supported
toolchain was green, reviewed and delivered — and it left `rules/version-control.md` asserting the
container was *opt-in*, the opposite of what its own new test enforced. No test caught it, because no
test read that sentence, and no step of the cycle asked. A reader following the mandatory rule would
have reached the conclusion the suite rejects.

## Step 1 — Determine the change surface

Work on **this sub-set's own diff**, not the whole repository:

```bash
git diff --name-only main...HEAD          # everything the plan has changed so far
git diff --name-only HEAD~<n>..HEAD       # narrow to this sub-set's commits when they exist
```

A step that re-reads every spec every time is a step that gets skipped. If the diff is empty, say so
and stop — there is nothing to align, and the advance is the router's either way (below).

## Step 2 — Map the changed paths to the documents that govern them

| Changed path | Documents that must be checked |
|---|---|
| `modules/<M>/<S>/**` | `modules/<M>/SPECS/**`, `modules/<M>/<S>/SPECS/**`, and that sub-module's bug-avoiders |
| `reusable.ui/**` | `reusable.ui/README.md`, `shared-ui-specs.md`, `framework-css-classes-reference.md` |
| `scripts/**`, `.githooks/**`, `framework.env` | `rules/**`, `IDEABLE-README.md`, `AGENTS.md`, and every `.agents/skills/**` that invokes them |
| `.agents/skills/**` | `AGENTS.md`, `rules/authoring-guidelines.md`, the generated `.devin/workflows/` |
| anything with a pinned version | `modules/<M>/SPECS/dependencies.md` |
| a file added or removed | `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md` |

Then **grep for the thing itself**, because the table catches locations and not mentions: every
identifier the change renamed or removed (env var, flag, script, function, path, endpoint) is
searched for across `rules/`, `*/SPECS/`, `.agents/`, and the READMEs.

```bash
grep -rn '<the removed identifier>' --include='*.md' rules modules reusable.ui .agents *.md
```

## Step 3 — The four guarantees

1. **Present-tense truth.** Every affected document describes what is true **now**. No sentence
   describes a superseded state: no *"used to"*, *"formerly"*, *"previously named"*, *"no longer
   exists"*, *"this section used to say the opposite"*. History belongs to git and to the plan
   artifact; a spec that narrates it charges every future reader for the privilege.
   - The exception, and it is narrow: a **rationale** may state what was tried and why it failed,
     when that reasoning is the content (a bug-avoider's *why*, a design note's rejected
     alternative). The test for the difference is whether a reader could mistake the sentence for a
     description of current behaviour. *"`datamodel.sql` is retired, and this section used to say
     the opposite"* fails that test; *"a shared list gives parity by convention; one digest gives it
     by construction"* passes it.
2. **No stale references.** Nothing removed or renamed is still named as if it were live.
3. **New reality is described.** Anything the change introduced that a reader must know about is in
   the document that governs it — not only in the plan. A plan is a status artifact; a spec is what
   the next person reads.
4. **Completeness is recorded.** Every thing in the sub-set gets its `Docs` cell set (Step 5).

## Step 4 — Reconcile, do not legislate

`ideable-spec-driven-edit` says *propose spec changes, never make them unasked*. `Documenting` is
the single node where editing a spec **is** the deliverable, and that is the edge of that rule, not
an exception to it:

- **Reconciling** — the spec says X, the approved and tested implementation now does Y, so the spec
  is updated to say Y. This is the job and needs no permission: the decision was taken when the
  change was approved and implemented.
- **Legislating** — aligning would require deciding something the plan never decided, or the code
  **contradicts a contract the spec exists to impose**. That is not drift, it is a conflict. Move
  the plan to **`Asking human direction`**, state the question, and stop. Do not pick an answer.
- **Discovering work** — aligning would require code that is not written, or a maintainer's answer
  added a row to the executing sub-set. That is neither drift nor a conflict: the thing's `Impl` is
  still 🔲/🔄, so there is nothing for a document to describe. Leave its `Docs` cell 🔲, name the
  rows in the report, and the docs gate routes the plan back to **`Implementing`**. Do not write
  prose about code that does not exist, and do not write the code here — `Documenting` writes
  documents. When the row came from an **answer**, the router has already taken that route one step
  earlier, at `Asking human direction` — the first exit its panel names in the canonical graph,
  named where the cause is, since `Documenting` never invents implementation work. The gate is the
  **safety net** for a
  sub-set that grew with no question behind it.

**In a remote module project, framework-owned files stay untouchable** regardless of this node.
`AGENTS.md` § *Framework-owned files* applies in full: report the needed change with its **Reason**
and **Change**, and direct the user to the Ideable maintainer. Never edit them locally.

## Step 5 — Record it in the plan

Resolve the active plan (`rules/implementation-plan.md` § *Active plan resolution* — the plan named
by an `ACTIVE PLAN - <description>.md` link in `implementation-plans/`, its current file being the
newest one bearing that description; an unlinked or parked plan is not active). If one exists:

- Set each thing's **`Docs`** cell: 🔄 while working, ✅ when its documents are aligned, ➖ when the
  thing changes nothing any spec or doc describes. **`➖` is a claim like any other and must be
  true** — a thing that changed a contract, a flag, a path or a command cannot be ➖.
- Set the Overall-view **Current step** to `Documenting (ideable-align-docs)`, move the graph
  highlight to the `Documenting` node (rewrite the two `class` lines), and refresh **Last updated**.
- Refresh the **Status summary** so it stays truthful.
- **Record every decision this node took that the plan had not already decided** — a question put to
  the maintainer (answered or still open), a document reconciled one way where two were defensible,
  an alignment deliberately left to a later sub-set — as a row in the plan's **`Decisions and
  answers`** chapter, its one decisions record, which sits before chapter 1
  (`rules/implementation-plan.md` § *Decisions and answers*: `When | Node | Sub-set | Question |
  Decision | Who | Why`, with `Node` = `Documenting` and `Who` = `agent`). Mandatory, and the reason is this node's own position
  in the chain: what this node knows is not something the next one may rely on. The router resumes
  the session across the nodes of one sub-set, so `Committing` is often this same agent — but a
  session can be gone, and the sub-set after this one starts a fresh agent on purpose, whose whole
  context is that file.

If no plan exists, skip the plan update silently and note it in the report — do not create one from
this skill.

**This step performs the `Documenting` node; it never advances the plan.**
`./scripts/dev/common/dev-cycle.sh run` is the only advance, and there is no `set`: one command
writes the next node together with the executing sub-set's label, the sub-set advance, the `Commit`
cells and the scope gate, so a node moved by anything else leaves the plan's state somewhere the
router does not look. That holds for every route off this node — `Committing` on a green gate,
`Asking human direction` when a question is owed, `Implementing` when the sub-set turns out to
hold unwritten work. Highlight **your own** node, say which route the plan owes, and stop there.

## Step 6 — Run the docs gate

Doc edits made after `Testing` would otherwise reach a commit with no test having read them, and
several tests do read them. Finish by running that subset and advance only when it is green, fixing
in place until it is:

```bash
IDEABLE_UNRECORDED_RUN=1 scripts/dev/common/tool.sh pytest -q \
  scripts/TESTS/test_docs_describe_the_present.py \
  scripts/TESTS/test_specs_name_only_paths_that_exist.py \
  scripts/TESTS/test_agent_skill_topology.py \
  scripts/TESTS/test_shared_framework_specs_is_complete.py \
  scripts/TESTS/test_process_rules_are_checked.py
```

The `IDEABLE_UNRECORDED_RUN=1` prefix is **required**, not a shortcut: `tool.sh pytest` refuses a
subset run that is not the recorded suite, and the router sets the same variable for the same reason
(`run_docs_gate`). It also fixes how the result may be read — this gate is bounded to the documents
this step just wrote, nothing is recorded under `TEST_REPORTS/`, and it cannot gate a push. The
recorded verdict stays the `Testing` node's.

This is **not** a second `Testing` node: it is the same fix-in-place loop as Step 3, bounded to the
documents this step just wrote. `scripts/dev/common/dev-cycle.sh` runs the same subset when it drives the node.

**In a remote module project there is nothing here to run.** `scripts/TESTS/` is maintainer-only, so
those files are absent and the router reports `docs gate DID NOT RUN` — never `passed`, because a
check that cannot fail must not report success. In that project the guarantees of Step 3 rest
entirely on your judgement and on the `Docs` column being filled honestly, so fill it deliberately:
`➖` there is a claim nobody else is checking.

## Step 7 — Report

- The documents changed, and for each, what was stale.
- Anything moved to `Asking human direction`, with the question that needs answering.
- Any row that sent the sub-set back to `Implementing`, and what is still unwritten in it.
- In a remote module project: the framework-owned changes that were reported rather than made.
