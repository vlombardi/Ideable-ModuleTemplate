#!/usr/bin/env python3
"""Remove the bookkeeping a released version has finished with, leaving a clean tree.

    scripts/dev/common/compact_release_bookkeeping.py --dry-run   # list what would go
    scripts/dev/common/compact_release_bookkeeping.py             # remove it and stage the removals

WHAT THIS IS FOR. A release's `worklog/<version>` tag carries `kanban/`, `implementation-plans/` and
`TEST_REPORTS/` in full, so nothing here is lost — it is retrieved with
`git show worklog/<version>:<path>`. What the purge buys is that the working set of the NEXT cycle
reads as a delta: those three folders answer "since the last release" instead of "since the
beginning", which is also what bounds the input to the next changelog.

THE SET IS NOT A NEW LIST. `implementation-plans/`, `kanban/` and `TEST_REPORTS/` are already
`BOOKKEEPING_PATHS` to `.githooks/pre-push`, `run_enabled_tests.sh` and `dev_cycle.py` — the paths
those three agree are outside the code under test. That is why the purged tree is test-equivalent to
the tagged one, and why a fourth list would be a fourth thing to keep in step. The two files that name a
release are in that set for the pre-push gate and are never purged: they ARE the release.

WHAT SURVIVES, and why each one would break something:

  - the newest `TEST_REPORTS/*-SUMMARY.md` — `.githooks/pre-push` reads `sort | tail -1`, so a
    repository holding none refuses every push;
  - `TEST_REPORTS/AGENT-RUNS.md` — a cumulative log, not a run artifact;
  - `(Done)` implementation plans — `Done` means green but UNLANDED, so removing one deletes live
    work. Only `(Merged)` and `(Cancelled)` plans have finished;
  - `kanban/todo/` and `kanban/backlog/` — the next release's input. Only `done/` and `cancelled/` are emptied;
  - `CHANGELOG.md` — cumulative, and the record that makes removing the rest safe.

IT REFUSES ON A NON-EMPTY `kanban/doing/` rather than deciding anything. A card sits there exactly
while its plan is in flight, so compacting would archive a card describing unfinished work as if it
were history. Resolving it is the maintainer's: land the plan, move the card, or revert the work as
its own change. See `rules/version-control.md` § *A release archives how it was made*.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    ).stdout


def cards_in_flight() -> list[Path]:
    doing = REPO / "kanban" / "doing"
    if not doing.is_dir():
        return []
    return sorted(p for p in doing.iterdir() if p.suffix == ".md")


def to_remove() -> list[Path]:
    out: list[Path] = []

    # `done/` and `cancelled/` are the two columns where a card is finished: landed, or ended by
    # `dev-cycle.sh cancel`. Both are history the worklog tag already carries.
    for column in ("done", "cancelled"):
        finished = REPO / "kanban" / column
        if finished.is_dir():
            out += sorted(p for p in finished.iterdir() if p.suffix == ".md")

    plans = REPO / "implementation-plans"
    if plans.is_dir():
        out += sorted(p for p in plans.iterdir() if p.name.endswith(("(Merged).md", "(Cancelled).md")))

    reports = REPO / "TEST_REPORTS"
    if reports.is_dir():
        summaries = sorted(p for p in reports.iterdir() if p.name.endswith("-SUMMARY.md"))
        keep = {reports / "AGENT-RUNS.md"}
        if summaries:
            keep.add(summaries[-1])
        out += sorted(p for p in reports.iterdir() if p not in keep)

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="list what would be removed; change nothing")
    args = ap.parse_args()

    in_flight = cards_in_flight()
    if in_flight:
        print("[compact] refusing: a plan is in flight — kanban/doing/ is not empty:", file=sys.stderr)
        for card in in_flight:
            print(f"[compact]   {card.relative_to(REPO)}", file=sys.stderr)
        print(
            "[compact] Resolve each one, then publish again:\n"
            "[compact]   - land the plan   — dev-cycle.sh deliver moves the card to kanban/done/\n"
            "[compact]   - kanban/todo/    — next up, but not in this release\n"
            "[compact]   - kanban/backlog/ — deferred\n"
            "[compact]   - revert the work — as its own change, BEFORE the publish, never inside it\n"
            "[compact] rules/version-control.md § A release archives how it was made",
            file=sys.stderr,
        )
        return 1

    victims = to_remove()
    if not victims:
        print("[compact] nothing to compact — the tree is already clean.")
        return 0

    if args.dry_run:
        print(f"[compact] --dry-run: would remove {len(victims)} path(s):")
        for v in victims[:20]:
            print(f"[compact]   {v.relative_to(REPO)}")
        if len(victims) > 20:
            print(f"[compact]   … and {len(victims) - 20} more")
        return 0

    tracked = set(_git("ls-files").splitlines())
    staged = 0
    for v in victims:
        rel = str(v.relative_to(REPO))
        if rel in tracked:
            subprocess.run(["git", "-C", str(REPO), "rm", "-r", "-q", "--", rel], check=True)
            staged += 1
        elif v.is_dir():
            subprocess.run(["rm", "-rf", str(v)], check=True)
        else:
            v.unlink(missing_ok=True)

    print(f"[compact] removed {len(victims)} path(s); {staged} staged for commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
