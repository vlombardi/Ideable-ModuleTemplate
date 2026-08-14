---
name: ideable-spec-driven-edit
description: The atomic spec-driven safe-edit discipline for the Ideable project — the single rulebook every code/config change must follow (look in bug-avoiders/specs first, edit only on the codebase, no fallbacks/hardcoding, propose-don't-edit specs, stop-and-ask on ambiguity, record the fix back). Referenced by ideable-implement-specs, ideable-test-and-fix, and ideable-bugfixing-and-changes — not a standalone workflow.
category: development
displayName: Spec-Driven Safe Edit
---

# Spec-driven safe edit (atomic discipline)

This is the **one canonical discipline** for making any source/configuration change in the
Ideable project. It is not a full workflow — it is the guard that every editing phase runs
through, so a change made from the test-fix loop obeys the **same** rails as one made from
`ideable-implement-specs` or `ideable-bugfixing-and-changes`. Those skills **reference** this
one (they must not restate it). Hard project constraints live in `rules/general-guidelines.md`;
this skill indexes and sequences them for the act of editing.

## 1. Look first (before diagnosing or editing)

For the affected sub-module, read in this order and honour what you find:
1. `SPECS/general_bug_avoider.md`, then any `<ASPECT>_bug_avoider.md` (e.g.
   `database_bug_avoider.md`, `ui_bug_avoider.md`) — a known cause/fix likely already exists.
2. The relevant `SPECS/base-specs.md` chain, including any framework-owned
   `ideable-framework-specs/` files it references — the constraint that explains the failure is
   usually written there.

Never edit blind: if you have not read the sub-module's bug-avoider(s) and specs for the area
you are about to touch, do that first.

## 2. Edit only on the codebase — never on the running system

- Change **`SOURCES/` and configuration** files only. **Never** modify a running container, the
  `deployment_root/` deployment, or `DIST/` artifacts. Every change takes effect only after the
  next build/restart (e.g. `redeploy.sh` / `update_*.sh`), not by editing what is running.
- Respect existing interfaces (API contracts, DB schemas, env-var names other sub-modules
  depend on) — do not change them without explicit instruction.
- Respect the **framework-owned boundary**: in a remote-module project, never edit host_app,
  `reusable.ui/`, `scripts/`, `rules/`, the shared `ideable-framework-specs/`, or the skill/tool
  dirs — route those to the maintainer + sync flow (see `rules/general-guidelines.md`
  § *host_app / Remote Boundary* and § *Framework-owned files*).

## 3. No fallbacks, no hardcoding, no silent deviation

- Implement **only** the requested change, assuming preconditions are met. If a precondition is
  not met (missing/different schema, data, or config), **stop and ask** the user to meet it —
  do not work around it.
- **Never** fabricate a fallback by hardcoding missing data, or silently alter a database
  schema, or add a "temporary" default. Surface what is missing or differs from expected.

## 4. Specs are propose-don't-edit

- If the change is a **specification change**, or you find a spec that is incomplete, ambiguous,
  or incorrect: **do not edit the spec and do not code around it.** Propose the change and
  **stop and ask** for confirmation. Only after confirmation, edit the spec — framework-owned
  `ideable-framework-specs/` contract first when the gap is a framework contract, otherwise the
  module-specific spec.
- Decision authority belongs to the human developer: on any genuine ambiguity, stop and ask
  rather than guessing.

## 5. Record the fix back

After a bug is fixed, add a short, specific entry so the next SPECS→SOURCES pass is bug-free:
- if the bug stems from a **missing/incorrect framework contract**, update the relevant
  `ideable-framework-specs/base-specs.md` **first**;
- otherwise add it to the appropriate module-specific `general_bug_avoider.md` /
  `<ASPECT>_bug_avoider.md` — stating **what failed, root cause, the fix, and how to avoid the
  regression** when implementing from specs again.

## Plan bookkeeping (delegated back to the caller)

This atom writes **no** implementation-plan cells itself. The calling skill owns the plan
updates for its node (`Implementing` or `Fixing`) per `rules/implementation-plan.md` — including
driving `Impl` (🔄/🛠️→✅), refreshing **Last updated**, and keeping the Overall-view highlight on
its node.
