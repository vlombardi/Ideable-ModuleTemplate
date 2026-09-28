# Implementation Plan — format & lifecycle (canonical)

> Single source of truth for the **implementation plan** artifact that the workflow skills
> create and keep current: `ideable-define-specs`, `ideable-implement-specs`,
> `ideable-test-and-fix`, `ideable-align-docs`, `ideable-build-and-deploy`,
> `ideable-bugfixing-and-changes`, `ideable-commit-changes`.
> Those skills **reference** this file — they must not restate the format or the legend.
> (This is a project-wide workflow convention → a **rule**, per `rules/authoring-guidelines.md`.)

An implementation plan is a **human-readable status artifact**, not a source of truth for
correctness. Correctness is always established by tests (see `rules/testing-guidelines.md`);
the plan only communicates *where the work currently stands* to a human reader at a glance.

## Location & naming

- Plans live in **`implementation-plans/`** at the repo root (a working artifact, like
  `TEST_REPORTS/` and `kanban/`; not force-synced, not git-ignored by convention).
- One file per implementation run. Filename:

  ```
  <date> - <time> - <description> (<state>).md
  ```

  - `<date>` is `YYYY-MM-DD` and `<time>` is `HH-MM-SS` (colon-free, same digits as
    `TEST_REPORTS/`), separated by ` - ` — the timestamp of the **latest execution**, not of the
    plan's creation: e.g. `2026-08-10 - 16-42-05 - add-audit-column-filtering (BuildDeploy).md`
    is the plan as of the 16:42:05 step. At creation that is the creation time; from then on
    `scripts/dev/common/dev-cycle.sh` re-stamps it at every transition. The creation timestamp is **not**
    lost — it stays in the Overall view's `Created at` line (with `Last updated` matching the
    name), which is exactly why the name is free to carry the more useful "when did this last
    move" instead.
  - `<state>` is the plan's **current dev-cycle node**, so the filename always shows where the
    run stands. `scripts/dev/common/dev-cycle.sh` maintains both parts: on every transition it **renames**
    the plan file onto the new timestamp and state. A plan is created with `(NotStarted)`; one
    created without the suffix picks one up at the first transition.
    It is the node's **id**, which for one node is shorter than the name a person reads: a plan
    waiting on the maintainer is `… (Asking).md`, and `Current step` spells the same node out as
    `Asking human direction`.
  - **`(Paused)` is the one state that is not a node**, and the one case where the filename and
    the graph's highlight disagree on purpose. `Paused` says nobody is working the plan; *where*
    the work is stays in the highlight, which `pause` leaves untouched because it is the only
    record `resume` has to return to (§ *Git integration* below). Everywhere else the two agree,
    and `scripts/TESTS/test_plan_status_is_true.py` checks that they do — for a plan being driven,
    which is why its fixture skips a paused one.
  - `<description>` is chosen as follows:
    - a **short description of what to implement**, when the whole scope is clearly
      summarizable in a few words (e.g. `add-audit-column-filtering`);
    - otherwise, when only the **main thing** is summarizable but there is more,
      `<main-thing>-and-other` (e.g. `new-items-page-and-other`);
    - otherwise `various`.
  - Keep `<description>` filesystem-safe: lowercase, words joined by `-`, no `/` or `:`.
- **The active plan has a stable name, and that name is the register.** While a plan is in flight
  the router maintains `implementation-plans/ACTIVE PLAN - <description>.md`, a **symlink** to
  whichever file is current, repointed at every transition. Everything else about a plan's filename
  moves — the timestamp is re-stamped at each execution and the state is part of the name — which is
  deliberate and makes the plan impossible to cite. This is the one name that holds for the life of
  the run, so a skill, a rule, an editor tab or a shell alias can refer to it — and it is also what
  says which plan is being worked at all (§ *Active plan resolution*).
  - **`scripts/dev/common/dev-cycle.sh start <description>` creates it**, and creating it is what
    makes that plan the active one. `start` changes nothing else: no rename, no highlight move, no
    branch. It refuses a plan that is not at `NotStarted`, a parked plan (`resume` is that plan's
    verb), and a plan named while another is already in flight; a bare `start` lists the candidates
    and stops rather than picking the only one, because which plan is the work in hand is a
    decision. A plan past `NotStarted` whose link was genuinely lost is refused too, with the
    `ln -sfn` to recreate it printed — deliberate and manual, because guessing which file of a
    mid-flight plan is current is the guess this mechanism removes.
  - It is keyed on the **description**, the only part of a plan's name that does not change. The
    link's target is stored **relative**, so it survives the repository being checked out elsewhere.
  - **Resolution reads the description the link names, not the link's target.** An agent performing
    a node renames the plan itself — the state lives in the name — and does not repoint the link, so
    reading the target would hand back a file that no longer exists. Reading the description makes a
    broken link as good as an intact one; the target is for the human reader, which is why
    every transition still repoints it.
  - **Reaching `Merged` or `Paused` removes it.** Its absence is the signal that no plan is in
    flight; a link that survived delivery — or a pause — would claim one forever. The two states
    differ only in what happens next: a delivered plan is finished, a paused one is picked up
    again by `resume`, which restores the link. The real plan file — or every file, under
    `--keep-history` — is never touched by any of this.
  - It is **not** a plan. `plan_files()` — which selects among one plan's files, and is what every
    resolution goes through — excludes symlinks explicitly, because resolving the alias would make
    the router read and rewrite a plan through it and rename the target out from under the link on
    the first transition.
  - **Anything that scans `implementation-plans/` excludes it the same way, and excludes it before
    touching the filesystem** — `is_symlink()` (which is an `lstat`) filters the glob, and only the
    survivors are `stat`ed, read or sorted. Inside the dev tools container the bind mount
    answers `lstat` on that link and returns EINVAL for `stat`, so a scan that sorts or reads first
    raises `OSError` before it has selected anything: no verdict at all, wearing the shape of one.
    **The trigger is the repointing**, which is why it bites this link and no other: Docker
    Desktop's bind mount keeps serving the size it cached, and every transition points the link at a
    target of a different length, so from then on the length and the target disagree and `readlink`
    — which `stat` and git both go through — fails. The container reads symlinks perfectly well,
    and `lstat` still answering is the evidence that the path is one.
- **History mode — and the two modes mean two different things, not one thing in two sizes.**
  By default a run keeps **one** plan file, renamed onto the execution timestamp and current state
  at each transition (the previous name is removed). Running `scripts/dev/common/dev-cycle.sh` with
  `--keep-history` instead **keeps every transition's file** — same naming, so the files sort
  chronologically (a same-second collision gets a ` (<state> 2)` suffix). In both modes the plan is
  named by its one `ACTIVE PLAN` link and its **current file** is the most-recent of the files
  bearing that description — so a plan's history trail is one plan, however long it grows.
  - **With `--keep-history`, each file describes THE STEP IT BELONGS TO.** The file named
    `… (Testing).md` is the plan as the `Testing` node left it, and the whole execution can be
    followed file by file: what each node found, what it decided, what it handed on. The trail is
    the artifact; no single file has to carry it.
  - **Without it, the one file is the plan AS IT STANDS** — and that is the whole of its job:
    what is done, what remains, the decisions taken by agent and by maintainer, and **every memory
    a later node needs to execute correctly**. It is not a log of the run. A node that *appends* its
    account to the chapter the previous node wrote is building the `--keep-history` trail inside a
    file that was chosen for not being one, and the chapter stops answering the question it is
    titled with. See § *Status summary* and § *Detailed summary*, which each say what they hold and
    that a node **rewrites** them.
  - **Why the default is the one that must carry everything.** **Nothing may be assumed to pass
    between the agents that perform successive nodes.** Within one sub-set the router resumes the
    agent that performed the last node, so the same mind usually continues — but a resumed session
    is a convenience, never a guarantee: it is remembered on one machine, a session that cannot be
    resumed starts a fresh one, the router's session setting can be narrowed to a single node
    (`scripts/dev/common/dev-cycle.sh --help`), and **a new sub-set starts a fresh agent on
    purpose** — that boundary is where anything the previous agent believed and never wrote down
    gets caught. A node that finds no session begins with this file and nothing else. So the test
    of the default mode is not "can the run be reconstructed" but "can the next node act correctly
    having read only this" — and anything needed for that belongs in the plan whatever else is
    trimmed.

## Emitting a plan's skeleton (`dev-cycle.sh new`)

A plan's structural parts — the Mermaid graph, the sub-sets timing table, the Legend, the chapter
headings, one `#### Decisions` block per sub-set, the Repos table's header — are the router's own
knowledge before any plan exists to hold them: `_write_plan` already rewrites the graph and
`Current step` at every transition, `ensure_timing_columns` already knows the timing-column order,
and `_decisions_markers`/`_decisions_block` already know the shape of a sub-set's decisions table.
Before this command existed, an agent transcribed all of that by hand at `NotStarted`, and the
transcription is where a plan actually broke: a hand-copied graph left with two `class … current;`
lines, or one naming a node the picture had already retired, is what made `current_node` read a
fresh plan as `Merged` and `run` refuses it.
None of that is new knowledge to write down twice — it is emitted once, by the same code that
maintains it at every later transition, and `current_node`/`run` read whatever it produced exactly
as they read a plan a transition rewrote.

`scripts/dev/common/dev-cycle.sh new <description> --subset "<title>" [--subset "<title>" …]`
writes a fresh plan file at `NotStarted`, and nothing else: it does not create the `ACTIVE PLAN`
link (`start` does, and remains a separate act, § *Active plan resolution*) and does not touch git.
It DOES move the card it finds into `kanban/doing/`, and reports what it found — § *The kanban card
moves with the plan* below is where that behaviour and its limits are stated. `<description>` is normalized to a slug exactly as `start`
already does (§ *Location & naming*); at least one `--subset` is required — a plan always has at
least one sub-set (§ *Sub-sets*) — and each one becomes that sub-set's `Description` cell, in the
order given, which is the execution order (§ *Sub-sets*: "order follows dependency"). Refused,
before anything is written: no `--subset` given; a plan file already on disk (any state, delivered
or not) whose slug matches — the same collision `start` already guards against, checked one step
earlier.

**What is emitted is structural; what is left is content**, and the boundary is the one
§ *Sub-sets summary* already draws between the `Specs` node's own claim and the target it describes:

- the H1 title, `## 1. Purpose`, `## 2. General design` and `## 5. Status summary` each carry one
literal placeholder line — `_Not yet written — filled by \`ideable-define-specs\`._` — rather than
invented prose a reader could mistake for a decision nobody made. The H1 is seeded from the slug
(hyphens to spaces, sentence-cased) as a mechanical starting point, not a title, and the agent
filling the plan is expected to replace it with an actual sentence, the same way it already writes
Purpose and General design;
- `## 3. Overall view` is real, not a placeholder: `Created at` and `Last updated` are stamped to
the same instant (nothing has happened yet, so there is only one moment to record — § *Overall
view*), the sub-sets timing table carries one row per `--subset`, every cell `—`/`0` (§ *Overall
view* → `Sub-sets timing`: "every row is `—`" before `Branching`), and the graph and `Current
step` are produced by feeding a template carrying the canonical graph (§ *Overall view*, copied
verbatim, with any legal `class … idle;` / `class … current;` pair — the values are about to be
overwritten) through the exact same `_apply_highlight(text, "NotStarted")` every later transition
calls, not a `NotStarted`-specific rendering invented for this command. Its `Current step`
therefore reads whatever `DRIVER["NotStarted"]` already says there, exactly as every other node's
does — reusing the one function that renders it is what keeps this command from becoming a second
place that can drift from the router's own rendering;
- `## 4. Sub-sets summary` gets one `### Sub-set <n> — <title>` heading per `--subset`, each with its
table's header and separator and **no rows** — the things to implement are the agent's to decide,
and they are not bundled with the parts that never needed deciding —
followed by the Legend, copied verbatim (§ *Sub-sets summary*);
- `## 6. Detailed summary` gets one `### Sub-set <n> — <title>` section per `--subset`, each holding
only its `#### Decisions` block, empty, between `<!-- dev-cycle:decisions:<n> -->` markers — built
the same way `_ensure_subset_section`/`_decisions_block` already build one on demand, reused rather
than reimplemented;
- `## 7. Repos updates summary table` gets its header and separator, no rows — which repos or
modules a plan touches is exactly as much content as what it implements.

**A plan emitted this way is not yet a valid target for `start`.** § *Sub-sets summary*'s rows and
§ *Detailed summary*'s per-thing budget both expect at least one thing, and none exist yet. It is a
target for the agent that just emitted it, in the same breath, before `start` is ever run — filling
in the things, Purpose, General design, Status summary, the Repos row(s) and any per-thing paragraph
the way `ideable-define-specs` § *Create or resume the implementation plan* already does — which is
the second half of this command's acceptance: a plan filled that way, and only then started, is
accepted by `run` on the first try, because the parts a hand transcription gets wrong are never
hand-written at all.

Checked by `scripts/TESTS/test_a_plans_skeleton_is_emitted.py`: the freshly emitted file round-trips
through `current_node` (reads `NotStarted`), `subsets` (one row per `--subset`, every state `—`) and
`decision_rows` (one empty table per sub-set, keyed `1..n`); and a filled-in copy — the things and
narrative added the way `ideable-define-specs`'s own step already writes them — drives cleanly
through `do_run`'s `NotStarted → Branching → Specs` in a scratch repository, the same shape
`test_a_plan_starts_unbranched.py` already exercises for the two nodes either side of it.

## What a decision row's cells may say

Two cells are the router's to write and it must not assert what it cannot know: a guard's name is
not a node, a decider the router cannot know is not a `Who`, and a deterministic route is not a
decision.

- **`Node` is a node, and the node that ASKED.** A row from an `Asking human direction` block carries
  the node the plan was standing on when the question was put — the plan's own `resume_at` — marked
  `⛔`. Not the name of the guard, check or skill that raised it: those are *why* it was asked, and
  the `Why` cell is where that belongs.
- **`Who` is who DECIDED, and `—` until somebody has.** `maintainer`, `agent` and `router` are the
  three answers; a row recorded BEFORE its answer is not a decision, so its `Who` is `—`, and whoever
  answers it — the maintainer at the terminal, or the agent writing the answer into the plan — fills
  it. A `router` row is for a decision the router itself took and the plan had not settled; a
  deterministic route is not one, and belongs in the run's output and the timing table.
- **A skip is reported, not recorded.** `BuildDeploy` skipping for want of a build input is already
  visible twice — in the run's output and in the timing table's `B&D` cell — and a decisions table
  defined as *"one row wherever that sub-set deferred a choice"* is not where a route belongs.

## The kanban card moves with the plan (mandatory)

A card in `kanban/` and the plan that implements it are the same piece of work seen from two sides:
the card says what should happen, the plan tracks it happening. They are linked by the
`<description>` slug — `kanban/<column>/<description>.md` alongside
`… - <description> (<state>).md` — so the pairing is visible in the filename and needs no index.

**When an implementation plan is created for a card, move that card `kanban/todo/` →
`kanban/doing/` in the same change.** Creating the plan *is* the start of the work; a card left in
`todo/` after that states the opposite of what is true, and the next person picking up work reads
the column, not the plan directory.

`dev-cycle.sh new` is the command that does it: it looks the description up as a slug across
`kanban/*/`, moves what it finds into `doing/`, and **reports** what it found. It never refuses.

- **A plan with no card is legal, and a spec change is the ordinary reason.** A plan implementing a
  change to a module's `SPECS/` has that spec as its authority, and forcing the change to be
  restated as a card would put the truth in two places. So `new` proceeds, and says what it saw:
  - **nothing pairs** — it says so, and says why a card may still be worth writing: a card that
    **REFERENCES** the spec change rather than copying it. The card is how the work appears on the
    board, while the spec stays the truth; a card that restated the spec would be a second copy, and
    a second copy drifts.
  - **something near-pairs** — a slug differing by a typo or a rename — it names the cards it could
    have meant. That is the failure this check exists for: a slug differing from its card's by one
    word pairs with nothing, so the pairing silently does not hold and the `deliver` guard below
    cannot fire — the card stays in `todo/`.
- **It does not ask.** Whether a card is written is not something the router may block a plan on: the
  plan is legal either way, and a question here would park it at `Asking human direction` and cost a
  decision to learn what the report already said.

The rest of the lifecycle already exists: at delivery the card moves to `kanban/done/`, which
`rules/version-control.md` § *Delivering a plan* records in the bookkeeping commit as
`Kanban: kanban/done/<card>.md`, one trailer per card.

**A plan declares every card it implements, and `deliver` moves them all.** One plan implementing
several cards is the ordinary case, not the exception — a plan is a sequence of sub-sets, and a
sub-set commonly came from a card filed when the defect was found. The slug links a plan to its
*own* card and says nothing about the others, so they are named in a `Kanban:` header, which takes
either form:

```markdown
Kanban: `kanban/doing/<card>.md`
```

```markdown
Kanban:
- `kanban/doing/<card>.md`
- `kanban/doing/<another-card>.md`
```

Three rules make that declaration trustworthy:

- **It is additive.** The card matching the plan's own slug is found whether or not it is declared,
  so a one-card plan declares nothing and a plan with no card at all declares nothing — the
  card-less case below stays free.
- **Only the header counts, never the plan body.** A plan names cards in prose for other reasons —
  deferred to their own card, raised as follow-ups — and those must not move. A body reference
  cannot be told from an *implemented* one by a parser, so it is not asked to.
- **A declared card must already be in `kanban/doing/`.** `deliver` refuses, before it changes
  anything, when one is still in `todo/` or when no column holds it. A card that never reached
  `doing/` was never recorded as in flight, and moving it straight to `done/` would erase that
  instead of reporting it.

**A paused plan gets a card of its own, in `kanban/paused/`, written by `pause` and removed by
`resume`.** It is a pointer, not a copy: the plan file, its `ACTIVE PLAN` link and every commit live
on `plan/<description>`, so on the delivery target — the branch a maintainer actually reads — a
parked plan otherwise leaves no trace at all, and `git branch --list 'plan/*'` is not a board. The
card names the branch that holds the plan, the node it resumes at, and the command that picks it up.
A card there with no matching `plan/*` branch means the branch was deleted under it.

Two things this rule does **not** say. A plan need not have a card — plenty of work starts from a
request rather than a card, and no card is invented for it. And a card need not have a plan — the
fast lane implements a card with no plan at all (`ideable-bugfixing-and-changes` § *First — plan or
fast lane?*), and moves it straight to `kanban/done/` when it lands.

Checked by `scripts/TESTS/test_kanban_card_follows_the_plan.py`, at both ends: a card in
`kanban/todo/` whose slug matches a plan in `implementation-plans/` fails, because the plan's
existence is the evidence that the card is no longer *to do*; and a card left in `kanban/doing/`
after its plan merged fails too, resolved through the declaration above rather than by slug, so a
multi-card delivery cannot strand the cards it did not name. Per § *Enforced, not aspirational* below, that is the artifact this
process rule leaves behind — the card's own location.

## Active plan resolution (used by every skill that *updates* a plan)

- The **active plan** is the plan named by an `ACTIVE PLAN - <description>.md` **symlink** in
  `implementation-plans/` (§ *The active plan has a stable name*). The link answers **which plan**;
  which **file** of that plan is current is the newest file bearing that description. A plan file
  with **no** link does not resolve at all, and that is the point: a plan in the directory is work
  somebody wrote down, and only a *started* plan is work in hand.
  - `scripts/dev/common/dev-cycle.sh start <description>` is what creates the link, so becoming the
    active plan is an **act** and not the consequence of holding the newest timestamp. With no link
    at all the router answers *"No active implementation plan"* and names the plans waiting to be
    started (or the parked ones, when that is what there is).
  - **One plan is one plan however many files it has.** Counting links rather than files is what
    lets § *History mode* keep its promise — every transition's file preserved — while the
    in-flight guard below keeps its own.
  - Two kinds of file are excluded from a plan's own files, and both *by kind*, before anything
    sorts: the `ACTIVE PLAN - <description>.md` symlink itself, and every file whose filename state
    is **`(Paused)`**.
  - Excluding a paused plan is the second of the two things that make a pause *hold* — `pause` also
    drops the link. It is what holds in the one place a parked plan's file **is** in the working
    tree: standing on that plan's own `plan/<description>` branch.
- **Two plans in flight is refused, not resolved.** A sort always produces a winner, and a winner
  is indistinguishable from an answer, so when more than one started plan is still being worked the
  router names them all and stops instead of letting the newest timestamp decide.
  - **In flight** means a plan has a link and its current file's state is one of the nodes
    **before `Done`** — `NotStarted` … `Committing`, plus `Asking human direction`, which is work
    waiting on a decision. `Merged` is delivered and `deliver` has already removed its link. `Done` is excluded
    even though the work it still owes is real — `deliver` runs there — and the consequence is
    admitted rather than hidden: two plans *both* sitting at `Done` are not reported, and the newest
    still wins.
  - A file whose name carries **no** state is not counted — it cannot be judged, and refusing to
    work because an unrelated note was dropped in the directory is the worse failure.
  - `run` and `status` refuse, both with a **non-zero exit code**: a command that answers cleanly
    while its answer is a coin toss is a lying signal. `start` refuses as well, which is the same
    refusal moved to the one moment a person is present to settle it. `pause` and `deliver` are
    deliberately **not** refused — they are how the situation is settled, and blocking them would
    leave no way out of it.
  - Checked by `scripts/TESTS/test_exactly_one_plan_is_active.py`.
- Only `ideable-define-specs` and `ideable-bugfixing-and-changes` may **create** a plan
  (define-specs at its dedicated step — the plan is created once, at `NotStarted`, before the
  `Specs` node it goes on to drive; bugfixing-and-changes when the maintainer answers its
  plan-or-fast-lane gate with *plan*). Whether a change needs a plan is the maintainer's decision,
  never a skill's — a skill recommends and asks. The other skills only **update** the active plan.
- If a skill that only updates a plan finds **no** plan in `implementation-plans/`, it skips
  the plan update silently (do not invent one) and notes this in its report.

## Enforced, not aspirational

`scripts/TESTS/test_plan_branch_has_a_plan.py` fails when a `plan/*` branch exists with no plan in
`implementation-plans/`, and `scripts/TESTS/test_process_rules_are_checked.py` fails when a plan or
kanban task marked **Done** still carries blank `____` acceptance values.

Both exist because a rule can be broken repeatedly while nothing objects. The rules that hold —
Dockerfile placement, no `build:` in compose, mount paths, `env_file` per compose kind — are exactly
the ones with tests. The difference is not importance; it is **checkability**. Rules about artifacts
live in the tree and are turned into tests. Rules about process leave nothing to check, and erode
silently.

So: a process rule here is expected to produce an artifact, and the artifact is expected to be
checked. If you add guidance to this file that cannot be checked, say so explicitly rather than
letting a reader assume it is enforced.

## Git integration (branch-per-plan)

The dev-cycle is **branch-per-plan** and **always on** (opt a single run out with the
`DEV_CYCLE_NO_GIT=1` environment variable, or when not inside a git repo):

- **A plan branch carries the plan's work, and nothing else.** Something discovered mid-plan that
  is not the plan's — a kanban card for a blocker, a fix that belongs on the target — belongs on the
  target, not on the branch. And **the tooling makes that true rather than asking you to remember
  it**: `pause` commits only what git already tracks, so a new file written while a plan was in
  flight stays in the working tree, survives the checkout, and is yours to commit where it belongs.
  Both halves are here because the rule alone would not hold: the moment you most need to write an
  unrelated card is the moment a plan blocked you, and "stash, switch, commit, switch back" is
  friction at exactly the wrong time — the shape § *Enforced, not aspirational* says erodes.
  A card written while a plan is blocked is swept onto the branch, vanishes at the checkout, and
  returns as a duplicate through the merge, in two columns at once.
- **Branch at `Branching`.** A plan owns a dedicated branch named `plan/<description>` — the
  plan's description slug. It is created by the `Branching` node: the plan is written at
  `NotStarted` on whatever branch the author is on and made active with
  `scripts/dev/common/dev-cycle.sh start <description>`, the first
  `scripts/dev/common/dev-cycle.sh run` advances it to `Branching`, and the next creates and checks
  out the branch from the current one and advances to `Implementing` (`run --auto-advance 2` does
  both). Nothing is committed before the
  branch exists — `commit_progress` commits on `plan/*` branches only. Past `Branching`,
  `scripts/dev/common/dev-cycle.sh` still **ensures** the branch at the start of every `run`, so a plan
  started by hand is on its branch however it was started.
- **Commit per execution.** Each time `scripts/dev/common/dev-cycle.sh run` finishes an execution it commits
  the whole working tree (`git add -A`) on the plan branch — a checkpoint of that step's progress
  (the plan plus any code produced). A nothing-to-commit run is skipped. Commits only ever land on
  the `plan/*` branch, never on `main`.
- **And once more *before* `Testing`.** The suite is the one step whose result is recorded against a
  commit, so the tree is committed first (`chore(dev-cycle): … → before Testing`). Otherwise the
  plan-file rename that advancing into `Testing` performs leaves the tree dirty, and
  `run_enabled_tests.sh` records the *previous* commit — a report naming code that is not what ran.
  Without it every summary reads `Working tree: dirty`, which leaves `.githooks/pre-push` unable to
  compare trees and refuses a plan delivery at `git push`.
- **The Repos `Commit` cells are folded after every checkpoint**, in a bookkeeping-only follow-up commit
  of its own touching `implementation-plans/` alone (see § *Repos updates summary table* for where
  the values come from). Two orderings are forced and both matter: the fold runs **after** the
  checkpoint, because the checkpoint is itself one of the commits the cell is a claim about; and it
  lands in a **second commit** rather than an amend, because the cell names the checkpoint's short
  sha and amending would replace a stale `Not committed` with a sha that no longer resolves. It
  also leaves the tree clean, which is what lets a test report certify a commit instead of a
  working tree.
- **A plan can be parked, and picked up where it left.**
  `scripts/dev/common/dev-cycle.sh pause [<description>]`
  checkpoints the tree on the plan's branch, renames the plan `(Paused)` **with the resume node
  still highlighted**, drops the `ACTIVE PLAN` name and checks the delivery target out, so the
  next plan branches from a clean base. `resume [<description>]` reverses it: the branch is
  checked out and the plan is renamed back onto the node it left. This is what a plan that stops
  being the thing to work on does — it is not `Asking human direction`, which is a decision the
  work is waiting on, and it is not `Done`.
  - **`pause` takes a description, symmetric with `resume`**, because it is the remedy the
    two-plans refusal names and a remedy that may act on the *other* plan is no remedy for an
    ambiguity. An unknown description is refused and the plans in flight are listed; parking some
    other plan because the named one does not exist is not a lesser version of the request.
  - **Bare `pause` is never refused**, unlike bare `resume`: it is the way out of the very
    ambiguity a refusal would restate (`scripts/TESTS/test_exactly_one_plan_is_active.py::test_pause_is_not_guarded`).
    With more than one plan in flight it parks the one the router resolves as active and **reports**
    which, printing the command that names the other.
  - **A paused plan is found on its branch, never in the working tree.** Its artifact lives on
    `plan/<description>` until `deliver` squashes it, and `pause` ends on the target — where git
    may not leave an `implementation-plans/` directory at all. So the router asks `for-each-ref`
    and `ls-tree`, the same correction `scripts/TESTS/test_plan_branch_has_a_plan.py` makes.
    Local branches only: nothing pushes a plan branch, so a paused plan is a local working state.
  - **Bare `resume` when exactly one plan is paused.** With more than one it lists them and
    stops — which plan becomes active is a decision, and picking the newest timestamp would be
    the script taking it. It also refuses on a dirty tree: resuming switches branches, and
    uncommitted work would follow the plan onto its branch and be committed into it by the next
    checkpoint, attributed to a plan that never did it.
  - Checked by `scripts/TESTS/test_a_plan_can_be_paused_and_resumed.py`.
- **One worker per CHECKOUT.** `run`, `pause`, `resume` and `deliver` hold one lock on the working
  tree for their whole duration — `.ideable-work/dev-cycle-locks/checkout.lock` — and a second one
  names the holder and exits `3` rather than starting. The key is the checkout, not the plan,
  because the hazard is the shared *tree*: two workers edit the same files and each then reads the
  other's diffs as unexplained change. Keyed per plan, two DIFFERENT plans each take their own lock
  and clobber that tree anyway, and a fast lane — which has no plan — falls outside the guard
  entirely. It is not a check on *who is calling*: an agent, a person, or the same caller
  running twice are all the second worker.
  **It is advisory, and that is a property of the problem, not of the implementation.** Acquisition
  is atomic (`O_EXCL`, the primitive git uses for `.git/index.lock`), but nothing can guard
  working-tree edits: `flock(2)` is advisory on Linux and macOS, mandatory locking is deprecated on
  one and absent on the other, and real isolation needs the separate worktrees
  one-active-checkout-per-project excludes. So an editor, or a tool that does not consult it, writes
  regardless. What the lock buys is atomic first-arrival, a named holder and a legible refusal.
  **Staleness is measured, never timed out.** A holder on another host is never stolen — and the identity that rule is applied to must be one the judging host can evaluate: a lock taken inside the toolbox records the real host (`IDEABLE_HOST_ID`) and the container, and its pid is asked about with `docker exec … kill -0`, because `os.kill` on a pid from another namespace reports a running router as dead. A refusal names the lock file only when the holder is **not** provably alive; when it is running, it says so and prints the command to stop it. A holder
  that is provably gone is judged by the branch rather than by the clock: with a `plan/*` or `fix/*`
  branch checked out and work in the tree it is *stalled*, and refused so that taking the lock
  cannot edit underneath it; with a clean tree it is *abandoned*, and taken over with that said. An
  expiry would need a guessed number, and guessing short releases a lock while work is still in
  flight — which is worse than not locking. `status` takes no lock — reading a plan is not working it.
- **The router advances on state, and answers the agent it runs.** At an LLM node the router
  first checks whether the node's acceptance cells are ✅ — if they are, it advances without
  spawning an agent, so a maintainer can drive a plan with any external agent (Devin, Cursor,
  Codex, or a human in an editor) that marks the cells itself. When the cells are not ✅ and
  `--auto-invoke` is set, the skill is performed through the Claude Agent SDK — for an agent
  caller exactly as for a human one — and `scripts/dev/common/agent_conversation.py` supplies
  its `can_use_tool`: a permission the project's allow-list does not settle, and any question
  only the maintainer can decide, are put to the person who ran the command.
  `DEV_CYCLE_AGENT_PERMISSIONS` chooses the policy — `ask` on a terminal, `deny` without one,
  so an unattended run never grants a permission nobody allowed. The policy governs
  **permissions only**: a question reaches the terminal under every policy, because a question
  is a decision the maintainer owes and a policy cannot take it for them. This is
  § *Decision Making Authority* made mechanical: the agent stops and asks, and the maintainer
  answers where they are standing.
- **One agent per sub-set, not per node, and each node is handed a brief.** The router resumes the
  agent's session across the LLM nodes of a single sub-set, so `Documenting` and `Committing` judge
  the diff `Implementing` wrote instead of rebuilding what it means — and **a new sub-set starts a
  fresh agent**, which is the boundary where reading only the plan catches whatever the previous
  agent believed and never wrote down. A session that cannot be resumed starts a fresh one and says
  so. Independently of that, every LLM node is given a **brief** — the node, the executing sub-set's
  rows, what is already decided, the maintainer's answers, the last recorded verdict, the
  sub-set's diff, and the instruction that **a decision only the maintainer can take is raised
  rather than taken quietly** — a node that picks one and proceeds leaves nothing to recover from,
  and one that cannot finish says so instead of reporting success on work it did not do — rather
  than being told to read a plan that has grown past a hundred kilobytes.
  The brief names the plan file and does not replace it: what it does not carry is in the plan, and
  it says so in its own last line. How long a session lives is a setting of the router's, described
  with the rest of them in `scripts/dev/common/dev-cycle.sh --help`.
- **An unanswered question blocks the plan; an unsettled permission does not.** A question only the
  maintainer can take is a **decision still owed**, so when one goes unanswered — the person chose
  `I'll answer later`, the countdown ran out, there was no terminal to put it to, or the read failed
  — `run` moves the plan to `Asking human direction`
  with the question, its options and the node to resume at, and stops before advancing. Advancing
  is precisely what must not happen: the next node may well be performed by a fresh agent reading
  this plan, which would meet the same decision with no more means of taking it. A refused *permission* is a
  thing the run could not do, which the agent reports; blocking a plan on every unsettled `Bash`
  would make the state mean nothing.
  - **The question waits for the person first, and is only then handed back.** The prompt rings the
    terminal's bell, offers `I'll answer later` beside the real answers, and counts down
    (`DEV_CYCLE_ASK_TIMEOUT`, whose default and `0`-waits-forever setting are in `dev-cycle.sh
    --help`) for a first keystroke, which cancels the countdown for good — someone who is there is
    never cut off mid-answer, and someone who is not is not waited on forever. A run with no
    terminal blocks at the first question at once rather than reading a stdin nobody is holding.
  - **The record lives in the plan**, delimited by HTML comments, because the agent that resumes
    may hold none of what the agent that asked knew: the router reuses the blocked node's session
    when it is still alive and starts a fresh one when it is not, and for a fresh one the
    repository and the plan are the whole context. Both are auditable, which a transcript is not.
    It is placed above the narrative — a reader who opens a blocked plan
    must not scroll past six sections to find what is being asked of them.
  - **Two ways to answer, and either resumes the plan.** The next `run` puts the
    question again at the terminal; or the answer is written on the plan's `**Answer**:` line and
    is then not asked again — which is how a maintainer settles a question without sitting at
    whatever terminal the router is attached to. The plan resumes only when **every** question in
    the record is answered, and answers already given are kept in the plan rather than discarded
    with the set. Answered questions are written into the resuming sub-set's own Decisions table
    (§ *Detailed summary*) as rows marked ⛔,
    because the node that acts on a decision is not the node that asked for it.
  - **The route back is decided where the cause is — at resume time, not when the question was
    asked.** The recorded node is where the plan returns, *unless* the answer left the executing
    sub-set holding a thing whose `Impl` is 🔲/🔄: then it resumes at `Implementing`, because an
    answer of the form *"that is a row in this sub-set"* creates work that no other node can do.
    The router reads the sub-set's cells and writes the node — the first exit `Asking human
    direction`'s panel names in the canonical graph. Deciding it when the question is *put* is not
    possible: the answer is what grows the scope.
  - Checked by `scripts/TESTS/test_run_is_the_only_advance.py`.
- **Nothing is asked at `Committing`.** That step commits; it does not prompt. A question there
  would block an unattended run for an answer the developer has no reason to give yet — the work is
  not finished being judged.
- **Landing the work is `deliver`, and `run` never does it.** `run` commits on the plan branch and
  stops there; at `Done` it *suggests* the delivery and prints the commands rather than running
  them. `scripts/dev/common/dev-cycle.sh deliver` is the `Done → Merged` arc: it squashes the branch
  onto the target as ONE commit whose message is the plan's abstract, moves the kanban card to
  `kanban/done/`, renames the plan `(Merged)` and deletes the branch. `deliver --pr` opens a **pull
  request** instead when the maintainer wants the work reviewed, leaving the target untouched and
  the branch alive. The full contract — the flags, the target, the refusals — is
  `rules/version-control.md` § *Delivering a plan*; it is not restated here.
  - **A delivery is all or nothing.** The final bookkeeping — the plan renamed `(Merged)`, its
    cards moved to `kanban/done/` — is committed on the branch BEFORE the squash, because the plan
    file is the only surviving record of per-thing detail once the branch is gone and the
    `(Merged)` version is the one that must land. Every failure after that point restores the
    branch to its pre-bookkeeping tip, and a failed squash also aborts the merge so the target is
    left clean. A plan therefore says `Merged` when it is merged and not before — the general rule
    being that a thing is marked as having happened when it is verified to have happened, not when
    it is attempted. Checked by `scripts/TESTS/test_a_delivery_is_all_or_nothing.py`.
  - **Two decisions belong to the maintainer, and neither is visible to the router**: *whether to
    land at all yet* — a plan can be green and committed and still want a manual pass (an
    exploratory test, a look at the deployed UI) before it joins a shared branch — and *what to land
    into*, since `main` is the common case and not the rule. So `deliver` asks, and a
    non-interactive run without `--yes` stops and says what to pass rather than assuming.
  - So `Done` is reached with the plan branch **unlanded**, and that is the normal, expected state —
    not an unfinished one.

## Status legend (canonical symbols — use exactly these)

**`Impl` column** (implementation state of a thing to implement):

| Symbol | Meaning |
|---|---|
| 🔲 | **To do** — not yet started |
| 🔄 | **Doing** — started, in progress |
| ✅ | **Done** — implemented |
| 🛠️ | **Fixing** — already implemented but failed tests; now being fixed |
| ⏭️ | **Deferred by decision** — implementable, deliberately not done in this run; name **who decided and why** in the detail section |
| ⛔ | **Blocked** — cannot be implemented: a missing precondition or an external blocker; explain in the detail section |

⏭️ and ⛔ are not interchangeable, and the distinction is the point: ⛔ says *nobody could do this*,
⏭️ says *someone chose not to, and can choose otherwise*. Marking a scope decision ⛔ turns a
reversible choice into an apparent dead end — a reader stops asking about it. Both are **decisions,
not test outcomes**: `scripts/dev/common/dev-cycle.sh` never overwrites either from a test run, and it names
their count in the Status summary so a green plan cannot read as "everything asked for was done".

**`Docs` column** (are the specs and docs that describe this thing true?):

| Symbol | Meaning |
|---|---|
| 🔲 | **To do** — not yet looked at |
| 🔄 | **Doing** — being aligned |
| ✅ | **Aligned** — every spec and doc this thing affects describes what is now true |
| ➖ | **N/A** — this thing changes nothing any spec or doc describes |

`➖` is a claim like any other and must be true. A thing that changed a contract, a flag, a path, a
command or an env var **cannot** be `➖` — something documents it. The column is driven by
`ideable-align-docs` at the `Documenting` node, and `scripts/dev/common/dev-cycle.sh` refuses to leave that
node while any thing in the executing sub-set is still 🔲 or 🔄.

**`BE test` and `FE test` columns** (backend / frontend test state of a thing):

| Symbol | Meaning |
|---|---|
| 🔲 | **To do** — test not yet started |
| 🔄 | **Doing** — test in progress |
| ✅ | **Done** — test executed and passing |
| ❌ | **Error** — test executed and failing |
| ➖ | **N/A** — not applicable (e.g. no backend part for a frontend-only thing, or vice-versa) |

### A failure must be visible, and sticky (mandatory)

A reader must be able to open a plan in the `Fixing` node and see **what** is being fixed, from
the tables alone:

- **A failing suite marks every thing it covers `❌`.** A run that reports failures may never
  leave the whole table green or `🔲` — that hides the failure exactly where a reader looks.
- **A run certifies the EXECUTING sub-set, and only it.** A `Done` sub-set was certified by its own
  green run, and the router never goes back to it, so a later sub-set's failing run leaves its rows
  exactly as they were: marking them `❌`/`🛠️` would claim a fix nobody is making. A regression in a
  finished sub-set's code still shows — on the executing sub-set's own suite and in the Status
  summary — and fixing it is the executing sub-set's work (`apply_test_results`).
- **A test cell is a measurement, never a forecast.** A thing still `🔲` in `Impl` has not been
  started, so nothing about it has been measured and its test cells stay `🔲` — including when a
  suite that will one day cover it is failing today precisely because the code is not there yet,
  and including a suite that errored in setup before it could exercise anything. `❌` claims the
  thing was executed and found wrong; on an unstarted row that is simply untrue, and it is also
  unrecoverable, because the fold leaves rows whose `Impl` is `🔲` untouched
  (`scripts/dev/common/dev_cycle.py`, `apply_test_results`) — so a later green run cannot clear it.
  That is how a plan comes to read "✅ all tests passing" directly above rows marked `❌`, both
  written by the same tool and neither wrong on its own terms. **Seeding a new plan from a
  baseline run is the same mistake**: a baseline run measures the code as it stands before the work,
  not the things the plan is about.
- **`❌` is sticky.** It stays until a run proves that same thing green again. A later step that
  produces no result for it (module absent from the run, a build or documenting transition) must leave the
  `❌` alone; nothing but a passing result may clear it.
- **A thing with a failing test is `🛠️` in the `Impl` column** (Fixing), not `✅` — implemented
  code that fails its tests is not done. It returns to `✅` when its tests pass.
- **The Status summary states the run's OWN verdict**, not a verdict derived from the test counts.
  The runner decides `❌ FAILED` on three inputs — failing tests, the static-analysis gate
  (`ruff`/`mypy`/`tsc`), and a suite that died before reporting anything — and the fold reads the
  `**Overall: …**` line the runner wrote (`dev_cycle.summary_verdict`), so a run whose every test
  passed while the static gate failed says `❌ FAILED — static analysis` instead of `✅ All tests
  passing`. A failure keeps the summary for as long as it stands, naming how many tests fail and in
  which module/suite when tests are what failed. A SUMMARY carrying no verdict line falls back to
  the counts and nothing is invented, because a verdict the runner never stated would be this same
  defect pointed the other way.

`scripts/dev/common/dev-cycle.sh` applies all five deterministically when it folds a test run into the plan
(it attributes a row to a module by finding the module name anywhere in the row, in its heading,
or via "both modules"; a row it cannot attribute is left untouched and reported in its log).
`ideable-test-and-fix` owns the finer, per-thing bookkeeping and must honour the same invariants.

### Name the module in every row (mandatory)

The test-result fold matches each row against the enabled module names and updates only the rows
it can attribute. A row naming no module is left exactly as it was — so a fully tested, finished
task can still show `BE test: 🔲` on half its rows, which reads as unstarted work.

So every row must either name its module (`— module_template`, `host_app`, `(both modules)`) or
carry `➖` because no test of that kind applies. The fold deliberately does not guess: attributing
a green run to rows nothing exercised would make ✅ meaningless, which is the same reason a
failure is sticky.

**`framework` is an attributable name**, and it is the one to use for a row whose only test subject
is `scripts/TESTS` — a shell gate, the router, `compose_merge`. `parse_summary` returns it for that
suite exactly as it returns a module name, so a row reading `… — framework` has its `Fw test` cell
maintained like any other. A framework-tooling row that names nothing is the common mistake: its
`BE`/`FE`/`Cfg` cells are honestly `➖`, which looks compliant, while its `Fw` cell is hand-written
and no run will ever correct it.

**This rule applies to the sub-task tables of § *Detailed summary* too**, which is where it is
usually broken: the Main table's rows get module names because that is where a plan author meets
the rule, and the sub-task tables repeat the same shape three sections later. A sub-task row can keep
`BE test: 🔲` — *"test not yet started"* — through a run that passes every test covering it, directly
above a Status summary reading `✅ All tests passing`. Both cells are written by the same tool and
neither is wrong on its own terms.

**Checked, in both directions** (§ *Enforced, not aspirational*):
`scripts/TESTS/test_plan_rows_are_attributable.py` fails when a row of the active plan names nothing
the fold can attribute while claiming any measurement, and when a thing that is `✅`/`🛠️` still
carries `🔲`/`🔄` in a test column at or past `Documenting`. It asks `dev_cycle._row_modules` and
`parse_summary` rather than re-deriving the attributable names, so the checker and the fold cannot
certify different sets. `scripts/dev/common/dev_cycle.py` additionally ends every fold with an
aggregated `⚠` report naming the rows it could not attribute **and** which of them now read as
unstarted work — because a per-row log is one indistinguishable line among seventy, which is
information that exists and cannot be read.

`➖` is the honest mark for things a backend or frontend suite cannot cover — a developer CLI, a
build-time shell gate — and the Status summary should say so, rather than leaving a reader to
assume the coverage exists.

### Name what measures a row (recommended, and it changes the verdict)

A test cell can be filled from two sources, and they are different claims:

- **A measurement.** The row names the test file(s) that exercise it — `test_migrations.py`, in the
  row text or in the heading above its table — and the fold reads exactly those files' results out
  of that run's per-module report. This is the row's own verdict, and a failure in it marks the
  thing `🛠️` in `Impl`, because the thing really is being fixed.
- **A module roll-up.** The row names no file, so the fold uses the one verdict the SUMMARY carries
  per module per suite. That is an *estimate of coverage*, not a measurement of this row: it says
  "something in this module's backend suite failed", which may or may not have anything to do with
  this thing. The cell still carries `❌` — a failure must stay visible — but **`Impl` is left
  alone**, and the fold reports how many rows were filled this way.

Why the distinction exists. A roll-up marks every row of a module whose suite failed, including rows
measured by files that passed in the same run, and demotes each of their `Impl` cells `✅ → 🛠️`. The
plan then reads "four sub-sets failing" while the run says "one file fails, and the plan knows why".
Since a plan cannot reach `Done` while a thing is `🛠️`, one accounted-for failure holds the whole
plan open, and a newly-broken thing is indistinguishable from a row repainted by an unrelated file.

`scripts/dev/common/dev_cycle.py` reads the per-file results from
`TEST_REPORTS/<run>-<module>/test-report-<suite>.md`, whose `What was tested` table already lists
every test with its `path::Class::test` location — there is no JUnit XML in this framework and none
is needed. A file a row names that no report mentions is reported as unmatched (a rename or a typo)
and that row falls back to the roll-up rather than silently looking measured.

The `Tests` counts in § *Repos updates summary table* are driven by the roll-up, always. That is the
one place a per-module total is exactly the right number.

### The four test columns

| Column | Filled from | Owned by |
|---|---|---|
| `BE test` | `modules/<m>/backend/TESTS` | module developers |
| `FE test` | `modules/<m>/frontend/TESTS` (pytest contracts) + its Playwright suite | module developers |
| `Cfg test` | `modules/<m>/TESTS` and every other sub-module's `TESTS` (`database/`, `authentik/`, `traefik/`) | module developers |
| `Fw test` | `scripts/TESTS` | the Ideable maintainer |

`Cfg test` is the module's own configuration and deployment contracts: its compose file, `.env`
contracts, database and bootstrap contracts, `authorization.yaml`, menu definitions, seed. Every
module has these, remote ones included.

`Fw test` is framework tooling — the dev-cycle router, `compose_merge`, `build_and_deploy`,
`validate_modules`. **In a remote module's plan it is always `➖`**: a remote consumes the
framework and must never modify it, so it has nothing to report there. That is a statement of
ownership, not a gap.

These are separate columns because they have separate owners: one pytest run reports everything as
backend, so a row about compose ordering has no column that could describe it, and `➖` would be
doing double duty for "not applicable" and "nowhere to put this".

Use `➖` only when a test of that kind genuinely cannot apply. When something *is* testable and
simply untested, leave `🔲` so the gap stays visible: a compose merge that drops a service's
environment, and a bind mount resolving outside `deployment_root`, are both defects in code no
column covers.

**Finished means written *and* measured.** A thing whose `Impl` is ✅ while a test column of its is
still 🔲 is written and unproved, and that is the state every sub-set legitimately passes through
between `Implementing` and a green `Testing`. So `Impl` alone never says a plan is finished, and the
checks that read these tables read the measurement too
(`scripts/TESTS/test_plan_status_is_true.py`). `Docs` is not a measurement and is excluded from that
reading: it is the `Documenting` node's own output, 🔲 by definition until that node runs.

## Required contents

A plan file MUST contain the following sections, in this order: **Purpose, General design, Overall
view, Sub-sets summary, Status summary, Detailed summary, Repos updates summary
table.**

There is no plan-wide "Decisions and answers" chapter any more. **Every choice the plan did not
already contain — what a node decided on its own, and what the maintainer answered — is recorded in
one compact table per sub-set**, inside that sub-set's own section of § *Detailed summary*. See
§ *Detailed summary* below for the table's columns, placement and lifecycle; this is the one place
it is defined.

**Why per sub-set rather than one plan-wide ledger.** A single accumulating chapter reads as a full
audit trail of every decision the whole run ever took, most of it about sub-sets a resuming agent is
not touching. What a fresh agent starting a sub-set needs is what THAT sub-set decided — and § *Detailed
summary* is already where a fresh agent meets the sub-set it is about to work, so the record and the
work it explains sit together rather than in a chapter six sections apart. The per-sub-set table is
still the plan's only decisions record — there is no second table anywhere for the same sub-set, and
the file does not read like a plan-wide ledger, one compact table per sub-set rather than a growing
transcript of every agent's turn.

The table's exact columns, placement, migration and writers are defined once, at the point of use:
§ *Detailed summary* below.

Checked by `scripts/TESTS/test_a_plan_records_its_decisions.py`.

### 1. Purpose

A short chapter (a few sentences) summarizing **what this plan sets out to implement** — the
goal of the run in plain language, so a reader understands the intent before scanning statuses.
Written once at creation; updated only if the scope materially changes.

### 2. General design

Holds **only the durable design assumptions and cross-cutting design statements that apply across
the whole plan** — the stable architecture the sub-sets are built on, stated once so no sub-set has
to re-derive or repeat it. It is not a decision log (that is § *Detailed summary*'s per-sub-set
Decisions table) and not a per-thing spec-change record (a design note kept for one specific thing
belongs under that thing in § *Detailed summary* instead, see that section).

- Written once, early — typically at plan creation, alongside § *Purpose* — and updated only when the
  cross-cutting design itself changes, not on every sub-set that merely uses it.
- **What belongs here**: an architectural choice more than one sub-set depends on, an invariant every
  sub-set must respect, a shape the plan commits to before any sub-set is implemented. A design point
  that concerns exactly one sub-set belongs in that sub-set's own section instead — a design note
  under § *Detailed summary*, kept until the thing it describes is done (see that section).
- **What does not belong here**: the record of how a design point was arrived at (a question asked,
  an option chosen between two the specs allow) — that is a decision, and every decision is a row in
  the sub-set's own Decisions table, never prose in this chapter. This chapter states **what was
  settled**, not **how** or **why it was settled** beyond what a reader needs to apply it correctly.
- May be empty (a short "Nothing beyond the sub-sets' own scope" line) when a plan has no
  cross-cutting design of its own — most small plans do not.

### 3. Overall view

A glance-level chapter that answers "where are we now?". It MUST contain:

- **Created at** — the plan creation timestamp (day and hour, `YYYY-MM-DD HH:MM`), equal to the
  timestamp encoded in the filename. Written once at creation, never changed.
- **Last updated** — day and hour (`YYYY-MM-DD HH:MM`) of the most recent change to this plan.
  Every skill that writes any cell refreshes this.
- **Current step** — the **sub-set** the run is on and the **state** it is in, plus (in
  parentheses) the skill/phase acting on it, e.g.
  `sub-set 3/8 “The seed writes SQL…” — Testing (ideable-test-and-fix)`. The node name alone does
  not say *what* is being tested once a plan is delivered as several sub-sets, which is why the
  sub-set is named here. A plan with no sub-set table falls back to `Testing (…)`.
- **Dev-cycle graph** — placed **immediately after `Current step`**, because it is the picture of
  that line. See the graph bullet below for the colour convention and the verbatim block.
- **Sub-set table** — placed **after the graph**, giving the context around it: which sub-sets came
  before, and which are still to come.

The order of this chapter is fixed, because it is read top-down as the answer to "where are we?":
**Created at → Last updated → Current step → the graph → the sub-set table.**

- **Sub-sets timing table** — one row per sub-set, in execution order, titled `Sub-sets timing`,
  with columns **#**, **Description**, **State**, **It #**, one **time column per dev-cycle state
  that does real work** — `Specs`, `Impl`, `B&D`, `Test`, `Doc`, `Fix`, `Commit` — and **`Ask`**,
  the time the sub-set spent waiting on the maintainer, plus **Total**. See § *Sub-sets* below for
  how the sub-sets themselves are chosen. `State` is `—` before a sub-set
  starts, one of `Specs` / `Implementing` / `Building&Deploying` / `Testing` /
  `Fixing` / `Documenting` / `Committing` while it runs, and `Done` when it is finished. While the
  plan is at `NotStarted` or `Branching` every row is `—`: no sub-set is executing until the
  branch exists, and `Branching` is what starts the first one. **Exactly one row may hold a
  running state at any time**: the graph says which *step*, this table says which *sub-set* is on
  it, and `scripts/dev/common/dev-cycle.sh run` writes both together so they can never disagree —
  and it is the **only** advance there is, so no second writer can put half of a transition
  somewhere `run` does not look.

  ```markdown
  | # | Description | State | It # | Specs | Impl | B&D | Test | Fix | Doc | Commit | Ask | Total |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | 1 | The seed writes SQL, not Python | Done | 2 | 8m 10s | 42m 15s | 3m 2s | 9m 40s | — | 1m 30s | 1m 30s | 4m | 1h 10m 7s |
  | 2 | The sub-set table says where the time went | Implementing | 1 | 3m 5s | 9m 3s | — | — | — | — | — | — | 12m 8s |
  | 3 | A delivery certifies itself | — | 0 | — | — | — | — | — | — | — | — | — |
  ```
- **The time columns run in the order the loop does**: `Test`, then `Fix` (a failing suite's
  detour, which returns to `B&D`), then `Doc` — only a green `Testing` reaches `Documenting` — then
  `Commit`. The router brings a plan in flight onto this order on its next transition.
- **`It #` is how many passes this sub-set's own loop has taken** — starting at `0` before the
  sub-set starts, and incremented on each of the loop's **two re-entry arcs** (§ *Overall view*'s
  graph): entering `Specs`, once to start the sub-set fresh and once more each time `Implementing`
  finds a spec gap and loops back; and entering `Fixing`, each time `Testing` fails and the sub-set
  goes round again. `BuildDeploy` and `Testing` increment nothing — every pass goes through them, so
  counting them would count nodes rather than passes.
  **A sub-set that failed its tests cannot reach `Done` on the pass that failed them**: the `Fix`
  span and the count say the same thing, and a row reading `It # 1` beside a non-empty `Fix` column
  recorded a detour while denying the pass. It is the same count a sub-set's own Decisions table
  keys its `It #` column off (§ *Detailed summary*) — one counter, read by both, the timing table
  holding it and the decisions table reading it.
- **Each time column says where THAT PART of the plan's time went**, and the router is their only
  writer: at **every** transition it adds the in-flight span of the node it just left to that node's
  own column, in the same write that moves the highlight — `Testing`'s span, for instance, lands in
  `Test`, never in `Fix` even when the suite it ran was checking a fix. `Total` is the sub-set's sum
  across every column and every iteration to date, `Ask` included. `—` in any cell means **no span
  has been accrued there yet**, which covers two states and not one: the column has never been
  reached, *or* the sub-set is at its **first** node and has not transitioned. The transition that
  opens a sub-set is the one that credits the *previous* node's column, so a running row's current
  column reads `—` until its own first transition is written — every sub-set passes through that
  window, and `scripts/TESTS/test_a_plan_says_where_the_time_went.py` asserts that a running sub-set
  is being timed everywhere except there, naming the window rather than excusing the cell. Seconds
  are kept at every magnitude (`2h 3m 12s`) in every column, because each value is accrued by
  repeated read-add-write and rounding a cell to the minute leaks whatever is under it, once per
  transition.
  - **A node's span is IN-FLIGHT TIME SINCE THE NODE WAS ENTERED — not since `run` was called, and
    not since the sub-set started.** The two are different because of WHO performs the node. The
    router performs `BuildDeploy` and `Testing` itself, so its own clock covered them; but `Specs`,
    `Implementing`, `Fixing` and `Committing` are performed by an agent (or a person) **between two
    `run` invocations**, so a clock started by `run` measures the transition's own instant and
    reports `0s` for hours of work — the exact inversion of where the time went, and precisely the
    distinction this table exists to draw. The clock therefore starts at the **transition that
    entered the node**, which is the same moment for every node whoever performs it.
  - **A wait is reported, not dropped.** `Asking human direction` has its own column: the plan
    enters `Asking`, the maintainer is waited on, and that span lands in `Ask` rather than in the
    node that asked. `Paused` is charged to nothing at all — the clock is parked across it and the
    parked span is subtracted when the plan resumes — so a plan parked for a day is charged for none
    of it, which is what "waits fall outside" has always meant here.
  - It is what makes the plan's own cost readable without reconstructing it from git timestamps,
    and it is the instrument that answers whether a boundary is worth what § *Sub-sets* says it
    costs — a fresh agent and a full pass of the loop; splitting it per node is what lets that
    answer distinguish "this sub-set was a long implementation" from "this sub-set fought a fix
    that would not converge", and `Ask` is what keeps "a person was slow to answer" from being read
    as either.
  - **`NotStarted`, `Branching`, `Done` and `Merged` are charged to nothing.** No sub-set is
    executing when the first two run — `Branching` is the node that starts the first one — and the
    last two do no work a column exists for.
  - A plan whose table is missing `It #`, a timing column or `Total` gains them on its next
    transition; a delivered plan is a record of what was true then and is never rewritten. A plan
    carrying the single `Exec time` lump has it folded onto `Total` the same way, once: no per-node
    breakdown exists to carry forward, so the per-node columns start `—` rather than a guess.
- **Dev-cycle graph** — the canonical Mermaid state graph below, embedded verbatim, with the
  **current node highlighted**. The nodes are the dev-cycle states; the arcs are the Ideable
  skills that drive the transitions. Colour convention: the single **current** node is
  **yellow**, every other node is **grey**. This is expressed with exactly **two `class`
  lines** — one listing every node *except* the current (class `idle`), one listing the single
  current node (class `current`). The graph carries a third, `class AskingExits exits;`, which is
  fixed and colours the annotation panel rather than a state (see below). Whenever the run
  advances (a skill executes or the plan is
  otherwise changed), rewrite those two `class` lines so exactly one node is `current`, and
  update **Current step** + **Last updated** to match.
  **Only the node fills are pinned.** The leading `%%{init: …}%%` line sets spacing and drops the
  edge-label plate, and pins **no text colours at all**: the arcs, their labels and the panel take
  the reader's own theme, so the graph is legible dark-on-light and light-on-dark — which a fixed
  palette cannot be in both. The `classDef` fills stay pinned because the yellow/grey highlight
  *is* the state, and a themed fill would stop saying which node the plan is on. Keep the line
  verbatim.

Canonical graph (copy verbatim; only the two `class` lines change per run):

````markdown
```mermaid
%%{init: {"flowchart":{"rankSpacing":25,"nodeSpacing":40},"themeVariables":{"edgeLabelBackground":"transparent"}}}%%
flowchart TB
    NotStarted["Not started"] --> Branching --> Specs["Specs *"] --> Implementing["Implementing *"]
    Implementing --> BuildDeploy["Building &amp; Deploying"]
    Implementing -->|spec gap| Specs
    BuildDeploy --> Testing
    Testing -->|pass| Documenting["Documenting *"]
    Testing -->|fail| Fixing["Fixing *"]
    Fixing --> BuildDeploy
    Documenting --> Committing
    Committing -->|next sub-set| Specs
    Committing -->|all sub-sets done| Done
    Done --> Merged["Merged &amp; pushed"]
    Done -->|plan not true| Committing

    Asking["Asking human direction"]
    Asking -.->|exits| AskingExits["→ Implementing — when the answer grew the sub-set's scope<br>→ the step that asked — otherwise"]

    classDef idle fill:#e0e0e0,stroke:#9e9e9e,color:#333333;
    classDef current fill:#ffd54a,stroke:#f9a825,color:#000000,stroke-width:2px;
    classDef exits fill:none,stroke:#9e9e9e,stroke-dasharray:4 3,text-align:left,white-space:nowrap;
    class AskingExits exits;

    %% --- state lines (rewritten on every advance): all-but-current = idle, the current = current ---
    class Branching,Specs,Implementing,BuildDeploy,Testing,Fixing,Documenting,Committing,Done,Merged,Asking idle;
    class NotStarted current;
```

`*` — this step can ask for human direction, which moves the plan to *Asking human direction*.
````

- **The happy path is one vertical line, and nothing crosses it.** `NotStarted → Branching →
  Specs → Implementing → BuildDeploy → Testing → Documenting → Committing → Done → Merged` reads
  top to bottom, and the only arcs leaving it are the four the run genuinely branches on:
  `Implementing`'s `spec gap` back to `Specs` — symmetric to `Fixing`'s `BuildDeploy` arc, one node
  earlier — `Testing`'s `fail` to `Fixing`, `Committing`'s `next sub-set` back to `Specs` — the
  loop § *Sub-sets* says the router runs **once per sub-set**, and now starts each pass by
  deciding the target before coding it — and `Done`'s `plan not true` back to `Committing`, which
  is the route-back for a plan that reached `Done` with an unfinished Repos row or thing. That loop
  is not boxed: a box a plan can never be highlighted on is one more thing in the picture that is
  not a state.
- **`Specs` mirrors `rules/general-guidelines.md` § *Development process* inside the automated
  loop.** That process already names "specifications" (step 1) before "coding" (step 2); without a
  `Specs` node the automated `Implementing` node conflates the two and reconciles a spec against
  reality only afterwards, at `Documenting` (step 8) — a different activity
  (reconcile spec-to-built-reality) than deciding the target before building. `Specs` closes that
  gap, and — like `Documenting`'s "reconcile, not legislate" — has **direct spec-write authority**:
  defining a sub-set's spec target is its job, not a proposal to someone else's, so `Implementing`
  never edits or proposes a spec change itself. When it meets a gap the spec does not yet settle,
  it raises a spec gap and the router routes back to `Specs` — the same shape as `Testing` routing
  a failure to `Fixing`, one node earlier in the graph. Three distinct `Specs`-named things
  exist and are not the same thing — see § *Documenting* for the boundary between this node and
  its time column, the `Docs` column, and the per-thing `Specs` status icon.
- **The ask is a STEP, and it has no arcs into the flow.** `Asking human direction` is where a plan
  goes when a step meets a decision only the maintainer can take. The graph draws that with **two
  notations that say the same thing in words**:
  - a `*` on each step that can ask — `Specs *`, `Implementing *`, `Fixing *`, `Documenting *` —
    with the legend line directly under the graph. `Committing` carries no `*`, and that is a
    claim, not an omission: *nothing is asked at `Committing`* by contract.
  - a **dashed panel** linked to the node by a dashed `exits` arrow, naming where the answer sends
    the plan: **`Implementing`** when the answer grew the sub-set's scope, and **the step that
    asked** otherwise.
  A condition belongs in words rather than on a line — a reader cannot tell two identically drawn
  arcs apart, and the label that distinguished them was the part being missed.
- **`AskingExits` is a panel, not a state.** It must never appear in the `class … idle;` or
  `class … current;` lines, or a plan would render as though it were sitting on an annotation. Its
  transparent fill, dashed border and dashed arrow are what say so to a reader; `class AskingExits
  exits;` is a third, fixed line and is not one of the two the router rewrites.
- **The exit to `Implementing` is the one a reader most needs, and the panel is why.** An answer can
  add a thing to the executing sub-set (*"that is a row in this sub-set"*), and prose cannot close
  unwritten work — so the plan resumes at the step that writes code rather than at the step that
  asked, whichever that was. The route is decided **where the cause is**, at resume time, by the
  router reading the sub-set's `Impl` cells (`resume_node`). `documenting_gate`'s route-back
  (§ *Documenting*) survives as the **safety net** for a scope that grew without a question.
  **A DELIVERED plan keeps the picture it was written with** — it is a record of what was true
  then — and only the canonical graph here is the contract. **A plan still in flight is brought onto
  this picture**, because the router writes `class <node> current;` against the node *names* above:
  a plan carrying an older graph gets the highlight applied to a node its own picture does not draw,
  and the highlight lands nowhere at the moment a reader most needs it.
- **Nodes (dev-cycle states):** `NotStarted` (the plan has been written and nothing has run: no
  branch exists, every sub-set is `—`; `scripts/dev/common/dev-cycle.sh start <description>` makes
  it the active plan without leaving this node, and the first
  `scripts/dev/common/dev-cycle.sh run` leaves it), `Branching`
  (the router creates and checks out `plan/<description>` and starts the first sub-set — the one
  node whose whole job is the branch, so the picture shows it being made rather than it appearing
  as a side effect), `Specs` (`ideable-define-specs` — defines or updates the spec files the
  sub-set's things need, with direct write authority; every sub-set starts here, and
  `Implementing` loops back to it on a spec gap), `Implementing` (coding against the now-settled
  spec, `ideable-implement-specs` — no spec-write authority of its own),
  `BuildDeploy` (build+deploy+restart, `ideable-build-and-deploy` / `redeploy.sh` — **skipped, and the
  skip reported in the run's output, when the executing sub-set's diff holds nothing a build can read**: a
  sub-set that changed only rules, skills and plan bookkeeping would otherwise rebuild the previous
  sub-set and let the test run that follows certify that. An unknown path counts as a build input,
  so the skip is provable rather than assumed), `Testing`
  (`ideable-test-and-fix`, test phase — **which refuses a lap that cannot inform anyone**: when the tree, bookkeeping excluded, is identical to the previous `Testing` run's, the previous `Fixing` changed nothing a test can read, so the suite is not run and the plan goes to `Asking human direction` resuming at `Fixing`. A lap whose checkpoints touch only the SUMMARY, the plan file and the `ACTIVE PLAN` link produces an identical verdict, so it cannot inform anyone. The criterion is the codebase and not the failure set, because an honest fix may fail the same test three times over three different trees and land on the third), `Fixing` (`ideable-test-and-fix` fix phase or
  `ideable-bugfixing-and-changes`, both via `ideable-spec-driven-edit`), `Documenting`
  (`ideable-align-docs` — the specs and docs governing what changed are brought into line with what
  is now true; see § *Documenting* below), `Committing` (`ideable-commit-changes`), `Done` (all
  things green, documented **and committed on the plan branch** — the work has not landed anywhere
  yet, and that is a finished state, not a broken one), `Merged` (`scripts/dev/common/dev-cycle.sh deliver` has landed the
  plan on the target as one squashed commit — directly, or through the pull request `--pr`
  opens), `Asking human direction` (a decision only the maintainer can take is owed —
  reachable from any step; the run waits here per the decision-authority rule. The router assigns
  it: when a question put to the maintainer goes unanswered, `run` records the node carrying that
  question and the step to resume at, and `run` is also how the plan leaves it, once every question
  is answered — at the recorded node, or at `Implementing` when the answer left the executing
  sub-set holding a thing whose `Impl` is 🔲/🔄; see § *Git integration*.
  A skill may set it itself when aligning or implementing
  would require a decision the plan never took; a plan at `Asking human direction` with **no**
  recorded question simply stops, because there is nothing to put again. It is named for what it
  is waiting on rather than for being stuck: *blocked* stated a problem and no remedy, and the
  remedy — answer the question — is the whole of the state).
- **`Done` and `Merged` are different claims, and the filename says which.** `Done` means green and
  committed on `plan/<description>`; `(Merged)` means it is on the target branch. Without the two
  being distinguished, `implementation-plans/` cannot answer "did this ship?" — a `(Done)` file says
  nothing about whether it landed. Older files are **not** retrofitted: the distinction works from
  the first plan that uses it.
- **`Paused` is a filename state and deliberately not a node**, which is why it is absent from the
  graph. A node answers *where is the work*; `Paused` answers *nobody is on it*, and those are
  different questions. A `Paused` node would have to take the highlight, and the highlight is the
  only record of the node `resume` returns to — see § *Location & naming* and § *Git integration*.
- The graph is **fixed** — do not edit its nodes/edges per plan; only move the highlight.
- `scripts/dev/common/dev-cycle.sh` reads/advances this highlight deterministically (see that script);
  skills also update it when they act. After a `Testing` run the router additionally folds the
  latest `TEST_REPORTS/*-SUMMARY.md` into the plan — setting each thing's `BE test` / `FE test`
  cell (BE ⇐ that module's pytest suite, FE ⇐ its playwright suite) and the Repos `Tests` counts —
  so the columns reflect the results without a separate manual pass. The `ideable-test-and-fix`
  skill remains the authority for finer, per-thing test bookkeeping.

### 3b. Sub-sets (mandatory)

A task is delivered as an **ordered sequence of coherent sub-sets**, declared **when the plan is
first written** — not discovered as the work proceeds. Deciding them up front is what makes each
pass through the dev-cycle loop mean something; deciding them as you go is how a plan ends up with
increments that are individually green and jointly incoherent.

A sub-set is correctly sized when all three hold:

1. **Each thing in it can be described in a short sentence.** If a thing cannot be described
   briefly, it is not one thing — split it.
2. **Its acceptance criteria can be tested atomically and independently**, without the sub-sets
   that come after it. A sub-set nothing can exercise on its own is not a sub-set: it will pass its
   tests by being inert, which tells you nothing.
3. **Its commit message can be simple** — close to the sub-set's own description. Needing a long
   message to explain what one sub-set did means it did more than one thing.

**And it is as LARGE as one green run can certify, not as small as one sentence can describe.**
The three criteria above are a ceiling — they say when a sub-set is too big. This is the floor, and
it exists because a boundary is not free: each one costs a full pass of the loop
(`Implementing → BuildDeploy → Testing → Documenting → Committing`, five nodes), and between two
sub-sets it also costs a **fresh agent** that rebuilds its understanding from the plan — and about
half of such a node's actions are re-reading. Splitting a coherent increment because each half can
be named in a sentence buys a shorter sentence and pays a whole cycle for it. So: put in one sub-set
everything **one test run can certify together**, and split only where criterion 2 makes you — where
the later half cannot be tested without the earlier one, or where the two would need two different
commit messages.

**And the plan measures this for itself.** The sub-sets timing table's per-node columns
(§ *Overall view*) are what a boundary actually cost on this plan, per sub-set, accrued by the router
rather than reconstructed afterwards — so the next author sizing a sub-set reads a figure instead of
an anecdote.

**Order follows dependency.** If sub-set X is a prerequisite for sub-set Y, X is implemented first.
The table's row order *is* the execution order.

The dev-cycle then runs the loop once per sub-set: `Implementing → BuildDeploy → Testing →
Documenting → Committing`, and at `Committing` the router checks that sub-set's own sub-table:

- things still 🔲/🔄 in this sub-set → back to **Implementing** on the same sub-set;
- this sub-set complete, a later one pending → mark it `Done`, start the next at **Implementing**;
- every sub-set `Done` → **Done**.

`Documenting` asks the same question one node earlier, and gives the same answer: a sub-set holding
a thing that is still 🔲/🔄 there goes back to **Implementing** too, because what is unwritten has
nothing for a document to describe (§ *Documenting*).

`Done` therefore means the scope was delivered, not that the last test run was green. ⏭️ deferred
and ⛔ blocked are decisions and do not hold a sub-set open — mark the remainder that way, with the
reason in the Detailed summary, to finish a task early.

### 3c. Documenting (mandatory)

Between a green `Testing` and `Committing`, the **specs and docs governing what changed are brought
into line with what is now true**. The node is driven by `ideable-align-docs`, which owns the
procedure; this section states the rule it implements.

- **Scope is the sub-set's own diff**, not the repository. A step that re-reads everything every
  time is a step that gets skipped.
- **Documents describe the present.** No shipped spec, rule or README may describe a superseded
  state as though it were current, and none may narrate its own history — *"used to"*, *"formerly"*,
  *"previously named"*.
- **A bug-avoider may narrate; nothing else may, and the boundary is a FILE CLASS.** A
  bug-avoider's subject **is** what once went wrong: it exists so a defect is not reintroduced, so it
  says what the defect was and why the guard exists. Everywhere else — a spec, a rule, a README — the
  document describes the system as it stands, and the reasoning behind a line is not part of that
  description. The boundary is checkable by path, which a judgement about whether a sentence *"could
  be mistaken for current behaviour"* is not: that asks every reader to agree on the same call.
- **Nothing removed is still named as live** — env vars, flags, scripts, functions, paths,
  endpoints, contracts.
- **Reconcile, do not legislate.** Updating a spec to match approved, tested reality is this node's
  job and needs no permission. If aligning would require deciding something the plan never decided,
  or the code contradicts a contract the spec exists to impose, the plan goes to **`Asking human
  direction`** with the question stated — per the decision-authority rule. In a remote module project, framework-owned
  files are reported and never edited, per `AGENTS.md`.
- **Three things are named `Specs`, and they answer three different questions — say which one a
  reader means.** They legitimately coexist:
  - **The `Specs` NODE and its time column** (§ *Overall view* → `Sub-sets timing`) answer *did
    this sub-set's spec-defining phase run, and how long did it take* — a measurement of the
    ROUTER'S OWN CLOCK, accrued the same way as `Impl`/`B&D`/`Test`/`Doc`/`Fix`/`Commit`. It says
    nothing about whether any particular thing's spec is good.
  - **The `Docs` column** (this node's own artifact, above) answers *does the spec/doc now
    describe what was actually built and tested* — unchanged by this node's addition: `Documenting`
    still reconciles spec-to-built-reality **after** the fact, which is a different activity from
    `Specs` deciding the target **before** it. A thing can be `Specs: ✅` (its target was written
    and later verified) and still owe `Docs` work if something *else* about it — a path, a flag —
    drifted after the target was set.
  - **The per-thing `Specs` STATUS ICON** (§ *Sub-sets summary*) answers *was THIS thing's intended
    spec change written down* — a per-row claim, not a per-sub-set time or a per-sub-set document
    pass. It is what the `Specs` node's own work leaves behind for a reader who is not asking "how
    long did this take" or "does the doc match reality today", but "was the target for this one
    thing actually decided".

  A reader who confuses these reads a plan whose `Specs` node ran fast, whose `Docs` are green and
  whose per-thing `Specs` icon is still 🔲 as contradictory; it is not — the three answer different
  questions, and a plan can be any combination of them honestly.
- **Drift is expected work, not a failure.** `Documenting` fixes in place and advances to
  `Committing`. It **never** branches into the build/test loop — there is no arc from it to
  `Fixing`, `BuildDeploy` or `Testing`, because a text edit must not be sent round a loop that
  rebuilds and re-runs the suite (`scripts/TESTS/test_dev_cycle_graph.py::test_documenting_never_reaches_fixing`).
- **A sub-set whose scope GREW goes back to `Implementing`.** A node can discover work — a
  maintainer answers a question with *"that is a row in this sub-set"*, or a document cannot be
  reconciled without new code. The row is then unimplemented, and prose cannot close it: the gate
  returns the executing sub-set's things whose `Impl` is still 🔲/🔄, names them, and `run` writes
  `Implementing` — the same answer `Committing`'s scope gate has always given. The check is scoped
  to the **executing** sub-set on purpose: un-scoped it would read every later sub-set's 🔲 rows and
  route every plan back at its first `Documenting`.
  **Where the scope grew from an answer, the route is taken one step earlier** — at `Asking human
  direction`, the first exit its panel names in the canonical graph (§ *Overall view*), because
  that is where the cause is. This gate is what catches a sub-set that grew without a question: a row added by hand, or a
  thing the node could not reconcile and did not ask about. It is the **safety net**, and a safety
  net is deliberately not a second drawn path — the picture draws the cause.
  Checked by `scripts/TESTS/test_dev_cycle_docs_gate.py` and
  `scripts/TESTS/test_dev_cycle_graph.py::test_a_sub_set_whose_scope_grew_goes_back_to_implementing`,
  which pins the arc against the router: an edge drawn with no route-back behind it is a lying
  signal pointed the other way.
- **It leaves an artifact**: the `Docs` column (§4), and it ends on a green **docs gate** — the
  tests that actually read specs and docs — because edits made after `Testing` would otherwise reach
  a commit no test had read.
- **The artifact is checked twice, and both readings are scoped the same way.** The router refuses
  to leave the node while a thing in the executing sub-set is 🔲/🔄; and
  `scripts/TESTS/test_docs_describe_the_present.py::test_no_plan_past_documenting_has_an_unfinished_docs_cell`
  reads every plan whose filename says `(Committing)`, `(Done)` or `(Merged)` — the states where the
  node is behind it — and names any thing it left unfinished. That second reader is scoped to the
  **executing** sub-set for the reason given above: un-scoped it counts rows of sub-sets nobody has
  begun, which are 🔲 by definition, and a six-sub-set plan fails at its first `Committing` for work
  that has not started. **With no sub-set executing it reads the whole table**, which is where it
  still bites: a plan at `Done` or `Merged` has nothing in flight and owes a `Docs` cell on every
  row.
- **In a remote module project the gate has nothing to run**, and says so. Those tests live in
  `scripts/TESTS/`, which is maintainer-only, so the router reports `docs gate DID NOT RUN` rather
  than `passed` — a check that cannot fail must never report success. There, the step's guarantees
  rest on the skill's judgement and on the `Docs` column being filled honestly.

**Why this is a node.** A change can be green, reviewed and delivered and still leave a document a
reader is told to trust describing a reality that is not there — a rule calling a toolchain *opt-in*
that its own test makes mandatory, a retired spec file presented as live. Nothing earlier in the
cycle asks whether the documents still match the system; this node is that question.

### 4. Sub-sets summary

**Divided into one sub-table per sub-set**, in the same order as the Overall view's sub-set table,
each under a heading carrying that sub-set's description so the router can find it. Every sub-table
has the same columns. A thing belongs to exactly one sub-set.

A flat list of the **things to implement**, one row each, with `Specs` first, the test columns of
§ *The four test columns*, and `Docs` last, valorized from the legend below:

```markdown
| Thing to implement | Specs | Impl | BE test | FE test | Cfg test | Fw test | Docs |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| <short name of the thing> | 🔲 | 🔲 | ➖ | 🔲 | ➖ | ➖ | 🔲 |
```

`Specs` is **first**, because it is the first thing the cycle does to a thing, at the `Specs`
node — before any code is written. `Docs` is the **last** column, because it is the last thing
the cycle does to a thing before it is committed.

**`Specs` tracks whether the intended spec change for the thing has been written down — and nothing
else.** It is the `Specs` node's own claim about its own deliverable, made at the end of that node:
the target is written, and the other steps of the iteration — `Implementing`, `Testing`,
`Documenting` — exist to implement, prove and describe it, not to certify the target. `Docs` is the
separate question of whether the spec/doc describes what was built and tested, and that is
`Documenting`'s. A thing can be `Specs: ✅` and still owe `Docs` work, and a thing whose `Specs` is
still 🔄 has not had its target written yet. See § *Documenting* for the third, related-but-distinct
thing this is not: the `Specs` node's own time column, which measures the sub-set's clock, not any
one row's spec status.

**Every per-thing icon — `Specs` included — is written directly to the plan file by the skill
doing the work, the same way `Impl` and `Docs` already are.** There is no router round-trip
and no extra commit per icon change: `ideable-define-specs` sets `Specs` 🔲→🔄 while it writes the target,
and 🔄→✅ once the target is written, inside the node's own ordinary working commit. A spec gap
found later (`Implementing → Specs`) re-opens that thing's target, and the `Specs` pass that closes
it drives the thing's cell 🔄→✅ again — the same *iterate on the one thing until it is done* the
other columns already show. **`ideable-align-docs` does NOT touch `Specs`:** its job is the `Docs`
column, and a spec that was written and then tested green is documentation to align, not a target
to re-verify.

**The router reads it the same way it reads `Docs`.** `Specs` advances when no row of the executing
sub-set is still 🔲 or 🔄: **✅ is this node's own output** — the target is written — and reading it
here is what lets the node be left at all. A plan carrying no `Specs` cell keeps the rule that an
agent performs the node: an empty unfinished-list is the absence of the column, not evidence of a
written target. Checked by
`scripts/TESTS/test_the_router_advances_on_state.py`.

Immediately **below the table**, embed this compact legend (copy verbatim) so a reader can
decode the icons without leaving the plan — the same symbols defined in **Status legend**
above, restated here at the point of use:

```markdown
> **Legend**
> - **Specs:** 🔲 To do · 🔄 Doing (spec being written/updated) · ✅ Done — the target is written · ➖ Nothing a spec describes
> - **Impl:** 🔲 To do · 🔄 Doing · ✅ Done · 🛠️ Fixing (failed tests) · ⏭️ Deferred by decision · ⛔ Blocked
> - **BE/FE/Cfg/Fw test:** 🔲 To do · 🔄 Doing · ✅ Pass · ❌ Fail · ➖ N/A — a *measured* result; a row whose `Impl` is 🔲 stays 🔲 here
> - **Docs:** 🔲 To do · 🔄 Doing · ✅ Aligned · ➖ Nothing a spec or doc describes
```

(This is the one place the legend is intentionally restated inside the artifact; sub-task
tables in the Detailed summary reuse the same symbols and need no separate legend.)

**The router writes 🔄 when the plan ENTERS a node**, for the executing sub-set, in that node's own
column (`dev_cycle.mark_node_started`): `Specs`, `Impl` and `Docs` go 🔲 → 🔄 at `Specs`,
`Implementing` and `Documenting`; at `Testing` the test cells of every row whose `Impl` is written go
🔲/✅ → 🔄 while the suite runs, and a cell the run did not measure reads 🔲 afterwards. A ❌ is
never moved to 🔄: a failure stays visible until the same thing passes again. Entering `Testing`
also sets those rows' `Docs` ✅ back to 🔲: `Documenting` aligns the docs against this pass's green
run, so a `Docs` ✅ written before it is premature, whoever wrote it. So the table says what
is running at every moment, and never shows a previous lap's verdict as the current one. The node's
agent still writes its outcome (✅, ⏭️, ⛔); the router writes only the start.

### 5. Status summary

**Where the plan stands, now.** It opens with one **very short** free-text line — the overall
status, no details (e.g. *"3 of 5 things done; frontend tests failing on the items page; not yet
committed."*) — which is the line `scripts/dev/common/dev-cycle.sh status` reads and prints. Below
it, a few short paragraphs at most: the last recorded test verdict, what the executing sub-set
still owes, and anything a reader must know before touching the work.

**A node REWRITES this chapter; it never appends to it.** The question the chapter is titled with
is *where does this stand*, and the answer has one tense. A node that adds its account below the
previous node's — *"the record of the node that preceded this one follows"* — is writing a run log
into the one file that exists precisely because the maintainer did not ask for one (§ *Location &
naming* → History mode). A run log runs to hundreds of lines, of which the status is the first few.

**What a node must carry forward it writes INTO the chapter, not below it.** A finding the next
node needs, an open item, a hand-off — those belong in the current text, phrased as what is true
now. What a node did and no longer matters is dropped; the file-per-step trail is `--keep-history`.

### 6. Detailed summary

**Organized in one section per sub-set**, `### Sub-set <n> — <description>`, in the same order as
the Overall view's sub-set table. Each sub-set's section holds, in this order:

1. **An updated description of the sub-set's current state** — what is in progress during an
   iteration, the real final summary once the sub-set is done. Like § *Status summary*, a node
   **rewrites** this rather than adding another account beside it: two paragraphs about one sub-set
   make a reader work out which is current, and the newer one is not reliably the lower one.
2. **That sub-set's Decisions table** (below).

**For each thing the sub-set's Main-table row declares, one short paragraph** — only when it adds
real information about the true status of that thing, written inside the sub-set's section. A node
**rewrites** its thing's paragraph rather than adding another beside it, for the same reason.

One kind of content is deliberately **not** a paragraph about a thing and does not follow the
rewrite rule:

- **A design note the plan must keep** — the shape a later node has to implement, an argument that
  would otherwise be re-derived. Give it its own `####` heading and keep it until the thing it
  describes is done, then remove it: a target that has been built is described by the code. See
  § *Sub-sets summary* for the durable version of this note, which survives past `Impl` being done
  and backs that table's `Specs` column.

When a thing has sub-tasks, describe them with a **sub-task table of the same shape** as the Main
table (`Impl` / `BE test` / `FE test`), but scoped to that thing's sub-tasks:

```markdown
#### <thing>

<short paragraph on the real status, if useful>

| Sub-task | Impl | BE test | FE test |
|---|:--:|:--:|:--:|
| <sub-task> | 🔄 | 🔲 | ➖ |
```

#### The sub-set's Decisions table (mandatory whenever the sub-set owes one)

**One table records every choice this sub-set did not already contain — what a node decided on its
own, and what the maintainer answered.** It is not a full audit timeline of every agent turn: one
compact table per sub-set, holding only that sub-set's own decisions (plus, per the `Who` rule below,
a maintainer ruling taken while a different sub-set was executing but binding this one too).

**Why per sub-set, and not one plan-wide ledger.** The current sub-set and the actual work being done
already carry all the context a decision needs; a plan-wide chapter forces a reader into every
sub-set's history to find the handful of rows that matter to the one being resumed. Putting the
table inside § *Detailed summary*'s own sub-set section is also where a fresh agent already goes to
learn what this sub-set is — the record and the work it explains sit together.

Placed as the last thing in the sub-set's section — after its narrative and its things' paragraphs —
under a `#### Decisions` heading, delimited by HTML comments keyed to the sub-set number
(`<!-- dev-cycle:decisions:<n> -->` … `<!-- /dev-cycle:decisions:<n> -->`) for the same reason the
blocked record is delimited: creating, appending to and migrating it have to be exact, and a heading
is prose that gets edited.

One table, one row per decision, **newest last**, with exactly these columns:

```markdown
#### Decisions

| It # | Node | Premises | Question | Answer | Who | Consequences |
|---|---|---|---|---|---|---|
| 3 | ⛔ Documenting | Documenting could not reconcile the spec without knowing whether `pause` takes a description | Does `pause` gain an optional `<description>`? | Yes, a row in this sub-set | maintainer | Symmetric with `resume`, so the remedy the two-plans refusal names reaches the plan the reader means |
```

- **It #** — the iteration of this sub-set's own loop the decision was taken in, starting at 1, and
  **read from** the Overall view's `Sub-sets timing` row for that sub-set (§ *Overall view*), which
  is the one counter. So **several decisions taken in one pass share a number**, and the rows are
  ordered by position rather than by it: two decisions about one thing are distinguishable by which
  came later in the table (newest last). A column that incremented per row would be a row number
  wearing an iteration's name, and would make a sub-set that made one pass read as five.
- **Node** — the dev-cycle node that took or asked it (`Implementing`, `Documenting`, …). A cell
  marked **⛔** came from an `Asking human direction` block and names the node the plan STOOD ON when
  the question was put — not the guard, check or skill that raised it, which is *why* it was asked
  and belongs in `Consequences`.
- **Premises** — what brought the agent to the need to ask: the fact, the missing precondition, the
  contradiction it met. This is what lets a reader (and a later node) judge whether the premises
  still hold, rather than only what was concluded from them.
- **Question** — what was actually undecided, in the words a reader meets it in.
- **Answer** — what was chosen. `—` is a legitimate value while the question is open; a question
  with no answer yet is recorded, not omitted.
- **Who** — `maintainer`, `agent` or `router` — or `—` while nobody has decided — and **the first
  is different in kind**: a maintainer's decision may not be revisited without asking them again,
  while an agent's judgement or the router's rule-following may be. A decision with no owner cannot
  be revisited by anyone.
- **Consequences** — why the answer solves the problem, with the pros and cons that made it the
  chosen one over the alternative. This column is the one that stops the same question being
  re-opened every time a fresh agent meets it.

**When it is mandatory.** Wherever the sub-set deferred a choice, its table records how it was taken
— every choice the sub-set did not already contain: a question put to the maintainer (answered or
still open), an option the node picked between two the specs allow, a thing deliberately **not**
done, and any precedent applied rather than a rule followed. Implementing what the plan already says
is not a decision and needs no row.

**A maintainer's ruling binds every sub-set, not only the one that provoked it.** It stays a row of
the sub-set that asked — the table is still one table per sub-set, not duplicated — but a node
briefed for a *different* sub-set is still told about every standing maintainer ruling, wherever its
row lives (§ *Git integration* → node briefs); a maintainer ruling is not something the next sub-set
may re-litigate merely because it was written in an earlier one's table.

**The node that takes a decision hands the router a row**, the same way it hands over a `Docs` cell:
the node writes it, the router owns the sub-set's table and writes its own rows into the same table.
Three authors, one table per sub-set. The router asks each node it runs for it by name in the node's
brief, and writes the maintainer's answers there itself when it resumes a plan from `Asking human
direction` — what the maintainer said and what was done about it are halves of one record.

**Why it is in the plan and not in a transcript.** An agent's memory is not something the next node
may rely on: a new sub-set starts a fresh agent deliberately, and within a sub-set a resumed session
is a convenience that can be absent. The repository and the plan are the whole context, and both are
auditable. A decision that stayed in a terminal is a decision the next node will take again,
differently.

**A sub-set's table accumulates for the life of that sub-set**, and is the one part of its section
that does not follow the sub-set-narrative's rewrite rule — a decision does not stop being true
because the sub-set's narrative moved on, and re-deciding it is exactly what these rows prevent.

A plan whose sub-sets record no decisions at all carries no `#### Decisions` heading for them — the
table is owed only where § *When it is mandatory* applies, not manufactured to satisfy the shape.

Checked by `scripts/TESTS/test_a_plan_records_its_decisions.py`.

### 7. Repos updates summary table

One row per repo/module touched by the run, with the general status:

```markdown
| Repo / module | Implementation | Tests | Commit |
|---|---|---|---|
| host_app | In progress | 4 passed / 1 failed / 2 pending | Committed — "feat(audit): column filtering" |
```

- **Implementation**: `Not started` · `In progress` · `Done` · `In error` · `Fixing`.
- **Tests**: counts as `<n> passed / <n> failed / <n> pending`.
- **Commit**: `Not committed` · `Committed` · `Pushed`, followed by the commit message
  (` — "<message>"`). List multiple commits comma-separated when a repo has several.

**The `Commit` cell must be true when the run reaches `Done`.** `Done` means *all things green
**and committed on the plan branch***, so a plan that reaches it still saying `Not committed` is
stating something false about the repository. `Committed` is the correct value at `Done`; `Pushed`
is written only after the developer has actually merged and pushed, which happens outside the
graph. `scripts/dev/common/dev-cycle.sh` enforces this deterministically: after **every** checkpoint
commit — not only at `Committing` — it reads the plan branch's commits (`main..HEAD`), attributes
each to the **scopes** whose paths it touched, and writes the matching Repos rows itself, in the
follow-up commit described in § *Git integration*. That is the same
git-is-the-authority treatment the `Tests` counts get from `TEST_REPORTS/`, and it is folded at
every transition because the router commits the tree at every transition: the first checkpoint
carrying a repo's scope makes `Not committed` false for that row, so a fold that waited for
`Committing` would leave every earlier node describing a repository that had already moved.
A cell already
reading `Pushed` is left alone (the router cannot verify a push), and
`ideable-commit-changes` still owns the finer bookkeeping.

**A row names a scope, and three rules decide which:**

- A path under `modules/<name>/` belongs to that module's row.
- **Everything else belongs to the `framework` row** — `scripts/`, `rules/`, `.githooks/`,
  `.github/`, `reusable.ui/`, the root wrappers. The framework has no `modules/<name>/` prefix to be
  discovered under, so a rule deriving scopes from that prefix alone cannot see it.
- **Run bookkeeping belongs to nothing**: `implementation-plans/`, `kanban/` and `TEST_REPORTS/`
  record a run rather than being the work it did. Without this, the `Branching` checkpoint — which
  touches only the plan file — would mark the framework `Committed` at the instant the branch was
  created, which is how a cell starts lying.

A row's **scope is its leading name**, not its whole label: the framework row lists its paths in a
parenthetical, and that list is not its identity. **Both the `Commit` and the `Tests` cells are
folded per row scope** — the `Tests` fold matches the same `row_scope()` the `Commit` fold uses, so
the framework row's `Tests` count is written by the run's `framework` suite, not typed by hand.

**The `Implementation` cell must be true there too, and the router writes it for the same reason.**
At `Done` and `Merged` it folds any row still reading `Not started`, `In progress`, `In error` or
`Fixing` to `Done` — but **only where that row's `Commit` cell says the work landed**, so the fold
rests on git rather than on the node. `ideable-implement-specs` still drives the cell as it works;
what the router adds is the last write, the one an agent has no reason to make because it finishes
a sub-set and moves to the next. The fold runs at the end of the run that reaches `Done` and again
inside `deliver`, before the suite is certified — the two places the cell is read.

**A row no commit touched keeps whatever it says.** `Not committed` is the truth for a module the
branch never changed, so writing `Committed` there would trade one false cell for another — and the
check on these cells is per row, against the commits that touched *that* row's scope, for the same
reason. Compared against the branch as a whole, one commit anywhere fails every row, including the
rows that are true, so no truthful plan can pass.

## Who writes which part

| Skill | Node it drives | Responsibility on the plan |
|---|---|---|
| `ideable-define-specs` | `Specs` | **Creates** the plan at `NotStarted` (Purpose, General design, Overall view, Sub-sets summary, Detailed summary), then runs `scripts/dev/common/dev-cycle.sh start <description>` to make it the active plan and `scripts/dev/common/dev-cycle.sh run --auto-advance 2` so the router performs `Branching`. Defines or updates the spec files the executing sub-set's things need — direct write authority, no propose-and-ask — before any code is written; also the node `Implementing` loops back to on a spec gap. Drives the `Specs` column (🔲→🔄→✅) for every thing it writes a target for: 🔄 while writing it, ✅ once it is written. |
| `ideable-implement-specs` | `Implementing` | Implements SOURCES against the now-settled spec; drives the `Impl` column (🔲→🔄→✅) and the Repos `Implementation` cell as it works. Raises a spec gap (routing the plan back to `Specs`) rather than proposing or editing a spec itself. |
| `ideable-build-and-deploy` | `BuildDeploy` | Sets the Repos `Implementation` cell to `In error` if build/deploy fails (otherwise leaves it). |
| `ideable-test-and-fix` | `Testing` / `Fixing` | Drives the `BE test` / `FE test` columns (🔲→🔄→✅/❌) and the Repos `Tests` counts. On a failure it re-implements (via `ideable-spec-driven-edit`) and sets the thing's `Impl` to 🛠️ (`Fixing`), back to ✅ when green. |
| `ideable-align-docs` | `Documenting` | Drives the `Docs` column (🔲→🔄→✅/➖) for every thing in the sub-set. Updates the docs (and, where the built reality genuinely contradicts a spec, the spec) so they describe the present; moves the plan to `Asking human direction` when aligning would require a decision the plan never took. It does NOT drive the `Specs` column — a written-and-tested spec is documentation to align, not a target to re-verify. |
| `ideable-bugfixing-and-changes` | `Fixing` | Appends rows and drives `Impl` on the plan route. **Creates** a plan only when the maintainer answers its plan-or-fast-lane gate with *plan*; on the fast lane no plan exists and none is created. Edits go through `ideable-spec-driven-edit`. |
| `ideable-commit-changes` | `Committing` | Drives the Repos `Commit` cell (`Not committed`→`Committed`→`Pushed`) and records the commit message(s). |
| `scripts/dev/common/dev-cycle.sh` | every node | Writes what git and `TEST_REPORTS/` can settle without asking anyone: the graph highlight, `Current step`, `Last updated`, the executing sub-set and its timing cells, the `Tests` counts, and the Repos `Commit` and (at `Done`/`Merged`) `Implementation` cells. |

**Every skill above, whenever it acts, MUST record the decisions it took** as rows in the
**executing sub-set's own Decisions table** (§ *Detailed summary*) — its own, and the maintainer's
answers it acted on. The node that takes a decision is the only one that knows why; the node that
lives with it may hold nothing but this file — at a sub-set boundary it certainly does. A node hands
over a row the way it hands over a `Docs` cell: it writes the row, the router owns that sub-set's
table.

**The router is the other writer of that record.** `scripts/dev/common/dev-cycle.sh` writes the
maintainer's answers there when it resumes a plan from `Asking human direction`, and writes its
**own** decisions as rows with `Who` = `router` and `Node` naming the node it was routing. Each sub-set's table is the same shape;
only the author differs per row, which is what the `Who` column is for.

**Every skill above, whenever it acts, REWRITES the chapters it owns rather than appending to
them.** § *Status summary* and a sub-set's own narrative and things' paragraphs in § *Detailed
summary* say what is true **now**; each sub-set's Decisions table is the one part of its section
that accumulates. Without the rewrite rule, every node adds a layer and the plan becomes the run log
that `--keep-history` already produces — while the one question the default single file exists to
answer, *where does this stand*, gets harder to answer with every node that passes
(§ *Location & naming* → History mode).

**Every skill above, whenever it acts, MUST also update the Overall view** (§3): set
**Current step** to its node, rewrite the two `class` lines so its node is the only `current`
(yellow) one, and refresh **Last updated**. It also refreshes the **Status summary** line so it
stays truthful. (`scripts/dev/common/dev-cycle.sh` performs the same Overall-view update deterministically
when it advances the run.) `ideable-spec-driven-edit` is an **atomic capability** invoked inside
the `Implementing`/`Fixing`/`Documenting` nodes — it does not own a node of its own and writes no plan cells.
