---
name: ideable-bugfixing-and-changes
description: Use whenever a change or bugfix is needed in the Ideable project's sources or configuration. Enforces a consistent, spec-driven process — check bug-avoiders first, implement safely on the codebase (never on running containers/deployment/DIST), no fallbacks or hardcoding, propose spec changes rather than editing specs unasked, and record fixes back into the specs/bug-avoiders.
category: bug-fixing
color: blue
displayName: Bug Fixing Expert
---

Use this skill for **any change or bugfix** in the Ideable project — a code fix, a configuration/env change, or resolving a reported bug. It keeps the spec-driven approach intact across iterations.

## The Ideable project (context)

- Specification- and test-driven; divided into **modules and sub-modules**, each with its own `SPECS/` and `TESTS/`.
- **Framework-owned contracts** live in the `ideable-framework-specs/` folders under `SPECS/`, `backend/SPECS/`, `database/SPECS/`, and `frontend/SPECS/` — shared across host_app, module_template, and every remote; never edited in a remote project.
- **Module-specific contracts** are the remaining files under a module/sub-module `SPECS/` folder.
- Each relevant `SPECS/` folder may contain:
  - (mandatory) `base-specs.md` — the base specification for that scope;
  - (optional) `general_bug_avoider.md` — known bugs + how to avoid/fix them;
  - (optional) `<ASPECT>_bug_avoider.md` — bug-avoider for a specific aspect (e.g. `database_bug_avoider.md`, `ui_bug_avoider.md`, `api_bug_avoider.md`).

## Making the change — follow the `ideable-spec-driven-edit` discipline

This skill is the **entry point** for a change/bugfix (it establishes context and owns the
implementation plan). The actual edit MUST follow the atomic **`ideable-spec-driven-edit`**
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

## Track the change in the implementation plan

Keep the change visible in the **implementation plan** (format/legend/naming defined once in
`rules/implementation-plan.md`):

- Resolve the active plan (most-recently-modified `*.md` in `implementation-plans/`).
- If one exists, add a row per change/bugfix to the Main implementation summary table (or
  update the matching row) and drive its `Impl` cell (⬜→🔄→✅; 🛠️ while re-fixing after a
  failed test; ⛔ if it turns out not implementable). Refresh the Status summary.
- If **no** plan exists and this is a standalone change/bugfix, **create** one (this skill and
  `ideable-implement-specs` are the only skills that may create a plan): name it per the
  convention, its things-to-implement are the changes being made, and fill the required
  sections (including the **Purpose** and **Overall view** chapters). BE/FE test cells stay ⬜
  (or ➖) until `ideable-test-and-fix` runs.
- Set the Overall-view **Current step** to `Fixing (ideable-bugfixing-and-changes)`, move the
  graph highlight to the `Fixing` node (rewrite the two `class` lines), and refresh **Last
  updated**.
