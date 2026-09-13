#!/usr/bin/env python3
"""Thin, deterministic dev-cycle router for the Ideable development loop.

The Ideable skills are the ARCS and the dev-cycle states are the NODES of a graph
(canonical definition + colour convention live in `rules/implementation-plan.md`). This script
is the deterministic router over that graph — it does NOT run LLM steps (those stay with the
agent/human, per the decision-authority rule). It:

  - reads the **active implementation plan** — the one named by an `ACTIVE PLAN - <desc>.md` link
    in implementation-plans/, which the `start` action creates. Becoming the active plan is an
    ACT: a plan file with no link is work somebody wrote down, not work in hand, and counting
    links rather than files is also what makes one plan one plan under `--keep-history`,
  - shows the current node + the recommended next transition (which skill drives it),
  - deterministically **recolours** the plan's Mermaid graph, sets `Current step` + `Last updated`
    (the `--set` action — the same Overall-view update the skills perform),
  - **executes** the current node and **advances** the plan (`run`): deterministic nodes
    (`BuildDeploy` -> redeploy.sh, `Testing` -> run_enabled_tests.sh) run here and the
    highlight moves on (Testing branches on the exit code: pass → `Documenting`, fail →
    `Fixing`). After a `Testing` run it folds the
    latest TEST_REPORTS SUMMARY into the plan — setting each thing's BE/FE test cell (BE ⇐ the
    module's pytest suite, FE ⇐ its playwright suite) and the Repos `Tests` counts. A node whose
    INPUT THE SUB-SET'S DIFF CANNOT TOUCH is skipped and the skip is written into the plan with its
    reason: a sub-set that changed no build input runs no `BuildDeploy`. The tests are never skipped
    and never scoped. LLM nodes
    (`Implementing`/`Fixing`/`Documenting`/`Committing`) are **performed automatically** via a headless agent
    Agent SDK **by default**, ANSWERING it as it works — permissions and questions reach the
    person who ran the command (DEV_CYCLE_AGENT_PERMISSIONS sets the policy) — and rendering its
    messages and tool calls live so a long step is visible rather than silent (DEV_CYCLE_AGENT_QUIET=1 opts
    out), and falling back to suggesting the skill when the CLI is unavailable; with
    `--deterministic` they are not run — the router suggests the skill and stops. After a
    `Committing` step it folds the branch's commits into the plan's Repos `Commit` cells, so a
    plan can never reach `Done` still claiming `Not committed`.
    Each LLM node is handed a **brief** — the node, the executing sub-set's rows, what is already
    decided, the last recorded verdict and the sub-set's diff — instead of being told to read a
    170 KB plan, and the AGENT SESSION IS RESUMED across the nodes of one sub-set, so `Documenting`
    and `Committing` are performed by the agent that did the `Implementing`. A new sub-set starts a
    fresh agent, which is where "the plan is the whole context" earns its keep;
    `DEV_CYCLE_AGENT_SESSION` moves that boundary (`per-sub-set` · `per-plan` · `per-node`).
    `--auto-advance` chains steps so one command drives the plan forward;
    The plan file is named `<date> - <time> - <description> (<state>).md` and is **renamed** on
    every transition — timestamp re-stamped at execution, state updated — so the name shows when
    the run last moved and where it stands (the creation time lives in the file's `Created at`).
    `--keep-history` keeps every transition's file instead of rolling a single one.
  - can **park a plan and pick it up again**: `pause [<description>]` commits the tree on the
    plan's branch, renames the plan `(Paused)` while leaving the graph's highlight on the node to
    resume at, drops the `ACTIVE PLAN` name and checks the delivery target out, so the next plan
    branches from a clean base. `resume [<description>]` reverses it — a paused plan is found by
    asking the `plan/*` branches (its file is on its own branch, never in the working tree), its
    branch is checked out, and the plan is renamed back onto the node it left. The two are
    symmetric: bare `pause` when exactly one plan is in flight, bare `resume` when exactly one is
    paused, and with more each lists them and stops, because which plan is the work in hand is a
    decision. Naming the plan is what lets the two-plans refusal's own remedy reach the plan the
    reader means.
  - is **branch-per-plan** (always on; `DEV_CYCLE_NO_GIT=1` disables it): a plan starts at
    `NotStarted`, the `Branching` node creates and checks out `plan/<description>`, and from then
    on `run` works on that branch (re-ensuring it if missing), commits the working tree there
    after each execution, and — once the plan reaches `Done` — suggests `deliver`, which is
    what lands the branch (as one squashed commit, or as a PR with `--pr`). `run` never lands
    anything itself.

Usage:
  scripts/dev/common/dev-cycle.sh status                    # where are we + what's next (default)
  scripts/dev/common/dev-cycle.sh start <desc>              # make that plan the active one (NotStarted only)
  scripts/dev/common/dev-cycle.sh run                        # run the current node and advance one step
                                                  #   (agent nodes are auto-invoked by default)
  scripts/dev/common/dev-cycle.sh run --auto-advance         # drive to Done (bounded by a safety cap)
  scripts/dev/common/dev-cycle.sh run --auto-advance 3       # advance exactly 3 steps
  scripts/dev/common/dev-cycle.sh run --deterministic        # advance only deterministic nodes; suggest the
                                                  #   skill (do NOT auto-invoke) at LLM nodes
  scripts/dev/common/dev-cycle.sh run --auto-advance --keep-history   # keep every transition's plan file
  scripts/dev/common/dev-cycle.sh pause [<desc>]             # park a plan on its branch and check the
                                                  #   target out (bare: the only plan in flight)
  scripts/dev/common/dev-cycle.sh resume [<desc>]            # pick a paused plan up at the node it left
  scripts/dev/common/dev-cycle.sh deliver --pr               # open the delivery PULL REQUEST
                                                  #   (target untouched; branch kept)
                                                  #   (default: one file, renamed per state)
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLANS_DIR = REPO_ROOT / "implementation-plans"

# Canonical nodes (must match rules/implementation-plan.md). Order is the happy-path order.
NODES = ["NotStarted", "Branching", "Implementing", "BuildDeploy", "Testing", "Fixing",
         "Documenting", "Committing", "Done", "Merged", "Asking"]

# How a node is written where a human reads it (`Current step`). Only the ids that are not already
# readable English appear here; the mermaid id must stay a single word.
#
# `Asking` is the node formerly drawn as `Blocked (human gate)`. The name was the reader's problem
# and not the router's: *blocked* says the plan is stuck and names no way out, while what has
# actually happened is that the run needs a person to decide something — the maintainer is the
# resource it is waiting on, and the remedy is to answer. The row symbol `⛔ Blocked` is a
# DIFFERENT vocabulary item and deliberately unchanged: it marks one THING in the table as unable
# to proceed, not the plan as waiting on the maintainer.
NODE_DISPLAY = {"NotStarted": "Not started", "BuildDeploy": "Building & Deploying",
                "Asking": "Asking human direction"}

# node -> (which skill/tool drives leaving it, is it deterministic-runnable by this script)
DRIVER = {
    # The two nodes before any work. `NotStarted` is where a freshly written plan sits: no branch,
    # nothing executed. `Branching` is the one step whose whole job is `git checkout -b
    # plan/<description>` — it is a node rather than a side effect of the first run so that a plan
    # at `NotStarted` is provably still on the branch it was written on, and so the picture shows
    # the branch being created rather than it silently appearing. Both are performed by the router.
    "NotStarted": ("./scripts/dev/common/dev-cycle.sh run (nothing to do — advances to Branching)", None),
    "Branching": ("./scripts/dev/common/dev-cycle.sh run (creates + checks out plan/<description>)", None),
    "Implementing": ("ideable-implement-specs (agent)", None),
    "BuildDeploy": ("ideable-build-and-deploy / ./redeploy.sh", str(REPO_ROOT / "redeploy.sh")),
    "Testing": ("ideable-test-and-fix / run_enabled_tests.sh",
                str(REPO_ROOT / "scripts" / "dev" / "common" / "run_enabled_tests.sh")),
    "Fixing": ("ideable-test-and-fix (fix) / ideable-bugfixing-and-changes → ideable-spec-driven-edit (agent)", None),
    "Documenting": ("ideable-align-docs (agent)", None),
    "Committing": ("ideable-commit-changes (agent)", None),
    "Done": ("./scripts/dev/common/dev-cycle.sh deliver", None),
    "Merged": ("— (terminal)", None),
    "Asking": ("— (human decision required)", None),
}

# Recommended next node(s) from each node (the graph edges).
NEXT = {
    "NotStarted": ["Branching"],
    "Branching": ["Implementing"],
    "Implementing": ["BuildDeploy"],
    "BuildDeploy": ["Testing"],
    "Testing": ["Documenting (if pass)", "Fixing (if fail)"],
    "Fixing": ["BuildDeploy"],
    "Documenting": ["Committing"],
    "Committing": ["Done (all sub-sets done)", "Implementing (next sub-set)"],
    "Done": ["Merged (via `deliver`, on the maintainer's say-so)"],
    "Merged": [],
    "Asking": [],
}

# Unconditional single successor (used when advancing after a node completes). `Testing`
# is intentionally absent — it branches on the test runner's exit code (see `next_after`).
NEXT_SINGLE = {
    "NotStarted": "Branching",
    "Branching": "Implementing",
    "Implementing": "BuildDeploy",
    "BuildDeploy": "Testing",
    "Fixing": "BuildDeploy",
    "Documenting": "Committing",
    "Committing": "Done",
}

# `Done` -> `Merged` is deliberately NOT in NEXT_SINGLE: `run` must never take it. Landing the work
# on a shared branch is the maintainer's decision (which target, and whether yet), so it is reached
# only by the explicit `deliver` subcommand.

# LLM nodes → the single skill the router auto-invokes for them (unless --deterministic).
# (Deterministic nodes are absent — they run their runner, not a skill.)
SKILL_CMD = {
    "Implementing": "ideable-implement-specs",
    "Fixing": "ideable-bugfixing-and-changes",
    "Documenting": "ideable-align-docs",
    "Committing": "ideable-commit-changes",
}

# Safety bound for `--auto-advance` (until-Done): stops a runaway Testing→Fixing→…→Testing loop.
HARD_CAP = 100

# Where an agent session id is kept between processes. One `run` is one node, so the session that
# performed it is gone from memory before the next node starts — and the sub-set the session belongs
# to spans several `run` invocations. Beside the locks, and for the same reasons: git-ignored, local
# to the machine, and keyed on the plan's DESCRIPTION because its filename changes at every
# transition.
SESSIONS_DIR = REPO_ROOT / ".ideable-work" / "dev-cycle-sessions"

# Paths a build and a deploy provably cannot read. Everything else counts as a build input, so an
# UNKNOWN path means `BuildDeploy` runs: the skip has to be provable, and the cost of the two
# mistakes is not symmetric — a needless build wastes three minutes, a skipped one tests the
# previous build and calls the result this sub-set's.
#
# `modules/`, `reusable.ui/`, `scripts/dev/`, `scripts/runtime/`, `framework.env` and the root env
# files are deliberately absent: each is read by `build_and_deploy.py`, by `validate_modules.sh`, or
# by a `SPECS/build.sh`, so a change to any of them can reach a container.
NON_BUILD_INPUTS = (
    "implementation-plans/", "kanban/", "TEST_REPORTS/", "rules/",
    ".agents/", ".claude/", ".cursor/", ".devin/", ".kiro/", ".github/", ".githooks/",
    ".ideable-work/", "tmp/", "scripts/TESTS/", "scripts/SPECS/", "scripts/README.md",
    "AGENTS.md", "CLAUDE.md", "README.md", "IDEABLE-README.md",
)


def next_after(node: str, rc: int) -> str:
    """The node to advance to after `node` finishes. `Testing` branches on the runner exit
    code (0 → Documenting, non-zero → Fixing); every other node has one successor."""
    if node == "Testing":
        return "Documenting" if rc == 0 else "Fixing"
    return NEXT_SINGLE[node]


# --- Live progress rendering for the headless agent -------------------------------------------

# How a tool call is summarised on one line: tool name -> the input field worth showing.
_TOOL_SUMMARY_FIELD = {
    "Bash": "command", "Read": "file_path", "Write": "file_path", "Edit": "file_path",
    "NotebookEdit": "notebook_path", "Grep": "pattern", "Glob": "pattern",
    "WebFetch": "url", "WebSearch": "query", "Task": "description", "Skill": "skill",
}
_AGENT_PREFIX = "[agent]"


def _clip(text: str, width: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _tool_summary(name: str, tool_input: dict) -> str:
    """`Bash(git status)` — the one field that says what this call actually does."""
    if not isinstance(tool_input, dict) or not tool_input:
        return name
    field = _TOOL_SUMMARY_FIELD.get(name)
    value = tool_input.get(field) if field else None
    if value is None:
        key = next(iter(tool_input))
        value = f"{key}={tool_input[key]}"
    return f"{name}({_clip(value, 120)})"


def _conversation():
    """`scripts/dev/common/agent_conversation.py`, imported lazily.

    Lazily because this file is otherwise stdlib-only and runs on the host: a module-level sibling
    import would make the router unimportable wherever the conversation module is absent, and the
    conversation is an OPTIONAL feature — `--deterministic` drives the whole cycle without it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import agent_conversation

    return agent_conversation


# --- One agent per sub-set: the session store --------------------------------------------------
#
# A session has to be remembered ACROSS PROCESSES. One `run` performs one node and exits, so the
# agent that did `Implementing` is gone before `Documenting` starts — while the scope that session
# belongs to, the sub-set, spans four or five invocations. Kept beside the locks for the same three
# reasons: git-ignored, local to this machine, and keyed on the plan's description.


def _session_path(plan: Path) -> Path:
    """One session record per plan, keyed by its DESCRIPTION — the only part of a plan's name that
    does not change. The same key as the lock, and for the same reason."""
    return SESSIONS_DIR / f"{plan_branch(plan).removeprefix('plan/')}.json"


def session_scope(text: str, granularity: str) -> str | None:
    """What a session may outlive, as a string two nodes can compare. None means: never reuse one.

    `per-node` has no scope, so nothing is remembered. `per-plan` is the plan. `per-sub-set` is the
    executing sub-set — and a plan with NO sub-set table degenerates to the plan deliberately: such
    a plan has exactly one scope, and treating it as unscoped would make the default behave like
    `per-node` for the smallest plans, which is where one session costs least and saves most.
    """
    if granularity == "per-node":
        return None
    if granularity == "per-plan":
        return "plan"
    executing = current_subset(text)
    return f"sub-set {executing['index'] + 1}" if executing else "plan"


def load_session(plan: Path, scope: str | None) -> str | None:
    """The session to resume for this scope, or None. A record for a scope that has moved on is
    not reused — that is the whole of "a new sub-set starts a fresh session"."""
    if not scope:
        return None
    try:
        record = json.loads(_session_path(plan).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record.get("session") or None if record.get("scope") == scope else None


def save_session(plan: Path, scope: str | None, session_id: str | None, node: str) -> None:
    """Remember the session that performed a node, so the next node of the same scope resumes it.

    Never raises: a session that could not be written costs a rebuild at the next node, which is
    the behaviour before this existed — not a reason to fail a node whose work is already done.
    """
    if not scope or not session_id:
        return
    with contextlib.suppress(OSError):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        _session_path(plan).write_text(
            json.dumps({"scope": scope, "session": session_id, "node": node, "updated": _now()},
                       indent=2) + "\n", encoding="utf-8")


def drop_session(plan: Path) -> None:
    """Forget this plan's session. Delivery ends the run that owned it."""
    with contextlib.suppress(OSError):
        _session_path(plan).unlink(missing_ok=True)


# --- What a sub-set changed, and whether a node's input is in it -------------------------------


def subset_diff_base() -> str | None:
    """The commit a sub-set's own diff starts from: the newest CURATED commit on the branch.

    Every sub-set ends at `Committing` with a curated commit and the router's checkpoints sit
    between them, so everything after the last curated one is this sub-set's work and nothing else's.
    Deriving the boundary from the checkpoints instead does not work: a sub-set that loops
    `Documenting → Implementing` writes a second `→ Implementing` checkpoint inside itself.
    """
    if not _git_enabled():
        return None
    r = _git("log", "--format=%h%x00%s", f"{DEFAULT_TARGET}..HEAD", capture=True)
    if r.returncode == 0:
        for entry in (r.stdout or "").strip().splitlines():
            sha, _, subject = entry.partition("\0")
            if sha and not _is_checkpoint(subject):
                return sha
    base = _git("merge-base", DEFAULT_TARGET, "HEAD", capture=True)
    return base.stdout.strip() if base.returncode == 0 and base.stdout.strip() else None


def subset_diff(base: str | None) -> list[str]:
    """The paths this sub-set has touched: committed since `base`, plus the working tree.

    Both halves, because a node reads the plan at a point where the two are routinely different —
    `Documenting` runs on work that is written and not yet committed, and `Committing` on work that
    is partly both.
    """
    if not _git_enabled():
        return []
    paths: set[str] = set()
    if base:
        r = _git("diff", "--name-only", f"{base}..HEAD", capture=True)
        if r.returncode == 0:
            paths.update(p.strip() for p in (r.stdout or "").splitlines() if p.strip())
    status = _git("status", "--porcelain", capture=True)
    if status.returncode == 0:
        for line in (status.stdout or "").splitlines():
            entry = line[3:].strip()
            if " -> " in entry:  # a rename changed two paths, and both are part of the diff
                before, _, after = entry.partition(" -> ")
                paths.update({before.strip().strip('"'), after.strip().strip('"')})
            elif entry:
                paths.add(entry.strip('"'))
    return sorted(p for p in paths if p)


def is_build_input(path: str) -> bool:
    """Whether a changed path can reach a container. An unknown path counts as one — see
    `NON_BUILD_INPUTS` for why the two mistakes are not worth the same."""
    return not any(path == known or path.startswith(known) for known in NON_BUILD_INPUTS)


def build_skip_reason() -> str | None:
    """Why this sub-set needs no build, or None when it does — and "I cannot tell" is None.

    TESTS ARE NEVER SKIPPED AND NEVER SCOPED, and the asymmetry is deliberate: the suite is ~8% of a
    cycle and has caught a regression in a module the sub-set never named. What is removed here is
    work whose INPUT is absent; scoping the tests would remove a check whose output was assumed.
    """
    if not _git_enabled():
        return None
    paths = subset_diff(subset_diff_base())
    if not paths:
        # A diff nothing could be read from is not a diff known to be empty. Saying otherwise would
        # make an unreadable repository look like a docs-only sub-set.
        return None
    if any(is_build_input(p) for p in paths):
        return None
    shown = ", ".join(paths[:5]) + (", …" if len(paths) > 5 else "")
    return f"{len(paths)} changed path(s), none of them a build input ({shown})"


# --- The brief the router hands an LLM node ----------------------------------------------------


def subset_table(text: str, index: int) -> list[str]:
    """The Main table's sub-table at `index`, verbatim — heading, header and rows.

    Selected by POSITION rather than by description, because the two spellings are allowed to
    differ: on the plan this was written for, the sub-table heading carries the short form and the
    Overall view's row the whole sentence. § *Sub-sets* fixes the order of both, so position is the
    thing they actually agree on.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Main implementation summary" in l), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    seen, out, taking = -1, [], False
    for line in lines[start + 1:end]:
        stripped = line.strip()
        if stripped.startswith("#"):
            seen += 1
            taking = seen == index
            if taking:
                out.append(stripped)
            continue
        if taking and stripped:
            out.append(stripped)
    return out


def node_brief(plan: Path, node: str) -> str:
    """What the router already knows and the node would otherwise spend its first turns rebuilding.

    IT DOES NOT REPLACE THE PLAN, and it says so in its own last line. A brief that claimed to be
    complete would be the next thing to go stale, and the plan is the artifact every rule points at.
    What it removes is the part of a node's reading that is identical every time and derivable here:
    which node, which sub-set, which rows, what was already decided, what the last run said, and
    what has changed. Measured on this plan at roughly 30 tool calls and 45k tokens per node against
    a 170 KB file.
    """
    try:
        text = plan.read_text(encoding="utf-8")
    except OSError:
        return ""
    out: list[str] = [
        "--- BRIEF (assembled by the router; the plan remains the authority) ---",
        f"Plan file: implementation-plans/{plan.name}",
        f"Node: {NODE_DISPLAY.get(node, node)}",
    ]
    executing = current_subset(text)
    if executing is not None:
        out.append(f"Executing sub-set: {executing['index'] + 1} of {len(subsets(text))} — "
                   f"{executing['description']}")

    purpose = plan_purpose(text)
    if purpose:
        out += ["", "## Why this plan exists", *purpose]

    rows = subset_table(text, executing["index"]) if executing is not None else []
    if rows:
        out += ["", "## The rows this node is answerable for", *rows]

    decided = subset_decisions(text, executing["index"] if executing is not None else None)
    if decided:
        out += ["", "## Already decided — do not take these again (this sub-set's rows, and every "
                    "maintainer answer, whichever sub-set it was given in)", *decided]

    summary = latest_summary()
    if summary is not None:
        verdict = summary_verdict(summary) or "no `Overall:` line in the SUMMARY"
        out += ["", "## Last recorded test run",
                f"{summary.parent.name}/{summary.name}: {verdict}"]

    base = subset_diff_base()
    paths = subset_diff(base)
    if paths:
        out += ["", f"## What this sub-set has changed ({len(paths)} path(s)"
                    f"{f', since {base}' if base else ''}, committed and working tree)",
                *[f"- {p}" for p in paths[:60]]]
        if len(paths) > 60:
            out.append(f"- … and {len(paths) - 60} more")

    out += ["", "Anything this brief does not carry is in the plan file named above — read it for "
                "that, not for what is already here.",
            "--- END BRIEF ---"]
    return "\n".join(out)


# --- The one place a plan records what was decided ----------------------------------------------
#
# ONE CHAPTER, BEFORE CHAPTER 1. A decision recorded in two places is recorded in two shapes: the
# router's answers block carried `Asked by` and no `Why`, the nodes' `#### Decisions taken …` tables
# carried `Why` and no `Asked by`, and neither carried a timestamp. Measured on the plan that
# prompted this: 4 answers and 22 decisions across 26 tables, the 4 answers in both places, and no
# way to read any of them in the order they were taken. One table, one row per decision, newest
# last, with `When` first.
#
# IT IS THE FIRST CHAPTER because a resuming agent must meet it before anything else. That position
# is what makes a fresh agent per sub-set safe: what the previous agent settled is the first thing
# the next one reads, rather than the thing it finds after six sections of narrative — or does not
# find, and decides again, differently.
#
# DELIMITED BY HTML COMMENTS, like the blocked record and for the same reason: creating, appending
# to and migrating it have to be exact, and a heading is prose that gets edited.

DECISIONS_OPEN = "<!-- dev-cycle:decisions -->"
DECISIONS_CLOSE = "<!-- /dev-cycle:decisions -->"
DECISIONS_HEADING = "## Decisions and answers"
DECISIONS_COLUMNS = ("When", "Node", "Sub-set", "Question", "Decision", "Who", "Why")

#: The mark a row carries when it came from an `Asking human direction` block — the glyph that
#: block's own heading uses, so the questions the maintainer was actually stopped for stay readable
#: as a subset of the chapter by one grep rather than by a second table.
ASKED_MARK = "⛔"

#: The three kinds of author a row can have. `maintainer` is different in kind from the other two,
#: which is the whole reason the column exists: a maintainer's decision may not be revisited
#: without asking again, while an agent's judgement or the router's rule-following may be.
DECISION_AUTHORS = ("maintainer", "agent", "router")


def _cell(value: object) -> str:
    """One table cell: whitespace collapsed and `|` escaped, so a row can never break the table.

    Escaped as the HTML entity rather than `\\|`, because the row is READ BACK — by the brief, by
    the checks, and by the next writer — and a backslash-escaped pipe is still a pipe to anything
    that splits on one. Measured on the migration: a legacy row carrying
    `` `Committing -->|next sub-set| Implementing` `` round-tripped into a row whose `Who` cell was
    a fragment of its own question.
    """
    out = " ".join(str(value if value not in (None, "") else "—").split())
    return out.replace("|", "&#124;")


def _decisions_block(rows: list[str]) -> str:
    return "\n".join([
        DECISIONS_OPEN,
        "",
        DECISIONS_HEADING,
        "",
        "Every choice this plan did not already contain, newest last — what a node decided on its "
        "own, and what the maintainer answered. **A decision recorded here is not taken again.** "
        "The node that took it is not the node that lives with it: the next one may be a fresh "
        "agent whose whole context is this file.",
        "",
        f"`Who` is `{'` · `'.join(DECISION_AUTHORS)}`, and the first is different in kind — a "
        f"maintainer's decision may not be revisited without asking them again. A `Node` cell "
        f"marked {ASKED_MARK} is a row that came from an `Asking human direction` block, so the "
        f"questions the plan was actually stopped for stay readable as a subset.",
        "",
        "| " + " | ".join(DECISIONS_COLUMNS) + " |",
        "|" + "|".join(["---"] * len(DECISIONS_COLUMNS)) + "|",
        *rows,
        "",
        DECISIONS_CLOSE,
    ])


def _decision_row(question: str, decision: str, who: str, why: str,
                  node: str = "", subset: object = "", when: str | None = None,
                  asked: bool = False) -> str:
    node_cell = _cell(node)
    if asked:
        node_cell = f"{ASKED_MARK} {node_cell}"
    return "| " + " | ".join([_cell(when or _now()), node_cell, _cell(subset),
                              _cell(question), _cell(decision), _cell(who), _cell(why)]) + " |"


def _without_when(row: str) -> str:
    """A row minus its `When` cell — what two records of the same decision have in common."""
    return "|".join(row.split("|")[2:])


def record_decision(text: str, question: str, decision: str, who: str, why: str,
                    node: str = "", subset: object = "", when: str | None = None,
                    asked: bool = False) -> str:
    """Append one row to the plan's `Decisions and answers` chapter, creating it if absent.

    Every writer goes through here — the router's own decisions, the maintainer's answers, and a
    node handing over a row the way it hands over a `Docs` cell — because one record with three
    authors is the point, and three writers each building their own table is what it replaces.

    Idempotent on everything but `When`: a node reached twice in one sub-set decides the same thing
    twice, and a second identical row would read as a decision that was taken again.
    """
    text = migrate_decisions(text)
    row = _decision_row(question, decision, who, why, node, subset, when, asked)
    bounds = _marked_block(text, DECISIONS_OPEN, DECISIONS_CLOSE)
    if bounds is None:
        block = _decisions_block([row])
        # BELOW A BLOCKED RECORD, ABOVE EVERYTHING ELSE. A plan that is Asking human direction leads
        # with the question, because that is what its reader is being asked for; the chapter is the
        # next thing they meet.
        blocked = _marked_block(text, BLOCKED_OPEN, BLOCKED_CLOSE)
        if blocked is not None:
            at = blocked[1]
            return text[:at].rstrip("\n") + "\n\n" + block + "\n\n" + text[at:].lstrip("\n")
        return _insert_at_top(text, block)
    start, end = bounds
    body = text[start:end]
    if any(_without_when(row) == _without_when(existing)
           for existing in body.splitlines() if existing.startswith("|")):
        return text
    close_at = text.rindex(DECISIONS_CLOSE, start, end)
    return text[:close_at].rstrip("\n") + "\n" + row + "\n\n" + text[close_at:]


def decision_rows(text: str) -> list[list[str]]:
    """The chapter's rows as lists of cells, header and separator excluded, in the order written."""
    bounds = _marked_block(text, DECISIONS_OPEN, DECISIONS_CLOSE)
    if bounds is None:
        return []
    out = []
    for line in text[bounds[0]:bounds[1]].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells[:len(DECISIONS_COLUMNS)] == list(DECISIONS_COLUMNS):
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        out.append(cells)
    return out


def subset_decisions(text: str, index: int | None) -> list[str]:
    """The rows a node of this sub-set must not take again, rendered as a table for the brief.

    Not the whole chapter: on a nine-sub-set plan that is most of the file, which is the cost the
    brief exists to remove rather than to relocate. What is carried is this sub-set's own rows, the
    plan-wide ones, and **every maintainer answer whatever sub-set it was given in** — a maintainer
    ruling binds the plan, not the sub-set that happened to provoke it.
    """
    rows = decision_rows(text)
    if not rows:
        return []
    want = "—" if index is None else str(index + 1)
    kept = [r for r in rows
            if r[2] in (want, "—") or (len(r) > 5 and r[5].strip("`* ") == "maintainer")]
    if not kept:
        return []
    return ["| " + " | ".join(DECISIONS_COLUMNS) + " |",
            "|" + "|".join(["---"] * len(DECISIONS_COLUMNS)) + "|",
            *["| " + " | ".join(r) + " |" for r in kept]]


# --- Migrating a plan written before the two records were merged --------------------------------

_LEGACY_ANSWERS_OPEN = "<!-- dev-cycle:answers -->"
_LEGACY_ANSWERS_CLOSE = "<!-- /dev-cycle:answers -->"
_LEGACY_DECISIONS_HEADING = re.compile(r"^####\s+Decisions taken\b.*$")
_WHO_AND_DATE = re.compile(r"^[`*\s]*(?P<who>maintainer|[A-Za-z][\w &`]*?)[`*\s]*,\s*"
                           r"(?P<when>\d{4}-\d{2}-\d{2}[^|]*?)\s*$")


def _split_legacy_owner(cell: str) -> tuple[str, str, str]:
    """A legacy `Who` cell → `(who, node, when)`.

    The old column packed three facts into one: `maintainer, <date>` for the person and
    `<Node>, <date>` for a node that took it under an existing rule. The chapter gives each its own
    column, so a reader can sort by time and filter by author without parsing prose.
    """
    m = _WHO_AND_DATE.match(cell.strip())
    if not m:
        return ("agent", cell.strip().strip("`* ") or "—", "")
    owner, when = m.group("who").strip(), m.group("when").strip()
    if owner.lower().startswith("maintainer"):
        return ("maintainer", "—", when)
    return ("agent", owner, when)


def _split_legacy_row(line: str, trailing: int = 2) -> list[str] | None:
    """A legacy 4-column row → `[question, decision, who, rest]`, tolerating an unescaped `|`.

    Hand-written rows are not all well-formed markdown: rows on the plan that prompted the merge
    carried `` `Committing -->|next sub-set| Implementing` `` inside a cell, in the question of one
    and in the `Why` of another, so neither counting from the left nor counting from the right finds
    the columns. **`Who` is the anchor** — it is the one cell with a fixed shape, `<name>, <date>` —
    and the columns are read outwards from it. Best-effort by nature: what the chapter writes itself
    is escaped by `_cell`, so this arises only for text written by hand.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) < 2 + trailing or set("".join(cells)) <= set("-: "):
        return None
    at = next((i for i in range(len(cells) - 1, 0, -1) if _WHO_AND_DATE.match(cells[i])), None)
    if at is None:
        at = len(cells) - trailing
    left, who, right = cells[:at], cells[at], cells[at + 1:]
    if not left:
        return None
    question = " | ".join(left[:-1]) if len(left) > 1 else left[0]
    decision = left[-1] if len(left) > 1 else "—"
    return [question, decision, who, " | ".join(right) or "—"]


def _legacy_tables(lines: list[str]) -> list[tuple[int, int, str]]:
    """`(start, end, heading)` for each `#### Decisions taken …` section.

    `end` is the end of the FIRST contiguous table under the heading, not the next heading: a
    `####` section runs on through paragraphs and sub-task tables that have nothing to do with the
    decisions record, and taking everything up to the next heading swept those rows in too.
    """
    out = []
    for i, line in enumerate(lines):
        if not _LEGACY_DECISIONS_HEADING.match(line.strip()):
            continue
        end, started = i + 1, False
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped.startswith("|"):
                started, end = True, end + 1
                continue
            if not stripped and not started:
                end += 1
                continue
            break
        out.append((i, end, line.strip()))
    return out


def migrate_decisions(text: str) -> str:
    """Fold a plan's legacy records into the one chapter and remove them. A no-op when there are none.

    A plan written before the merge carries the router's `Answers the maintainer gave …` block and
    the nodes' `#### Decisions taken while …` tables. They are migrated rather than left alone: two
    places recording one thing IS the defect, and a plan still in flight when the format changed
    would otherwise keep half of what it decided somewhere no node is told to read. `Asked by`
    folds into `Node`, `Why` is kept, and an answer that came from a blocked record keeps the
    `ASKED_MARK` that says so.

    Delivered plans are NOT rewritten by this: a `(Merged)` plan is a record of what was true then,
    and nothing calls this on one.
    """
    rows: list[tuple[str, dict]] = []
    bounds = _marked_block(text, _LEGACY_ANSWERS_OPEN, _LEGACY_ANSWERS_CLOSE)
    if bounds is not None:
        for line in text[bounds[0]:bounds[1]].splitlines():
            cells = _split_legacy_row(line, trailing=2)
            if cells is None or cells[0] == "Question":
                continue
            who, _node, when = _split_legacy_owner(cells[2])
            rows.append((when, dict(
                question=cells[0], decision=cells[1], who=who or "maintainer", when=when or "—",
                why="A maintainer ruling — it may not be revisited without asking them again",
                node=cells[3], subset="—", asked=True)))
        text = _drop_block(text, _LEGACY_ANSWERS_OPEN, _LEGACY_ANSWERS_CLOSE)

    lines = text.splitlines()
    tables = _legacy_tables(lines)
    for start, end, heading in tables:
        m = re.search(r"sub-set\s+(\d+)", heading)
        subset = m.group(1) if m else "—"
        routing = "routing" in heading.lower()
        for line in lines[start + 1:end]:
            cells = _split_legacy_row(line, trailing=2)
            if cells is None or cells[0] == "Question":
                continue
            who, node, when = _split_legacy_owner(cells[2])
            rows.append((when, dict(question=cells[0], decision=cells[1],
                                    who="router" if routing else who,
                                    why=cells[3], node=node, subset=subset, when=when or "—")))
    for start, end, _heading in reversed(tables):
        while end > start and not lines[end - 1].strip():
            end -= 1
        del lines[start:end]
    if tables:
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    if not rows:
        return text

    # NEWEST LAST, which is the chapter's whole ordering contract. The legacy tables were written
    # newest-first by the nodes that appended them, so migrating in file order would invert the one
    # property the merge exists to give a reader.
    rows.sort(key=lambda r: r[0] if r[0] and r[0] != "—" else "")
    migrated = [_decision_row(**fields) for _when, fields in rows]
    bounds = _marked_block(text, DECISIONS_OPEN, DECISIONS_CLOSE)
    if bounds is None:
        return _insert_at_top(text, _decisions_block(migrated))
    close_at = text.rindex(DECISIONS_CLOSE, bounds[0], bounds[1])
    return (text[:close_at].rstrip("\n") + "\n" + "\n".join(migrated) + "\n\n" + text[close_at:])


def invoke_skill_headless(node: str, skill: str, unanswered=None,
                          plan: Path | None = None) -> tuple[bool, str | None]:
    """Perform an LLM node by running an agent, and ANSWER IT while it works.

    Returns `(ok, reason_if_not)`. Every way this can fail to start — a missing SDK, a bad policy,
    the run itself — is a reason string, so the caller falls back to suggesting the skill rather
    than dying.

    A question the maintainer did not answer is not one of those ways, and is not in the tuple: the
    agent can finish every decided part of a node and still owe one decision. Those questions are
    appended to `unanswered`, and the caller records them in the plan and blocks on them.

    WHO CALLS THIS IS NOT ONE OF THEM. It used to be: an agent caller was refused, on the reasoning
    that spawning another agent duplicates the worker. What that produced was worse than what it
    prevented — the refusal directed the caller to `set`, the one transition that cannot advance a
    sub-set, so a plan driven by an agent recorded its state in a place `run` never looked. The
    hazard was never the caller's identity but two workers on one plan, and `plan_lock` refuses
    that from any caller, including a second run by the same one.

    THE ROUTER OWNS THE CONVERSATION. `agent_conversation` supplies the SDK's `can_use_tool`, so two
    things the agent needs reach the person who ran the command: permission for an action the
    project's allow-list did not settle, and an answer to a question only the maintainer can decide.
    Driven as `claude -p` it had neither channel, and the `Documenting` node of the framework-version
    plan ended twice with edits "refused by the permission layer" and a docs gate that never ran.

    ONE AGENT PER SUB-SET, and `plan` is what makes it possible. The session that performed the last
    node is resumed when it belongs to the same scope, so `Documenting` and `Committing` judge the
    diff `Implementing` wrote instead of rebuilding what it means — and a new sub-set starts a fresh
    agent, which is where reading only the plan earns its keep. The plan is also where the BRIEF
    comes from: the node, the sub-set's rows, what is already decided, the last verdict and the diff,
    handed over rather than rediscovered.

    What is NOT here any more: a hand-rolled parser over `--output-format stream-json`. The SDK
    yields typed messages, so progress is rendered from them.
    """
    try:
        conversation = _conversation()
    except ImportError as exc:
        return False, f"scripts/dev/common/agent_conversation.py could not be imported ({exc})"
    try:
        policy = conversation.resolve_policy()
        # Built HERE so a countdown that is not a number is refused before the agent starts, the
        # way a misspelt policy is — not discovered at the first question, twenty minutes in.
        terminal = conversation.Terminal()
        granularity = conversation.resolve_session_granularity()
    except ValueError as exc:
        return False, str(exc)

    # Flags for the SDK, not for a CLI. Permission flags are REFUSED here rather than forwarded:
    # they are the pre-decided policies this change replaces, and one arriving through a side door
    # would switch the conversation off without saying so.
    extra: dict = {}
    stated = shlex.split(os.environ.get("DEV_CYCLE_AGENT_ARGS", ""))
    banned = [f for f in stated if f.startswith(("--permission-mode", "--dangerously-skip"))]
    if banned:
        return False, (
            f"DEV_CYCLE_AGENT_ARGS carries {banned[0]}, which pre-decides what the router now asks "
            f"you about. Set {conversation.POLICY_ENV} instead "
            f"({'|'.join(conversation.POLICIES)})."
        )
    for flag, value in zip(stated, stated[1:]):
        if flag == "--model":
            extra["model"] = value
        elif flag == "--max-turns":
            extra["max_turns"] = int(value)

    # The two switches that outlived the subprocess, mapped onto the SDK's own options rather than
    # deleted. `DEV_CYCLE_AGENT_BIN` earned its keep on 2026-09-07, when the `claude` on PATH was
    # too old for the configured model: the SDK bundles a binary but PREFERS one on PATH, so the
    # same trap exists and the same override answers it.
    agent_bin = os.environ.get("DEV_CYCLE_AGENT_BIN", "").strip()
    if agent_bin:
        extra["cli_path"] = agent_bin
    quiet = bool(os.environ.get("DEV_CYCLE_AGENT_QUIET"))

    # THE PROMPT ASKS FOR THE DECISIONS RECORD, because nothing else can: no memory passes between
    # the agents that perform successive nodes, so a decision this node takes and does not write
    # down is one the next node meets again, with no record that it was ever settled. The plan
    # format has the one chapter (`rules/implementation-plan.md` § *Decisions and answers*); this
    # sentence is what makes the node that took the decision the one that fills it.
    prompt = (
        f"Invoke the {skill} skill now to advance the active implementation plan "
        f"(current dev-cycle node: {node}). Follow the skill exactly and keep the plan updated. "
        "Record every decision you take that the plan had not already decided — when, the node and "
        "sub-set, the question, the decision, who took it and why, including a question you put "
        "and nobody answered — as a row in the plan's `Decisions and answers` chapter "
        "(`rules/implementation-plan.md` § *Decisions and answers*), which is the one place a plan "
        "records them. You are not the node that will live with it: the next one is a fresh agent "
        "whose whole context is that file."
    )
    # THE BRIEF GOES AFTER THE INSTRUCTION, not before it: the instruction is what the agent is
    # being asked to do, and a page of context ahead of it buries the ask.
    brief = node_brief(plan, node) if plan is not None else ""
    if brief:
        prompt = f"{prompt}\n\n{brief}"

    # WHICH SESSION, and therefore whether this node inherits the last one's context. Resolved here
    # rather than in the conversation module because the scope is a fact about the PLAN — which
    # sub-set is executing — and the plan is the router's.
    scope = resume_id = None
    if plan is not None:
        with contextlib.suppress(OSError):
            scope = session_scope(plan.read_text(encoding="utf-8"), granularity)
        resume_id = load_session(plan, scope)
    session: dict = {}

    print(f"[dev-cycle] running '{skill}' for node {node} through the Agent SDK "
          f"({conversation.POLICY_ENV}={policy}).")
    if resume_id:
        print(f"[dev-cycle] Session: resuming the agent that performed the last node of {scope} "
              f"({conversation.SESSION_ENV}={granularity}). It is not re-reading the plan from "
              f"scratch; a fresh one starts at the next scope.")
    elif scope:
        print(f"[dev-cycle] Session: a FRESH agent for {scope} "
              f"({conversation.SESSION_ENV}={granularity}) — its whole context is the plan and the "
              f"brief, which is what makes anything the last one failed to write down visible here.")
    else:
        print(f"[dev-cycle] Session: a fresh agent per node "
              f"({conversation.SESSION_ENV}={granularity}); nothing is carried between nodes.")
    if policy == "ask":
        print("[dev-cycle] It will ask YOU for any permission the project's allow-list does not "
              "already settle, and for any question only you can answer.")
    elif policy == "skip":
        print("[dev-cycle] WARNING: policy `skip` — every tool call is allowed without asking.")
    else:
        print(f"[dev-cycle] Policy `{policy}`: no PERMISSION will be asked. Anything it does not "
              f"cover is refused, and the agent is told to report it as not done.")
    # A QUESTION is outside the policy: it is a decision the maintainer owes. Said up front, with
    # the wait, so a person who walks away knows what happens to a question asked while they are
    # gone — and a run with no terminal knows it will Block at the first one rather than hang.
    if not terminal.interactive:
        print("[dev-cycle] No terminal: a question the agent asks Blocks the plan at once, with the "
              "question recorded in it.")
    elif terminal.countdown_seconds:
        print(f"[dev-cycle] A question the agent asks rings this terminal and waits "
              f"{terminal.countdown_seconds}s for a first keystroke ({conversation.COUNTDOWN_ENV}); "
              f"unanswered, the plan moves to `Asking human direction` with the question recorded.")
    else:
        print(f"[dev-cycle] A question the agent asks rings this terminal and waits indefinitely "
              f"({conversation.COUNTDOWN_ENV}=0).")
    # Attribution, stated before the child runs: whatever appears in `git status` afterwards was
    # caused by THIS command. Unlabelled, those diffs read as somebody else's work — which is
    # exactly how they were once reported.
    print("[dev-cycle] NOTE: a CHILD agent process is being started by this command. Every file it "
          "changes is a consequence of running this router, not of anything external.")

    ok, why = conversation.run_agent(prompt, REPO_ROOT, policy, extra_options=extra,
                                     terminal=terminal, quiet=quiet, label=f"{node} / {skill}",
                                     unanswered=unanswered, resume=resume_id, session=session)
    # Saved whatever the outcome: a node that failed part-way still did work the next attempt should
    # not repeat, and the run that most wants resuming is the one that did not finish.
    if plan is not None:
        save_session(plan, scope, session.get("id"), node)
    return ok, why


def _plan_order(path: Path) -> tuple:
    """Sort key for plan files: the execution timestamp in the NAME, not the file's mtime.

    Plan names are `<YYYY-MM-DD> - <HH-MM-SS> - <description> (<state>).md`, and that timestamp is
    re-stamped at every transition precisely so the newest plan is identifiable. Sorting by mtime
    instead made the active plan depend on which file was written last by anything at all — a
    bulk edit, a formatter, a `git checkout` — and a rewrite of several plans in one pass silently
    moved the active plan backwards from Committing to an earlier BuildDeploy.

    Files whose name does not parse fall back to mtime, so a hand-named plan still resolves.
    """
    match = re.match(r"(\d{4}-\d{2}-\d{2})\s*-\s*(\d{2}-\d{2}-\d{2})\s*-", path.name)
    if match:
        return (1, f"{match.group(1)} {match.group(2)}")
    return (0, str(path.stat().st_mtime))


# --- Which plan is active: the links name the plans, and `start` is what creates one -----------
#
# WHY THE LINKS, AND NOT A SCAN OF THE DIRECTORY. Resolving by scanning `implementation-plans/`
# made the active plan whichever FILE sorted newest — a winner rather than an answer — and it could
# not count plans at all. `--keep-history` keeps one file per transition, so from a plan's second
# transition its own trail (`(Implementing)`, `(BuildDeploy)`, `(Testing)`, …) read as several
# plans in flight and `one_plan_in_flight` refused the plan to itself: a documented flag, unusable
# past its second transition. A plan is now named by exactly one thing — its
# `ACTIVE PLAN - <description>.md` link — so one plan is one plan however many files it has, and
# becoming the active plan is an ACT (`start`) rather than the consequence of holding the newest
# timestamp.
#
# WHY THE LINK'S TARGET IS NOT READ. The link answers WHICH PLAN; which FILE of that plan is
# current is still the timestamp sort, now scoped to that plan's description. That is not a
# nicety: an agent performing a node renames the plan itself — the state lives in the name — and
# does not repoint the link, so a resolution that read the target would hand back a file that no
# longer exists. That is the 2026-09-08 crash (see `test_the_router_survives_the_agent_it_ran.py`)
# arriving in a new place, and reading the description instead makes a broken link as good as an
# intact one.


def active_links() -> list[Path]:
    """Every `ACTIVE PLAN - <description>.md` link — one per plan that has been started."""
    if not PLANS_DIR.is_dir():
        return []
    return sorted(p for p in PLANS_DIR.glob(f"{ACTIVE_LINK_PREFIX}*.md") if p.is_symlink())


def link_description(link: Path) -> str:
    """The plan a link names. The description is the one part of a plan's name that never moves."""
    return link.stem.removeprefix(ACTIVE_LINK_PREFIX)


def plan_files(description: str) -> list[Path]:
    """The files of ONE plan, newest first. Normally one; under `--keep-history`, one per transition.

    TWO exclusions, both by KIND and both before the sort rather than left to it.

    Symlinks: the stable name lives in this directory, and resolving it as a plan would make the
    router read and rewrite a plan through its own alias — renaming the target out from under the
    link on the first transition. `is_symlink()` (an `lstat`) filters the glob before anything
    stats, reads or sorts the survivors, which `rules/implementation-plan.md` § *The active plan
    has a stable name* requires of every scan of this directory: inside the dev tools container the
    bind mount answers `lstat` on that link and returns EINVAL for `stat`, so a scan that sorts
    first raises `OSError` before it has selected anything — no verdict at all, wearing the shape
    of one.

    PAUSED PLANS: a parked plan is one nobody is working, so it is not a candidate for being the
    active one — and it is deliberately the most-recently-named file at the moment it is parked.
    `pause` drops the link too, so this exclusion is the second of two; it is what makes the pause
    hold in the one place the parked file IS in the tree, standing on the plan's own branch.
    """
    if not PLANS_DIR.is_dir():
        return []
    found = []
    for path in PLANS_DIR.glob("*.md"):
        if path.is_symlink() or is_paused(path):
            continue
        parts = _plan_parts(path.stem)
        if parts and parts[2] == description:
            found.append(path)
    return sorted(found, key=_plan_order, reverse=True)


def started_plans() -> list[Path]:
    """The current file of every started plan, newest first — ONE entry per plan.

    A link whose plan has no file left (deleted, or renamed to a name that no longer parses) drops
    out rather than being reported as a plan with nothing behind it.
    """
    current = [files[0] for link in active_links()
               if (files := plan_files(link_description(link)))]
    return sorted(current, key=_plan_order, reverse=True)


def active_plan() -> Path | None:
    """The one plan every skill reads and updates, or None when no plan has been started.

    A plan with no `ACTIVE PLAN` link is NOT resolved, and that is the point: a plan file sitting
    in the directory is work somebody wrote down, not work in hand. `start` is what says which one
    is being worked, and `main()` answers "no active plan" by naming the plans that could be
    started rather than by silently picking the newest.
    """
    started = started_plans()
    return started[0] if started else None


#: The filename states of a plan that is still being worked, and therefore a *candidate* for being
#: the active one. It is `NODES` minus the two that mean the work is over.
#:
#: `Merged` is delivered. `Done` is excluded for a reason worth stating, because it is not finished
#: in the same sense: a plan at `Done` is waiting for `deliver`, which is real work still owed. But a
#: plan file is never removed — `implementation-plans/` in this repository holds seventy delivered
#: plans, sixty of which are named `(Done)` because they predate `deliver` renaming them `(Merged)`.
#: Counting `Done` as in flight would make every command below report seventy plans competing for
#: one highlight, which is why the useful set is "before Done" rather than "not Merged".
#:
#: The consequence is precise and admitted: two plans BOTH sitting at `Done` are not reported by
#: `plans_in_flight()`, and the newest still silently wins. Nothing here can tell those apart from
#: the sixty historical ones by name alone.
#:
#: `Paused` is not in `NODES` at all (see `PAUSED_STATE`), so a parked plan is excluded by
#: construction rather than by a second rule.
IN_FLIGHT_STATES = tuple(n for n in NODES if n not in ("Done", "Merged"))


def plans_in_flight() -> list[Path]:
    """Every started plan that is still being worked, newest first — the plans competing to be active.

    `active_plan()` answers "which plan does a skill update?" with a single resolution, and it has
    to: a rule, a skill or an editor tab needs one answer. This answers the different question
    "is that resolution a fact, or a guess?" — because a sort always produces a winner, and a
    winner is indistinguishable from an answer.

    ONE ENTRY PER PLAN, because it counts `ACTIVE PLAN` links and not files. That is what lets
    `--keep-history` keep its promise — every transition's file preserved — while this guard keeps
    its own, instead of a single plan's trail of files reading as a directory full of ambiguity.

    A plan whose current file carries no state (a hand-written name, a stray note) is NOT counted.
    It cannot be judged, and refusing to work because an unrelated markdown file was dropped in the
    directory would be a worse failure than the one this prevents.
    """
    return [p for p in started_plans() if plan_state(p) in IN_FLIGHT_STATES]


def one_plan_in_flight(action: str) -> bool:
    """True when work may proceed; False — having said why — when two plans are both in flight.

    WHY THIS IS A REFUSAL AND NOT A DEFAULT. `_plan_order` sorts by the timestamp in the filename,
    so with two unfinished plans in the tree the newest becomes the active one and nothing says a
    choice was made. It is the same shape `resume` already refuses: which plan is the one being
    worked is a decision, and picking the newest timestamp would be this script taking it. The
    difference is only that `resume` is asked the question openly, while here it arrives silently.

    Reported by `run` and by `status`, and by neither `pause` nor `deliver` — those are how the
    situation is settled, so blocking them would leave no way out of it.
    """
    live = plans_in_flight()
    if len(live) < 2:
        return True
    print(f"[{action}] {len(live)} plans are in flight, so which one is active is not something "
          f"this router can read — it would silently be the newest timestamp:")
    for p in live:
        print(f"[{action}]     {p.name}")
    print(f"[{action}] Park the ones that are not the work in hand, so exactly one is left:")
    # NAMED, not "the one the router resolves as active". A remedy for an ambiguity that is itself
    # resolved by the ambiguity is no remedy: with two plans in flight a bare `pause` would park
    # whichever holds the newest timestamp, which may be neither the plan the reader is standing on
    # nor the one they meant to park.
    for p in live:
        print(f"[{action}]   ./scripts/dev/common/dev-cycle.sh pause {plan_description(p)}")
    print(f"[{action}]   ./scripts/dev/common/dev-cycle.sh resume <description>   "
          f"# picks whichever one back up")
    print(f"[{action}] A plan that has never been through Branching has nothing committed, so "
          f"deleting its file is the other way to settle it.")
    return False


def current_node(text: str) -> str | None:
    m = re.search(r"^\s*class\s+(\w+)\s+current\s*;", text, re.MULTILINE)
    return m.group(1) if m else None


# --- Sub-sets: a plan is delivered as an ordered sequence of coherent sub-sets -----------------
#
# A task of any size is not one pass through the loop. The Overall view therefore carries a sub-set
# table, one row per sub-set, and exactly ONE of them is executing at any time — its State cell holds
# a node name while every other row holds `Done` or `—`.
#
# The sub-sets are declared when the plan is written, in dependency order (a prerequisite sub-set
# precedes the sub-set that needs it), each small enough to describe in a short sentence, to be
# accepted by a test that stands on its own, and to be committed with a message that is close to its
# own description. If a sub-set cannot be described briefly it is two sub-sets.

SUBSET_PENDING = "—"
SUBSET_DONE = "Done"
# The State cell holds one of these while a sub-set is executing.
SUBSET_NODE_LABELS = {
    "Implementing": "Implementing",
    "BuildDeploy": "Building&Deploying",
    "Testing": "Testing",
    "Fixing": "Fixing",
    "Documenting": "Documenting",
    "Committing": "Committing",
}
_LABEL_TO_NODE = {v: k for k, v in SUBSET_NODE_LABELS.items()}


#: The column that says where the time went. Optional in a plan's table only in the sense that a
#: plan written before it gains it on the first transition (`ensure_exec_time_column`) — every
#: reader here treats its absence as "not accrued yet", never as "not applicable".
EXEC_TIME_COLUMN = "Exec time"
EXEC_TIME_NONE = "—"


def format_duration(seconds: float) -> str:
    """Seconds → `2h 3m 12s`, dropping leading zero units. Round-trips through `parse_duration`.

    SECONDS ARE KEPT, at every magnitude. A cell rendered `1h 12m` loses whatever was under the
    minute, and this value is accrued by repeated read-add-write — so the rounding would not be a
    display choice but a leak, taken again at every transition. Deterministic nodes finish in
    seconds and there are more of them than of anything else.
    """
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


_DURATION_PART = re.compile(r"(\d+)\s*([hms])")
_DURATION_UNIT = {"h": 3600, "m": 60, "s": 1}


def parse_duration(cell: str) -> int:
    """`2h 3m 12s` → seconds. Anything unreadable — `—`, blank, prose — is 0, never an error.

    A cell a person edited by hand must not stop the router mid-transition; the worst it can cost
    is one sub-set's accrued total, which is a number about the run and not the run itself.
    """
    return sum(int(n) * _DURATION_UNIT[u] for n, u in _DURATION_PART.findall(cell or ""))


def _split_row(line: str) -> list[str]:
    """A markdown row's cells, with the empty elements a leading/trailing `|` produces removed."""
    cells = line.strip().split("|")
    if cells and not cells[0].strip():
        cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [c.strip() for c in cells]


def _subset_table(lines: list[str]) -> dict | None:
    """`{header, columns, start, end}` for the sub-set table — the data rows, and their headings.

    READ BY HEADING, not by position. The table carries `#`, `Description`, `State` and — once a
    plan has run — `Exec time`, and a fourth column shifts every index a positional reader used.
    """
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        columns = _split_row(line)
        if "Description" not in columns or "State" not in columns:
            continue
        start = i + 2  # skip the header separator
        end = start
        while end < len(lines) and lines[end].strip().startswith("|"):
            end += 1
        return {"header": i, "columns": columns, "start": start, "end": end - 1} if end > start \
            else None
    return None


def subsets(text: str) -> list[dict]:
    """The sub-set rows, in declared order: {index, description, state, exec_time, line}."""
    lines = text.splitlines()
    table = _subset_table(lines)
    if not table:
        return []
    columns = table["columns"]
    at_state = columns.index("State")
    at_description = columns.index("Description")
    at_exec = columns.index(EXEC_TIME_COLUMN) if EXEC_TIME_COLUMN in columns else None
    out = []
    for i in range(table["start"], table["end"] + 1):
        cells = _split_row(lines[i])
        if len(cells) <= max(at_state, at_description) or set(cells[0]) <= set("-: "):
            continue
        out.append({
            "index": len(out),
            "description": cells[at_description],
            "state": cells[at_state],
            "exec_time": (cells[at_exec] if at_exec is not None and at_exec < len(cells)
                          else EXEC_TIME_NONE),
            "line": i,
        })
    return out


def current_subset(text: str) -> dict | None:
    """The one sub-set that is executing — its State is a node label, not `Done` or `—`."""
    for row in subsets(text):
        if row["state"] in _LABEL_TO_NODE:
            return row
    return None


def _set_subset_cell(text: str, index: int, column: str, value: str) -> str:
    """Rewrite one sub-set row's cell under `column`, preserving the rest of the row verbatim."""
    lines = text.splitlines(keepends=True)
    table = _subset_table([line.rstrip("\n") for line in lines])
    rows = subsets(text)
    if table is None or index >= len(rows) or column not in table["columns"]:
        return text
    at = table["columns"].index(column)
    i = rows[index]["line"]
    parts = lines[i].rstrip("\n").split("|")
    lead = 1 if parts and not parts[0].strip() else 0
    if lead + at >= len(parts):
        return text
    parts[lead + at] = f" {value} "
    lines[i] = "|".join(parts) + "\n"
    return "".join(lines)


def set_subset_state(text: str, index: int, state: str) -> str:
    """Rewrite one sub-set row's State cell, preserving the rest of the row verbatim."""
    return _set_subset_cell(text, index, "State", state)


def ensure_exec_time_column(text: str) -> str:
    """Give the sub-set table its `Exec time` column when it has none. A no-op when it has.

    A plan in flight when the column was added has a three-column table, and the first transition
    after that is where it gains the fourth — the same self-healing the decisions record gets. A
    delivered plan is never passed here: it is a record of what was true then.
    """
    lines = text.splitlines(keepends=True)
    table = _subset_table([line.rstrip("\n") for line in lines])
    if table is None or EXEC_TIME_COLUMN in table["columns"]:
        return text

    def _append(i: int, cell: str, pad: str = " ") -> None:
        raw = lines[i].rstrip("\n").rstrip()
        lines[i] = (raw if raw.endswith("|") else raw + " |") + f"{pad}{cell}{pad}|\n"

    _append(table["header"], EXEC_TIME_COLUMN)
    _append(table["header"] + 1, "---", pad="")  # separators carry no padding in this table
    for i in range(table["start"], table["end"] + 1):
        if lines[i].strip().startswith("|"):
            _append(i, EXEC_TIME_NONE)
    return "".join(lines)


def accrue_exec_time(text: str, index: int, seconds: float) -> str:
    """Add `seconds` to one sub-set's accrued `Exec time`. Creates the column if it is absent.

    ACCRUED, NOT MEASURED FROM A START TIME. What the cell answers is *how long the router spent
    executing this sub-set*, and that is not wall-clock since the sub-set began: a plan sits at
    `Asking human direction` overnight, is paused for a day, or loses a node to a session limit,
    and none of that is time the work took. Only the span from a node's execution starting to its
    transition being written is added, so every wait falls outside by construction rather than by
    being subtracted afterwards.
    """
    if seconds <= 0:
        return text
    text = ensure_exec_time_column(text)
    rows = subsets(text)
    if index >= len(rows):
        return text
    total = parse_duration(rows[index]["exec_time"]) + seconds
    return _set_subset_cell(text, index, EXEC_TIME_COLUMN, format_duration(total))


# --- The execution clock ------------------------------------------------------------------------
#
# ONE EXECUTION, ONE SLICE. `run` starts the clock once it is past the states that execute nothing
# — `Done`, `Merged`, and `Asking human direction`, where the only thing that happens is a question
# being put to a person — and `_write_plan` consumes it at the transition. So the accrual is the
# router's own working time, and a wait is never inside it.
#
# THE SUB-SET IS CAPTURED WITH THE CLOCK, not read back at the transition. At `Committing` the
# router marks sub-set N `Done` and starts N+1 before it writes the plan, so a reader that asked
# "which sub-set is executing?" at that moment would charge N's whole commit step to N+1.

_exec_clock: tuple[int | None, float] | None = None


def start_exec_clock(subset_index: int | None) -> None:
    global _exec_clock
    _exec_clock = (subset_index, time.monotonic())


def take_exec_clock() -> tuple[int | None, float] | None:
    """`(subset_index, elapsed_seconds)` and stop, or None when no execution is being timed."""
    global _exec_clock
    if _exec_clock is None:
        return None
    index, started = _exec_clock
    _exec_clock = None
    return index, time.monotonic() - started


def line_value(text: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\*\*\s*[:—-]\s*(.+)", text)
    return m.group(1).strip() if m else None


def status_summary(text: str) -> str | None:
    # The very short line under a "## ... Status summary" / "### N. Status summary" heading.
    m = re.search(r"#+\s*(?:\d+\.\s*)?Status summary\s*\n+([^\n]+)", text)
    return m.group(1).strip() if m else None


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _now_stamp() -> tuple[str, str]:
    """(date, time) for a plan filename — `YYYY-MM-DD`, `HH-MM-SS` — stamped at execution."""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H-%M-%S")


def _apply_highlight(text: str, node: str) -> tuple[str, bool]:
    """Return (text, ok) with the mermaid highlight + Current step/Last updated set to `node`.
    `ok` is False when the two `class … idle;` / `class … current;` lines could not be found."""
    if node not in NODES:
        sys.exit(f"Unknown node '{node}'. Valid: {', '.join(NODES)}")
    idle = ",".join(n for n in NODES if n != node)
    driver = DRIVER[node][0]
    new_text, n_idle = re.subn(r"^\s*class\s+[\w,]+\s+idle\s*;",
                               f"    class {idle} idle;", text, count=1, flags=re.MULTILINE)
    new_text, n_cur = re.subn(r"^\s*class\s+\w+\s+current\s*;",
                              f"    class {node} current;", new_text, count=1, flags=re.MULTILINE)
    # `Current step` names the SUB-SET and the state it is in, because "Testing" alone does not say
    # what is being tested when a plan is delivered as eight sub-sets.
    executing = current_subset(text)
    if executing is not None:
        label = SUBSET_NODE_LABELS.get(node, node)
        step = (f"sub-set {executing['index'] + 1}/{len(subsets(text))} "
                f"“{executing['description']}” — {label} ({driver})")
    else:
        step = f"{NODE_DISPLAY.get(node, node)} ({driver})"
    new_text = re.sub(r"(\*\*Current step\*\*\s*[:—-]\s*).+",
                      lambda m: m.group(1) + step, new_text, count=1)
    new_text = re.sub(r"(\*\*Last updated\*\*\s*[:—-]\s*).+",
                      rf"\g<1>{_now()}", new_text, count=1)
    return new_text, bool(n_idle and n_cur)


def _plan_parts(stem: str) -> tuple[str, str, str] | None:
    """Split a plan filename stem into (date, time, description), tolerating both the base
    `YYYY-MM-DD-HH-MM-SS - desc` form and the history `YYYY-MM-DD - HH-MM-SS - desc (state)`
    form. Any trailing ` (state)` is dropped. Returns None if the stem doesn't match."""
    s = re.sub(r"\s*\([^()]*\)\s*$", "", stem).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ -]+(\d{2}-\d{2}-\d{2})\s*-\s*(.+)$", s)
    return (m.group(1), m.group(2), m.group(3).strip()) if m else None


def plan_description(plan: Path) -> str:
    """The plan's description — the ONE part of its name that does not move, and therefore the
    part everything keyed to a plan uses: its `ACTIVE PLAN` link, its branch, and its lock.

    A name that does not parse falls back to the stem with any trailing ` (state)` removed, so a
    hand-named plan is still identifiable rather than raising from the middle of a rename.
    """
    parts = _plan_parts(plan.stem)
    return parts[2] if parts else re.sub(r"\s*\([^()]*\)\s*$", "", plan.stem).strip()


def _state_path(plan: Path, node: str, unique: bool) -> Path:
    """Target file `<date> - <time> - <description> (<state>).md`, where date/time are stamped
    **now** (the moment of this execution) and the description comes from the active plan's name.

    The filename therefore answers "what happened last, and when"; the plan's creation timestamp
    is not lost — it lives in the Overall view's `Created at` line inside the file. With `unique`
    (--keep-history) a same-second collision is disambiguated so no state overwrites an earlier
    one; otherwise the single plan file is simply renamed."""
    date, time = _now_stamp()
    base = f"{date} - {time} - {plan_description(plan)}"
    target = PLANS_DIR / f"{base} ({node}).md"
    if not unique:
        return target
    i = 2
    while target.exists():
        target = PLANS_DIR / f"{base} ({node} {i}).md"
        i += 1
    return target


#: The one filename state that is NOT a node, and it is deliberate.
#:
#: `Paused` says nothing about where the work is — it says nobody is working the plan. WHERE the
#: work is stays in the graph's highlight, which `pause` leaves exactly as it found it, because
#: that highlight is the only record of the node `resume` has to return to. A `Paused` *node* would
#: have to take the highlight for itself and would therefore have to forget the resume node.
#:
#: So a paused plan is the one plan whose filename state and highlighted node differ, on purpose,
#: and `resume` is what makes them agree again.
PAUSED_STATE = "Paused"

#: A parked plan's card. `pause` writes one on the DELIVERY TARGET and `resume` removes it, because
#: a paused plan otherwise exists only on its own branch — invisible to anyone reading the board,
#: which is the thing a maintainer actually reads. The card is a pointer, not a copy: the plan
#: itself stays the one record, on its branch.
PAUSED_CARDS = "kanban/paused"


def paused_card_path(description: str) -> Path:
    return REPO_ROOT / PAUSED_CARDS / f"{description}.md"


def paused_card_text(description: str, branch: str, node: str, plan_name: str) -> str:
    """What the board shows for a parked plan: where it is, where it stopped, how to pick it up."""
    return (
        f"# ⏸ {description}\n\n"
        f"**Paused** on {_now()} — this plan is parked, not abandoned.\n\n"
        f"- **Plan**: `{plan_name}`\n"
        f"- **Branch**: `{branch}` — the plan file and every commit live there, not on this branch\n"
        f"- **Resumes at**: `{node}`\n\n"
        f"Pick it up with:\n\n"
        f"```bash\n"
        f"./scripts/dev/common/dev-cycle.sh resume {description}\n"
        f"```\n\n"
        f"Written by `dev-cycle.sh pause` and removed by `resume`. A card here with no matching\n"
        f"`plan/*` branch means the branch was deleted under it.\n"
    )


#: States after which no plan is in flight, so the stable name below must not claim one. `Merged`
#: is finished work; `Paused` is work nobody is on.
_NO_ACTIVE_PLAN_STATES = ("Merged", PAUSED_STATE)

#: The stable name an active plan can be referred to by. Everything else about a plan's filename
#: moves: the timestamp is re-stamped at every transition and the state is part of the name, which
#: is deliberate (the name answers "when did this last move, and where does it stand?") and makes
#: the plan impossible to cite. A skill, a rule, an editor tab or a shell alias needs ONE name that
#: holds for the life of the run, and this is it.
ACTIVE_LINK_PREFIX = "ACTIVE PLAN - "


def plan_state(plan: Path) -> str | None:
    """The state carried by a plan's FILENAME — `Implementing`, `Paused`, `Merged`, … or None.

    `--keep-history` disambiguates a same-second collision as `(<state> 2)`, so the state is the
    first word of the parenthetical rather than the whole of it.
    """
    m = re.search(r"\(([^()]*)\)\s*$", plan.stem)
    if not m or not m.group(1).strip():
        return None
    return m.group(1).split()[0]


def is_paused(plan: Path) -> bool:
    """Whether this plan file is parked. Reads the NAME only, so it answers for a path on a branch
    that is not checked out — which is where every paused plan lives."""
    return plan_state(plan) == PAUSED_STATE


def active_link_path(plan: Path) -> Path:
    """`implementation-plans/ACTIVE PLAN - <description>.md` for this plan.

    Keyed on the DESCRIPTION, the one part of a plan's name that does not change: two plans cannot
    be active at once (the active plan is a single resolution), and a link named after the state or
    the timestamp would be exactly the moving name this exists to avoid.
    """
    return PLANS_DIR / f"{ACTIVE_LINK_PREFIX}{plan_description(plan)}.md"


def sync_active_link(target: Path, node: str) -> None:
    """Point the stable name at `target`, or remove it once no plan is in flight.

    RELATIVE target, so the link keeps working if `implementation-plans/` is moved or the repository
    is checked out elsewhere — git stores the link's text verbatim, and an absolute path would name
    somebody else's machine.

    Removed at `Merged` and at `Paused` rather than left pointing at the parked file: the absence IS
    the signal that no plan is in flight. A link that survived either would say "a plan is active"
    forever, which is the same class of lying signal as a status line that reports success
    regardless. The two differ only in what happens next — a delivered plan is finished, a paused
    one is picked up again by `resume`.
    """
    link = active_link_path(target)
    if node in _NO_ACTIVE_PLAN_STATES:
        if link.is_symlink() or link.exists():
            link.unlink()
            why = ("the plan is delivered" if node == "Merged" else "the plan is paused")
            print(f"[dev-cycle] removed '{link.name}' — {why}, none is active.")
        return
    # `is_symlink()` before `exists()`: a link whose target this transition just deleted is broken,
    # and `exists()` follows the link, so it answers False for a file that is very much there.
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target.name)


def _write_plan(plan: Path, text: str, node: str, keep_history: bool) -> Path:
    """Apply the `node` highlight to `text` and write it to `<now> - <description> (<state>).md`.
    By default the plan is a single rolling file that is *renamed* on each transition (the
    previous name is removed), so its name always carries the latest execution's date/time and
    state; with keep_history each transition lands in its own file so all are preserved.
    Returns the path written."""
    # WHERE THE TIME WENT, accrued at EVERY transition and nowhere else. This is the one function
    # every transition passes through, so a node that moved the plan without its execution being
    # charged somewhere would have to bypass the rename itself.
    timed = take_exec_clock()
    if timed is not None and timed[0] is not None:
        text = accrue_exec_time(text, timed[0], timed[1])
    # The graph highlight and the sub-set table must never disagree: the graph says which STEP, the
    # table says which SUB-SET is on that step. Writing one without the other is how a plan starts
    # describing two different states at once.
    executing = current_subset(text)
    if executing is not None and node in SUBSET_NODE_LABELS:
        text = set_subset_state(text, executing["index"], SUBSET_NODE_LABELS[node])
    new_text, ok = _apply_highlight(text, node)
    if not ok:
        sys.exit("Could not find the two `class … idle;` / `class … current;` lines to rewrite. "
                 "Is the canonical dev-cycle graph present in the plan's Overall view?")
    target = _state_path(plan, node, unique=keep_history)
    target.write_text(new_text, encoding="utf-8")
    renamed = target != plan
    if renamed and not keep_history and plan.exists():
        plan.unlink()  # rolling file: the state lives in the name, so only one file remains
    sync_active_link(target, node)
    print(f"[dev-cycle] {('→ ' + target.name) if renamed else target.name}: "
          f"current node → {node}  (updated {_now()})")
    return target


def set_node(plan: Path, node: str, keep_history: bool = False) -> Path:
    return _write_plan(plan, plan.read_text(encoding="utf-8"), node, keep_history)


# --- Asking human direction: the question the plan is waiting on ------------------------------
#
# `Asking human direction` HAD NO WRITER. `run` stopped when it found a plan already there, and the only thing
# that could put one there was `set` — the hand-driven transition deleted with this one. So the
# state a plan must reach when it meets a decision only the maintainer can take was reachable only
# by hand, and what happened instead was measured at three consecutive nodes of this plan: the
# question was put, nobody was at the terminal, the agent reported it open in prose, and the run
# carried on with the decision still owed. Two of those questions are still open today.
#
# The record lives IN THE PLAN, not in a side file, for the same reason this plan passes no memory
# between the agents that perform its nodes: the repository and the plan are the whole context, and
# both are auditable. A transcript would carry one agent's mistaken beliefs forward as premises; a
# question written in the plan is read by whoever opens it, agent or person.
#
# It is delimited by HTML COMMENTS rather than found by its heading, because reading, rewriting and
# removing it have to be exact. A heading is prose, prose gets edited, and a router that loses the
# question it is blocked on is the defect this closes rather than a new one.

BLOCKED_OPEN = "<!-- dev-cycle:blocked -->"
BLOCKED_CLOSE = "<!-- /dev-cycle:blocked -->"


def _marked_block(text: str, open_marker: str, close_marker: str) -> tuple[int, int] | None:
    """(start, end) character offsets of a marked block including its markers, or None."""
    start = text.find(open_marker)
    if start < 0:
        return None
    end = text.find(close_marker, start)
    if end < 0:
        return None
    return start, end + len(close_marker)


def _drop_block(text: str, open_marker: str, close_marker: str) -> str:
    bounds = _marked_block(text, open_marker, close_marker)
    if bounds is None:
        return text
    start, end = bounds
    while end < len(text) and text[end] == "\n":
        end += 1
    return text[:start] + text[end:]


def _insert_at_top(text: str, block: str) -> str:
    """Put `block` immediately before the plan's first `## ` heading — under the title.

    At the top because a blocked plan's most important fact is the question: a reader opening the
    file must not have to scroll past six sections of narrative to find out what is being asked of
    them. Falls back to prepending when a plan has no `## ` heading at all.
    """
    m = re.search(r"^## ", text, re.MULTILINE)
    if not m:
        return block + "\n\n" + text
    return text[: m.start()] + block + "\n\n" + text[m.start():]


def clear_blocked(text: str) -> str:
    """Remove the blocked record. Called when the question has been answered, and only then."""
    return _drop_block(text, BLOCKED_OPEN, BLOCKED_CLOSE)


def _render_question(entry: dict, index: int) -> list[str]:
    header = entry.get("header") or ""
    out = [f"#### Question {index}" + (f" — {header}" if header else ""),
           "",
           "> " + " ".join((entry.get("question") or "").split()),
           ""]
    for n, option in enumerate(entry.get("options") or [], start=1):
        label = option.get("label", "")
        description = " ".join((option.get("description") or "").split())
        out.append(f"- {n}. **{label}**" + (f" — {description}" if description else ""))
    answer = entry.get("answer")
    out += ["", f"- **Answer**: {answer}" if answer else "- **Answer**:", ""]
    return out


def render_blocked(resume_at: str, asked_by: str, questions: list[dict],
                   asked_at: str | None = None) -> str:
    """The plan section a blocked plan carries: the node to resume at, and THE QUESTION."""
    lines = [
        BLOCKED_OPEN,
        "",
        "## ⛔ Asking human direction — a decision only the maintainer can take",
        "",
        f"`{resume_at}` ran and stopped here. The question below was put and not answered, so "
        "**nothing was chosen for you**. There are two ways to answer it, and either resumes the "
        f"plan at **{resume_at}**:",
        "",
        "- run `./scripts/dev/common/dev-cycle.sh run`, which puts the question again at your "
        "terminal; or",
        "- write the answer on the `**Answer**:` line below, then run it — an answer already "
        "written here is not asked again.",
        "",
        f"- **Resume at**: {resume_at}",
        f"- **Asked at**: {asked_at or _now()}",
        f"- **Asked by**: {asked_by}",
        "",
    ]
    for index, entry in enumerate(questions, start=1):
        lines += _render_question(entry, index)
    lines += [BLOCKED_CLOSE]
    return "\n".join(lines)


_QUESTION_SPLIT = re.compile(r"^#### Question \d+", re.MULTILINE)
_OPTION_RE = re.compile(r"^- \d+\.\s*\*\*(?P<label>[^*]*)\*\*(?:\s*—\s*(?P<description>.*))?$",
                        re.MULTILINE)


#: Horizontal whitespace ONLY. `\s` matches a newline and `re.MULTILINE` changes what `^`/`$`
#: anchor to, NOT what `\s` matches — so `\s*:\s*(.+?)\s*$` on an EMPTY `- **Answer**:` line
#: happily consumed the blank line after it and captured whatever came next. Measured: the last
#: question in a record took the closing HTML comment as its answer, which made every partly
#: answered record read as fully answered and resumed a plan on a decision nobody had taken.
_H = r"[^\S\n]*"


def _block_value(block: str, label: str) -> str | None:
    m = re.search(rf"^- \*\*{re.escape(label)}\*\*{_H}:{_H}(.+?){_H}$", block, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_blocked(text: str) -> dict | None:
    """Read the blocked record back: `{resume_at, asked_at, asked_by, questions[]}`, or None.

    None means this plan carries no record — which a plan at `Asking human direction` can
    legitimately be, since the state predates this writer and an agent may still set it itself. The
    caller stops on such a plan rather than treating a missing record as "nothing to wait for".
    """
    bounds = _marked_block(text, BLOCKED_OPEN, BLOCKED_CLOSE)
    if bounds is None:
        return None
    block = text[bounds[0]:bounds[1]]
    resume_at = _block_value(block, "Resume at")
    if resume_at not in NODES or resume_at == "Asking":
        # A record whose resume node is missing or unusable cannot resume anything. Reported as
        # absent so the plan stops, rather than resumed to a node nobody named.
        return None
    questions = []
    for chunk in _QUESTION_SPLIT.split(block)[1:]:
        m = re.search(rf"^>{_H}(.+?){_H}$", chunk, re.MULTILINE)
        questions.append({
            "question": m.group(1) if m else "",
            "header": chunk.splitlines()[0].partition("—")[2].strip(),
            "options": [{"label": o.group("label").strip(),
                         "description": (o.group("description") or "").strip()}
                        for o in _OPTION_RE.finditer(chunk)],
            "answer": _block_value(chunk, "Answer"),
        })
    return {"resume_at": resume_at, "asked_at": _block_value(block, "Asked at"),
            "asked_by": _block_value(block, "Asked by") or "?", "questions": questions}


def record_answers(text: str, asked_by: str, questions: list[dict]) -> str:
    """Write the answered questions into the plan's `Decisions and answers` chapter.

    KEPT IN THE PLAN, because the node that asked does not perform the resumed node: a fresh agent
    reads the plan and nothing else. An answer collected at the terminal and not written down would
    be an answer the work never sees, which is the same loss as never asking.

    IN THE SAME TABLE AS EVERY OTHER DECISION, marked as having come from a blocked record. What
    the maintainer said and what was done about it are halves of one record, and keeping them in
    two chapters is what made the same four answers appear twice while neither copy carried both
    `Why` and who was asked.
    """
    executing = current_subset(text)
    for entry in questions:
        text = record_decision(
            text,
            question=" ".join((entry.get("question") or "").split()),
            decision=entry.get("answer") or "—",
            who="maintainer",
            why="A maintainer ruling — it may not be revisited without asking them again",
            node=asked_by,
            subset=(executing["index"] + 1) if executing is not None else "—",
            asked=True,
        )
    return text


def record_blocked(plan: Path, resume_at: str, asked_by: str, questions: list[dict],
                   keep_history: bool = False) -> Path:
    """Move the plan to `Asking human direction`, carrying the question and the node to come back to.

    The highlight DOES move to `Asking human direction`, unlike `pause`, which leaves it where it
    was. The two differ in what they are: `Paused` is not a node and has nowhere to put itself,
    whereas `Asking human direction` is a node in the canonical graph and a reader of the picture
    must see the plan standing on it. The resume node is not lost by that, because it is written down here instead
    of being inferred from the highlight.
    """
    text = clear_blocked(plan.read_text(encoding="utf-8"))
    text = _insert_at_top(text, render_blocked(resume_at, asked_by, questions))
    print(f"[dev-cycle] ⛔ Asking human direction, from {resume_at}: {len(questions)} question(s) went unanswered, "
          f"and are recorded in the plan rather than lost.")
    for entry in questions:
        if not entry.get("answer"):
            print(f"[dev-cycle]     - {' '.join((entry.get('question') or '').split())[:150]}")
    print("[dev-cycle] Answer them in the plan, or run again with a terminal and the router will "
          "put them to you.")
    return _write_plan(plan, text, "Asking", keep_history)


def resume_blocked(plan: Path, keep_history: bool = False) -> Path | None:
    """Put the recorded question again; return the plan resumed at its node, or None if still open.

    "When the answer suffices" means EVERY question in the record has an answer — one of three
    answered out of three still leaves the node unable to act. An answer already written into the
    plan is not asked again, which is how a maintainer settles a question without sitting at the
    terminal the router happens to be attached to.
    """
    text = plan.read_text(encoding="utf-8")
    record = parse_blocked(text)
    if record is None:
        print("[dev-cycle] Plan is Asking human direction (a decision only you can take) — stopping, per "
              "decision-authority.")
        print("[dev-cycle] No question is recorded with it, so there is nothing to put again. "
              "Write what the plan is waiting on into it, or move it on deliberately.")
        return None

    pending = [q for q in record["questions"] if not q.get("answer")]
    if pending:
        try:
            terminal = _conversation().Terminal()
        except ValueError as exc:  # a countdown that is not a number — refused, not defaulted
            print(f"[dev-cycle] {exc}")
            return None
        terminal.write("")
        terminal.write(f"[dev-cycle] This plan is Asking human direction on {len(pending)} question(s), recorded "
                       f"by {record['asked_by']} at {record['asked_at']}.")
        for index, entry in enumerate(pending, start=1):
            terminal.write("")
            terminal.write(f"[dev-cycle] question {index} of {len(pending)}"
                           + (f" ({entry['header']})" if entry.get("header") else "") + ":")
            terminal.write(f"[dev-cycle]   {entry['question']}")
            for n, option in enumerate(entry.get("options") or [], start=1):
                terminal.write(f"[dev-cycle]     {n}. {option['label']}"
                               + (f" — {option['description']}" if option.get("description")
                                  else ""))
            reply = terminal.ask_line("[dev-cycle] your answer (number, or your own words, or "
                                      "blank to keep asking): ")
            # Anything that is not a typed line — no terminal, the countdown ran out, a read that
            # failed, a blank — leaves the question open. The same exit the agent's questions take.
            if not isinstance(reply, str) or not reply.strip():
                break
            options = entry.get("options") or []
            entry["answer"] = (options[int(reply) - 1]["label"]
                               if reply.isdigit() and 1 <= int(reply) <= len(options) else reply)
            terminal.write(f"[dev-cycle]   recorded: {entry['answer']}")

    still_open = [q for q in record["questions"] if not q.get("answer")]
    if still_open:
        # Whatever WAS answered is written back before stopping. Losing a settled answer because a
        # later question in the same set went unanswered would make answering twice the price of
        # answering once, and is the loss this whole record exists to prevent.
        text = clear_blocked(text)
        text = _insert_at_top(text, render_blocked(record["resume_at"], record["asked_by"],
                                                   record["questions"], record["asked_at"]))
        plan.write_text(text, encoding="utf-8")
        print(f"[dev-cycle] {len(still_open)} question(s) still unanswered — still Asking human direction. "
              f"Answers already given are kept in the plan.")
        return None

    text = record_answers(clear_blocked(text), record["asked_by"], record["questions"])
    resume_at = resume_node(text, record["resume_at"])
    print(f"[dev-cycle] Every question is answered → resuming at {resume_at}.")
    return _write_plan(plan, text, resume_at, keep_history)


def resume_node(text: str, recorded: str) -> str:
    """Where an answered plan comes back to — the recorded node, or `Implementing`.

    THE ROUTE IS DECIDED WHERE THE CAUSE IS, and the cause is the ANSWER. An answer of the form
    *"that is a row in this sub-set"* adds work to the executing sub-set, and the node that asked
    cannot do it: `Documenting` writes prose, and prose cannot close a thing that is not written.
    So the sub-set's `Impl` cells are read at resume time and the plan comes back to the node that
    writes code — the first exit the canonical graph's panel names, taken from `Asking human
    direction` because that is where the question and its answer are.

    Deciding this when the question was PUT is not possible: what grows the scope is the answer,
    which does not exist yet. That is why `resume_at` records where the plan stood and this
    function, not `record_blocked`, chooses.

    Scoped to the **executing** sub-set, for the reason `documenting_gate` is: every later sub-set
    is 🔲 by definition, so an un-scoped read would route every answered plan to `Implementing`.
    `documenting_gate`'s own route-back survives as the safety net for a scope that grew without a
    question — a row added by hand, or work a node found and did not ask about.
    """
    if recorded == "Implementing":
        return recorded
    executing = current_subset(text)
    if executing is None:
        return recorded
    unimplemented = unfinished_in_subset(text, executing["description"])
    if not unimplemented:
        return recorded
    print(f"[dev-cycle] the answer leaves sub-set {executing['index'] + 1} "
          f"({executing['description']}) holding {len(unimplemented)} unimplemented thing(s), so "
          f"the plan resumes at Implementing rather than at {recorded}:")
    for name in unimplemented[:10]:
        print(f"[dev-cycle]     - {name}")
    return "Implementing"


# --- Test-result → plan bookkeeping (folded in after the deterministic Testing run) ----------

def latest_summary() -> Path | None:
    """The newest recorded run, selected BY NAME rather than by mtime.

    The filename carries the run's own timestamp and sorts chronologically; mtime records when the
    file was last WRITTEN, and a checkout, a merge or a rebase rewrites every tracked report and
    hands the oldest run the newest mtime. `deliver` checks the target out, so this is not a
    theoretical ordering: `.githooks/pre-push` learned it first and sorts by name for the same
    reason. The two must agree — a delivery that certifies one run while the gate reads another is
    a delivery that cannot certify itself, which is the whole point of the exercise.
    """
    d = REPO_ROOT / "TEST_REPORTS"
    if not d.is_dir():
        return None
    sums = sorted(d.glob("*-SUMMARY.md"), key=lambda p: p.name, reverse=True)
    return sums[0] if sums else None


#: One row of the SUMMARY's "Per module" table: module, suite, passed, failed, skipped, and the
#: per-module report the run wrote. The report path is what makes per-file attribution possible.
_SUMMARY_ROW_RE = re.compile(
    r"^\|\s*\S+\s+([\w.\-]+)\s*\|"
    r"\s*(backend|frontend|playwright|config|scripts|pytest)\s*\|"
    r"\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|[^|]*\|\s*`?([^`|]*?)`?\s*\|"
)

#: The same row without the trailing report column, for a SUMMARY that does not carry one.
_SUMMARY_ROW_RE_NO_REPORT = re.compile(
    r"^\|\s*\S+\s+([\w.\-]+)\s*\|"
    r"\s*(backend|frontend|playwright|config|scripts|pytest)\s*\|"
    r"\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)"
)


#: The SUMMARY's own verdict line: `**Overall: ❌ FAILED — static analysis (…); every test passed**`.
#: Written by `run_enabled_tests.sh`, which computes it from the test counts AND from the two inputs
#: a count cannot carry — the static-analysis gate, and a suite that died before reporting anything.
_SUMMARY_VERDICT_RE = re.compile(r"^\s*\*\*\s*Overall\s*:\s*(.+?)\s*\*\*\s*$")


def summary_verdict(path: Path) -> str | None:
    """The run's OVERALL verdict, as the runner stated it — or None for a SUMMARY without one.

    `parse_summary()` answers "how many tests failed", and that is a strictly smaller question. A
    run whose every test passed while `ruff`/`mypy`/`tsc` failed is `❌ FAILED — static analysis`,
    and a run whose suite died during collection is `❌ FAILED` with zero failures counted. Reading
    the counts alone turns both into "all tests passing" — see `_status_line()`, which is where that
    was actually written into a plan.

    None is returned for an older SUMMARY that carries no such line, and the caller falls back to
    the counts: inventing a verdict for a report that never stated one would be the same defect
    pointed the other way.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _SUMMARY_VERDICT_RE.match(line)
        if m:
            return m.group(1)
    return None


def parse_summary(path: Path) -> dict[str, dict[str, tuple[int, int, int]]]:
    """Parse the cross-module SUMMARY into module -> suite -> (passed, failed, skipped).

    A **roll-up**, and that is all it can be: one verdict per module per suite kind. It is exactly
    right for the Repos `Tests` counts and wrong in a per-thing cell — see `parse_report_files()`
    for the finer source, and `apply_test_results()` for which one drives which column.
    """
    res: dict[str, dict[str, tuple[int, int, int]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _SUMMARY_ROW_RE_NO_REPORT.match(line)
        if m:
            res.setdefault(m.group(1), {})[m.group(2)] = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
    return res


def summary_report_paths(path: Path) -> dict[tuple[str, str], Path]:
    """(module, suite) -> the per-module report that run wrote, from the SUMMARY's Report column."""
    out: dict[tuple[str, str], Path] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _SUMMARY_ROW_RE.match(line)
        if not m:
            continue
        rel = m.group(6).strip()
        if not rel:
            continue
        report = REPO_ROOT / rel
        if report.is_file():
            out[(m.group(1), m.group(2))] = report
    return out


#: A row of a per-module report's "What was tested" table: the verdict and the test's location,
#: `modules/<m>/backend/TESTS/test_x.py::Class::test_name`.
_REPORT_ROW_RE = re.compile(
    r"^\|\s*(✅|❌|🔵)[^|]*\|[^|]*\|\s*`?([^`|]+?)`?\s*\|"
)

#: A raw pytest progress line, inside the report's `Raw pytest output` block:
#: `scripts/TESTS/test_x.py::TestY::test_z PASSED [ 12%]`.
#:
#: The second source, and it is not redundant. `rules/testing-guidelines.md` says every per-module
#: report carries a *What was tested* table, and the **framework** report does not — it ships raw
#: output only. So every framework row silently fell back to the module roll-up, which is the very
#: thing per-file attribution exists to avoid, in the suite that covers the framework's own tooling.
#: Reading both shapes makes the fold work against every report the runner produces today rather
#: than against the one the rule describes.
_RAW_PYTEST_LINE_RE = re.compile(
    r"^(\S+\.py)::\S+\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b"
)

_RAW_VERDICT_SLOT = {
    "PASSED": 0, "XPASS": 0,
    "FAILED": 1, "ERROR": 1,
    "SKIPPED": 2, "XFAIL": 2,
}

#: What a parsed location must look like to be a test file. Both parsers are given the same gate:
#: a report contains several three-column tables, and only one of them is about tests.
_TEST_FILENAME_RE = re.compile(r"[\w.\-]+\.(?:py|ts|tsx|js|jsx)")


def parse_report_files(path: Path) -> dict[tuple[str, str], dict[str, tuple[int, int, int]]]:
    """(module, suite) -> test-file basename -> (passed, failed, skipped).

    The measurement a per-thing cell needs, and it was available all along. `parse_summary()`
    resolves no finer than one verdict per module per suite, and `apply_test_results()` wrote that
    single verdict into every attributable row — so on the run that prompted this, 36 failures in
    one force-synced file (`test_tenant_isolation.py`, which the plan already carried as a ⛔ row)
    marked 19 other rows across four sub-sets as failing and demoted each `Impl` ✅ → 🛠️. Those rows
    were measured by files that passed in that same run. The plan then read "four sub-sets failing"
    while the run said "one file fails, and the plan knows why".

    There is no JUnit XML in this framework and none is needed: each
    `TEST_REPORTS/<run>-<module>/test-report-<suite>.md` already lists every test with its
    `path::Class::test` location. This reads that.

    Keyed on the **basename**, because that is what a plan row can readably name
    (`test_migrations.py`, not the four-segment path). Two files of the same name in one module's
    suite would collide; the suites are flat directories, so they cannot.
    """
    out: dict[tuple[str, str], dict[str, tuple[int, int, int]]] = {}
    for (module, suite), report in summary_report_paths(path).items():
        text = report.read_text(encoding="utf-8")
        per_file: dict[str, list[int]] = {}

        for line in text.splitlines():
            m = _REPORT_ROW_RE.match(line)
            if not m:
                continue
            location = m.group(2).strip()
            filename = location.split("::", 1)[0].rsplit("/", 1)[-1].strip()
            # Must LOOK like a test file, or any three-column table in the report feeds this. The
            # framework report's "Skipped, by reason" table matched here and produced one entry
            # named `🔵 Skipped` — enough to look like a successful parse and suppress the raw
            # fallback below, so every framework row fell back to the module roll-up instead.
            if not _TEST_FILENAME_RE.fullmatch(filename):
                continue
            counts = per_file.setdefault(filename, [0, 0, 0])
            counts[{"✅": 0, "❌": 1, "🔵": 2}[m.group(1)]] += 1

        if not per_file:
            # No *What was tested* table — the framework report's shape. Fall back to the raw
            # pytest lines, which are a record of the same run and are present in every report.
            for line in text.splitlines():
                m = _RAW_PYTEST_LINE_RE.match(line.strip())
                if not m:
                    continue
                filename = m.group(1).rsplit("/", 1)[-1].strip()
                if not filename:
                    continue
                counts = per_file.setdefault(filename, [0, 0, 0])
                counts[_RAW_VERDICT_SLOT[m.group(2)]] += 1

        if per_file:
            out[(module, suite)] = {k: (v[0], v[1], v[2]) for k, v in per_file.items()}
    return out


#: A test file named in a plan row. Plan rows name what measures them the way a developer would
#: type it — `test_migrations.py` — so that is the token this looks for.
_ROW_TEST_FILE_RE = re.compile(r"\b(test_[\w.]*?\.py)\b")


def _row_test_files(*texts: str) -> list[str]:
    """Test-file basenames a plan row (or its heading) names, in order, without duplicates."""
    seen: list[str] = []
    for text in texts:
        for name in _ROW_TEST_FILE_RE.findall(text or ""):
            if name not in seen:
                seen.append(name)
    return seen


def _verdict(counts: tuple[int, int, int] | None) -> str | None:
    """(passed, failed, skipped) → ✅ / ❌ / None (None = no assertable result, leave the cell)."""
    if not counts:
        return None
    passed, failed, _ = counts
    if failed > 0:
        return "❌"
    if passed > 0:
        return "✅"
    return None


def _row_modules(thing: str, known: list[str]) -> list[str]:
    """Modules a plan row refers to, matched **anywhere** in the row text.

    Plan rows name their module wherever it reads best — `… — module_template`,
    `host_app backend healthcheck`, `(both modules)`. Matching only the first word (the old
    behaviour) silently attributed `TTL JWKS cache … — module_template` to a module called
    "TTL", so its result was dropped and a failing suite left no ❌ anywhere in the table.
    Longest name first, so `module_template` wins over a hypothetical `template`.
    """
    low = thing.lower()
    if re.search(r"\b(both|all|each|every)\s+modules\b", low):
        return list(known)
    hits: list[str] = []
    for name in sorted(known, key=len, reverse=True):
        if name.lower() in low and not any(name.lower() in h.lower() for h in hits):
            hits.append(name)
    return hits


def _worst(verdicts: list[str | None]) -> str | None:
    """❌ beats ✅ beats "no result": a row covering several modules fails if any of them does."""
    if "❌" in verdicts:
        return "❌"
    if "✅" in verdicts:
        return "✅"
    return None


def _fold_cell(current: str, new: str | None) -> str:
    """Apply a fresh verdict to a test cell, keeping ❌ **sticky**.

    A ❌ stays until a run actually proves that thing green again: a missing result (module not
    in this run's SUMMARY) never clears it, so a failure cannot quietly disappear from the plan
    between steps.
    """
    if current == "➖" or new is None:
        return current
    return new


# Impl states that record a *decision*, not a test outcome. A run never overwrites them: no
# amount of green proves that something deliberately not done is now done, and no failure makes a
# blocked thing "being fixed".
TODO = "🔲"       # never started
DOING = "🔄"      # started, in progress
DEFERRED = "⏭️"   # implementable, deliberately not done in this run — say who decided and why
BLOCKED = "⛔"    # cannot be implemented: missing precondition or external blocker
DECIDED_STATES = (DEFERRED, BLOCKED)


def _fold_impl(impl: str, *cells: str) -> str:
    """A thing whose tests fail is `🛠️` (Fixing) until they pass — so the table shows *what* is
    being fixed, not merely that the run is in the Fixing node.

    Takes every test cell of the row (BE, FE, and where present Cfg and Fw), because a thing whose
    configuration contract fails is just as much in Fixing as one whose backend does.

    `⏭️` and `⛔` are left alone: they are human decisions about scope, and a test run has no
    standing to change them.
    """
    if impl in DECIDED_STATES:
        return impl
    failing = "❌" in cells
    if failing and impl in ("✅", "🔲", "🔄"):
        return "🛠️"
    if not failing and impl == "🛠️" and "✅" in cells:
        return "✅"
    return impl

def _count_decided(text: str) -> tuple[int, int]:
    """(deferred, blocked) counts from the plan's **Main implementation summary table**.

    Scoped to section 3 and to ALL of it. `rules/implementation-plan.md` §3 divides that table
    into one sub-table per sub-set, and this used to `break` at the first blank line after the
    first sub-table — so on a plan with five sub-sets it counted only the first. A run with one
    ⏭️ thing in sub-set 2 therefore produced `✅ All tests passing` with no mention of the
    deferred item, which is precisely what the rule says must never happen: *"it names their count
    in the Status summary so a green plan cannot read as 'everything asked for was done'"*.

    Sub-task tables in § *Detailed summary* are still excluded, so a sub-task does not double-count
    the thing it belongs to — that is what the section boundary is for, and it is now the boundary
    being used rather than the first blank line.
    """
    deferred = blocked = 0
    in_section = False
    in_table = False
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("#"):
            # Section 3 starts at its own heading and ends at the next top-level `##`.
            heading = st.lstrip("# ").lower()
            if heading.startswith(("3. main implementation", "main implementation")):
                in_section = True
            elif st.startswith("## "):
                if in_section:
                    break
            in_table = False
            continue
        if not in_section:
            continue
        if not st.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in st.split("|")]
        if "Impl" in cells and "BE test" in cells:
            in_table = True
            continue
        if not in_table or len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue
        if cells[2] == DEFERRED:
            deferred += 1
        elif cells[2] == BLOCKED:
            blocked += 1
    return deferred, blocked


def unfinished_in_subset(text: str, description: str) -> list[str]:
    """Unfinished things in the sub-table belonging to one sub-set.

    The Main implementation summary is divided into a sub-table per sub-set, each introduced by a
    heading carrying that sub-set's description. Scoping the check this way is what lets `Committing`
    tell "this sub-set is finished, move to the next" from "this sub-set is not finished yet".
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and description.strip().lower() in line.lower():
            start = i
            break
    if start is None:
        return []
    # Read to the next heading of the same or higher level.
    end = len(lines)
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    for i in range(start + 1, len(lines)):
        st = lines[i].lstrip()
        if st.startswith("#"):
            if len(lines[i]) - len(lines[i].lstrip("#")) <= level:
                end = i
                break
    return unfinished_things("\n".join(lines[start:end]))


def unfinished_things(text: str) -> list[str]:
    """Main-table things whose `Impl` cell is still 🔲 To do or 🔄 Doing.

    `_count_decided` covers ⏭️ and ⛔ — the states that are *decisions*. It has no notion of
    to-do, so nothing stopped a plan reaching `Done` with most of its scope unstarted: the router
    advances on a green test run, and tests are green whenever nothing is broken, which is not the
    same as the work existing. A purely additive first increment passes every test precisely because
    nothing depends on the parts that are missing.

    Returns the thing names, so the refusal can say which rows rather than only that some exist.
    """
    # Bound the scan to the Main implementation summary SECTION, then read every table inside it.
    #
    # Two requirements pull against each other: the Main summary is now a sub-table per sub-set, so
    # stopping at the first table's end would ignore every sub-set after the first — while sub-task
    # tables in the Detailed summary reuse the same columns and must NOT be counted, or a thing gets
    # counted twice, once as itself and once as its own sub-task.
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Main implementation summary" in l), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        lines = lines[start:end]

    unfinished, in_main = [], False
    for line in lines:
        st = line.strip()
        if not st.startswith("|"):
            in_main = False
            continue
        cells = [c.strip() for c in st.split("|")]
        if "Impl" in cells and "BE test" in cells:
            in_main = True
            continue
        if not in_main or len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue
        if cells[2] in (TODO, DOING):
            unfinished.append(cells[1])
    return unfinished


# --- The `Docs` column: the artifact the Documenting node leaves behind -----------------------
#
# `rules/implementation-plan.md` § *Documenting* makes doc alignment a node of the cycle. A node
# with no artifact is a process rule with nothing to check, which is the failure
# `test_process_rules_are_checked.py` was written for — so every thing carries a `Docs` cell and the
# router refuses to leave `Documenting` while one is still to-do.
DOCS_ALIGNED = "✅"
DOCS_NA = "➖"      # nothing any spec or doc describes -- a claim, and it must be true

#: The tests that actually READ specs and docs. `Documenting` edits documents after `Testing` has
#: run, so without this subset those edits would reach a commit no test had read.
DOCS_GATE_TESTS = (
    "scripts/TESTS/test_docs_describe_the_present.py",
    "scripts/TESTS/test_specs_name_only_paths_that_exist.py",
    "scripts/TESTS/test_agent_skill_topology.py",
    "scripts/TESTS/test_shared_framework_specs_is_complete.py",
    "scripts/TESTS/test_process_rules_are_checked.py",
)


def _docs_column_index(cells: list[str]) -> int | None:
    """Position of the `Docs` header in a split table row, or None when the table has no such column.

    Plans written before the column existed simply have none, and the gate is then vacuous rather
    than failing — history is not retrofitted (`rules/implementation-plan.md` § *Documenting*).
    """
    return cells.index("Docs") if "Docs" in cells else None


def undocumented_things(text: str) -> list[str]:
    """Main-table things whose `Docs` cell is still 🔲 To do or 🔄 Doing.

    Mirrors `unfinished_things` — same section bounding, same sub-table handling — but reads the
    `Docs` column. ⏭️ and ⛔ things are skipped: a thing nobody implemented has no reality for a
    spec to describe, and the decision is already recorded in the Detailed summary.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Main implementation summary" in l), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        lines = lines[start:end]

    pending, docs_at = [], None
    for line in lines:
        st = line.strip()
        if not st.startswith("|"):
            docs_at = None
            continue
        cells = [c.strip() for c in st.split("|")]
        if "Impl" in cells and "BE test" in cells:
            docs_at = _docs_column_index(cells)
            continue
        if docs_at is None or len(cells) <= docs_at or set(cells[1]) <= set("-: "):
            continue
        if cells[2] in DECIDED_STATES:
            continue
        if cells[docs_at] in (TODO, DOING):
            pending.append(cells[1])
    return pending


def undocumented_in_subset(text: str, description: str) -> list[str]:
    """`undocumented_things`, scoped to one sub-set's sub-table."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and description.strip().lower() in line.lower():
            start = i
            break
    if start is None:
        return []
    end = len(lines)
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("#"):
            if len(lines[i]) - len(lines[i].lstrip("#")) <= level:
                end = i
                break
    return undocumented_things("\n".join(lines[start:end]))


def run_docs_gate() -> tuple[int, str, int]:
    """Run the docs-gate subset. Returns (returncode, how-it-was-run, how-many-files-ran).

    Routed through the dev tools container like every other shipped tool-runner
    (`test_shipped_scripts_use_the_container.py`). `IDEABLE_UNRECORDED_RUN` is set deliberately:
    this is a bounded gate on the documents the step just wrote, not the recorded suite that gates a
    push — that stays `run_enabled_tests.sh` at the `Testing` node.

    THE COUNT IS PART OF THE RESULT, and that is the whole reason for the third element. The gate's
    tests live in `scripts/TESTS/`, which is maintainer-only — a remote module project does not have
    them, by design. Returning a bare 0 there made the caller print "docs gate passed" when nothing
    had run, which is the reassuring-signal-for-an-absent-check failure this repository keeps
    paying for: a `--doctor` probe that could not fail, a runner printing green while exiting 1.
    """
    tool = REPO_ROOT / "scripts" / "dev" / "common" / "tool.sh"
    present = [t for t in DOCS_GATE_TESTS if (REPO_ROOT / t).exists()]
    if not present:
        return 0, "no framework doc checks in this project", 0
    if not tool.exists():
        return 0, f"{tool} not found", 0
    env = {**os.environ, "IDEABLE_UNRECORDED_RUN": "1"}
    cmd = [str(tool), "pytest", "-q", *present]
    rc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env).returncode
    return rc, f"{len(present)} file(s) via {tool.name}", len(present)


# --- The delivery message: a plan's abstract, projected from material that already exists ------
#
# `rules/version-control.md` § *Delivering a plan* is the authority for the shape. Two rules govern
# everything below:
#
#   PROSE COMES FROM THE PLAN, EVERY NUMBER COMES FROM A MEASUREMENT. Descriptions, purpose and
#   deferral reasons are human judgement and are copied. Counts come from TEST_REPORTS and from git.
#   The plan's ✅ marks are NOT evidence that tests passed and are never the source of `Tests:` — a
#   plan is a status artifact, and this repo has already paid for treating a written claim as a
#   measurement.
#
#   ⏭️ AND ⛔ ARE NEVER OMITTED. A summary that drops them makes a partial delivery read as
#   "everything asked for was done", at the most visible point in the history.

#: Conventional-commit types, per rules/version-control.md § Commit Guidelines.
COMMIT_TYPES = ("feat", "fix", "docs", "style", "refactor", "test", "chore")

#: Branch commits that describe the process rather than the change. They are the wrong evidence for
#: "what kind of change was this", and they are exactly what the squash removes from the target.
_BOOKKEEPING = re.compile(r"^(?:chore\(dev-cycle\)|docs\(plan\))", re.IGNORECASE)


def plan_purpose(text: str) -> list[str]:
    """The Purpose chapter's first paragraph, as lines. Empty when the plan has none."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Purpose" in l), None)
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.lstrip().startswith("#"):
            break
        if not line.strip():
            if out:
                break
            continue
        out.append(line.strip())
    return out


def plan_subset_things(text: str) -> list[tuple[str, list[str]]]:
    """[(sub-set description, [thing names])] in execution order, from the Main summary section.

    The sub-set descriptions come from the sub-table HEADINGS rather than from the Overall view's
    table, because the headings are what the things sit under — reading the two from different
    places is how they come to disagree.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Main implementation summary" in l), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))

    out: list[tuple[str, list[str]]] = []
    in_table = False
    for line in lines[start + 1:end]:
        st = line.strip()
        if st.startswith("#"):
            desc = st.lstrip("#").strip()
            desc = re.sub(r"^Sub-set\s*\d+\s*[—–-]\s*", "", desc, flags=re.IGNORECASE)
            out.append((desc, []))
            in_table = False
            continue
        if not st.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in st.split("|")]
        if "Impl" in cells and "BE test" in cells:
            in_table = True
            continue
        if not in_table or len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue
        if out and cells[2] not in DECIDED_STATES:
            out[-1][1].append(cells[1])
    return [(d, t) for d, t in out if t]


def plan_decided(text: str) -> list[tuple[str, str, str]]:
    """[(symbol, thing, reason)] for every ⏭️/⛔ row in the Main table.

    The reason is looked up in the Detailed summary: the heading whose words overlap the thing name
    most, then that section's first sentence. A row with no such section still appears, pointing at
    the plan — the entry is never dropped, only its reason can be thin.
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Main implementation summary" in l), None)
    end = (next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
           if start is not None else 0)

    rows: list[tuple[str, str]] = []
    in_table = False
    for line in lines[start + 1:end] if start is not None else []:
        st = line.strip()
        if not st.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in st.split("|")]
        if "Impl" in cells and "BE test" in cells:
            in_table = True
            continue
        if not in_table or len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue
        if cells[2] in DECIDED_STATES:
            rows.append((cells[2], cells[1]))
    return [(sym, thing, _reason_for(text, thing)) for sym, thing in rows]


def _reason_for(text: str, thing: str) -> str:
    """First sentence of the Detailed-summary section that best matches `thing`."""
    words = {w for w in re.findall(r"[a-z_]{4,}", thing.lower())}
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.lstrip().startswith("#") and "Detailed summary" in l), None)
    if start is None or not words:
        return "see the Detailed summary in the plan"
    best, best_at = 0, None
    for i in range(start + 1, len(lines)):
        st = lines[i].lstrip()
        if not st.startswith("#"):
            continue
        if lines[i].startswith("## "):
            break
        score = len(words & {w for w in re.findall(r"[a-z_]{4,}", st.lower())})
        if score > best:
            best, best_at = score, i
    if best_at is None:
        return "see the Detailed summary in the plan"
    body: list[str] = []
    for line in lines[best_at + 1:]:
        if line.lstrip().startswith("#"):
            break
        if line.strip():
            body.append(line.strip())
        elif body:
            break
    prose = re.sub(r"\*\*|\*|`", "", " ".join(body))
    sentence = re.split(r"(?<=[.!?])\s", prose)[0] if prose else ""
    return sentence.strip() or "see the Detailed summary in the plan"


def _branch_commit_subjects(target: str, branch: str) -> list[str]:
    r = _git("log", "--format=%s", f"{target}..{branch}", capture=True)
    return [l for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else []


def delivery_type_and_scope(target: str, branch: str, text: str) -> tuple[str, str]:
    """`<type>` and `<scope>` for the subject line, measured from the branch's own commits.

    The type is the commonest conventional type among the real commits — bookkeeping checkpoints are
    excluded, because "this plan was mostly chore(dev-cycle)" says nothing about the change. The
    scope is the commonest scope, falling back to the first Repos row's module.
    """
    subjects = [s for s in _branch_commit_subjects(target, branch) if not _BOOKKEEPING.match(s)]
    types: dict[str, int] = {}
    scopes: dict[str, int] = {}
    for subj in subjects:
        m = re.match(r"^(\w+)\(([^)]*)\):", subj)
        if not m:
            continue
        if m.group(1) in COMMIT_TYPES:
            types[m.group(1)] = types.get(m.group(1), 0) + 1
        scopes[m.group(2)] = scopes.get(m.group(2), 0) + 1
    ctype = max(types, key=lambda k: types[k]) if types else "feat"
    if scopes:
        return ctype, max(scopes, key=lambda k: scopes[k])
    return ctype, _first_repo_row(text) or "framework"


def _first_repo_row(text: str) -> str | None:
    """The first module named in the plan's Repos table — the scope fallback for a branch with no
    conventional-commit subjects to read (a plan whose commits are all bookkeeping, or none yet)."""
    in_repos = False
    for line in text.splitlines():
        st = line.strip()
        if not st.startswith("|"):
            in_repos = False
            continue
        cells = [c.strip() for c in st.split("|")]
        if any(c.startswith("Repo") for c in cells):
            in_repos = True
            continue
        if not in_repos or len(cells) < 3 or set(cells[1]) <= set("-: "):
            continue
        # "Ideable — framework (`rules/`, `scripts/`)" -> "framework"; "host_app (…)" -> "host_app".
        cell = re.sub(r"\s*\(.*$", "", cells[1]).strip().strip("`")
        segments = [seg.strip().strip("`") for seg in re.split(r"[—–]", cell) if seg.strip()]
        segments = [seg for seg in segments if seg.lower() != "ideable"]
        if segments:
            return segments[-1].split()[0]
    return None


def delivery_subject(text: str, ctype: str, scope: str, plan_path: Path) -> str:
    """`<type>(<scope>): <what the plan delivered>`, ≤72 chars.

    The description comes from the plan's H1, which is prose a human wrote, rather than from the
    filename slug, which is a filesystem-safe mangling of it.
    """
    m = re.search(r"^#\s*Implementation plan\s*[—–-]\s*(.+)$", text, re.MULTILINE)
    parts = _plan_parts(plan_path.stem)
    what = (m.group(1) if m else (parts[2] if parts else plan_path.stem)).strip()
    subject = f"{ctype}({scope}): {what}"
    if len(subject) > 72:
        room = 72 - len(f"{ctype}({scope}): ") - 1
        subject = f"{ctype}({scope}): {what[:max(room, 0)].rstrip()}…"
    return subject


def delivery_evidence(target: str, branch: str, text: str) -> list[str]:
    """The `Tests:` / `Files:` / `Sub-sets:` lines. Every one of them measured, none read off ✅."""
    out: list[str] = []
    summary = latest_summary()
    if summary is not None:
        totals = [0, 0, 0]
        for suites in parse_summary(summary).values():
            for counts in suites.values():
                for i in range(3):
                    totals[i] += counts[i]
        stamp = summary.name.replace("-SUMMARY.md", "")
        out.append(f"Tests: {totals[0]} passed / {totals[1]} failed / {totals[2]} skipped ({stamp})")

    r = _git("diff", "--name-only", f"{target}...{branch}", capture=True)
    if r.returncode == 0:
        paths = [f for f in r.stdout.splitlines() if f.strip()]
        # Every plan rewrites its own plan file and drops a TEST_REPORTS run per Testing node, so
        # counting those buries the change: one measured delivery read "238 changed across .devin,
        # TEST_REPORTS, framework, host_app, implementation-plans, kanban, module_template". The
        # bookkeeping is real and is still counted — it is just not what the reader came for, so it
        # goes in a parenthesis instead of setting the headline number.
        work = [f for f in paths if not f.startswith(_BOOKKEEPING_PATHS)]
        book = len(paths) - len(work)
        mods = sorted({_top_area(f) for f in work})
        line = f"Files: {len(work)} changed across {', '.join(mods) if mods else 'the repo'}"
        if book:
            line += f" (plus {book} plan and test-report files)"
        out.append(line)

    out.append(f"Sub-sets: {len(plan_subset_things(text))}")
    return out


#: Paths every plan touches by construction: its own artifact and the runs it recorded.
_BOOKKEEPING_PATHS = ("implementation-plans/", "TEST_REPORTS/")


def _top_area(path: str) -> str:
    """The area a changed path belongs to, for the `Files:` line."""
    parts = path.split("/")
    if parts[0] == "modules" and len(parts) > 1:
        return parts[1]
    if parts[0] in ("scripts", "rules", ".agents", ".githooks", ".github"):
        return "framework"
    if parts[0] == "reusable.ui":
        return "reusable.ui"
    return parts[0] if len(parts) > 1 else "repo root"


def _plain(text: str) -> str:
    """Markdown emphasis and code ticks removed — a commit message is read as plain text."""
    return re.sub(r"\s{2,}", " ", re.sub(r"\*\*|\*|`", "", text)).strip()


def _thing_text(name: str) -> str:
    """A thing's name as it should read in a commit message.

    Two pieces of plan bookkeeping are dropped. The trailing `— <module>` exists so the test-result
    fold can attribute the row (`rules/implementation-plan.md` § *Name the module in every row*);
    the message's `Files:` line already names the areas, and thirty repetitions of `— framework`
    are noise. `**Added:**` marks a row appended mid-run, which is a fact about the plan, not about
    what was delivered.
    """
    out = re.sub(r"\s*[—–]\s*(?:both modules|all modules|[\w./ ,+_-]{1,60})\s*$", "", name)
    out = re.sub(r"\*\*Added:\*\*\s*", "", out).strip()
    return out or name.strip()


def _wrap(text: str, width: int = 76, indent: str = "") -> list[str]:
    """Wrap a body paragraph. Commit bodies are read in terminals; 76 leaves room for `git log`."""
    words, line, out = text.split(), "", []
    for w in words:
        candidate = f"{line} {w}".strip()
        if len(candidate) + len(indent) > width and line:
            out.append(indent + line)
            line = w
        else:
            line = candidate
    if line:
        out.append(indent + line)
    return out


def plan_delivery_message(plan: Path, target: str, branch: str,
                          kanban: str | None = None) -> str:
    """The whole message: subject, purpose, Delivered, decisions, evidence, trailers."""
    text = plan.read_text(encoding="utf-8")
    ctype, scope = delivery_type_and_scope(target, branch, text)

    parts: list[str] = [delivery_subject(text, ctype, scope, plan), ""]

    purpose = plan_purpose(text)
    if purpose:
        prose = _plain(" ".join(purpose))
        parts += _wrap(prose) + [""]

    subsets_ = plan_subset_things(text)
    if subsets_:
        parts.append("Delivered:")
        for desc, things in subsets_:
            parts += _wrap(_plain(desc), indent="")[:1] or [f"- {desc}"]
            parts[-1] = "- " + parts[-1].lstrip("- ")
            # Uncapped, by decision: the plan's own things are the abstract's detail, and the
            # branch that held them is deleted at delivery. Measured worst case is a 47-line body.
            for t in things:
                wrapped = _wrap(_plain(_thing_text(t)), width=74)
                parts.append(f"  - {wrapped[0]}")
                parts += [f"    {w}" for w in wrapped[1:]]
        parts.append("")

    decided = plan_decided(text)
    if decided:
        for sym, thing, reason in decided:
            label = "Deferred (⏭️)" if sym == DEFERRED else "Blocked (⛔)"
            wrapped = _wrap(_plain(f"{label}: {_thing_text(thing)} — {reason}"))
            parts.append(wrapped[0])
            parts += [f"  {w}" for w in wrapped[1:]]
        parts.append("")

    parts += delivery_evidence(target, branch, text) + [""]

    parts.append(f"Plan: {plan.relative_to(REPO_ROOT).as_posix()}")
    if kanban:
        parts.append(f"Kanban: {kanban}")
    summary = latest_summary()
    if summary is not None:
        parts.append(f"Test-Report: {summary.relative_to(REPO_ROOT).as_posix()}")

    return "\n".join(parts).rstrip() + "\n"


def _decided_clause(text: str) -> str:
    """The clause that stops a plan with unfinished-by-decision things reading as fully complete."""
    deferred, blocked = _count_decided(text)
    parts = []
    if deferred:
        parts.append(f"{deferred} thing{'s' if deferred != 1 else ''} deferred by decision")
    if blocked:
        parts.append(f"{blocked} blocked")
    return f"; {', '.join(parts)} (see the Detailed summary)" if parts else ""


def _status_line(results: dict[str, dict[str, tuple[int, int, int]]], text: str = "",
                 verdict: str | None = None) -> str:
    """One short, truthful Status-summary line for this run's results.

    Failing runs always overwrite the line — the failure must be stated where a reader looks
    first. A green line only replaces a previous *generated* failure line (see the caller), so a
    skill's own summary is never clobbered by a passing run.

    Green does not mean complete: a plan carrying things that were deferred or blocked says so on
    the same line, or "all tests passing" reads as "everything asked for was done".

    THE RUN'S OWN VERDICT OUTRANKS THE COUNTS, and it has to. `verdict` is the SUMMARY's
    `**Overall: …**` line, and the counts are one input to it: the static-analysis gate and a suite
    that died before reporting are the other two. On 2026-09-11-08-56-18 the runner said
    *"❌ FAILED — static analysis (ruff / mypy / tsc); every test passed"* and this function wrote
    `✅ All tests passing` into the plan from the counts — which made
    `rules/implementation-plan.md` § *A failure must be visible, and sticky*, a MANDATORY rule,
    false at the one line a reader looks at first. A count of failing tests is not a verdict about
    a run; the verdict is, so it is read and stated as the runner stated it.
    """
    failed_suites = [
        (mod, suite, counts[1])
        for mod, suites in results.items() for suite, counts in suites.items() if counts[1]
    ]
    passed = sum(c[0] for suites in results.values() for c in suites.values())
    if failed_suites:
        total = sum(n for _, _, n in failed_suites)
        detail = ", ".join(f"{mod} {suite}: {n} failed" for mod, suite, n in sorted(failed_suites))
        line = (f"❌ {total} test{'s' if total != 1 else ''} failing ({detail}) — "
                f"things with a failing suite are marked 🛠️ below; fixing in progress")
    elif verdict is not None and not verdict.startswith("✅"):
        # Every test green and the RUN still not green. Quote the runner's own words rather than
        # paraphrasing them: whatever new reason it grows (a gate, a suite that never ran), the
        # plan states it instead of reporting the subset of it this function happens to model.
        mark = verdict[0] if verdict[:1] in ("❌", "🔵") else "❌"
        stated = verdict.removeprefix(mark).strip()
        line = (f"{mark} The run did not pass — {stated} ({passed} passed / 0 failed, so the test "
                f"counts alone would have read as green; this states the run's own verdict)")
    else:
        line = f"✅ All tests passing ({passed} passed / 0 failed) across {len(results)} module(s)"
    return line + _decided_clause(text) + "."


def apply_test_results(text: str) -> tuple[str, list[str]]:
    """Fold the latest TEST_REPORTS SUMMARY into the plan: set each thing's BE/FE test cell
    (BE ⇐ the module's pytest suite, FE ⇐ its playwright suite) and the Repos `Tests` counts.
    Deterministic and best-effort — cells marked ➖ and rows whose module can't be identified
    are left untouched (and reported). Returns (new_text, log lines)."""
    summ = latest_summary()
    if summ is None:
        return text, ["no TEST_REPORTS *-SUMMARY.md found — test columns left unchanged"]
    results = parse_summary(summ)
    per_file = parse_report_files(summ)
    known = list(results)
    logs = [f"using {summ.name}"]
    #: Rows this fold could not attribute to a module, so it left them exactly as they were.
    #: Collected rather than logged one by one — see the report built at the end of this function.
    unattributed: list[tuple[str, list[str]]] = []
    #: Rows that named no test file, so the module ROLL-UP was used. Reported, because the roll-up
    #: is an estimate of coverage and not a measurement of this row — see § *the roll-up* below.
    rolled_up: list[str] = []
    #: A test file a row named that no report mentions. Almost always a typo or a renamed file, and
    #: silently falling back to the roll-up would make the row look measured when it is not.
    unmatched_files: list[tuple[str, str]] = []
    lines = text.splitlines()
    mode: str | None = None  # 'things' (Impl/BE/FE tables) | 'repos' | None
    heading = ""             # nearest heading above the table — extra context for attribution
    for i, line in enumerate(lines):
        st = line.strip()
        if not st.startswith("|"):
            mode = None  # any non-table line ends the current table
            if st.startswith("#"):
                heading = st.lstrip("# ")
            continue
        cells = [c.strip() for c in line.split("|")]
        # Tables are recognised by their HEADER, not by the heading above them, so the Main
        # table and every sub-task table in the Detailed summary are folded the same way.
        if "Impl" in cells and "BE test" in cells:
            mode = "things"
            continue
        if "Tests" in cells and any(c.startswith("Repo") for c in cells):
            mode = "repos"
            continue
        if len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue  # separator row or too few columns

        if mode == "things":
            thing = cells[1]
            # A sub-task row often names its module only in the heading it sits under.
            mods = _row_modules(thing, known) or _row_modules(heading, known)
            if not mods and len(known) == 1:
                mods = known  # single-module run: every row belongs to it
            if not mods:
                unattributed.append((thing, list(cells)))
                continue
            # Column order is fixed by the header: Impl, BE test, FE test, then optionally
            # Cfg test and Fw test. Older plans have three columns and fold exactly as before.
            #
            #   BE  ⇐ <m>/backend/TESTS
            #   FE  ⇐ <m>/frontend/TESTS (pytest contracts) and its playwright suite
            #   Cfg ⇐ <m>/TESTS and every other sub-module's TESTS — the module's own
            #         configuration and deployment contracts
            #   Fw  ⇐ scripts/TESTS — framework tooling, which belongs to no module, so it is
            #         folded from the run rather than from `mods`
            impl = cells[2]
            if impl == TODO:
                # A thing that has not been started has nothing to test, so a suite result says
                # nothing about it. Folding the module's green suite onto it produced rows reading
                # "not implemented, tests pass" — a claim that is not merely useless but false, and
                # the same shape of over-stated signal as a green run over a suite that never ran.
                logs.append(f"{thing[:44]}: {TODO} not started — test cells left unchanged")
                continue
            # Which suites feed which column. `mods` scopes it to the row's own module(s); the Fw
            # column is folded from the run, because framework tooling belongs to no module.
            suites = {
                3: [(m, "backend") for m in mods],
                4: [(m, "frontend") for m in mods] + [(m, "playwright") for m in mods],
                5: [(m, "config") for m in mods],
                6: [("framework", "scripts")],
            }

            # ── Per file where the row says so, the module roll-up otherwise ──────────────────
            #
            # A row that names the test files measuring it gets a verdict from exactly those files.
            # A row that names none gets the module roll-up — the best available estimate of what
            # covers it, and no more than an estimate, which is why it is not allowed to demote
            # `Impl` below and is reported at the end.
            named = _row_test_files(thing, heading)
            row_files = [f for f in named if any(f in per_file.get(key, {}) for key in
                                                 sum(suites.values(), []))]
            for missing in (f for f in named if f not in row_files):
                # `row_files` decides whether this row still gets measured: a row naming two files
                # of which one matched is measured by the one that did, and only a row where NONE
                # matched falls back to the roll-up. Recorded per file so the report can say which
                # actually happened, rather than asserting a fallback that did not occur.
                unmatched_files.append((thing, missing, bool(row_files)))

            counts_by_col: dict[int, list[tuple[int, int, int] | None]] = {}
            for idx, keys in suites.items():
                if row_files:
                    counts_by_col[idx] = [
                        per_file.get(key, {}).get(f) for key in keys for f in row_files
                    ]
                else:
                    counts_by_col[idx] = [
                        results.get(key[0], {}).get(key[1]) for key in keys
                    ]

            before = list(cells)
            for idx, counts in counts_by_col.items():
                if idx >= len(cells) - 1:
                    continue
                cells[idx] = _fold_cell(cells[idx], _worst([_verdict(c) for c in counts]))

            if row_files:
                new_impl = _fold_impl(
                    impl, *[cells[i] for i in sorted(counts_by_col) if i < len(cells) - 1]
                )
            else:
                # The roll-up stays out of `Impl`.
                #
                # This is the single change that fixes the reported defect: 36 failures in one
                # already-⛔ file demoted 19 unrelated rows to 🛠️ *Fixing*, and a plan cannot reach
                # `Done` while any of them is down. `Impl` is a statement about a thing, and
                # "some test somewhere in this module failed" is not one. The failure is still
                # visible — the test cell above carries ❌ — which is what
                # `rules/implementation-plan.md` § *A failure must be visible, and sticky* asks for.
                new_impl = impl
                rolled_up.append(thing)
            cells[2] = new_impl
            if cells == before:
                continue
            lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
            names = {3: "BE", 4: "FE", 5: "Cfg", 6: "Fw"}
            changed = ", ".join(
                f"{names[i]} {before[i]}→{cells[i]}" for i in sorted(names)
                if i < len(cells) - 1 and before[i] != cells[i]
            )
            source = f" [from {', '.join(row_files)}]" if row_files else " [module roll-up]"
            logs.append(
                f"{thing[:44]}: Impl {impl}→{new_impl}" + (f", {changed}" if changed else "") + source
            )
        elif mode == "repos":
            mres = results.get(cells[1], {})
            if mres and len(cells) > 3:
                passed = sum(v[0] for v in mres.values())
                failed = sum(v[1] for v in mres.values())
                cells[3] = f"{passed} passed / {failed} failed / 0 pending"
                lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
                logs.append(f"repo {cells[1]}: {passed} passed / {failed} failed")

    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")

    # A row this fold could not attribute is LEFT UNCHANGED, which is the right thing to do — a
    # green run attributed to rows nothing exercised would make ✅ meaningless. But it is not the
    # right thing to say quietly.
    #
    # This used to emit one `no module named in the row — left unchanged` line per row, with the
    # same prefix as every successful update. A real run produced thirty of them interleaved with
    # forty updates, and five sub-task rows kept `BE test: 🔲` — "not yet started" — directly above
    # a Status summary this same function had just written as "✅ All tests passing". Both were
    # generated by this code and neither was wrong on its own terms. The information existed and
    # could not be read, which is the same failure as a sync that prints "Converged" after
    # delivering nothing.
    #
    # So the report is aggregated, last, and split by whether it MATTERS: a row carrying `➖`
    # everywhere is unattributable and fine (a shell script has no backend suite), while a row
    # still showing 🔲/🔄 after a run is a cell that now reads as unstarted work.
    if unattributed:
        stale = [t for t, cells in unattributed
                 if any(c in (TODO, DOING) for c in cells[3:-1])]
        logs.append(
            f"⚠ {len(unattributed)} row(s) name no enabled module, so this fold LEFT THEM "
            f"UNCHANGED (correct — attributing a run to rows nothing exercised would make ✅ "
            f"meaningless)."
        )
        if stale:
            logs.append(
                f"⚠ {len(stale)} of them still show 🔲/🔄 in a test column and will read as "
                f"UNSTARTED WORK. Name the module in the row (or use ➖ where no test of that kind "
                f"applies) — rules/implementation-plan.md § Name the module in every row:"
            )
            for thing in stale:
                logs.append(f"⚠     {thing[:88]}")
        else:
            logs.append("⚠ None of them carry 🔲/🔄, so nothing reads as unstarted.")

    # A row measured by a file it named is a measurement. A row filled from the module roll-up is
    # an estimate, and the difference has to be legible or the two are read as the same claim.
    if unmatched_files:
        logs.append(
            f"⚠ {len(unmatched_files)} row(s) name a test file this run's reports do not mention — "
            f"a rename or a typo:"
        )
        for thing, missing, still_measured in unmatched_files:
            # Two different outcomes, and saying "fell back to the roll-up" for both would be the
            # same class of over-stated signal this change exists to remove.
            outcome = ("row still measured by its other named file(s)" if still_measured
                       else "row fell back to the MODULE ROLL-UP")
            logs.append(f"⚠     {missing} — {outcome} — in row: {thing[:56]}")
    if rolled_up:
        logs.append(
            f"ℹ {len(rolled_up)} row(s) name no test file, so their test cells carry the MODULE "
            f"ROLL-UP — one verdict per module per suite, not a measurement of that row. Their "
            f"`Impl` was therefore left alone: one failing file must not mark every row of the "
            f"module as being fixed. Name the file(s) that measure a row (e.g. "
            f"`test_migrations.py`) to have it measured — rules/implementation-plan.md § "
            f"Name what measures a row."
        )

    # Failing run → always state the failure in the Status summary. Green run → only clear a
    # previously generated failure line (a skill's own summary is left alone), so the plan can
    # never keep claiming a failure that has been fixed.
    line = _status_line(results, new_text, summary_verdict(summ))
    current = status_summary(new_text) or ""
    # Rewrite when this run was NOT green, or when the existing line is one we generated (it starts
    # with ✅/❌/🔵). A human-written summary starts with none of them and is left alone.
    #
    # "Not green" rather than "starts with ❌", because the verdict line above can also be 🔵
    # (`SKIPPED / no assertions` — a run that asserted nothing), and a failure that does not
    # overwrite the plan's summary is a failure the reader never sees.
    if not line.startswith("✅") or current.startswith(("❌", "✅", "🔵")):
        new_text, n = re.subn(r"(#+\s*(?:\d+\.\s*)?Status summary\s*\n+)[^\n]+",
                              lambda m: m.group(1) + line, new_text, count=1)
        logs.append("status summary: " + (line if n else "NOT updated (section not found)"))
    return new_text, logs


#: Paths that RECORD a run rather than being the work it did. A checkpoint touching only these —
#: every `Branching` commit, and every plain state advance — changed no repo's code, so it is
#: attributed to no Repos row. Without this, the plan file's own commit would mark the framework
#: `Committed` at the moment the branch was created.
BOOKKEEPING_PREFIXES = ("implementation-plans/", "kanban/", "TEST_REPORTS/")

#: The scope every non-`modules/` path belongs to. `scripts/`, `rules/`, `.githooks/`,
#: `.github/`, `reusable.ui/`, the root wrappers — the framework itself, which has no
#: `modules/<name>/` prefix to be discovered under, and so was invisible to the attribution
#: until 2026-09-08.
FRAMEWORK_SCOPE = "framework"


def commit_scopes(paths: Iterable[str]) -> set[str]:
    """The Repos scopes a set of touched paths belongs to.

    A path under `modules/<name>/` belongs to that module; run bookkeeping belongs to nothing;
    everything else is the framework. Pure, so it can be checked without a repository.
    """
    scopes: set[str] = set()
    for path in paths:
        path = path.strip()
        if not path or path.startswith(BOOKKEEPING_PREFIXES):
            continue
        parts = path.split("/")
        if parts[0] == "modules" and len(parts) > 2:
            scopes.add(parts[1])
        else:
            scopes.add(FRAMEWORK_SCOPE)
    return scopes


def row_scope(label: str) -> str:
    """The scope a Repos row's label names.

    The framework row lists its paths in a parenthetical — ``framework (`scripts/`, `rules/`)`` —
    so the label is not the scope; the leading name is.
    """
    return label.split("(")[0].strip().strip("*`_ ")


def plan_commits(base: str = "main") -> list[tuple[str, str, set[str]]]:
    """Commits on this branch that `base` doesn't have: (sha, subject, scopes touched).

    Scopes are derived from the paths each commit touches (see `commit_scopes`), so a commit can
    be attributed to the Repos rows it actually changed without anyone hand-labelling it.
    """
    if not _git_enabled():
        return []
    r = _git("log", "--format=%h%x00%s", f"{base}..HEAD", capture=True)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    out: list[tuple[str, str, set[str]]] = []
    for entry in r.stdout.strip().splitlines():
        sha, _, subject = entry.partition("\0")
        files = _git("show", "--name-only", "--format=", sha, capture=True)
        out.append((sha, subject, commit_scopes((files.stdout or "").splitlines())))
    return out


def _is_checkpoint(subject: str) -> bool:
    """The router's own per-step checkpoint commits — real commits, but not the curated ones a
    reader wants to see in the plan's `Commit` cell."""
    return bool(re.match(r"^chore\(dev-cycle\): (plan/|re-stamp)", subject))


def _commit_cell(commits: list[tuple[str, str]], show: int = 3) -> str:
    """Render a Repos `Commit` cell: the curated commits, or the checkpoints when that's all
    there is (the work is still committed either way)."""
    curated = [(sha, subj) for sha, subj in commits if not _is_checkpoint(subj)]
    if not curated:
        # No curated commit touched this module — the work rode in on the router's own
        # checkpoint(s). Name the latest so the reader can still find it.
        sha, subj = commits[0]
        more = f", +{len(commits) - 1} more" if len(commits) > 1 else ""
        return f'Committed — dev-cycle checkpoint "{subj}" ({sha}){more}'
    shown = ", ".join(f'"{subj}" ({sha})' for sha, subj in curated[:show])
    extra = len(curated) - show
    return "Committed — " + shown + (f", +{extra} more" if extra > 0 else "")


def apply_commit_results(text: str, base: str = "main") -> tuple[str, list[str]]:
    """Fold this plan branch's commits into the Repos `Commit` cells.

    The Committing step is an agent step, so nothing deterministic used to guarantee the plan's
    `Commit` cells were ever updated — a plan could (and did) reach `Done` still claiming
    `Not committed` while the work sat committed on its branch. Git is the authority here, so the
    router reads it and writes the cells itself. A cell already marked `Pushed` is left alone —
    that is a human-confirmed state the router cannot observe.

    A row **no commit touched** keeps whatever it says: `Not committed` is the truth for a module
    the branch never changed, and writing `Committed` there would trade one false cell for another.
    Returns (new_text, log lines).
    """
    commits = plan_commits(base)
    if not commits:
        return text, [f"no commits on this branch vs {base} — Commit cells left unchanged"]
    logs = [f"{len(commits)} commit(s) vs {base}"]
    lines = text.splitlines()
    in_repos = False
    for i, line in enumerate(lines):
        st = line.strip()
        if not st.startswith("|"):
            in_repos = False
            continue
        cells = [c.strip() for c in line.split("|")]
        if "Commit" in cells and any(c.startswith("Repo") for c in cells):
            in_repos = True
            continue
        if not in_repos or len(cells) < 5 or set(cells[1]) <= set("-: "):
            continue
        module, current = cells[1], cells[4]
        if current.startswith("Pushed"):
            continue  # human-confirmed state; the router cannot verify a push
        scope = row_scope(module)
        mine = [(sha, subj) for sha, subj, scopes in commits if scope in scopes]
        if not mine:
            continue
        cells[4] = _commit_cell(mine)
        lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
        logs.append(f"repo {scope}: {len(mine)} commit(s) → Committed")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), logs


# --- Git branch-per-plan integration (always on; DEV_CYCLE_NO_GIT=1 disables for a run) -------

def _git_enabled() -> bool:
    if os.environ.get("DEV_CYCLE_NO_GIT"):
        return False
    return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=str(REPO_ROOT),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _git(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO_ROOT), text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def plan_branch(plan: Path) -> str:
    """`plan/<description>` — the plan's description slug, made branch-safe."""
    return f"plan/{_describes(plan_description(plan)) or 'unnamed'}"


# --- One process per plan ---------------------------------------------------------------------
#
# WHAT THIS PREVENTS, and why it is not a check on WHO is calling. Two processes working one plan
# concurrently is the hazard: on 2026-08-26 a router run spawned a second agent onto a plan an
# agent was already implementing by hand, and the two edited the same tree; on 2026-09-10 a second
# `redeploy.sh` was started while a router run was still executing, and they raced on image labels
# and on a commit that landed mid-build. The first was addressed by refusing agent callers, which
# could not see the second at all — same hazard, no agent involved.
#
# So the lock is on the PLAN, for the duration of the work, and it refuses every second worker
# equally. `status` takes none: reading a plan is not working it.

LOCKS_DIR = REPO_ROOT / ".ideable-work" / "dev-cycle-locks"


def _lock_path(plan: Path) -> Path:
    """One lock per plan, keyed by its DESCRIPTION.

    Not by the filename: that carries the state and is renamed at every transition, so two callers
    a transition apart would take two different locks and neither would see the other.
    """
    return LOCKS_DIR / f"{plan_branch(plan).removeprefix('plan/')}.lock"


def _readable(path: Path) -> str:
    """A path as a reader would type it: repo-relative when it is inside the repo, absolute when
    it is not. `Path.relative_to` RAISES for a path outside, and doing that while composing a
    refusal message replaces the diagnosis with a `ValueError` from the error path itself."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _holder(path: Path) -> dict:
    """What the lock file says, or `{}` when it is unreadable — an unreadable lock is not a wall."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _holder_is_running(info: dict) -> bool:
    """Whether the recorded holder is still alive, decided only where it can be decided.

    A lock left by a killed process must not block the plan forever, and a lock held by a live
    process must never be stolen. `os.kill(pid, 0)` answers that on THIS host; for another host
    there is no answer from here, so the holder is assumed alive and the message says how to clear
    it by hand. Guessing "probably dead" is how two workers get in.
    """
    if info.get("host") != socket.gethostname():
        return True
    pid = info.get("pid")
    if not isinstance(pid, int):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def plan_lock(plan: Path, what: str):
    """Hold `plan` for the duration of `what`, or refuse naming who holds it.

    Released in a `finally`, and SIGTERM is turned into a `SystemExit` so that `finally` runs for
    it too — a lock that survives its own process is the failure mode that makes locking worse than
    not locking.
    """
    path = _lock_path(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    mine = {"pid": os.getpid(), "host": socket.gethostname(), "what": what,
            "plan": plan.name, "since": _now()}
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            info = _holder(path)
            if _holder_is_running(info):
                print(f"[dev-cycle] '{plan.name}' is already being worked by "
                      f"{info.get('what', 'another dev-cycle run')} "
                      f"(pid {info.get('pid', '?')} on {info.get('host', '?')}, since "
                      f"{info.get('since', '?')}).")
                print("[dev-cycle] Refusing to start a second worker on the same plan: two of them "
                      "edit one tree, and each then sees the other's diffs with no idea where they "
                      "came from.")
                print(f"[dev-cycle] Wait for it, or — if that process is gone — remove "
                      f"{_readable(path)}.")
                sys.exit(3)
            print(f"[dev-cycle] Taking over a lock left by pid {info.get('pid', '?')}, which is no "
                  f"longer running.")
            path.unlink(missing_ok=True)
            continue
        break
    os.write(fd, json.dumps(mine, indent=2).encode("utf-8"))
    os.close(fd)
    previous = signal.getsignal(signal.SIGTERM)

    def _term(_signum, _frame):
        raise SystemExit(f"[dev-cycle] terminated while {what}")

    with contextlib.suppress(ValueError):  # not the main thread: no handler to install
        signal.signal(signal.SIGTERM, _term)
    try:
        yield path
    finally:
        with contextlib.suppress(ValueError):
            signal.signal(signal.SIGTERM, previous)
        path.unlink(missing_ok=True)


def _current_branch() -> str | None:
    r = _git("rev-parse", "--abbrev-ref", "HEAD", capture=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def ensure_plan_branch(plan: Path) -> None:
    """Make sure work is on the plan's branch, creating it from the current branch if missing."""
    if not _git_enabled():
        return
    br = plan_branch(plan)
    if _current_branch() == br:
        return
    exists = _git("rev-parse", "--verify", "--quiet", f"refs/heads/{br}", capture=True).returncode == 0
    _git("checkout", br) if exists else _git("checkout", "-b", br)
    print(f"[dev-cycle] git: {'switched to' if exists else 'created'} plan branch '{br}'")


def commit_progress(plan: Path, node: str) -> None:
    """Checkpoint the whole working tree on the plan branch (never on main); skip if clean.

    THE `Commit` CELLS ARE FOLDED AT EVERY CHECKPOINT, not only at `Committing`. The fold used to
    run in `run`'s `Committing` branch alone, which left every transition before it describing a
    repository that had already moved: this router commits the tree at each one, so the first
    checkpoint carrying a repo's scope makes `Not committed` false for that row, and
    `test_plan_status_is_true.py` says so — correctly — at the next `Testing`.

    AFTER the commit rather than before it, because the checkpoint is itself one of the commits
    the cell is a claim about. Folding first can only see the branch as it was: the commit that
    carries a sub-set's work also carries the plan file, so a fold running before it wrote
    `Not committed` into the very commit that falsified it. That is the shape the 2026-09-10 run
    failed on — `57adc92` held both the work and the plan denying it.
    """
    if not _git_enabled():
        return
    cur = _current_branch()
    if not (cur and cur.startswith("plan/")):
        return  # only ever commit on a plan branch
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return  # nothing staged
    msg = f"chore(dev-cycle): {cur} → {node}"
    if _git("commit", "-q", "-m", msg).returncode != 0:
        return
    print(f"[dev-cycle] git: committed progress on '{cur}' — {msg}")
    fold_commit_cells(plan, cur, node)


def fold_commit_cells(plan: Path, branch: str, node: str) -> None:
    """Write the plan's Repos `Commit` cells from git, in a follow-up commit of its own.

    A SECOND COMMIT RATHER THAN AN AMEND, because the cell names the checkpoint's short sha and
    amending would change it — trading a stale `Not committed` for a sha that no longer resolves.
    The follow-up touches `implementation-plans/` only, which `commit_scopes` attributes to no
    scope, so it cannot itself make a row it just corrected go stale.

    It also leaves the tree clean, which is the property `test_a_green_run_certifies_a_commit.py`
    depends on: the suite must run against a commit rather than a working tree.
    """
    if not plan.exists():
        return
    before = plan.read_text(encoding="utf-8")
    folded, logs = apply_commit_results(before)
    if folded == before:
        return  # nothing to correct — the common case, and the fold is idempotent
    plan.write_text(folded, encoding="utf-8")
    for msg in logs:
        print(f"[dev-cycle]   commit-column: {msg}")
    _git("add", "--", str(plan))
    if _git("commit", "-q", "-m", f"chore(dev-cycle): {branch} → {node} (Commit cells)").returncode == 0:
        print(f"[dev-cycle] git: folded the Repos Commit cells into the plan on '{branch}'")
    else:
        # Said out loud, because the corrected plan is now uncommitted: the run that follows would
        # be recorded against a dirty tree, and a silent version of this is the defect this
        # function exists to end.
        print("[dev-cycle] WARNING: the Commit cells were corrected but could not be committed — "
              "the tree is dirty and the next recorded run will say so")


def suggest_merge(plan: Path) -> None:
    """At `Done`, PRINT the merge/push commands. Never ask, never run them.

    This used to prompt at the commit step and merge into `main` on a `y`. Two things were wrong
    with that, and both belong to the maintainer rather than to this router:

    - **Timing.** A question at `Committing` blocks an unattended run for an answer nobody has a
      reason to give yet: the work has not finished being judged. A plan can be green and committed
      and still want a manual pass — an exploratory test, a look at the deployed UI — before it
      joins a shared branch.
    - **Target.** `main` is the common case, not the rule. A release branch, a long-running
      integration branch, or a fork's branch are all legitimate, and nothing here can know which.

    So `Done` is reached with the plan branch unmerged, and that is the expected state rather than
    an unfinished one. See rules/implementation-plan.md § Git integration.
    """
    if not _git_enabled():
        return
    br = plan_branch(plan)
    print(f"[dev-cycle] Plan complete on '{br}'. Landing it is `deliver`, which composes the")
    print("[dev-cycle] message, squashes onto the target and deletes the branch:")
    print("[dev-cycle]   ./scripts/dev/common/dev-cycle.sh deliver --dry-run     # see the message, touch nothing")
    print("[dev-cycle]   ./scripts/dev/common/dev-cycle.sh deliver               # confirm, squash, push")
    print("[dev-cycle]   ./scripts/dev/common/dev-cycle.sh deliver --target release/1.4")
    print("[dev-cycle] Whether to land, and into what, stay yours — deliver asks, it does not decide.")


# --- deliver: Done -> Merged ------------------------------------------------------------------

DEFAULT_TARGET = "main"


def _kanban_card(plan: Path) -> Path | None:
    """The kanban card matching this plan's description slug, wherever it currently sits."""
    parts = _plan_parts(plan.stem)
    desc = parts[2] if parts else None
    if not desc:
        return None
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", desc).strip("-").lower()
    for state in ("doing", "todo", "done"):
        cand = REPO_ROOT / "kanban" / state / f"{slug}.md"
        if cand.exists():
            return cand
    return None


def _confirm(question: str, assume_yes: bool) -> bool:
    """Ask, unless the answer was granted on the command line.

    A non-interactive run without `--yes` STOPS and says what to pass. It does not assume: whether
    to land the work is the maintainer's decision (`rules/general-guidelines.md` § decision
    authority), and a script silently choosing "yes" is that decision being taken by nobody.
    """
    if assume_yes:
        print(f"[deliver] {question} — granted by --yes.")
        return True
    if not sys.stdin.isatty():
        print(f"[deliver] {question}")
        print("[deliver] Non-interactive and no --yes: stopping. Re-run with --yes (and --target "
              "<branch> if not main) when you mean to land it.")
        return False
    return input(f"[deliver] {question} [y/N] ").strip().lower() in ("y", "yes")


def documenting_gate(plan: Path) -> tuple[bool, int, list[str]]:
    """The two things that must hold before a plan may leave `Documenting`.

    `run` is the only route off the node, and it REFUSES on a failure rather than warning. The gate
    used to warn on one of its two callers, because a second writer of plan state needs an escape
    hatch and a gate that takes one away is a gate that gets worked around. With one writer there is
    nothing to soften: a refusal here cannot strand anyone, since the only way past it is to make the
    claim true. `test_dev_cycle_docs_gate.py` checks that no second exit comes back.

    Returns `(ok, rc, back)`. `back` is the third outcome and it is not a failure: the things of the
    executing sub-set whose **`Impl`** is still 🔲/🔄, which send the plan back to `Implementing`
    instead of holding it here.

    WHY A THIRD OUTCOME EXISTS. A sub-set's scope can GROW at `Documenting` — a maintainer answers a
    question with "that is a row in this sub-set", or the node finds a document it cannot reconcile
    without new code. The row is then unimplemented, `undocumented_things()` skips only ⏭️ and ⛔ so
    it counts as undocumented, and the refusal said *"fix it in place, then run again"* — but the
    fix is code, and the node that writes code is `Implementing`. The next `run` re-invoked the same
    skill onto the same rows, and the plan could only be moved by renaming it by hand. `Committing`
    has said the same thing correctly all along (*"has N thing(s) left → back to Implementing on the
    same sub-set"*); this is that arc, at the one node that lacked it.

    IT IS THE SAFETY NET, NOT THE DRAWN PATH. When the scope grew because a question was answered,
    `resume_node` takes the route one step earlier, at `Asking human direction` — where the cause
    is. What is left
    for this outcome is a sub-set that grew with no question behind it: a row added by hand, or work
    a node found and did not ask about. A net catches what the path did not, and the canonical graph
    draws the path.

    Unimplemented rows are looked for ONLY when a sub-set is executing. Un-scoped, the check would
    read the whole Main table — where every later sub-set is 🔲 by definition — and route every plan
    back at its first `Documenting`.
    """
    text = plan.read_text(encoding="utf-8")
    executing = current_subset(text)
    if executing is not None:
        unimplemented = unfinished_in_subset(text, executing["description"])
        if unimplemented:
            print(f"[dev-cycle] sub-set {executing['index'] + 1} ({executing['description']}) "
                  f"grew: {len(unimplemented)} thing(s) are not implemented yet, so there is "
                  f"nothing written for a document to describe:")
            for name in unimplemented[:10]:
                print(f"[dev-cycle]     - {name}")
            print("[dev-cycle] Documenting cannot close a sub-set whose scope is unfinished, and "
                  "the fix is code, not prose.")
            return False, 0, unimplemented
    left = (undocumented_in_subset(text, executing["description"])
            if executing else undocumented_things(text))
    if left:
        print(f"[dev-cycle] {len(left)} thing(s) still have a Docs cell to do:")
        for name in left[:10]:
            print(f"[dev-cycle]     - {name}")
        print("[dev-cycle] `➖` is the honest mark for a thing no spec or doc describes — but it "
              "is a claim, so make it deliberately.")
        return False, 0, []
    rc, how, ran = run_docs_gate()
    if rc != 0:
        print(f"[dev-cycle] docs gate FAILED (exit {rc}, {how}).")
        return False, rc, []
    if not ran:
        # Never "passed" — nothing was asked. `scripts/TESTS/` is maintainer-only, so in a remote
        # module project the step's guarantees rest on the skill's judgement and the `Docs` column.
        print(f"[dev-cycle] docs gate DID NOT RUN ({how}). The Docs cells are the only artifact "
              "here — the framework's doc checks are maintainer-only.")
        return True, 0, []
    print(f"[dev-cycle] docs gate passed ({how}).")
    return True, 0, []


def message_subject(message: str) -> str:
    """A composed message's first line — what the pull request title must be.

    Distinct from `delivery_subject()` above, which BUILDS a subject from a plan. This splits one
    that has already been built.
    """
    return message.splitlines()[0].strip() if message.strip() else ""


def message_body(message: str) -> str:
    """Everything after the subject — what the pull request body must be."""
    rest = message.split("\n", 1)[1] if "\n" in message else ""
    return rest.lstrip("\n")


def pr_merge_command(pr: str, subject: str, body_file: str) -> str:
    """The one command that merges a delivery PR without losing its message.

    GitHub's squash-merge does NOT reuse the branch's commit message: its default subject is
    `<PR title> (#N)` and its default body concatenates the branch's commits. Both break the
    delivery format this project checks — the ` (#N)` suffix eats into the 72-character subject
    limit, and the `Plan:` / `Kanban:` / `Test-Report:` trailers that
    `test_plan_deliveries_say_what_they_did.py` reads would be replaced by whatever the router's
    checkpoints happened to say. Passing `--subject` and `--body-file` makes the landed commit
    byte-for-byte the message composed from the plan.
    """
    return (f"gh pr merge {pr} --squash --subject {shlex.quote(subject)} "
            f"--body-file {shlex.quote(body_file)}")


def _commits_target_has(branch: str, target: str) -> int:
    """How many commits `target` carries that `branch` does not. -1 when git cannot answer."""
    r = _git("rev-list", "--count", f"{branch}..{target}", capture=True)
    if r.returncode != 0:
        return -1
    try:
        return int(r.stdout.strip() or 0)
    except ValueError:
        return -1


# --- A delivery certifies itself ----------------------------------------------------------------
#
# THE COMMAND THAT NEEDS THE CERTIFICATE IS THE ONE THAT PRODUCES IT. `.githooks/pre-push` refuses a
# push whose code was never tested green, and it is right to — but it runs at the very end, after the
# delivered commit is already on the target, which leaves the maintainer holding a local branch they
# cannot push. Measured on 2026-09-12: one delivery refused four times in a row, for a stale
# assertion, for a suite run before the commit rather than after, and for the run's own report
# dirtying the tree it had just certified. Every refusal was correct; the sequence is simply not one
# a person drives reliably by hand.
#
# TWO ORDERINGS ARE FORCED, and they are the two that were got wrong:
#   * the tree is COMMITTED BEFORE THE RUN — `deliver` already refuses a dirty tree, so HEAD is a
#     commit and the report certifies it rather than a working tree tied to nothing;
#   * the report is COMMITTED AFTER IT — so the tree that gets pushed carries its own certificate,
#     instead of the run's own output being the thing that makes the tree dirty.

#: What a delivery and the run itself rewrite AFTER the suite, and which therefore cannot make a
#: tested tree untested. It is the same set as `BOOKKEEPING_PREFIXES` and says the same thing —
#: these paths record a run rather than being the work it did — so it is that set, not a second
#: copy of it.
#:
#: A SUBSET of `.githooks/pre-push`'s `BOOKKEEPING_PATHS`, not an equal: the hook also forgives
#: `framework.env` and `framework.lock.json`, because a RELEASE commit is bookkeeping in the same
#: sense and `publish_framework.sh` writes those two itself. `deliver` lands plans, never releases,
#: so it gains nothing by forgiving them — and naming them here would make this the second Python
#: file that mentions the lock, which `test_framework_version_is_one_line.py` forbids for a good
#: reason. The direction of the inequality is what matters and
#: `test_a_delivery_certifies_itself.py` pins it: stricter than the gate only ever costs a suite
#: run that was not needed, while looser certifies a tree the push then refuses — the failure this
#: whole mechanism exists to move earlier.
DELIVERY_BOOKKEEPING = BOOKKEEPING_PREFIXES

_CERTIFIED_SHA_RE = re.compile(r"^- Commit: `([0-9a-f]{7,})`", re.MULTILINE)


def certified_commit(summary: Path | None = None) -> str | None:
    """The commit the newest recorded run says it tested, or None when nothing recorded one."""
    summary = summary or latest_summary()
    if summary is None:
        return None
    try:
        m = _CERTIFIED_SHA_RE.search(summary.read_text(encoding="utf-8"))
    except OSError:
        return None
    return m.group(1) if m else None


def delivery_needs_a_run(certified: str | None) -> tuple[bool, list[str]]:
    """`(needs_run, the paths that make it necessary)` for the tree at HEAD.

    A run is needed unless every path that differs between the certified commit and HEAD is
    bookkeeping. No certified commit at all means a run is needed and there is nothing to list —
    the honest answer to "what changed since the run?" when there is no run.
    """
    if not certified:
        return True, []
    changed = _git("diff", "--name-only", certified, "HEAD", capture=True)
    if changed.returncode != 0:
        # The recorded commit is not in this history — a rebase, a fresh clone, a squashed branch.
        # Unknown is not the same as unchanged, so it is run rather than assumed.
        return True, []
    paths = [p for p in changed.stdout.splitlines() if p.strip()]
    substantive = [p for p in paths if not p.startswith(DELIVERY_BOOKKEEPING)]
    return bool(substantive), substantive


def certify_delivery() -> int:
    """Make HEAD's tree provably green, running the suite when it is not already. 0 when certified.

    Called with a CLEAN tree and before any of the delivery's own bookkeeping, so a refusal here
    leaves the plan at `Done`, the kanban card where it was and nothing on the target.
    """
    summary = latest_summary()
    certified = certified_commit(summary)
    needs, paths = delivery_needs_a_run(certified)
    if not needs:
        # `needs` is False only when a summary named a commit, so both are present here. Asserted
        # rather than assumed: the alternative is two `or ""` fallbacks printing an empty name.
        assert summary is not None and certified is not None
        print(f"[deliver] Certified by {summary.name} ({certified[:12]}): HEAD's tree differs only "
              f"in bookkeeping, so the suite is not re-run.")
        return 0

    if certified and summary is not None:
        print(f"[deliver] HEAD has moved since {summary.name} certified {certified[:12]}, in "
              f"{len(paths)} path(s) a run must cover:")
        for path in paths[:10]:
            print(f"[deliver]     {path}")
        if len(paths) > 10:
            print(f"[deliver]     … and {len(paths) - 10} more")
    else:
        print("[deliver] No recorded run names a commit, so nothing certifies this tree.")
    print("[deliver] Running the suite against HEAD — the command that needs the certificate is "
          "the one that produces it. Nothing has been landed yet.")

    runner = DRIVER["Testing"][1]
    if runner is None:
        print("[deliver] No test runner is configured for `Testing`, so this tree cannot be "
              "certified. Nothing has been landed.")
        return 1
    rc = subprocess.run([runner], cwd=str(REPO_ROOT)).returncode
    produced = latest_summary()
    verdict = summary_verdict(produced) if produced is not None else None
    if rc != 0 or produced is None or not verdict or "PASSED" not in verdict:
        print(f"[deliver] The suite did not pass ({verdict or f'exit {rc}'}). NOTHING has been "
              "landed: the plan is still Done, the kanban card has not moved and the target is "
              "untouched.")
        print("[deliver] Fix it — `./scripts/dev/common/dev-cycle.sh run` from a node that reaches "
              "Fixing — then deliver again.")
        return 1

    # The report is committed HERE, after the run and before the squash, so the tree that gets
    # pushed carries the certificate for itself. Left uncommitted it would dirty the very tree it
    # certifies, which is one of the four refusals that produced this function.
    if _git("status", "--porcelain", capture=True).stdout.strip():
        _git("add", "-A")
        _git("commit", "-m", f"chore(tests): the run that certifies {certified_commit() or 'HEAD'}")
    print(f"[deliver] Green: {produced.name} certifies this tree.")
    return 0


def do_deliver(plan: Path, target: str, dry_run: bool, assume_yes: bool,
               keep_history: bool, open_pr: bool = False) -> int:
    """Land a `Done` plan on `target` as ONE squashed commit whose message is the plan's abstract.

    Squash, not merge, and by decision: the implement-fix-refix sequence is not useful on a shared
    branch, and the plan branch is deleted afterwards. What survives is the plan artifact — which is
    tracked, and which this function writes into the delivered commit before squashing, so the
    per-thing detail outlives the branch that produced it.

    `open_pr` lands it under review instead: the same bookkeeping commit is made on the branch, the
    branch is pushed, and a pull request is opened. Nothing is committed to the target and the
    branch is kept — GitHub creates the delivered commit at merge time, so the reviewer sees the
    change before it is on the shared branch rather than after. `rules/version-control.md`
    § *Git Workflow* requires this route for plan-driven work.
    """
    if not _git_enabled():
        print("[deliver] Git is disabled (DEV_CYCLE_NO_GIT) — nothing to deliver.")
        return 1

    text = plan.read_text(encoding="utf-8")
    node = current_node(text)
    if node != "Done":
        print(f"[deliver] The plan is at '{node}', not 'Done'. Delivery lands finished work; "
              "finish the cycle first.")
        return 1

    branch = plan_branch(plan)
    if _current_branch() != branch:
        print(f"[deliver] Not on the plan branch. Expected '{branch}', on "
              f"'{_current_branch()}'.")
        return 1
    if _git("status", "--porcelain", capture=True).stdout.strip():
        print("[deliver] The working tree is dirty. Commit or stash first — a delivery must be "
              "exactly what was tested.")
        return 1

    # A run recorded against a dirty tree is tied to no commit, so it cannot say that THIS code is
    # green. Refuse here, before anything is squashed: the push gate would catch it, but only after
    # the delivery commit is already on the target branch, which is exactly where this defect was
    # found — the maintainer left holding a local `main` they could not push.
    _summary = latest_summary()
    if _summary is not None:
        _recorded = re.search(r"^- Working tree: `(\w+)`",
                              _summary.read_text(encoding="utf-8"), re.MULTILINE)
        if _recorded and _recorded.group(1) == "dirty":
            print(f"[deliver] The newest run ({_summary.name}) was recorded against a DIRTY tree, "
                  "so it certifies no commit and cannot say this code is green.")
            print("[deliver] Re-run the suite on a committed tree — "
                  "`./scripts/dev/common/dev-cycle.sh run` from a node that reaches Testing — "
                  "then deliver again. Nothing has been landed.")
            return 1

    card = _kanban_card(plan)
    card_dest = (REPO_ROOT / "kanban" / "done" / card.name) if card else None
    kanban_ref = card_dest.relative_to(REPO_ROOT).as_posix() if card_dest else None

    message = plan_delivery_message(plan, target, branch, kanban_ref)
    print("\n" + "-" * 72)
    print(message, end="")
    print("-" * 72 + "\n")

    if dry_run:
        # It says whether the suite WOULD run, because that is most of what a real delivery will
        # spend, and a dry run that describes only the message describes the cheap half.
        _needs, _paths = delivery_needs_a_run(certified_commit())
        print(f"[deliver] --dry-run: nothing was changed. A real delivery would "
              f"{'RUN THE SUITE first (' + str(len(_paths)) + ' uncertified path(s))' if _needs else 'not re-run the suite'}.")
        return 0

    if open_pr:
        if not shutil.which("gh"):
            print("[deliver] --pr needs the GitHub CLI (`gh`) and it is not on PATH.")
            return 1
        # Below `--dry-run` on purpose: `git fetch` writes remote-tracking refs, and --dry-run is
        # documented as changing nothing. A dry run prints the message and makes no claim about
        # whether the PR route would succeed.
        _git("fetch", "--quiet", "origin", target)
        # A moved target is refused rather than merged. The message's `Tests:` and `Files:` lines
        # were measured against THIS branch's tree; if the target has moved, GitHub squash-merges
        # branch+target and lands a tree nobody tested while the message still reports the old
        # numbers. The direct route never had to care: it squashes onto the target immediately, so
        # the two cannot drift apart. A review window is exactly the gap where they can.
        for ref in (target, f"origin/{target}"):
            behind = _commits_target_has(branch, ref)
            if behind > 0:
                print(f"[deliver] '{ref}' has {behind} commit(s) this branch does not. A "
                      "squash-merge would land a tree that was never tested, under a message "
                      "whose numbers describe a different one.")
                print(f"[deliver] Rebase onto '{ref}', re-run the suite, then deliver again.")
                return 1

    question = (f"Open a pull request from '{branch}' onto '{target}' with the message above?"
                if open_pr else
                f"Squash '{branch}' onto '{target}' with the message above?")
    if not _confirm(question, assume_yes):
        print("[deliver] Not delivered. The branch is untouched.")
        return 0

    # 0. CERTIFY THE TREE, before any of the delivery's own bookkeeping. The order matters both
    #    ways: HEAD is clean here (refused above otherwise) so a run certifies a COMMIT, and a
    #    refusal at this point has renamed no plan, moved no card and touched no target.
    if certify_delivery() != 0:
        return 1

    # 1. Final bookkeeping ON THE BRANCH, so the delivered commit carries it. The plan file is the
    #    only surviving record of per-thing detail once the branch is gone, so it must be the
    #    (Merged) version that lands, not the (Done) one.
    delivered_plan = _write_plan(plan, plan.read_text(encoding="utf-8"), "Merged", keep_history)
    delivered_plan.write_text(_mark_repos_pushed(delivered_plan.read_text(encoding="utf-8")),
                              encoding="utf-8")
    # The run that owned the agent session is over. Dropped here and not at `pause`, which is the
    # other place a plan stops being worked: a paused plan is picked up again, and a session recorded
    # for the sub-set it left is exactly what `resume` should try first.
    drop_session(plan)
    if card and card_dest and card != card_dest:
        card_dest.parent.mkdir(parents=True, exist_ok=True)
        card.rename(card_dest)
        print(f"[deliver] kanban: {card.relative_to(REPO_ROOT)} → {card_dest.relative_to(REPO_ROOT)}")
    _git("add", "-A")
    _git("commit", "-m", f"docs(plan): {plan_branch(plan)} reaches Merged")

    # The message names the plan file, which step 1 may have renamed — recompose against the tree
    # that is actually being delivered rather than the one that was printed.
    message = plan_delivery_message(delivered_plan, target, branch, kanban_ref)

    if open_pr:
        return _open_delivery_pr(branch, target, message)

    # 2. Squash onto the target.
    if _git("checkout", target).returncode != 0:
        print(f"[deliver] Could not check out '{target}'.")
        return 1
    r = _git("merge", "--squash", branch, capture=True)
    if r.returncode != 0:
        conflicts = _git("diff", "--name-only", "--diff-filter=U", capture=True).stdout.strip()
        print("[deliver] The squash hit conflicts. Nothing has been committed or pushed.")
        for path in conflicts.splitlines():
            print(f"[deliver]     {path}")
        print("[deliver] Resolve them yourself — this never resolves a conflict automatically.")
        return 1

    msg_file = REPO_ROOT / ".git" / "IDEABLE_DELIVERY_MSG"
    msg_file.write_text(message, encoding="utf-8")
    if _git("commit", "-F", str(msg_file)).returncode != 0:
        print("[deliver] The commit failed — the squash is still staged.")
        return 1
    msg_file.unlink(missing_ok=True)
    delivered = _git("rev-parse", "HEAD", capture=True).stdout.strip()
    parents = _git("rev-list", "--parents", "-n", "1", "HEAD", capture=True).stdout.split()
    print(f"[deliver] Delivered as {delivered[:12]} on {target} "
          f"({len(parents) - 1} parent — a squash, as intended).")

    # 3. Push, then delete the branch. In that order: git does not record a squash as merged, so a
    #    surviving branch would re-apply on a second deliver.
    if _confirm(f"Push '{target}'?", assume_yes):
        if _git("push", "origin", target).returncode != 0:
            print("[deliver] The push failed. The commit is on your local "
                  f"'{target}'; the plan branch is kept until it lands.")
            return 1
        # The cleanup is REPORTED, never assumed. Both of these used to run unconditionally and be
        # followed by one line claiming they had both worked — so a delivery of a plan branch that
        # had never been pushed printed:
        #
        #     error: unable to delete 'plan/x': remote ref does not exist
        #     error: failed to push some refs
        #     [deliver] Pushed, and deleted 'plan/x' locally and on origin.
        #
        # Two failures and a success claim, in that order. Nothing in the dev-cycle pushes a plan
        # branch, so "it was never on origin" is the NORMAL case, not an error — but a line that
        # says otherwise is a lying signal, and this repository has already paid for those.
        local_gone = _git("branch", "-D", branch).returncode == 0
        on_origin = bool(_git("ls-remote", "--heads", "origin", branch, capture=True).stdout.strip())
        remote_gone = _git("push", "origin", "--delete", branch).returncode == 0 if on_origin else None

        print(f"[deliver] Pushed '{target}'.")
        if local_gone:
            print(f"[deliver] Deleted '{branch}' locally.")
        else:
            print(f"[deliver] WARNING: could not delete '{branch}' locally. git does not record a "
                  f"squash as merged, so a surviving plan branch would RE-APPLY on a second "
                  f"deliver. Remove it: git branch -D {branch}")
        if remote_gone is None:
            print(f"[deliver] '{branch}' was never pushed, so there was nothing to delete on origin.")
        elif remote_gone:
            print(f"[deliver] Deleted '{branch}' on origin.")
        else:
            print(f"[deliver] WARNING: '{branch}' is still on origin — the delete was refused. "
                  f"Remove it: git push origin --delete {branch}")
    else:
        print(f"[deliver] Not pushed. '{branch}' is kept — delete it once '{target}' is pushed.")
    return 0


def _open_delivery_pr(branch: str, target: str, message: str) -> int:
    """Push the plan branch and open the delivery pull request. The target is not touched.

    The branch is deliberately NOT deleted: the direct route deletes it because git does not record
    a squash as merged, but here the branch is the pull request — it has to outlive this command.
    GitHub deletes it on merge when the repository is configured to.
    """
    subject, body = message_subject(message), message_body(message)

    if _git("push", "--set-upstream", "origin", branch).returncode != 0:
        print(f"[deliver] Pushing '{branch}' failed. Nothing was opened; the branch is intact.")
        return 1

    r = subprocess.run(
        ["gh", "pr", "create", "--base", target, "--head", branch,
         "--title", subject, "--body", body],
        cwd=str(REPO_ROOT), text=True, capture_output=True,
    )
    if r.returncode != 0:
        print("[deliver] `gh pr create` failed:")
        print((r.stderr or r.stdout).strip())
        print(f"[deliver] '{branch}' is pushed, so the PR can be opened by hand.")
        return 1
    url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""

    # The message is written out so the merge can reuse it verbatim rather than being retyped.
    msg_file = REPO_ROOT / ".git" / "IDEABLE_DELIVERY_MSG"
    msg_file.write_text(body, encoding="utf-8")

    print(f"[deliver] Pull request opened: {url}")
    print(f"[deliver] '{target}' was NOT modified and '{branch}' is kept until the PR merges.")
    print("[deliver] Merge it with THIS command — GitHub's own squash-merge would replace the")
    print("[deliver] message's trailers and push the subject past 72 characters:")
    print(f"[deliver]   {pr_merge_command(url or '<pr>', subject, str(msg_file))}")
    return 0


def _mark_repos_pushed(text: str) -> str:
    """Repos `Commit` cells → `Pushed`, now that the work is landing on the target."""
    out = []
    in_repos = False
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("|") and any(c.strip().startswith("Repo") for c in st.split("|")):
            in_repos = True
            out.append(line)
            continue
        if in_repos and st.startswith("|") and "Committed" in line:
            out.append(line.replace("Committed", "Pushed"))
            continue
        if not st.startswith("|"):
            in_repos = False
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def do_status(plan: Path) -> None:
    text = plan.read_text(encoding="utf-8")
    node = current_node(text)
    print(f"Active plan : {plan.relative_to(REPO_ROOT)}")
    print(f"Created at  : {line_value(text, 'Created at') or '—'}")
    print(f"Last updated: {line_value(text, 'Last updated') or '—'}")
    print(f"Current step: {line_value(text, 'Current step') or '—'}")
    summ = status_summary(text)
    if summ:
        print(f"Status      : {summ}")
    print()
    if not node:
        print("No current node highlighted (no `class … current;` line found).")
        return
    print(f"Current node: {node}")
    nxt = NEXT.get(node, [])
    if nxt:
        print(f"Next        : {' or '.join(nxt)}")
    for target in [t.split()[0] for t in nxt]:
        drv, runnable = DRIVER.get(target, ("?", None))
        if target in ("NotStarted", "Branching"):
            mark = "▶ performed by the router"
        else:
            mark = "▶ runnable here" if runnable else "→ agent/human step"
        print(f"   {target:<11} via {drv}   [{mark}]")


# --- start: becoming the active plan is an act ------------------------------------------------
#
# WHY THIS EXISTS. Before it, a plan became the active one by being the newest file in
# `implementation-plans/` — nothing anywhere recorded that a choice had been made, and the choice
# could not even be expressed. `start` is that choice: it creates the plan's `ACTIVE PLAN` link,
# which is the only thing `active_plan()` and the in-flight guard read.


def startable_plans() -> list[Path]:
    """The plans `start` would accept: at `NotStarted`, and not already named by a link.

    Deliberately NOT every unlinked plan. `implementation-plans/` holds seventy delivered plans,
    and offering those as candidates would bury the one or two a reader actually means.
    """
    named = {link_description(link) for link in active_links()}
    return [p for p in _all_plan_files()
            if plan_state(p) == "NotStarted" and plan_description(p) not in named]


def _all_plan_files() -> list[Path]:
    """Every real plan file in the directory, newest first — links and non-plans excluded."""
    if not PLANS_DIR.is_dir():
        return []
    found = [p for p in PLANS_DIR.glob("*.md")
             if not p.is_symlink() and _plan_parts(p.stem) is not None]
    return sorted(found, key=_plan_order, reverse=True)


def do_start(description: str | None) -> int:
    """Make a plan the active one, and refuse anything that is not a plan waiting to begin."""
    candidates = startable_plans()

    def _list_candidates() -> None:
        if candidates:
            print("[start] These plans are waiting to be started:")
            for p in candidates:
                print(f"[start]   ./scripts/dev/common/dev-cycle.sh start {plan_description(p)}")
        else:
            print("[start] Nothing is waiting to be started: a plan is created at NotStarted by "
                  "ideable-implement-specs or ideable-bugfixing-and-changes.")

    if description is None:
        # Not "the only candidate wins": which plan is the work in hand is a decision, and it is
        # the same one `resume` refuses to take on the reader's behalf.
        if candidates:
            print("[start] Which plan is the work in hand is a decision, so say which one:")
        _list_candidates()
        return 1

    slug = _describes(description)
    matches = [p for p in _all_plan_files() if _describes(plan_description(p)) == slug]
    if not matches:
        print(f"[start] No plan called '{description}' in {_readable(PLANS_DIR)}.")
        _list_candidates()
        return 1
    # Newest first, so under --keep-history a plan's own trail resolves to its current file.
    plan = matches[0]

    if is_paused(plan):
        print(f"[start] '{plan.name}' is parked, not waiting to begin. A paused plan is picked up "
              f"at the node it left:")
        print(f"[start]   ./scripts/dev/common/dev-cycle.sh resume {plan_description(plan)}")
        return 1

    link = active_link_path(plan)
    if link.is_symlink() or link.exists():
        print(f"[start] '{plan_description(plan)}' is already the active plan "
              f"({plan_state(plan) or 'no state in its name'}). Nothing was changed.")
        return 0

    state = plan_state(plan)
    if state != "NotStarted":
        # Refused rather than allowed, because `start` on a plan mid-flight is almost always a plan
        # whose link was lost, and guessing which file of it is current is the guess this whole
        # sub-set removes. The escape is manual and deliberate, like the `set`-on-Merged refusal.
        print(f"[start] '{plan.name}' is at {state or 'no state in its name'}, not NotStarted, so "
              f"it is not a plan waiting to begin.")
        print("[start] A plan past NotStarted is either in flight already (its link was created by "
              "its first transition), parked (`resume` picks it up), or delivered.")
        print("[start] If its link was genuinely lost, recreate it by hand — deliberately, "
              "because nothing else will:")
        print(f"[start]   ln -sfn '{plan.name}' '{_readable(link)}'")
        return 1

    live = plans_in_flight()
    if live:
        # Starting a second plan would manufacture exactly the ambiguity `run` and `status` refuse,
        # and it would do it at the one moment a person is present to settle it instead.
        print(f"[start] '{live[0].name}' is already in flight, and two plans in flight is the "
              f"ambiguity `run` and `status` refuse. Park it first:")
        print("[start]   ./scripts/dev/common/dev-cycle.sh pause")
        return 1

    with plan_lock(plan, "a start"):
        sync_active_link(plan, "NotStarted")
    print(f"[start] '{plan.name}' is the active plan — '{link.name}' now names it.")
    print("[start] Nothing else changed: the plan is still at NotStarted and has no branch yet.")
    print("[start] Drive it with:")
    print("[start]   ./scripts/dev/common/dev-cycle.sh run --auto-advance 2   "
          "# Branching, then Implementing")
    return 0


# --- pause / resume: a plan is parked, and picked up again where it left ----------------------
#
# WHY THIS EXISTS. A plan can stop being the thing to work on without being finished: something
# more urgent arrives, or a prerequisite turns out to belong to a different plan. Before `pause`
# the only way to do that was to rename the file by hand and leave the checkout wherever it stood,
# which is how a plan came to be "parked at Documenting" with nothing recording that fact and no
# defined way back.
#
# WHY A PAUSED PLAN IS FOUND ON ITS BRANCH AND NOT IN THE WORKING TREE. A plan's artifact lives on
# `plan/<description>` until `deliver` squashes it onto the target, and `pause` deliberately ends
# on the target so the next plan branches from a clean base. The paused file is therefore absent
# from the tree by design, and scanning `implementation-plans/` for it would answer "nothing is
# paused" for every paused plan there is. `paused_plans()` asks the branches instead — the same
# correction `test_plan_branch_has_a_plan.py` already had to make for the same reason.


def _branch_exists(branch: str) -> bool:
    return _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                capture=True).returncode == 0


def _write_paused(plan: Path, keep_history: bool) -> Path:
    """Rename the plan to `(Paused)` WITHOUT touching the graph highlight.

    Every other transition rewrites the two `class` lines; this one must not, and that is the whole
    mechanism: the highlight is the record of where to resume, so `resume` needs nothing else
    written down. `Current step` is the one line that changes, because a reader of a parked plan
    needs to know it is parked and how to pick it up — and `resume` recomputes that line from the
    highlight, so overwriting it here loses nothing.
    """
    text = plan.read_text(encoding="utf-8")
    node = current_node(text)
    description = plan_branch(plan).removeprefix("plan/")
    step = (f"PAUSED at {NODE_DISPLAY.get(node, node)} — resume with "
            f"`./scripts/dev/common/dev-cycle.sh resume {description}`")
    text = re.sub(r"(\*\*Current step\*\*\s*[:—-]\s*).+",
                  lambda m: m.group(1) + step, text, count=1)
    text = re.sub(r"(\*\*Last updated\*\*\s*[:—-]\s*).+",
                  lambda m: m.group(1) + _now(), text, count=1)
    target = _state_path(plan, PAUSED_STATE, unique=keep_history)
    target.write_text(text, encoding="utf-8")
    if target != plan and not keep_history and plan.exists():
        plan.unlink()
    sync_active_link(target, PAUSED_STATE)
    print(f"[pause] → {target.name}: parked, still highlighting {node} "
          f"(updated {_now()})")
    return target


def do_pause(plan: Path, target: str, keep_history: bool) -> int:
    """Park the active plan on its own branch and leave the checkout on the delivery target."""
    if not _git_enabled():
        print("[pause] Git is disabled (DEV_CYCLE_NO_GIT). A pause parks a plan on its branch and "
              "checks the target out, and there is neither a branch nor a target here.")
        return 1

    if is_paused(plan):
        print(f"[pause] '{plan.name}' is already paused.")
        return 1

    # THE BRANCH IS CHECKED BEFORE THE FILE IS READ, and the order is load-bearing. A plan's file
    # is tracked on its own branch, so standing anywhere else means the file is not in the tree at
    # all — reading it first turns "you are on the wrong branch", which a reader can act on, into a
    # `FileNotFoundError` from the diagnosis itself.
    branch = plan_branch(plan)
    if not _branch_exists(branch):
        # A plan at NotStarted or Branching has no branch yet and its file is untracked, so a
        # "pause" would leave that file sitting in the target's working tree, still resolving as
        # the active plan. That is not a pause; it is the same plan with a different name.
        print(f"[pause] '{branch}' does not exist yet: this plan has not been through Branching, "
              f"so its file is untracked and there is nothing to park it on.")
        print("[pause] Run it once (`./scripts/dev/common/dev-cycle.sh run --auto-advance 2`) or "
              "simply delete the plan file — nothing has been committed.")
        return 1
    if _current_branch() != branch:
        print(f"[pause] Not on the plan branch. Expected '{branch}', on '{_current_branch()}'.")
        print("[pause] A pause commits the working tree onto the plan's branch; doing that from "
              "another branch would sweep that branch's work into this plan.")
        # Reachable whenever a plan is NAMED — parking the other of two in-flight plans is exactly
        # the case the description exists for — so the refusal says what to do rather than only
        # what it would not do.
        print(f"[pause] Check it out first, with a clean tree: git checkout {branch}")
        return 1

    if not plan.exists():
        print(f"[pause] '{plan.name}' is not in the working tree on '{branch}'. Nothing was "
              "changed.")
        return 1

    node = current_node(plan.read_text(encoding="utf-8"))
    if node is None:
        print(f"[pause] '{plan.name}' has no highlighted node, so there would be no node to "
              "resume it at. Nothing was changed.")
        return 1
    if node == "Merged":
        print(f"[pause] '{plan.name}' is at Merged — it is delivered, not in flight. There is "
              "nothing to park.")
        return 1

    # 1. Checkpoint the work, exactly as a transition would — the parked plan must describe a
    #    committed tree, or resuming would come back to a plan whose claims nothing carries.
    commit_progress(plan, PAUSED_STATE)

    # 2. Park the artifact: `(Paused)` in the name, the resume node still highlighted, and the
    #    stable name dropped because no plan is in flight once this returns.
    paused = _write_paused(plan, keep_history)

    # 3. Commit the parked artifact ON THE BRANCH. This is the step that makes it findable again:
    #    an uncommitted rename would follow the checkout into the target's working tree, which is
    #    precisely where a paused plan must not be.
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode != 0:
        if _git("commit", "-q", "-m", f"chore(dev-cycle): {branch} → {PAUSED_STATE}").returncode != 0:
            print("[pause] Could not commit the parked plan. It is renamed in the working tree "
                  f"but still on '{branch}' — commit it before switching branches.")
            return 1
        print(f"[pause] git: committed the parked plan on '{branch}'")

    # 4. Leave the checkout on the delivery target, so the next plan branches from a clean base.
    if _git("checkout", target).returncode != 0:
        print(f"[pause] Could not check out '{target}'. The plan IS parked on '{branch}' — switch "
              "branches yourself when the tree allows it.")
        return 1

    # The card goes on the TARGET, where the board is read — the plan stays on its branch. The
    # description comes from the BRANCH, which `plan_branch` derived from the plan's own name, so
    # the card, the branch and the `resume` argument are one name by construction.
    description = branch.removeprefix("plan/")
    card = paused_card_path(description)
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(paused_card_text(description, branch, node, paused.name), encoding="utf-8")
    rel = str(card.relative_to(REPO_ROOT))
    _git("add", "--", rel)
    if _git("commit", "-q", "-m", f"chore(kanban): {description} is paused").returncode == 0:
        print(f"[pause] kanban: {rel} — the board now shows it as paused")
    else:
        print(f"[pause] WARNING: wrote {rel} but could not commit it; the tree is dirty on "
              f"'{target}'.")

    print(f"[pause] '{paused.name}' is parked on '{branch}', which is where it stays until it is "
          f"resumed.")
    print(f"[pause] On '{target}' now. Pick it up with:")
    print(f"[pause]   ./scripts/dev/common/dev-cycle.sh resume {branch.removeprefix('plan/')}")
    return 0


def plan_to_pause(description: str | None) -> Path | None:
    """Which plan a `pause` parks — named, or the only one in flight. None when it cannot be read.

    SYMMETRIC WITH `resume`, and for the same reason. `pause` is the remedy the two-plans refusal
    names (`one_plan_in_flight()`), and until this existed that remedy could not be aimed: the
    parked plan was whichever one `active_plan()` resolved, which with two in flight is the newest
    timestamp — not necessarily the one the reader is standing on, and not necessarily the one they
    meant. A remedy that may act on the other plan is not a remedy for an ambiguity.

    So a description parks that plan. BARE `pause` KEEPS PARKING THE PLAN THE ROUTER RESOLVES AS
    ACTIVE, and deliberately does not grow a refusal to match bare `resume`'s: sub-set 3 settled that
    `pause` is never blocked by the ambiguity it exists to settle (`one_plan_in_flight()`'s docstring
    and `test_pause_is_not_guarded`), and a refusal here would be that block arriving under another
    name. What the ambiguous case gains is a REPORT — which plan is being parked, and the command
    that names the other — because the complaint the description answers was that the reader could
    not tell which plan a bare `pause` would take.

    Unknown description is the one refusal, and it is not about ambiguity: parking some other plan
    because the named one does not exist is not a lesser version of the request.
    """
    live = plans_in_flight()
    if description:
        slug = _describes(description)
        chosen = next((p for p in live if _describes(plan_description(p)) == slug), None)
        if chosen is not None:
            return chosen
        # Not in flight — but it may still be a started plan at `Done`, which pause accepts.
        # Newest first, so under `--keep-history` a plan's own trail resolves to its current file.
        files = [p for p in _all_plan_files() if _describes(plan_description(p)) == slug]
        if files:
            return files[0]
        print(f"[pause] No plan called '{description}'.")
        if live:
            print("[pause] These are started and unfinished:")
            for p in live:
                print(f"[pause]   ./scripts/dev/common/dev-cycle.sh pause {plan_description(p)}")
        return None
    chosen = live[0] if live else active_plan()
    if len(live) > 1 and chosen is not None:
        print(f"[pause] {len(live)} plans are started and unfinished. Parking "
              f"'{plan_description(chosen)}' — the one this router resolves as active. Name "
              f"another to park it instead:")
        for p in live:
            if p != chosen:
                print(f"[pause]   ./scripts/dev/common/dev-cycle.sh pause {plan_description(p)}")
    return chosen


def paused_plans() -> list[dict]:
    """Every paused plan, read from the `plan/*` branches rather than from the working tree.

    See the section comment above for why the working tree is the wrong place to look. Each entry
    is `{branch, description, name}`; the newest name comes first, so a bare `resume` reporting
    several of them lists the most recent first.

    LOCAL branches only, deliberately. Nothing in the dev-cycle pushes a plan branch — `deliver`
    treats "it was never on origin" as the normal case — so a paused plan is a local working state,
    and `resume` checks out a local branch. Listing `origin/plan/*` would offer to resume work that
    is not on this machine.
    """
    if not _git_enabled():
        return []
    refs = _git("for-each-ref", "--format=%(refname:short)", "refs/heads/plan/", capture=True)
    found = []
    for branch in (refs.stdout or "").split():
        listing = _git("ls-tree", "--name-only", f"{branch}:implementation-plans", capture=True)
        if listing.returncode != 0:
            continue  # no implementation-plans/ on that branch at all
        for name in listing.stdout.splitlines():
            name = name.strip()
            if name.endswith(".md") and is_paused(Path(name)):
                found.append({"branch": branch, "description": branch.removeprefix("plan/"),
                              "name": name})
    return sorted(found, key=lambda p: p["name"], reverse=True)


def _describes(description: str) -> str:
    """The description as a branch slug, however the caller spelled it on the command line."""
    return re.sub(r"[^0-9A-Za-z._-]+", "-",
                  description.strip().removeprefix("plan/")).strip("-").lower()


def do_resume(description: str | None, keep_history: bool) -> int:
    """Make a paused plan the active one again, at the node it left."""
    if not _git_enabled():
        print("[resume] Git is disabled (DEV_CYCLE_NO_GIT). A paused plan lives on its branch, and "
              "there is no branch to read it from.")
        return 1

    found = paused_plans()
    if not found:
        print("[resume] No plan is paused. `pause` parks the active plan on its branch; nothing "
              "has been parked.")
        return 1

    if description:
        slug = _describes(description)
        chosen = next((p for p in found if p["description"] == slug), None)
        if chosen is None:
            print(f"[resume] No paused plan called '{description}'. These are paused:")
            for p in found:
                print(f"[resume]     {p['description']}   ({p['name']})")
            return 1
    elif len(found) == 1:
        chosen = found[0]
    else:
        # Which plan becomes the active one is a decision, and it is not this script's to take.
        print(f"[resume] {len(found)} plans are paused — say which one:")
        for p in found:
            print(f"[resume]   ./scripts/dev/common/dev-cycle.sh resume {p['description']}"
                  f"   ({p['name']})")
        return 1

    plan_path = PLANS_DIR / chosen["name"]
    with plan_lock(plan_path, "a resume"):
        dirty = _git("status", "--porcelain", capture=True).stdout.strip()
        if dirty:
            print("[resume] The working tree is dirty. Commit, stash or discard first — resuming "
                  "switches branches, and uncommitted work would follow the plan onto its branch "
                  "and be committed into it by the next checkpoint.")
            return 1

        # The board card goes BEFORE the branch switch, because it lives on the branch being left:
        # removing it afterwards would delete it from the plan's own branch, where it never was, and
        # leave the target still advertising a plan that is running.
        card = paused_card_path(chosen["description"])
        if card.is_file():
            rel = str(card.relative_to(REPO_ROOT))
            _git("rm", "-q", "--", rel)
            if _git("commit", "-q", "-m",
                    f"chore(kanban): {chosen['description']} is resumed").returncode == 0:
                print(f"[resume] kanban: removed {rel} — it is no longer paused")
            else:
                print(f"[resume] WARNING: removed {rel} but could not commit it.")

        if _current_branch() != chosen["branch"]:
            if _git("checkout", chosen["branch"]).returncode != 0:
                print(f"[resume] Could not check out '{chosen['branch']}'. Nothing was changed.")
                return 1
            print(f"[resume] git: switched to plan branch '{chosen['branch']}'")

        if not plan_path.exists():
            print(f"[resume] '{chosen['name']}' is on '{chosen['branch']}' but not in the tree "
                  "after checking it out. Nothing was changed beyond the checkout.")
            return 1

        text = plan_path.read_text(encoding="utf-8")
        node = current_node(text)
        if node not in NODES:
            print(f"[resume] '{chosen['name']}' highlights no known node, so where to resume it is "
                  f"not recorded (found {node!r}). Nothing was changed beyond the checkout.")
            return 1

        # The highlight already says `node`; writing it back is what renames `(Paused)` to
        # `(<node>)`, recomputes `Current step` from the node and the executing sub-set, and
        # restores the stable `ACTIVE PLAN` name.
        resumed = _write_plan(plan_path, text, node, keep_history)
        print(f"[resume] '{chosen['description']}' is the active plan again, at {node}.")
        commit_progress(resumed, node)
        print()
        do_status(resumed if resumed.exists() else plan_path)
    return 0


def _run_one(plan: Path, auto_invoke: bool, keep_history: bool) -> tuple[bool, int]:
    """Execute the plan's current node once and advance the highlight.

    Returns (advanced, rc): `advanced` is True when the highlight moved on (so a chaining
    caller should continue), False when the run stopped at this node (terminal, asking, a
    deterministic failure, or an agent step that was not auto-invoked). `rc` is the exit code
    of whatever ran (0 when nothing external ran).
    """
    node = current_node(plan.read_text(encoding="utf-8"))
    if not node:
        print("[dev-cycle] No current node highlighted — nothing to run.")
        return False, 0
    if node == "Done":
        print("[dev-cycle] Plan is at Done — nothing to run. "
              "Land it with `./scripts/dev/common/dev-cycle.sh deliver` when you are ready.")
        return False, 0
    if node == "Merged":
        print("[dev-cycle] Plan is at Merged — delivered and pushed. Nothing to run.")
        return False, 0
    if node == "Asking":
        # `run` used to only ever STOP here. It now also puts the recorded question again, which is
        # the other half of making `Asking human direction` the router's to assign: a state that can be entered
        # automatically and left only by hand is a trap, and `set` — the hand transition that used
        # to be the way out — is gone.
        resumed = resume_blocked(plan, keep_history)
        return (True, 0) if resumed is not None else (False, 0)

    # PAST HERE, THE ROUTER IS EXECUTING, so this is where the clock starts. Everything above it
    # returns without doing work: `Done` and `Merged` have none left, and `Asking human direction`
    # only puts a question back to a person — timing that would charge the sub-set for how long the
    # maintainer took to answer, which is the one thing `Exec time` must never become.
    start_exec_clock(
        (current_subset(plan.read_text(encoding="utf-8")) or {}).get("index"))

    # --- The two nodes before any work: performed here, no runner, no agent. ---
    if node == "NotStarted":
        # Nothing is executed and NO branch is touched: this is the only transition that may run
        # while the checkout is still on the branch the plan was written on, and `do_run` skips
        # the branch guard for it. The plan file is renamed in place; `commit_progress` will not
        # commit it, because it commits on `plan/*` branches only.
        print("[dev-cycle] Plan has never run — advancing to Branching (no branch created yet).")
        _write_plan(plan, plan.read_text(encoding="utf-8"), "Branching", keep_history)
        return True, 0
    if node == "Branching":
        ensure_plan_branch(plan)
        text = plan.read_text(encoding="utf-8")
        # The first pending sub-set starts executing here, so the sub-set table and the graph move
        # together — `_write_plan` moves an EXECUTING row, and at this point there is none.
        if current_subset(text) is None:
            first = next((r for r in subsets(text) if r["state"] == SUBSET_PENDING), None)
            if first is not None:
                text = set_subset_state(text, first["index"], SUBSET_NODE_LABELS["Implementing"])
                print(f"[dev-cycle] → sub-set {first['index'] + 1} ({first['description']}) "
                      f"starts at Implementing.")
        _write_plan(plan, text, "Implementing", keep_history)
        return True, 0

    drv, runnable = DRIVER.get(node, ("?", None))

    # --- Deterministic node: run its runner, branch/advance on the exit code. ---
    if runnable:
        if not os.path.exists(runnable):
            sys.exit(f"Runner not found: {runnable}")
        if node == "BuildDeploy":
            # A NODE WHOSE INPUT THE DIFF CANNOT TOUCH IS SKIPPED, AND THE SKIP IS RECORDED.
            # A sub-set that changed only rules, skills and plan bookkeeping has nothing a build
            # could read, so building it re-builds the previous sub-set and the test run that
            # follows would be certifying that. The skip is written into the plan rather than only
            # printed, because the next node is a fresh agent for whom a step that silently did not
            # happen is indistinguishable from one that did.
            #
            # TESTS ARE NOT TREATED THIS WAY and never will be: see `build_skip_reason`.
            reason = build_skip_reason()
            if reason:
                nxt = next_after(node, 0)
                print(f"[dev-cycle] {node} SKIPPED: {reason}")
                print(f"[dev-cycle] → advancing to {nxt}. The tests are NOT skipped — they never "
                      f"are, and a build nothing feeds is the only work being removed here.")
                text = plan.read_text(encoding="utf-8")
                executing = current_subset(text)
                where = (f"sub-set {executing['index'] + 1}" if executing else "this plan")
                text = record_decision(
                    text,
                    question=f"Does {where} need a build before its tests?",
                    decision=f"**No — `BuildDeploy` skipped.** {reason}",
                    who="router",
                    why="A node is skipped only when its input is provably absent: every path "
                        "outside `NON_BUILD_INPUTS` counts as a build input, so an unknown path "
                        "still builds. Recorded rather than printed because a step that silently "
                        "did not happen reads exactly like one that did.",
                    node="BuildDeploy",
                    subset=(executing["index"] + 1) if executing else "—")
                _write_plan(plan, text, nxt, keep_history)
                return True, 0
        if node == "Testing":
            # Commit FIRST, so the run certifies a COMMIT rather than a working tree.
            #
            # `run` committed only after an execution, and advancing INTO Testing renames the plan
            # file — so the suite always started dirty and `run_enabled_tests.sh` recorded
            # `Working tree: dirty` against the PREVIOUS commit. Measured 2026-09-01: 6 of the 6
            # most recent summaries, every one.
            #
            # A report naming a commit whose tree is not what ran certifies nothing, which left
            # `.githooks/pre-push` unable to use its tree comparison and refused the first real
            # plan delivery at `git push` — after the squash was already on the target.
            commit_progress(plan, f"before {node}")
        print(f"[dev-cycle] {node}: running {runnable}  (why: deterministic node driven by {drv})")
        rc = subprocess.run([runnable], cwd=str(REPO_ROOT)).returncode
        if node == "BuildDeploy" and rc != 0:
            print(f"[dev-cycle] {node} FAILED (exit {rc}) — staying put; fix the build, then run again.")
            return False, rc
        nxt = next_after(node, rc)
        print(f"[dev-cycle] {node} exited {rc} → advancing to {nxt}.")
        if node == "Testing":
            # Fold the just-produced test results into the plan (BE/FE cells + Repos counts),
            # then advance — a single write so it honours --keep-history.
            text, logs = apply_test_results(plan.read_text(encoding="utf-8"))
            for msg in logs:
                print(f"[dev-cycle]   test-columns: {msg}")
            _write_plan(plan, text, nxt, keep_history)
        else:
            set_node(plan, nxt, keep_history)
        return True, rc

    # --- LLM node: auto-invoke the skill by default; --deterministic just suggests it. ---
    skill = SKILL_CMD[node]
    if auto_invoke:
        # Filled by the conversation when a question was put and not answered. A list rather than a
        # return value because it is not a failure: the agent can finish every decided part of a
        # node and still owe one decision, which is exactly the case that produced this.
        open_questions: list[dict] = []
        ok, why = invoke_skill_headless(node, skill, unanswered=open_questions, plan=plan)
        if ok:
            nxt = NEXT_SINGLE[node]
            # RE-RESOLVE THE PLAN. The agent was asked to keep it updated, and the plan's state
            # lives in its FILENAME — so any state the agent set renamed the file and the path this
            # function was handed no longer exists. It crashed exactly there, after 74 turns and 21
            # minutes of work that was luckily all still in the tree:
            #
            #   FileNotFoundError: … - scripts-are-positioned-by-when-they-run (Implementing).md
            #
            # And re-resolving alone is not enough: the agent had ALREADY advanced the plan to
            # BuildDeploy, so writing `nxt` over it would have been a second advance — harmless
            # here, and a move BACKWARDS had the agent gone further (to Testing, or to Asking). So
            # the router advances only while the plan still sits on the node it ran, and reports it
            # when the agent got there first.
            plan = active_plan() or plan
            landed = current_node(plan.read_text(encoding="utf-8")) if plan.exists() else None

            # A QUESTION THAT WENT UNANSWERED BLOCKS THE PLAN, and it is tested before any advance
            # because advancing is precisely what must not happen: the next node is performed by a
            # fresh agent reading this plan, and it would meet the same decision with no more means
            # of taking it. Recorded here rather than in the conversation module, because where a
            # plan stands is the router's to write — the same rule the rest of this sub-set states.
            #
            # `resume_at` is where the PLAN now stands, not where this run started: an agent that
            # advanced the plan itself has moved the work on, and coming back to the node it left
            # would redo it. `Asking` is excluded because an agent that set that itself has said
            # nothing about where to return to, and `node` is the one thing we know did run.
            if open_questions:
                resume_at = landed if landed in NODES and landed != "Asking" else node
                record_blocked(plan, resume_at, skill, open_questions, keep_history)
                return False, 0

            if landed != node:
                print(f"[dev-cycle] '{skill}' completed and moved the plan to {landed} itself — "
                      f"leaving it there rather than writing {nxt} over it.")
                return True, 0
            print(f"[dev-cycle] '{skill}' completed → advancing to {nxt}.")
            if node == "Documenting":
                ok, rc_docs, back = documenting_gate(plan)
                if back:
                    # The sub-set's scope GREW here, so the plan goes back to the node that writes
                    # code — the same arc `Committing` takes, and written by the router rather than
                    # by the agent that found the work, because where a plan stands is the router's
                    # to write.
                    print("[dev-cycle] → back to Implementing on the same sub-set.")
                    _write_plan(plan, plan.read_text(encoding="utf-8"), "Implementing",
                                keep_history)
                    return True, 0
                if not ok:
                    print("[dev-cycle] Staying at Documenting. Fix it in place, then run again.")
                    return False, rc_docs
            if node == "Committing":
                # Scope gate. `Done` must mean the scope was delivered, not that the last test run
                # was green — and a green run says nothing about things that were never started.
                # ⏭️ and ⛔ are decisions and do NOT block; 🔲 and 🔄 are not decisions.
                text_now = plan.read_text(encoding="utf-8")
                executing = current_subset(text_now)
                rows = subsets(text_now)
                if executing is None and rows:
                    # No row is executing. That happens when the Committing agent has already marked
                    # this sub-set Done in the table before the router looked — the agent and the
                    # router both maintain it, and whoever writes last wins. Rather than fall through
                    # to the un-scoped path (which leaves the table with nothing running and the
                    # sub-set unstarted), pick up where the table says the work is: the first pending
                    # row.
                    following = next((r for r in rows if r["state"] == SUBSET_PENDING), None)
                    if following is not None:
                        print(f"[dev-cycle] no sub-set marked as executing — starting the first "
                              f"pending one: {following['index'] + 1} ({following['description']}).")
                        text = set_subset_state(text_now, following["index"],
                                                SUBSET_NODE_LABELS["Implementing"])
                        new_text, ok = _apply_highlight(text, "Implementing")
                        if not ok:
                            sys.exit("Could not rewrite the graph highlight.")
                        target = _state_path(plan, "Implementing", unique=keep_history)
                        target.write_text(new_text, encoding="utf-8")
                        if target != plan and not keep_history and plan.exists():
                            plan.unlink()
                        sync_active_link(target, "Implementing")
                        print(f"[dev-cycle] → {target.name}: current node → Implementing "
                              f"(updated {_now()})")
                        return True, 0
                if executing is not None and rows:
                    # Per sub-set routing. Three outcomes, and the sub-set table is what tells them
                    # apart: finish this sub-set and start the next, loop on this sub-set because it
                    # is not finished, or reach Done because nothing is left anywhere.
                    still_here = unfinished_in_subset(text_now, executing["description"])
                    if still_here:
                        print(f"[dev-cycle] sub-set {executing['index'] + 1} "
                              f"({executing['description']}) has {len(still_here)} thing(s) left:")
                        for name in still_here[:10]:
                            print(f"[dev-cycle]     - {name}")
                        print("[dev-cycle] → back to Implementing on the same sub-set.")
                        text, logs = apply_commit_results(text_now)
                        for msg in logs:
                            print(f"[dev-cycle]   commit-column: {msg}")
                        _write_plan(plan, text, "Implementing", keep_history)
                        return True, 0

                    text, logs = apply_commit_results(text_now)
                    for msg in logs:
                        print(f"[dev-cycle]   commit-column: {msg}")
                    text = set_subset_state(text, executing["index"], SUBSET_DONE)
                    nxt_subset = next((r for r in subsets(text)
                                       if r["index"] > executing["index"]
                                       and r["state"] == SUBSET_PENDING), None)
                    if nxt_subset is not None:
                        print(f"[dev-cycle] sub-set {executing['index'] + 1} "
                              f"({executing['description']}) complete.")
                        print(f"[dev-cycle] → sub-set {nxt_subset['index'] + 1} "
                              f"({nxt_subset['description']}) starts at Implementing.")
                        text = set_subset_state(text, nxt_subset["index"],
                                                SUBSET_NODE_LABELS["Implementing"])
                        # _write_plan would move the *previous* executing row, which is now Done, so
                        # the new row's state is set here and the highlight applied without it.
                        new_text, ok = _apply_highlight(text, "Implementing")
                        if not ok:
                            sys.exit("Could not rewrite the graph highlight.")
                        target = _state_path(plan, "Implementing", unique=keep_history)
                        target.write_text(new_text, encoding="utf-8")
                        if target != plan and not keep_history and plan.exists():
                            plan.unlink()
                        sync_active_link(target, "Implementing")
                        print(f"[dev-cycle] → {target.name}: current node → Implementing "
                              f"(updated {_now()})")
                        return True, 0

                    leftover = unfinished_things(text)
                    if leftover:
                        print(f"[dev-cycle] every sub-set is Done but {len(leftover)} thing(s) sit "
                              f"outside them — not advancing to Done:")
                        for name in leftover[:10]:
                            print(f"[dev-cycle]     - {name}")
                        _write_plan(plan, text, "Implementing", keep_history)
                        return True, 0
                    print("[dev-cycle] every sub-set complete → Done.")
                    _write_plan(plan, text, "Done", keep_history)
                    return True, 0

                pending = unfinished_things(text_now)
                if pending:
                    # NOT Done, and not parked at Committing either. A task is normally delivered in
                    # several increments; this increment is committed, so the honest next state is
                    # back at Implementing for the next one. Parking at Committing reads as "the task
                    # is ready to commit", which is what made this state confusing twice over.
                    print(f"[dev-cycle] Increment committed, but {len(pending)} thing(s) in the Main "
                          f"table are still {TODO} to do or {DOING} in progress:")
                    for name in pending[:10]:
                        print(f"[dev-cycle]     - {name}")
                    if len(pending) > 10:
                        print(f"[dev-cycle]     … and {len(pending) - 10} more")
                    print("[dev-cycle] Tests being green means nothing was broken, not that the work "
                          "exists. Not advancing to Done.")
                    print("[dev-cycle] → returning to Implementing for the next increment. To finish "
                          "the task instead, mark the remaining things ⏭️ (deferred by decision) or "
                          "⛔ (blocked) with the reason in the Detailed summary.")
                    text, logs = apply_commit_results(plan.read_text(encoding="utf-8"))
                    for msg in logs:
                        print(f"[dev-cycle]   commit-column: {msg}")
                    _write_plan(plan, text, "Implementing", keep_history)
                    return True, 0
                # Git is the authority on what was committed — fold it in, so a plan can never
                # reach Done still claiming `Not committed`.
                text, logs = apply_commit_results(plan.read_text(encoding="utf-8"))
                for msg in logs:
                    print(f"[dev-cycle]   commit-column: {msg}")
                _write_plan(plan, text, nxt, keep_history)
            else:
                set_node(plan, nxt, keep_history)
            return True, 0
        # `rstrip('.')`: some reasons end in a sentence and some do not, and the printed line
        # read "--deterministic.." for the ones that do.
        print(f"[dev-cycle] auto-invoke not possible: {why.rstrip('.')}.")
        # A run that asked and then failed still owes the answer. Recorded on this path too, or a
        # question would survive only when the agent happened to finish cleanly — which makes
        # whether a decision is remembered depend on something unrelated to the decision.
        if open_questions:
            plan = active_plan() or plan
            record_blocked(plan, node, skill, open_questions, keep_history)
            return False, 0
        print(f"[dev-cycle] Falling back — invoke the '{skill}' skill manually for node '{node}' "
              f"({drv}), then run the router again.")
        return False, 0

    print(f"[dev-cycle] {node} is an agent step and --deterministic is set — the router only "
          f"advances deterministic nodes here and won't fake progress. `--auto-advance` does not "
          f"skip agent nodes.")
    print(f"[dev-cycle] To proceed: invoke the '{skill}' skill yourself (why: {drv}) and run "
          f"again, or drop --deterministic to have the router perform it via a headless agent.")
    return False, 0


def do_run(plan: Path, auto_invoke: bool, auto_advance, keep_history: bool) -> None:
    """Run the current node and progress the plan.

    `auto_advance`: None → a single node; a positive int → that many steps; <= 0 → until Done
    (bounded by HARD_CAP). Between steps the highlight is advanced deterministically; LLM nodes
    only advance when performed (auto-invoked by default; skipped under --deterministic)."""
    if auto_advance is None:
        budget = 1
    elif auto_advance > 0:
        budget = auto_advance
    else:
        budget = HARD_CAP  # bare --auto-advance: go until Done (or the safety cap)

    # branch-per-plan: work on plan/<description>. Not before `Branching` has run — creating the
    # branch IS that node, and a plan at `NotStarted` must be able to say "no branch exists yet".
    if current_node(plan.read_text(encoding="utf-8")) not in ("NotStarted", "Branching"):
        ensure_plan_branch(plan)

    steps = 0
    last_rc = 0
    while steps < budget:
        # Re-resolve each step: with --keep-history the previous step wrote a NEW file, which is
        # now this plan's current one; without it this returns the same file. `or plan` keeps the
        # plan this function was HANDED when no link names it yet — the plan written at NotStarted
        # and run directly, which is the one state in which the link does not exist.
        plan = active_plan() or plan
        if plan is None:
            break
        advanced, last_rc = _run_one(plan, auto_invoke, keep_history)
        if not advanced:
            break
        steps += 1
        latest = active_plan()
        if latest is not None and current_node(latest.read_text(encoding="utf-8")) == "Done":
            print("[dev-cycle] Reached Done.")
            break
    if steps >= budget and budget == HARD_CAP:
        print(f"[dev-cycle] Stopped at the safety cap ({HARD_CAP} steps).")
    print(f"[dev-cycle] Advanced {steps} step(s).")

    # Commit this execution's progress on the plan branch, then — only once the plan has actually
    # reached Done — SUGGEST the merge. Nothing is asked and nothing is merged: the target branch
    # and the timing are the maintainer's, and a question at the commit step would block an
    # unattended run for an answer nobody is ready to give.
    _plan = active_plan() or plan
    if steps:
        commit_progress(_plan, current_node(_plan.read_text(encoding="utf-8")) or "?")
    if current_node(_plan.read_text(encoding="utf-8")) == "Done":
        suggest_merge(_plan)
    sys.exit(last_rc)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="dev-cycle.sh",
        description="Thin, deterministic router over the Ideable dev-cycle skill graph.\n"
                    "Nodes are dev-cycle states, arcs are the Ideable skills; the active plan\n"
                    "(the one named by an `ACTIVE PLAN - <desc>.md` link, created by `start`)\n"
                    "holds the highlight.\n"
                    "Nodes: NotStarted → Branching → Implementing → BuildDeploy → Testing →\n"
                    "(Documenting | Fixing) → Committing → Done → Merged; Asking human direction\n"
                    "is where a decision only you can take is waited on.\n"
                    "See rules/implementation-plan.md for the canonical graph.",
        epilog=(
            "actions:\n"
            "  status            show the active plan, current node, and the next transition (default)\n"
            "  start <desc>      make a plan the active one, creating its `ACTIVE PLAN - <desc>.md`\n"
            "                    link. Only a plan at NotStarted, and only when no other plan is in\n"
            "                    flight: becoming active is an act, not the newest timestamp winning\n"
            "  run               execute the current node and advance the highlight one step.\n"
            "                    THE ONLY ADVANCE: there is no `set`, because a command that wrote\n"
            "                    the graph without the sub-set advance, the Commit cells and the\n"
            "                    scope gate produced a state `run` could not read\n"
            "  pause             park the active plan on its branch: commit the tree, rename it\n"
            "                    (Paused) with the resume node still highlighted, drop the\n"
            "                    `ACTIVE PLAN` name, and check the target out so the next plan\n"
            "                    branches from a clean base\n"
            "  resume [<desc>]   make a paused plan active again at the node it left, checking out\n"
            "                    its plan/<desc> branch. Bare when exactly one plan is paused; it\n"
            "                    lists them and stops when more than one is\n"
            "  deliver           land a Done plan on the target as ONE squashed commit whose\n"
            "                    message is the plan's abstract, then delete the plan branch\n"
            "                    (--dry-run to see the message and change nothing).\n"
            "                    IT CERTIFIES THE TREE IT LANDS: when HEAD differs from the\n"
            "                    commit the newest recorded run names, in any path that is not\n"
            "                    run bookkeeping, it runs the suite itself and refuses on red —\n"
            "                    so delivering needs no manual run and no SKIP_TEST_GATE. The\n"
            "                    check runs before any of the delivery's own bookkeeping, so a\n"
            "                    refusal leaves the plan at Done and the target untouched\n"
            "\n"
            "run behaviour:\n"
            "  NotStarted and Branching are performed by the router itself (Branching creates the\n"
            "  plan branch). Deterministic nodes run their runner (BuildDeploy → redeploy.sh,\n"
            "  Testing → run_enabled_tests.sh; Testing then branches: pass → Documenting, fail → Fixing).\n"
            "  A NODE WHOSE INPUT THE DIFF CANNOT TOUCH IS SKIPPED, and the skip is written into the\n"
            "  plan's decisions record with its reason — a sub-set whose changed paths are all rules,\n"
            "  skills or plan bookkeeping runs no BuildDeploy, because building it would rebuild the\n"
            "  PREVIOUS sub-set and the run that follows would certify that. An unknown path counts\n"
            "  as a build input, so the skip is provable rather than assumed. THE TESTS ARE NEVER\n"
            "  SKIPPED AND NEVER SCOPED: the suite is ~8 per cent of a cycle and has caught a\n"
            "  regression in a\n"
            "  module the sub-set never named.\n"
            "  ONE AGENT PER SUB-SET, NOT PER NODE. The agent's session is resumed across the LLM\n"
            "  nodes of one sub-set, so Documenting and Committing judge the diff Implementing wrote\n"
            "  instead of rebuilding what it means; a new sub-set starts a fresh agent whose whole\n"
            "  context is the plan, which is what catches anything the last one failed to write down.\n"
            "  Each node is also handed a BRIEF (the node, the sub-set's rows, what is already\n"
            "  decided, the last verdict, the diff) rather than being told to read the plan.\n"
            "  LLM nodes (Implementing/Fixing/Documenting/Committing) are performed automatically via a\n"
            "  headless\n"
            "  agent by default (falling back to suggesting the skill when the CLI is unavailable);\n"
            "  with --deterministic they are NOT run — the router suggests the skill and stops.\n"
            "  WHO calls run makes no difference: an agent caller gets the node performed exactly as\n"
            "  a human one does. What is refused is a SECOND WORKER on one plan — run and deliver\n"
            "  hold .ideable-work/dev-cycle-locks/<description>.lock for their whole duration, and a\n"
            "  second one names the holder and exits 3. A lock whose holder is provably gone is taken\n"
            "  over; one recorded on another host is never stolen. status takes no lock.\n"
            "  TWO PLANS IN FLIGHT is refused as well, by run and by status: a sort always produces a\n"
            "  winner, so the newest timestamp would silently be the active plan. Both are named and\n"
            "  the way out is `pause` (or `resume <desc>`), which are not themselves refused. A paused\n"
            "  plan never resolves as active, so parking one is what settles it. The guard counts\n"
            "  ACTIVE PLAN LINKS, so one plan is one plan however many files --keep-history left.\n"
            "  A QUESTION ONLY YOU CAN ANSWER stops the plan instead of being lost: if the agent\n"
            "  asks one and nobody answers, run moves the plan to ASKING HUMAN DIRECTION, carrying\n"
            "  the question and the node to come back to. The next run puts it again — or reads the\n"
            "  answer you wrote on the plan's `**Answer**:` line — and resumes at that node once\n"
            "  every one is answered. Assigning that node is the router's; nothing else writes plan\n"
            "  state.\n"
            "\n"
            "examples:\n"
            "  ./scripts/dev/common/dev-cycle.sh                      # = status\n"
            "  ./scripts/dev/common/dev-cycle.sh start my-slice       # make that plan the active one\n"
            "  ./scripts/dev/common/dev-cycle.sh run                  # run current node (auto-invokes agent nodes)\n"
            "  ./scripts/dev/common/dev-cycle.sh run --auto-advance   # drive to Done (safety-capped)\n"
            "  ./scripts/dev/common/dev-cycle.sh run --auto-advance 3 # advance exactly 3 steps\n"
            "  ./scripts/dev/common/dev-cycle.sh run --deterministic --auto-advance   # only deterministic nodes; suggest skills\n"
            "  ./scripts/dev/common/dev-cycle.sh run --auto-advance --keep-history     # keep a file per state transition\n"
            "\n"
            "git (branch-per-plan, always on):\n"
            "  run works on the plan's `plan/<description>` branch (created by Branching), commits the\n"
            "  working tree there after each execution, and suggests `deliver` once the plan is Done —\n"
            "  landing the branch is deliver's, never run's.\n"
            "  Each checkpoint is followed by a bookkeeping-only commit folding the plan's Repos\n"
            "  Commit cells from git — after the checkpoint, since the checkpoint is one of the\n"
            "  commits the cell is a claim about, and as a second commit rather than an amend, since\n"
            "  the cell names the checkpoint's sha.\n"
            "\n"
            "environment:\n"
            "  DEV_CYCLE_AGENT_PERMISSIONS  how a request the allow-list did not settle is answered:\n"
            "                         ask (default on a TTY) · deny (default without one) ·\n"
            "                         accept-edits · skip. `ask` puts the agent's permission requests\n"
            "                         to you in this terminal. Its QUESTIONS reach you under every\n"
            "                         policy: a question is a decision you owe, not a permission.\n"
            "  DEV_CYCLE_ASK_TIMEOUT  seconds a question waits at the terminal for a FIRST keystroke\n"
            "                         before it is taken as `I'll answer later` and the plan moves to\n"
            "                         Asking human direction with the question recorded (default 120;\n"
            "                         0 waits indefinitely). The prompt rings the bell, offers `0.\n"
            "                         I'll answer later` beside the answers, and a keystroke cancels\n"
            "                         the countdown for good. With no terminal the plan asks at once.\n"
            "  DEV_CYCLE_AGENT_SESSION  how long one agent session lives, and therefore which nodes\n"
            "                         inherit the previous node's context instead of rebuilding it:\n"
            "                         per-sub-set (default) · per-plan · per-node. per-sub-set keeps\n"
            "                         both properties where each is worth having — no rebuild WITHIN\n"
            "                         a sub-set, a fresh agent BETWEEN them, which is what makes a\n"
            "                         belief the last node never wrote down visible. per-plan is one\n"
            "                         agent for the whole plan, for a plan small enough that fresh\n"
            "                         eyes buy little; per-node is the behaviour before the knob.\n"
            "                         A session that cannot be resumed starts a fresh one and says so.\n"
            "                         The id is kept in .ideable-work/dev-cycle-sessions/<desc>.json.\n"
            "  DEV_CYCLE_AGENT_BIN    Claude Code binary the SDK should use (default: the one on PATH,\n"
            "                         else the SDK's bundled copy)\n"
            "  DEV_CYCLE_AGENT_ARGS   extra options for the agent: --model NAME, --max-turns N.\n"
            "                         A permission flag here is REFUSED — it would pre-decide what\n"
            "                         the router asks you about; use DEV_CYCLE_AGENT_PERMISSIONS.\n"
            "  DEV_CYCLE_AGENT_QUIET  set to stop streaming the agent's progress (default: the\n"
            "                         agent's messages and tool calls are printed as they happen)\n"
            "  DEV_CYCLE_NO_GIT       set to disable the branch/commit/merge git flow for a run\n"
            "  DEV_CYCLE_LOG          file every invocation is teed to, so a headless run can be\n"
            "                         watched with `tail -f` instead of reported on afterwards\n"
            "                         (default .ideable-work/dev-cycle.log; appended, rolls over at\n"
            "                         5 MB; set empty to disable). Read by dev-cycle.sh, which is\n"
            "                         what tees — the log therefore holds stderr and the child\n"
            "                         processes' output too, not only this script's.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "action", nargs="?", default="status",
        choices=["status", "start", "run", "pause", "resume", "deliver"],
        help="what to do: status (default) · start · run · pause · resume · deliver — see "
             "'actions' below",
    )
    ap.add_argument("node", nargs="?", default=None,
                    help="the plan description, for `start` / `pause` / `resume`")
    ap.add_argument(
        "--target", default=DEFAULT_TARGET, metavar="BRANCH",
        help=f"deliver/pause only: the branch to land on, or to check out when parking a plan "
             f"(default: {DEFAULT_TARGET}).",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="deliver only: compose and print the message, then stop. Changes nothing — and it "
             "says whether a real delivery would run the suite first, which is most of what one "
             "spends.",
    )
    ap.add_argument(
        "--yes", action="store_true",
        help="deliver only: grant both decisions (land it, push it) up front. A non-interactive "
             "run without this stops and says what to pass — it never assumes.",
    )
    ap.add_argument(
        "--pr", action="store_true", dest="pr",
        help="deliver only: open a PULL REQUEST instead of committing to the target. The plan's "
             "bookkeeping commit is made on the branch, the branch is pushed, and the PR carries "
             "the composed message as its title and body. The target is untouched and the branch "
             "is kept. An OPT-IN, not an obligation: rules/version-control.md § Git Workflow "
             "gives the maintainer both routes and lets them choose. "
             "Needs `gh`; refuses when the target has moved past the branch.",
    )
    ap.add_argument(
        "--deterministic", action="store_true",
        help="run only: advance ONLY deterministic nodes (BuildDeploy/Testing); at an LLM node "
             "(Implementing/Fixing/Documenting/Committing) suggest the skill to invoke and stop. Default "
             "(without this flag): LLM nodes are performed automatically via a headless agent CLI "
             "through the Agent SDK, which asks you about anything the allow-list did not settle "
             "($DEV_CYCLE_AGENT_PERMISSIONS), falling back to suggesting the skill when the SDK or "
             "the binary is unavailable. WHO runs this makes no difference — a second worker on the "
             "same plan is refused by the plan lock, whoever starts it.",
    )
    ap.add_argument(
        "--auto-advance", nargs="?", const=-1, type=int, default=None, metavar="N",
        help="run only: advance multiple steps. Omitted = a single node; bare = until Done "
             "(safety-capped); integer N = exactly N steps.",
    )
    ap.add_argument(
        "--keep-history", action="store_true",
        help="run/pause/resume: keep EVERY state transition as its own file, each describing the "
             "step it belongs to, so the whole execution can be followed file by file. Default: a "
             "single plan file, renamed to `<date> - <time> - <description> (<state>).md` at each "
             "transition (date/time = the moment of that execution) — and that one file is the plan "
             "AS IT STANDS, not a log: what is done, what remains, the decisions taken, and every "
             "memory a later node needs, since a later node may be performed by a fresh agent whose "
             "whole context is that file — and at a sub-set boundary it always is. Nodes REWRITE "
             "their chapters rather than appending "
             "(rules/implementation-plan.md § Status summary, § Detailed summary).",
    )
    args = ap.parse_args()

    # `resume` is dispatched BEFORE the active-plan guard, and has to be. After a `pause` the
    # paused plan is on its own branch and the checkout is on the delivery target, so there is
    # deliberately no active plan in the working tree — which is exactly the state in which resume
    # is the only useful action. Behind the guard it would answer "no active plan" and stop.
    if args.action == "resume":
        return do_resume(args.node, keep_history=args.keep_history)

    # `start` is dispatched before the guard for the same reason, one step earlier in the story:
    # it is the action that CREATES the resolution, so behind the guard it would answer "no active
    # plan" and stop — in the one state where it is the only useful thing to run.
    if args.action == "start":
        return do_start(args.node)

    plan = active_plan()
    if plan is None:
        print("No active implementation plan: no `ACTIVE PLAN - <description>.md` link names one "
              "in implementation-plans/.")
        waiting = startable_plans()
        if waiting:
            print("A plan becomes the active one by being started, not by being the newest file. "
                  "These are waiting:")
            for p in waiting:
                print(f"  ./scripts/dev/common/dev-cycle.sh start {plan_description(p)}")
        elif paused_plans():
            print("One or more plans are parked. Pick one up with "
                  "`./scripts/dev/common/dev-cycle.sh resume [<description>]`.")
        else:
            print("Create one via ideable-implement-specs (or ideable-bugfixing-and-changes), "
                  "then start it.")
        return 0

    # Exactly one plan is in flight, or the router says which two and stops. Guarded for the two
    # actions that would otherwise ACT on a guess — `run` performs a node, `status` states where the
    # work stands — and deliberately not for `pause` or `deliver`, which are how the ambiguity is
    # settled. `status` refuses with a non-zero code rather than printing a plan and returning 0: a
    # command that answers cleanly while the answer is a coin toss is the lying signal, not a
    # convenience.
    if args.action in ("status", "run") and not one_plan_in_flight(args.action):
        return 1

    # THERE IS NO `set`, AND ITS ABSENCE IS THE POINT OF THIS ROUTER.
    #
    # It wrote three of the six things a transition must write — the graph, `Current step`, the
    # executing sub-set's label — and none of the other three: the sub-set advance, the `Commit`
    # cells, and the scope gate. Those live in `run`'s `Committing` branch and nowhere else, so a
    # plan driven with `set` recorded its state in a place `run` never looked, and
    # `rules/implementation-plan.md`'s promise that the router "writes both together so they can
    # never disagree" was false for any plan moved by hand. Driving one plan that way made them
    # disagree for two whole sub-sets.
    #
    # Two verbs that both write plan state IS the defect; a second one that writes half of it is
    # not an escape hatch but a way to produce a state nothing can read. What `set` was reached for
    # has each been given to a command that writes the whole truth: parking a plan is `pause`,
    # picking it up is `resume`, and recording a decision nobody is there to take is `Asking`,
    # which `run` now assigns itself. A plan that must genuinely be moved by hand is renamed by
    # hand — deliberately, because nothing else will do it.
    if args.action == "status":
        do_status(plan)
    elif args.action == "run":
        # Auto-invoking LLM nodes is the default; --deterministic opts out.
        # Held for the whole run, not per node: the hazard is a second worker on this plan, and a
        # per-node lock would leave the gaps between nodes open — which is exactly where a plan's
        # branch is checked out and its file renamed.
        with plan_lock(plan, "a dev-cycle run"):
            do_run(plan, auto_invoke=not args.deterministic, auto_advance=args.auto_advance,
                   keep_history=args.keep_history)
    elif args.action == "pause":
        # The plan to park is RESOLVED BEFORE THE LOCK, because the lock is keyed on the plan's
        # description: locking the plan the router happens to resolve as active and then parking a
        # different one would hold the wrong plan's lock for the whole operation.
        parking = plan_to_pause(args.node)
        if parking is None:
            return 1
        # Pausing commits the tree and switches branches, so it is work on the plan like any other
        # and takes the same lock — a second worker mid-pause would find the branch changing under
        # it, which is the one thing the lock exists to prevent.
        with plan_lock(parking, "a pause"):
            return do_pause(parking, target=args.target, keep_history=args.keep_history)
    elif args.action == "deliver":
        # Delivery squashes, pushes and deletes a branch: the one operation where a second worker
        # would lose work rather than merely confuse it.
        with plan_lock(plan, "a delivery"):
            return do_deliver(plan, target=args.target, dry_run=args.dry_run, assume_yes=args.yes,
                              keep_history=args.keep_history, open_pr=args.pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
