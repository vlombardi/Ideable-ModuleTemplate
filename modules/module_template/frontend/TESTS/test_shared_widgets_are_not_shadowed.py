"""A module must not define a component `@ideable/ui` already exports.

`AGENTS.md` § *Building any frontend UI element* and `rules/general-guidelines.md` § *UI, Look &
Feel, and the shared widget library* make `reusable.ui` the single source of truth and say never to
hand-roll a table, popup, dialog, chart or primitive. Nothing measured it.

A reported module imported `@ideable/ui` in 18 of its 26 components and still carried its own
`components/DraggableResizablePopup.tsx` (170 lines) and `components/UnsavedChangesDialog.tsx`
(62 lines) — both exported by `@ideable/ui` under the same names, with the same prop names, both in
active use. No test, lint or sync step noticed.

`test_lf_parity_contract.py` cannot notice either, and that is not a gap in it: a copy is
pixel-identical on the day it is written. It diverges later, when a platform fix reaches every
module except the one that copied it — silently, which is precisely what the shared library exists
to prevent. So the check has to be about *identity of name*, not similarity of output.

Name-based is enough, and deliberately so. Two components with the same name are either the same
component (shadowed) or two different things wearing one name (worse). Both are worth failing.

Force-synced and slug-free: the export list is read from `reusable.ui/*/index.ts` at test time, so
the check grows with the library instead of ageing out of it, and the module root comes from this
file's own path.
"""
import json
import re
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parents[2]          # modules/<module>
PROJECT_ROOT = MODULE_ROOT.parents[1]                      # repo root
SOURCES_DIR = MODULE_ROOT / "frontend" / "SOURCES" / "src"
REUSABLE_UI = PROJECT_ROOT / "reusable.ui"

#: Barrels whose exports are the shared surface a module must consume rather than redefine.
BARRELS = ("widgets/index.ts", "primitives/index.ts", "index.ts")

#: A module may deliberately define a component of the same name, and says so here — by name, with
#: a reason. The point of the check is that shadowing becomes a stated decision, not that it becomes
#: impossible: a module can have a real need for a variant, and the framework has no standing to
#: forbid it. What it does forbid is the decision being invisible.
#:
#: An entry is a claim like any other and is itself checked: a name listed here that the module does
#: NOT define fails, so the list shrinks when a copy is removed instead of quietly exempting work
#: that was already finished.
DECLARED_OVERRIDES: dict[str, str] = {}


def _shared_component_names() -> set[str]:
    """Component names `@ideable/ui` exports, from its own barrels.

    Read rather than listed, so adding a widget to the library extends this check with no edit
    here. Only PascalCase names are treated as components: the library also exports hooks
    (`useTranslation`), types (`ColumnDef`, `VersionRecord`) and lowercase primitive helpers, and a
    module is free to define its own `useX` or a type of the same name.
    """
    names: set[str] = set()
    for barrel in BARRELS:
        path = REUSABLE_UI / barrel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # `export { A, default as B }` and `export { C } from './C'` — but never `export type { … }`,
        # which is the library's types and not its components.
        for match in re.finditer(r"^export\s+\{([^}]*)\}", text, re.M):
            clause = match.group(1)
            for part in clause.split(","):
                part = part.strip()
                if not part:
                    continue
                name = part.split(" as ")[-1].strip() if " as " in part else part
                if re.fullmatch(r"[A-Z][A-Za-z0-9]*", name):
                    names.add(name)
    return names


def _module_component_definitions() -> dict[str, Path]:
    """PascalCase component name -> the module file that DEFINES it (not re-exports it).

    A re-export is the correct way to consume a shared widget under a local path
    (`export { DataTable } from '@ideable/ui'`), so a file that only re-exports is not shadowing
    anything. A definition is `function X`, `const X = `, or `class X` at top level.
    """
    found: dict[str, Path] = {}
    if not SOURCES_DIR.is_dir():
        return found
    for path in sorted(SOURCES_DIR.rglob("*.ts*")):
        if path.name.endswith(".d.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"^(?:export\s+)?(?:default\s+)?(?:function|class|const|let|var)\s+([A-Z][A-Za-z0-9]*)",
            text, re.M,
        ):
            found.setdefault(match.group(1), path)
    return found


def test_the_shared_export_list_is_readable():
    """A check whose subject list came back empty would pass by inspecting nothing."""
    names = _shared_component_names()
    assert names, (
        f"no component exports were extracted from {REUSABLE_UI}/{{{', '.join(BARRELS)}}}. The "
        f"barrels moved or their export syntax changed, and every assertion below would then "
        f"pass by checking an empty set"
    )
    # Two the library has always exported, and the two the reported module had copied. Named
    # literally so that a regex change that silently narrows the extraction is caught here rather
    # than turning this whole file into a no-op.
    for expected in ("DraggableResizablePopup", "UnsavedChangesDialog", "ServerDataTable"):
        assert expected in names, (
            f"{expected!r} is exported by @ideable/ui and was not extracted — the extraction has "
            f"drifted from the barrels"
        )


def test_no_module_component_shadows_a_shared_one():
    shared = _shared_component_names()
    defined = _module_component_definitions()
    shadowed = {
        name: path for name, path in defined.items()
        if name in shared and name not in DECLARED_OVERRIDES
    }
    assert not shadowed, (
        "these components are already exported by `@ideable/ui` and this module defines its own:\n"
        + "\n".join(
            f"  {name}  —  {path.relative_to(MODULE_ROOT)}" for name, path in sorted(shadowed.items())
        )
        + "\n\nA local copy stops receiving platform fixes to that widget, silently, and no visual "
        "test can see it — a copy is pixel-identical the day it is written.\n"
        "  Fix: delete the local file and import from '@ideable/ui'. To re-export it under a local "
        "path, use `export { X } from '@ideable/ui'` — a re-export is not a definition and does "
        "not fail this check.\n"
        "  If this module genuinely needs a different component of the same name, add it to "
        "DECLARED_OVERRIDES in this file with the reason, so the decision is stated rather than "
        "invisible.\n"
        "  See rules/general-guidelines.md § 'UI, Look & Feel, and the shared widget library'."
    )


def test_a_declared_override_must_actually_exist():
    """A baseline nobody prunes stops describing reality and starts exempting finished work."""
    defined = _module_component_definitions()
    stale = sorted(name for name in DECLARED_OVERRIDES if name not in defined)
    assert not stale, (
        f"{stale} are declared as deliberate overrides and this module does not define them — "
        f"remove the entries, which is what makes that list shrink"
    )


def test_a_declared_override_must_name_a_shared_component():
    """Otherwise the list accumulates exemptions for a check that never applied to them."""
    shared = _shared_component_names()
    irrelevant = sorted(name for name in DECLARED_OVERRIDES if name not in shared)
    assert not irrelevant, (
        f"{irrelevant} are declared as overrides of shared components, but @ideable/ui does not "
        f"export them — nothing was being overridden"
    )


def test_a_declared_override_states_a_reason():
    blank = sorted(name for name, reason in DECLARED_OVERRIDES.items() if not (reason or "").strip())
    assert not blank, (
        f"{blank} are declared as overrides with no reason. The whole value of the escape hatch is "
        f"that the decision is legible to the next reader"
    )


def test_the_module_consumes_the_shared_library_at_all():
    """A module that imports nothing from `@ideable/ui` is not shadowing — it is not participating.

    Recorded as a separate, softer signal: a module with no frontend at all is legitimate, while a
    module with a frontend that reaches for none of the shared widgets has almost certainly
    hand-rolled them under different names, which the name-based check above cannot see.
    """
    if not SOURCES_DIR.is_dir():
        pytest.skip("this module has no frontend sources")
    package_json = MODULE_ROOT / "frontend" / "SOURCES" / "package.json"
    if package_json.is_file():
        deps = json.loads(package_json.read_text(encoding="utf-8"))
        declared = {**(deps.get("dependencies") or {}), **(deps.get("devDependencies") or {})}
        assert "@ideable/ui" in declared, (
            "frontend/SOURCES/package.json does not depend on @ideable/ui, so this module cannot "
            "be consuming the shared widgets and every UI element in it is a local definition"
        )
    importers = [
        path.relative_to(SOURCES_DIR)
        for path in sorted(SOURCES_DIR.rglob("*.ts*"))
        if "@ideable/ui" in path.read_text(encoding="utf-8")
    ]
    assert importers, (
        "no file under frontend/SOURCES/src imports from '@ideable/ui'. Either this module renders "
        "no shared UI element at all, or it has its own copies under its own names — which this "
        "check cannot detect by name and a reviewer has to look for"
    )
