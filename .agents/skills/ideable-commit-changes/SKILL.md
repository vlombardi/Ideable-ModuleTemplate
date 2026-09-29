---
name: ideable-commit-changes
description: create a commit for each set of changes that belong to a consistent group of changes. 
category: development
displayName: Commit changes
---

Analyze all the changes from the last commit and create a commit for each group of changes that:
- describe a consistent set of changes (e.g., all modified/added/deleted files that implement a new feature or solve a specific bug)
- can be summarized with a short unique commit name

For each set of changes:
- define the files to add to the commit
- create a commit message in the **mandatory** project format (see `rules/version-control.md` § *Commit Guidelines* — it is a hard rule; do not invent another format):
  - **Subject**: `<type>(<module>): <short description>` where `<type>` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, and `<module>` is the affected module/scope (e.g. `feat(hostapp-backend): add audit-trail column filtering`). Keep the subject short and imperative.
  - **Body** (after a blank line), describing the change:
    - omit it if the change is trivial (subject only);
    - otherwise a minimum of 3 and a maximum of 10 lines.
- commit and print the files list and the commit message for user convenience
- tell the user to push the change, to change the message or to roll-back

## Update the implementation plan

After committing, update the **implementation plan** (format defined once in
`rules/implementation-plan.md`). Resolve the active plan (§ *Active plan resolution* there — the
plan named by an `ACTIVE PLAN - <description>.md` link in `implementation-plans/`, its current file
being the newest one bearing that description; an unlinked or parked plan is not
active). If one exists, for each repo/module touched set its Repos `Commit`
cell to `Committed` (then `Pushed` once the user confirms the push) and append the commit
message(s) (` — "<message>"`, comma-separated when a repo has several commits); refresh the
Status summary. Also set the Overall-view **Current step** to
`Committing (ideable-commit-changes)`, move the graph highlight to the `Committing` node
(rewrite the two `class` lines), and refresh **Last updated**. If no plan exists, skip silently —
do not create one from this skill.

**This step performs the `Committing` node; it never advances the plan.**
`./scripts/dev/common/dev-cycle.sh run` is the only advance, and there is no `set`: the same command
that writes the next node also takes the `Committing` branch nothing else can — the scope gate, the
sub-set advance (sub-set N `Done`, N+1 started at `Implementing`), `Done` only when every thing is
green *and* committed, and the `Commit` cells folded from git afterwards. Marking `Done` here, or
starting the next sub-set here, writes half of that and contradicts the other half. Highlight your
own node and stop.

## Commit, and stop

Per `rules/implementation-plan.md` § *Git integration*, the dev-cycle is branch-per-plan: work
happens on the plan's `plan/<description>` branch, and **this step commits there and stops**. Do not
merge, do not push, and do not ask whether to.

Landing the work is a separate step, `Merged`, reached by `./scripts/dev/common/dev-cycle.sh deliver`:

```bash
./scripts/dev/common/dev-cycle.sh deliver --dry-run     # compose and print the message; change nothing
./scripts/dev/common/dev-cycle.sh deliver               # confirm, squash onto the target, push
```

**Why it is not asked here.** A question at `Committing` blocks an unattended run for an answer
nobody has a reason to give yet — the work has not finished being judged. A plan can be green and
committed and still want a manual pass before it joins a shared branch. `deliver` asks after `Done`,
which is when the maintainer has an answer, and it composes a message that says what the plan
delivered instead of git's default subject.

So `Done` is reached with the plan branch unlanded. That is the expected state, not an unfinished
one.
