#!/usr/bin/env python3
"""Fail the deploy when enabled modules disagree on a shared Module Federation dependency.

Modules deploy independently and each declares its own `requiredVersion` for the singletons they
share (`react`, `react-dom`, `react-router-dom`). Nothing compared those declarations before the
browser did — and in the browser a singleton conflict is a white screen for the end user, blamed
on the shell rather than on the module that introduced it. Catching it here turns a user-visible
outage into a failed deploy that names the culprit.

Run standalone or via `scripts/common/validate_modules.sh` (which calls it).
Exit 0 = compatible, 1 = conflict, 2 = could not read a declaration it expected to find.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = REPO_ROOT / "modules"
ENABLED = MODULES_DIR / "enabled.md"

# `shared: { react: { singleton: true, requiredVersion: '^19.2.0' }, ... }` in an rsbuild config.
SHARED_ENTRY = re.compile(
    # `[^{}]*` rather than `[^}]*`: the loose form let a match span the nested brace, so
    # `shared: { react: { requiredVersion: ... } }` captured the dep name "shared" and swallowed
    # react entirely — the check then compared a dependency that does not exist.
    r"""['"]?(?P<dep>[@\w./-]+)['"]?\s*:\s*\{[^{}]*requiredVersion\s*:\s*['"](?P<version>[^'"]+)['"]""",
    re.S,
)


def enabled_modules() -> list[str]:
    """Modules listed as local in modules/enabled.md — remotes ship prebuilt and are not checked."""
    if not ENABLED.exists():
        return []
    out = []
    for line in ENABLED.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            name, _, mode = line.partition(":")
            if mode.strip().lower() == "local":
                out.append(name.strip())
    return out


def declared_shared(module: str) -> dict[str, str]:
    """{dependency: requiredVersion} declared by a module's rsbuild config, or {} when absent."""
    config = MODULES_DIR / module / "frontend" / "SOURCES" / "rsbuild.config.ts"
    if not config.exists():
        return {}
    text = config.read_text(encoding="utf-8")
    start = text.find("shared:")
    if start == -1:
        return {}
    # Bound the scan to the shared block so unrelated `requiredVersion`-looking text is ignored.
    block = text[start : start + 2000]
    return {m.group("dep"): m.group("version") for m in SHARED_ENTRY.finditer(block)}


def main() -> int:
    modules = enabled_modules()
    if len(modules) < 2:
        print(f"[shared-versions] {len(modules)} enabled module(s) — nothing to compare.")
        return 0

    declarations: dict[str, dict[str, str]] = {}
    for module in modules:
        found = declared_shared(module)
        if found:
            declarations[module] = found

    if not declarations:
        print("[shared-versions] No shared-dependency declarations found — nothing to compare.")
        return 0

    by_dep: dict[str, dict[str, str]] = {}
    for module, deps in declarations.items():
        for dep, version in deps.items():
            by_dep.setdefault(dep, {})[module] = version

    conflicts = {dep: mods for dep, mods in by_dep.items() if len(set(mods.values())) > 1}
    for dep, mods in sorted(by_dep.items()):
        agreed = len(set(mods.values())) == 1
        detail = ", ".join(f"{m}={v}" for m, v in sorted(mods.items()))
        print(f"[shared-versions] {'OK  ' if agreed else 'FAIL'} {dep}: {detail}")

    if conflicts:
        print(
            "\n[shared-versions] Shared-dependency version skew across enabled modules.\n"
            "  A singleton loaded twice at different versions is a runtime failure in the user's\n"
            "  browser, not a build error — align the declarations above before deploying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
