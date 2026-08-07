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

## For a bug: look first, then fix, then record

1. **Look for a known solution first** — check the relevant `general_bug_avoider.md`, then the `<ASPECT>_bug_avoider.md` files, before diagnosing from scratch.
2. **Fix it** following the implementation rules below.
3. **Record the fix back into the specs** so the next SPECS→SOURCES pass is bug-free:
   - if the bug stems from a **missing/incorrect framework contract**, update the relevant `ideable-framework-specs/` `base-specs.md` **first**;
   - otherwise, add it to the appropriate module-specific `base-specs.md`, `general_bug_avoider.md`, or `<ASPECT>_bug_avoider.md`.

## Implementing the change (mandatory rules — bugs and changes alike)

1. **Identify the change needed.**
2. Then, depending on what it touches:
   - **Specification change** → *propose* the update to the user; **never change specifications yourself without confirmation.** If confirmed, update the spec files; otherwise stop.
   - **Configuration / environment variables / source files** → implement the change **on the codebase**. **Never modify running containers, the deployment, or `DIST/` files.**
3. **No fallbacks or workarounds** — implement only the requested change. If a pre-condition is not met, ask the user to meet it first.
4. **Never** fabricate a fallback by hardcoding missing data or silently altering database schemas — surface what is missing or different from expected.

**IMPORTANT:** every change must take effect only after the next build/restart of the application (e.g. via `redeploy.sh`) — not by editing a running container.
