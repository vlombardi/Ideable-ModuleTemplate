#!/usr/bin/env python3
"""Print the test files that need nothing but a checkout, one per line.

CI runs these; the rest need Postgres, Authentik, Traefik and Docker and stay local.

**Computed, never hardcoded.** A committed list of directories would be right the day it was written
and wrong the first time someone adds a test — and it would be wrong *silently*, either dropping a
new check out of CI or breaking CI with one that needs a stack. Deriving the set from what each file
actually imports means a new test lands in the correct half by itself.

A file needs more than a checkout if it reaches for a live resource (an HTTP client, a database
driver, `docker exec`) **or** for a generated artefact such as `deployment_root/`, which a deploy
produces and git ignores. That is a deliberately blunt test. Blunt in the safe direction: a file that merely
mentions one is excluded from CI and still runs locally, so the cost of a false positive is a test
CI does not run, never a CI failure nobody can reproduce.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

def _test_roots() -> list[str]:
    """Every TESTS directory in this project, DISCOVERED rather than listed.

    A hardcoded list works only in the master repo, and this file syncs to every remote module
    project — where `modules/host_app/` holds just `module.json` and `config/` (no SOURCES, no
    TESTS), and the module's own directory is named after the module rather than
    `module_template`. A list naming either would be wrong in every remote project: it would point
    at paths that do not exist and miss the ones that do.

    Ordering is stable and shallow-first so the output is deterministic.
    """
    roots: list[str] = []
    if (REPO / "scripts" / "TESTS").is_dir():
        roots.append("scripts/TESTS")
    modules = REPO / "modules"
    if modules.is_dir():
        for d in sorted(modules.iterdir()):
            if not d.is_dir():
                continue
            if (d / "TESTS").is_dir():
                roots.append(f"modules/{d.name}/TESTS")
            for sub in sorted(p for p in d.iterdir() if p.is_dir()):
                if (sub / "TESTS").is_dir():
                    roots.append(f"modules/{d.name}/{sub.name}/TESTS")
    return roots


TEST_ROOTS = _test_roots()

# Anything that needs MORE THAN A CHECKOUT.
#
# Two categories, and the second was learned the hard way. A live resource (HTTP, a database driver,
# docker) is the obvious one. The other is a **generated artifact**: `deployment_root/` is produced
# by a deploy and is git-ignored, so it exists on a developer machine and never in CI. Five tests
# read it, passed locally, and failed in CI — the selector called them stack-free because they import
# nothing, which was true and beside the point.
#
# Verify a change here against a pristine checkout, not against this working copy:
#
#     git worktree add --detach /tmp/pristine HEAD
#     cd /tmp/pristine && <run the selected suites>
#
# That is exactly CI's condition and it reproduces this class of failure in seconds.
NEEDS_MORE_THAN_A_CHECKOUT = re.compile(
    # live resources
    r"\bimport\s+requests\b"
    r"|\bfrom\s+requests\b"
    r"|\bpsycopg2\b"
    r"|\bdocker\s+exec\b"
    r"|urllib\.request\.urlopen"
    r"|\bimport\s+docker\b"
    # generated artefacts that only a deploy produces
    r"|deployment_root"
    r"|DIST/"
    # generated config: build_and_deploy.py writes it, git ignores it
    r"|modules_menu_mapping"
    r"|module_registry\.json"
)


def _needs_more(test_file: Path) -> bool:
    """True when this test — or a `conftest.py` it inherits — needs more than a checkout.

    THE CONFTEST CHAIN MATTERS, and missing it cost a CI failure. `modules/host_app/TESTS/backend/`
    holds tests that import nothing live, so the file-level check called them stack-free; their
    conftest opens a database and every one of them errored at fixture setup in a fresh checkout.
    A test inherits its conftest's requirements whether it mentions them or not.
    """
    if NEEDS_MORE_THAN_A_CHECKOUT.search(test_file.read_text(encoding="utf-8", errors="replace")):
        return True
    d = test_file.parent
    while True:
        conf = d / "conftest.py"
        if conf.is_file():
            try:
                if NEEDS_MORE_THAN_A_CHECKOUT.search(conf.read_text(encoding="utf-8", errors="replace")):
                    return True
            except OSError:
                pass
        if d == REPO or d.parent == d:
            break
        d = d.parent
    return False


def stack_free() -> list[Path]:
    out: list[Path] = []
    for root in TEST_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("test_*.py")):
            if "node_modules" in f.parts:
                continue
            try:
                if _needs_more(f):
                    continue
                out.append(f)
            except OSError:
                continue
    return out


def main() -> int:
    files = stack_free()
    if not files:
        print("no stack-free tests found — the selector is broken, not the repo", file=sys.stderr)
        return 1

    if "--by-suite" in sys.argv:
        # ONE LINE PER SUITE, and pytest must be invoked once per line.
        #
        # Running several TESTS trees in a single pytest process makes the wrong `conftest.py` win:
        # host_app's tests get module_template's conftest and die with
        # `cannot import name 'POSTGRES_DB' from 'conftest'`. That is not a missing dependency and
        # not a stack problem — it is pytest resolving one conftest for the whole run.
        # `run_enabled_tests.sh` has always run one pytest per suite for this reason; CI does the same.
        groups: dict[str, list[str]] = {}
        for f in files:
            rel = f.relative_to(REPO)
            root = next((r for r in TEST_ROOTS if str(rel).startswith(r + "/")), str(rel.parent))
            groups.setdefault(root, []).append(str(rel))
        for root in TEST_ROOTS:
            if groups.get(root):
                print(" ".join(groups[root]))
        return 0

    for f in files:
        print(f.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
