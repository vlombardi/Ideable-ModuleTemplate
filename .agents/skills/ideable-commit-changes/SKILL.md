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
`rules/implementation-plan.md`). Resolve the active plan (most-recently-modified `*.md` in
`implementation-plans/`). If one exists, for each repo/module touched set its Repos `Commit`
cell to `Committed` (then `Pushed` once the user confirms the push) and append the commit
message(s) (` — "<message>"`, comma-separated when a repo has several commits); refresh the
Status summary. Also set the Overall-view **Current step** to
`Committing (ideable-commit-changes)`, move the graph highlight to the `Committing` node
(rewrite the two `class` lines) — advance it to `Done` once every thing is green **and**
committed — and refresh **Last updated**. If no plan exists, skip silently — do not create one
from this skill.

## Merge the plan branch into `main` (the merge gate)

Per `rules/implementation-plan.md` § *Git integration*, the dev-cycle is branch-per-plan: work
happens on the plan's `plan/<description>` branch. Once the commit(s) for this step are made,
**ask the user whether to merge that branch into `main`**, and behave exactly as answered:

- **Yes** → `git checkout main && git merge --no-ff plan/<description>` (on conflicts, stop and
  report them for manual resolution — never force it).
- **No** → leave the branch unmerged and say so.

This is a **human decision gate** — never merge without an explicit yes. (`scripts/dev-cycle.sh`
runs the same prompt when it drives the `Committing` step; when this skill is invoked on its own,
perform the prompt here.)
