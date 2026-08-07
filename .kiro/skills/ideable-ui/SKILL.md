---
name: ideable-ui
description: Build any Ideable UI element from specs by reusing the @ideable/ui shared widget library (tables with server-side pagination/sort/filter, popups, audit trail, charts, buttons, toggles, dialogs, forms, Radix primitives). Use every time a frontend UI element is created or changed in host_app or any module derived from module_template. References only reusable.ui/** and module_template/** — never host_app (absent in remote projects).
category: development
displayName: Ideable UI Widgets
---

# Ideable UI — Build from Specs by Reusing Framework Widgets

The Ideable framework ships a single shared UI library, **`@ideable/ui`**, living in the top-level **`reusable.ui/`** folder (sibling of `modules/` and `deployment_root/`). host_app, `module_template`, and every remote module generated from it all consume it. **Reuse these widgets — never hand-roll a table, popup, dialog, chart, or primitive.**

## Use this skill when

- Any frontend UI element must be created or changed from specs (a page, table, form, popup, dialog, chart, button, toggle, menu icon) in host_app or any module.

## Do not use this skill when

- Pure backend / database / infra / config work with no UI surface.

## ⚠️ Self-contained-for-remotes boundary (mandatory)

In a remote module development project (derived from `Ideable-ModuleTemplate`), `modules/host_app/` contains only `module.json` + `config/` — **no host_app SOURCES**. Therefore this skill and everything it references must exist in a remote project. It references **only**:
- its own bundled `reference/*.md` files,
- `reusable.ui/**` (the `@ideable/ui` package),
- `modules/module_template/**` (the live gallery + framework specs).

**Never reference `modules/host_app/**` from this skill or its guidance.** host_app is framework-internal and invisible to remote developers.

## Mandatory first reads

1. `rules/general-guidelines.md` (always).
2. For module work, the module's `SPECS/base-specs.md` chain (per the project's Mandatory Reading Order), plus the framework UI specs under `modules/module_template/frontend/SPECS/ideable-framework-specs/` (`shared-ui-widgets-specs.md`, `shared-ui-specs.md`, `framework-css-classes-reference.md`).

## Workflow

**Step 1 — Map the UI need to a widget family.** Open `reference/decision-guide.md` and match "I need to show/collect/visualize X" → the framework widget.

**Step 2 — Look the widget up in the registry.** Open `reference/widget-index.md`. Each row points to (a) the `@ideable/ui` source, (b) the live gallery section demonstrating it, (c) the canonical spec section.

**Step 3 — Read the live example + the source.** Open the gallery section in `modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx` and the widget's source under `reusable.ui/`. Copy the real usage pattern.

**Step 4 — Read the cited spec section** for the contract (props, required behavior, i18n keys, permission gating).

**Step 5 — Honor conventions.** Read `reference/conventions.md`: import from `@ideable/ui`, the `ideable:` shared prefix vs the module's own prefix, design tokens + branding, the `.ideable-scope` wrapper, i18n split (widget strings vs page strings), and tree-shaking rules.

**Step 6 — Check the bug-avoider digest** (`reference/bug-avoider-digest.md`) for the mandatory anti-patterns before writing code.

**Step 7 — Implement by reusing the widget.** Never reinvent a table/popup/dialog/chart/primitive that already exists in `@ideable/ui`. Pass page-specific labels already translated; let the widget resolve its own chrome.

**Step 8 — Verify.** Typecheck and build the consuming frontend; run the module's L&F parity + i18n contract tests where present.

## Extending the widget library

To add a genuinely reusable widget (used by ≥2 pages/modules or mandated by a framework spec):
1. Implement it in `reusable.ui/` (`widgets/` or `primitives/`) using the `ideable:` prefix + design tokens.
2. Add a demonstrating section to `module_template`'s `WidgetGallery.tsx`.
3. Add a row to `reference/widget-index.md` pointing at the source + gallery section + spec.
4. Extend the canonical spec under `modules/module_template/**/SPECS` it cites.
All four live under `reusable.ui`/`module_template`/this skill so they reach every remote project via the sync flow. One-off page components do **not** enter the library.

## Boundaries & framework-owned files

`reusable.ui/`, `modules/host_app/`, the framework specs, `scripts/`, and this skill are **framework-owned**. In a remote module project they are read-only: invoke this skill and read `@ideable/ui`, but do not edit framework-owned files — route changes to the Ideable maintainer + sync flow (see `rules/general-guidelines.md` § framework-owned files).

## Resources

- `reference/widget-index.md` — widget → `@ideable/ui` source + gallery section + spec.
- `reference/decision-guide.md` — need → widget mapping.
- `reference/conventions.md` — prefix, tokens/branding, scope, i18n, imports, tree-shaking.
- `reference/bug-avoider-digest.md` — mandatory UI anti-patterns.
- Live examples: `modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx`.
- Library source: `reusable.ui/` (`widgets/`, `primitives/`, `hooks/`, `styles/`, `i18n/`).
- Developer guide (human‑facing): `reusable.ui/README.md` — benefits + step‑by‑step for receiving updates and adopting the widgets.
