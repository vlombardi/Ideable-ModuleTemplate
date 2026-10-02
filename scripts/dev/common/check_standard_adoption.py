#!/usr/bin/env python3
"""Name entity code the standard could serve. Informs; never fails.

Sub-set 9 of `an-entity-is-served-by-the-framework-unless-it-says-otherwise`. Sub-sets 1-6 built the
registry and adopted it where it was worth the rewrite; sub-set 8 wrote the guide for moving an
existing entity onto it. Nothing until now told a maintainer WHERE that guide would apply — the gap
this script closes.

**Gravity decides the mechanism**, per the maintainer's ruling of 2026-09-18: a broken framework
contract (a tenant-scoped model with no RLS, DDL a model promises and the schema lacks) is an ERROR
and other checks in this file's family (`check_entity_ddl.py`, `check_tenancy_markers.py`) fail the
build over it. *This entity has a hand-written page the standard could serve* is INFORMATION — a
missed opportunity, not a broken promise — so this script's exit code is always 0 and nothing calls
it from a gate. It is read, not enforced.

**The heuristic.** A router file under `<module>/backend/SOURCES/app/routers/` that declares all
four CRUD verbs (`@router.get`, `.post`, `.put`, `.delete`) is a hand-written full-CRUD
implementation — the shape a declared entity's generated router already produces for free. If that
router's own filename (`users.py` -> `users`) is not among the `key='...'` values registered in
`<module>/backend/SOURCES/app/entities/*.py`, nothing declares it, so the standard cannot already be
serving it. `permissions.py` (GET only, `read_only=True` descriptor) and `tenants.py` (no PUT — its
one hand-written route is a nested traversal, not a fourth CRUD verb) are not flagged by this
heuristic; `users.py`, `user_roles.py` and `user_profiles.py` are, because they still are exactly
what the heuristic looks for — the three pages sub-set 6 named and deferred rather than adopted.

**Silenced by a decision, never by neglect.** `<module>/backend/SPECS/custom-entities.md`, if
present, is a maintainer-authored list of entities kept custom on purpose — one bullet per entity,
naming the key in backticks followed by a reason. An entity named there is not reported: recording the decision is what turns
"nobody has gotten to this yet" into "this was decided", which is the only way silencing it does not
become a synonym for ignoring it.

    scripts/dev/common/check_standard_adoption.py                 # every module with backend routers
    scripts/dev/common/check_standard_adoption.py host_app        # one module
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

_CRUD_VERBS = ("get", "post", "put", "delete")
_METHOD_RE = re.compile(r"@router\.(get|post|put|delete|patch)\b")
_KEY_RE = re.compile(r"key\s*=\s*['\"](\w+)['\"]")
_ALLOWLIST_LINE_RE = re.compile(r"^-\s*`(\w+)`\s*:\s*(.+)$")

GUIDE_PATH = "modules/module_template/SPECS/ideable-framework-specs/adopting-the-entity-standard.md"


def declared_entity_keys(module_dir: Path) -> set[str]:
    """Every `key='...'` a module's own `app/entities/*.py` registers — never `app/entities/__init__.py`,
    which only re-exports the framework's registry functions and carries no descriptor of its own."""
    entities_dir = module_dir / "backend" / "SOURCES" / "app" / "entities"
    if not entities_dir.is_dir():
        return set()
    keys: set[str] = set()
    for entity_file in entities_dir.glob("*.py"):
        if entity_file.name == "__init__.py":
            continue
        keys.update(_KEY_RE.findall(entity_file.read_text(encoding="utf-8")))
    return keys


def custom_entities_allowlist(module_dir: Path) -> dict[str, str]:
    """A maintainer's recorded decision to keep an entity custom: key -> the reason they gave.

    Absent file means no decision has been recorded for this module — not that nothing needs one.
    """
    allow_file = module_dir / "backend" / "SPECS" / "custom-entities.md"
    if not allow_file.is_file():
        return {}
    entries: dict[str, str] = {}
    for line in allow_file.read_text(encoding="utf-8").splitlines():
        match = _ALLOWLIST_LINE_RE.match(line.strip())
        if match:
            entries[match.group(1)] = match.group(2).strip()
    return entries


def _display_path(path: Path) -> str:
    """`path` relative to the repo when it lives there; its own string otherwise (e.g. a test's
    temporary module directory) — a display helper must not raise on input a repo-relative
    assumption does not hold for."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def check_module(module_dir: Path) -> list[str]:
    """Advisory findings for one module. Never raises; an empty list is a clean report, not a
    'nothing was checked' signal — `main` already filtered to modules with a routers directory."""
    routers_dir = module_dir / "backend" / "SOURCES" / "app" / "routers"
    if not routers_dir.is_dir():
        return []

    declared = declared_entity_keys(module_dir)
    silenced = custom_entities_allowlist(module_dir)

    findings = []
    for router_file in sorted(routers_dir.glob("*.py")):
        key = router_file.stem
        if key == "__init__" or key in declared or key in silenced:
            continue
        verbs = set(_METHOD_RE.findall(router_file.read_text(encoding="utf-8")))
        if not all(verb in verbs for verb in _CRUD_VERBS):
            continue
        findings.append(
            f"{module_dir.name}: `{key}` ({_display_path(router_file)}) is a hand-written "
            f"full-CRUD router with no declared entity — the standard could serve it. Adopt it "
            f"following `{GUIDE_PATH}`, or record the decision to keep it custom as a bullet in "
            f"`{_display_path(module_dir / 'backend' / 'SPECS' / 'custom-entities.md')}` "
            f"(- `{key}`: <why>)."
        )
    return findings


def main(argv: list[str]) -> int:
    wanted = argv[1:]
    modules = sorted(
        d for d in (REPO / "modules").iterdir()
        if d.is_dir()
        and (d / "backend" / "SOURCES" / "app" / "routers").is_dir()
        and (not wanted or d.name in wanted)
    )

    total = 0
    for module_dir in modules:
        for finding in check_module(module_dir):
            print(f"ADVISORY: {finding}")
            total += 1

    if total:
        print(
            f"\n{total} entity(ies) could adopt the standard — informational only, "
            "this never fails a build."
        )
    else:
        print("No hand-written full-CRUD entity is missing a declaration, or every one is silenced "
              "by a recorded decision.")

    return 0  # Advisory: gravity never escalates a missed opportunity into a build failure.


if __name__ == "__main__":
    sys.exit(main(sys.argv))
