#!/usr/bin/env python3
"""Compute the incremental work-set for `ideable-implement-specs`.

A spec hash tracks the INPUT, not the output — so this script decides only *which specs are
worth (re)implementing this run*; correctness is always established later by tests
(`Done ⇐ contract tests pass`). It is a cache HINT, never a source of truth.

A spec needs work when it CHANGED, or a spec it (transitively) references changed. This is
computed fresh every run from:
  - the **reference graph**: edges A->B when spec file A mentions spec file B (rebuilt each run,
    so added/removed references are always rediscovered — never trust a cached list);
  - the **change oracle**: `git diff` over the spec paths against a base ref (default: working
    tree vs HEAD). Git handles renames/merges and never desyncs from history.

Work-set = changed ∪ transitive-dependents(changed). With --force, work-set = every spec.

Usage:
  scripts/common/spec_workset.py [--base <git-ref>] [--force] [--json] [--modules m1,m2]

Exit code is always 0 (advisory tool); parse stdout (or --json) for the work-set.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = REPO_ROOT / "modules"

# A spec file = a Markdown file under a SPECS/ folder (base-specs, framework specs, bug-avoiders…).
SPEC_GLOB = "**/SPECS/**/*.md"

# Reuse the canonical enabled.md parser (`name: local|remote`) rather than re-implementing it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import module_deps  # noqa: E402


def enabled_modules() -> list[str]:
    """Module names from modules/enabled.md, in file order (via the canonical parser)."""
    return [name for name, _mode in module_deps.read_enabled_modules(str(MODULES_DIR))]


def collect_spec_files(modules: list[str]) -> list[Path]:
    files: set[Path] = set()
    for mod in modules:
        for p in (REPO_ROOT / "modules" / mod).glob(SPEC_GLOB):
            if p.is_file():
                files.add(p.resolve())
    return sorted(files)


def build_reference_graph(spec_files: list[Path]) -> dict[Path, set[Path]]:
    """edges[A] = {B, …} where spec A's text references spec file B.

    References are matched heuristically by (a) repo-relative path and (b) bare filename — enough
    to catch markdown links, `@path` includes, and prose mentions. Fuzzy on purpose: this only
    seeds invalidation; tests are the real gate.
    """
    by_name: dict[str, list[Path]] = {}
    for f in spec_files:
        by_name.setdefault(f.name, []).append(f)

    edges: dict[Path, set[Path]] = {f: set() for f in spec_files}
    for f in spec_files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for other in spec_files:
            if other == f:
                continue
            rel = os.path.relpath(other, REPO_ROOT)
            # Match the repo-relative path, or the bare filename only when it is unambiguous
            # (a single spec file with that name) to avoid over-linking common names.
            if rel in text or (len(by_name[other.name]) == 1 and other.name in text):
                edges[f].add(other)
    return edges


def transitive_dependents(changed: set[Path], edges: dict[Path, set[Path]]) -> set[Path]:
    """All specs that (transitively) reference something in `changed` — the reverse reachability."""
    reverse: dict[Path, set[Path]] = {f: set() for f in edges}
    for src, dsts in edges.items():
        for dst in dsts:
            reverse.setdefault(dst, set()).add(src)
    out: set[Path] = set()
    stack = list(changed)
    while stack:
        node = stack.pop()
        for dep in reverse.get(node, ()):  # dep references node
            if dep not in out:
                out.add(dep)
                stack.append(dep)
    return out


def git_changed_specs(base: str | None, spec_files: list[Path]) -> set[Path]:
    spec_set = {f.resolve() for f in spec_files}
    args = ["git", "-C", str(REPO_ROOT), "diff", "--name-only"]
    if base:
        args.append(base)  # e.g. a commit SHA / branch: compares that ref to the working tree
    try:
        out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    changed: set[Path] = set()
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = (REPO_ROOT / rel).resolve()
        if p in spec_set:
            changed.add(p)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute the incremental spec work-set.")
    ap.add_argument("--base", default=None,
                    help="git ref to diff against (default: working tree vs HEAD).")
    ap.add_argument("--force", action="store_true", help="Work-set = every spec (full run).")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a human table.")
    ap.add_argument("--modules", default=None,
                    help="Comma-separated module names to scope to (default: modules/enabled.md).")
    args = ap.parse_args()

    modules = args.modules.split(",") if args.modules else enabled_modules()
    modules = [m.strip() for m in modules if m.strip()]
    spec_files = collect_spec_files(modules)

    if not spec_files:
        print("No spec files found for scope:", ", ".join(modules) or "(none)")
        return 0

    edges = build_reference_graph(spec_files)

    if args.force:
        changed: set[Path] = set(spec_files)
        dependents: set[Path] = set()
    else:
        changed = git_changed_specs(args.base, spec_files)
        dependents = transitive_dependents(changed, edges) - changed

    work_set = changed | dependents
    skipped = [f for f in spec_files if f not in work_set]

    def rel(p: Path) -> str:
        return os.path.relpath(p, REPO_ROOT)

    if args.json:
        print(json.dumps({
            "scope": modules,
            "changed": sorted(rel(p) for p in changed),
            "dependents": sorted(rel(p) for p in dependents),
            "work_set": sorted(rel(p) for p in work_set),
            "skipped": sorted(rel(p) for p in skipped),
            "forced": args.force,
        }, indent=2))
        return 0

    print(f"Scope: {', '.join(modules)}")
    print(f"Spec files: {len(spec_files)} | work-set: {len(work_set)} | skipped: {len(skipped)}"
          + (" | (forced full run)" if args.force else ""))
    print()
    if args.force:
        print("FORCED full run — every spec is in the work-set.")
    else:
        print("CHANGED (spec itself changed):")
        for p in sorted(changed):
            print(f"  ~ {rel(p)}")
        print("DEPENDENTS (reference something changed → re-implement):")
        for p in sorted(dependents):
            print(f"  → {rel(p)}")
    print()
    print("NOTE: this is a cache hint. `Done` is decided by tests, and even SKIPPED specs must "
          "have their contract tests re-run (the skip saves implementation, not verification). "
          "Run with --force periodically / in CI for a full self-healing pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
