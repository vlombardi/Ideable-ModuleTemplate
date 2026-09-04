#!/usr/bin/env python3
"""Thin, deterministic dev-cycle router for the Ideable development loop.

The Ideable skills are the ARCS and the dev-cycle states are the NODES of a graph
(canonical definition + colour convention live in `rules/implementation-plan.md`). This script
is the deterministic router over that graph — it does NOT run LLM steps (those stay with the
agent/human, per the decision-authority rule). It:

  - reads the **active implementation plan** (most-recently-modified *.md in implementation-plans/),
  - shows the current node + the recommended next transition (which skill drives it),
  - deterministically **recolours** the plan's Mermaid graph, sets `Current step` + `Last updated`
    (the `--set` action — the same Overall-view update the skills perform),
  - **executes** the current node and **advances** the plan (`run`): deterministic nodes
    (`BuildDeploy` -> redeploy.sh, `Testing` -> run_enabled_tests.sh) run here and the
    highlight moves on (Testing branches on the exit code: pass → `Documenting`, fail →
    `Fixing`). After a `Testing` run it folds the
    latest TEST_REPORTS SUMMARY into the plan — setting each thing's BE/FE test cell (BE ⇐ the
    module's pytest suite, FE ⇐ its playwright suite) and the Repos `Tests` counts. LLM nodes
    (`Implementing`/`Fixing`/`Documenting`/`Committing`) are **performed automatically** via a headless agent
    CLI (`claude`, or DEV_CYCLE_AGENT_BIN) **by default**, streaming that agent's messages and
    tool calls live so a long step is visible rather than silent (DEV_CYCLE_AGENT_QUIET=1 opts
    out), and falling back to suggesting the skill when the CLI is unavailable; with
    `--deterministic` they are not run — the router suggests the skill and stops. After a
    `Committing` step it folds the branch's commits into the plan's Repos `Commit` cells, so a
    plan can never reach `Done` still claiming `Not committed`.
    `--auto-advance` chains steps so one command drives the plan forward;
    The plan file is named `<date> - <time> - <description> (<state>).md` and is **renamed** on
    every transition — timestamp re-stamped at execution, state updated — so the name shows when
    the run last moved and where it stands (the creation time lives in the file's `Created at`).
    `--keep-history` keeps every transition's file instead of rolling a single one.
  - is **branch-per-plan** (always on; `DEV_CYCLE_NO_GIT=1` disables it): `run` works on the
    plan's `plan/<description>` branch (creating it if missing), commits the working tree there
    after each execution, and — once the plan reaches `Done` — suggests the merge into
    `main` (deferred in a non-interactive run).

Usage:
  scripts/dev-cycle.sh status                    # where are we + what's next (default)
  scripts/dev-cycle.sh set <NODE>                # recolour graph + set Current step/Last updated
  scripts/dev-cycle.sh run                        # run the current node and advance one step
                                                  #   (agent nodes are auto-invoked by default)
  scripts/dev-cycle.sh run --auto-advance         # drive to Done (bounded by a safety cap)
  scripts/dev-cycle.sh run --auto-advance 3       # advance exactly 3 steps
  scripts/dev-cycle.sh run --deterministic        # advance only deterministic nodes; suggest the
                                                  #   skill (do NOT auto-invoke) at LLM nodes
  scripts/dev-cycle.sh run --auto-advance --keep-history   # keep every transition's plan file
  scripts/dev-cycle.sh deliver --pr               # open the delivery PULL REQUEST
                                                  #   (target untouched; branch kept)
                                                  #   (default: one file, renamed per state)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANS_DIR = REPO_ROOT / "implementation-plans"

# Canonical nodes (must match rules/implementation-plan.md). Order is the happy-path order.
NODES = ["Implementing", "BuildDeploy", "Testing", "Fixing", "Documenting", "Committing",
         "Done", "Merged", "Blocked"]

# node -> (which skill/tool drives leaving it, is it deterministic-runnable by this script)
DRIVER = {
    "Implementing": ("ideable-implement-specs (agent)", None),
    "BuildDeploy": ("ideable-build-and-deploy / ./redeploy.sh", str(REPO_ROOT / "redeploy.sh")),
    "Testing": ("ideable-test-and-fix / run_enabled_tests.sh",
                str(REPO_ROOT / "scripts" / "common" / "run_enabled_tests.sh")),
    "Fixing": ("ideable-test-and-fix (fix) / ideable-bugfixing-and-changes → ideable-spec-driven-edit (agent)", None),
    "Documenting": ("ideable-align-docs (agent)", None),
    "Committing": ("ideable-commit-changes (agent)", None),
    "Done": ("./scripts/dev-cycle.sh deliver", None),
    "Merged": ("— (terminal)", None),
    "Blocked": ("— (human decision required)", None),
}

# Recommended next node(s) from each node (the graph edges).
NEXT = {
    "Implementing": ["BuildDeploy"],
    "BuildDeploy": ["Testing"],
    "Testing": ["Documenting (if pass)", "Fixing (if fail)"],
    "Fixing": ["BuildDeploy"],
    "Documenting": ["Committing"],
    "Committing": ["Done (if every thing is ✅/⏭️/⛔)", "Implementing (if things remain)"],
    "Done": ["Merged (via `deliver`, on the maintainer's say-so)"],
    "Merged": [],
    "Blocked": [],
}

# Unconditional single successor (used when advancing after a node completes). `Testing`
# is intentionally absent — it branches on the test runner's exit code (see `next_after`).
NEXT_SINGLE = {
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


def _render_agent_event(event: dict) -> None:
    """Print one stream-json event as a human-readable progress line.

    Renders what the agent is *doing* — its text and each tool call — so a step is no longer a
    silent wait. Tool results are not echoed (the call line already says what is happening);
    failures are, because those are what a watcher needs to see.
    """
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        print(f"{_AGENT_PREFIX} session started · model {event.get('model', '?')}", flush=True)
        return
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []) or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                for line in block["text"].strip().splitlines():
                    if line.strip():
                        print(f"{_AGENT_PREFIX} {_clip(line, 200)}", flush=True)
            elif block.get("type") == "tool_use":
                print(f"{_AGENT_PREFIX}   · {_tool_summary(block.get('name', '?'), block.get('input', {}))}",
                      flush=True)
        return
    if kind == "user":
        for block in event.get("message", {}).get("content", []) or []:
            if block.get("type") == "tool_result" and block.get("is_error"):
                print(f"{_AGENT_PREFIX}   ✗ tool error: {_clip(block.get('content', ''), 200)}", flush=True)
        return
    if kind == "result":
        secs = (event.get("duration_ms") or 0) / 1000
        cost = event.get("total_cost_usd")
        cost_part = f" · ${cost:.2f}" if isinstance(cost, (int, float)) else ""
        status = "failed" if event.get("is_error") else "finished"
        print(f"{_AGENT_PREFIX} {status} in {secs:.0f}s · {event.get('num_turns', '?')} turns{cost_part}",
              flush=True)


def _run_agent_streaming(exe: str, argv: list[str], prompt: str) -> tuple[int, bool]:
    """Run the agent with `--output-format stream-json` and render events as they arrive.

    Returns (returncode, saw_events). `saw_events` is False when the CLI produced no parseable
    event at all — the signal that this build doesn't speak stream-json, so the caller can retry
    plainly instead of leaving the user with a silent failure.
    """
    cmd = [exe, *argv, "--output-format", "stream-json", "--verbose", "-p", prompt]
    saw_events = False
    with subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
                          text=True, bufsize=1) as proc:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(f"{_AGENT_PREFIX} {_clip(line, 200)}", flush=True)
                continue
            saw_events = True
            _render_agent_event(event)
        return proc.wait(), saw_events


# ── Nested-agent guard ─────────────────────────────────────────────────────────────────────────
#: Environment markers Claude Code sets inside an agent session. Their presence means the process
#: that ran this router IS an agent, so spawning another one duplicates the worker.
_AGENT_ENV_MARKERS = ("CLAUDECODE", "AI_AGENT", "CLAUDE_CODE_ENTRYPOINT")


def agent_driven_run() -> str | None:
    """The env marker proving this run was started by an agent, or None for a human caller.

    This exists because of a real incident, and the failure had two halves:
    (1) an agent implementing a plan by hand ran `dev-cycle.sh run` at the `Implementing` node, so
        the router spawned a SECOND agent onto the same plan and the two edited the tree
        concurrently; and
    (2) the resulting diffs looked, to the first agent, like the work of somebody else — and got
        reported as an outside event rather than as the consequence of its own command.

    Detecting the caller removes both: an agent gets told to perform the step itself, and no
    mystery diffs appear. `--allow-nested-agent` is the deliberate override.
    """
    for marker in _AGENT_ENV_MARKERS:
        if os.environ.get(marker):
            return marker
    return None


def invoke_skill_headless(node: str, skill: str) -> tuple[bool, str | None]:
    """Try to perform an LLM node by invoking its skill through a headless agent CLI.

    Returns (ok, reason_if_not). The agent binary is `claude` by default, overridable via
    the DEV_CYCLE_AGENT_BIN env var; extra CLI flags can be injected via DEV_CYCLE_AGENT_ARGS
    (e.g. `--permission-mode acceptEdits` or `--dangerously-skip-permissions` for a headless run
    in an untrusted workspace). Availability of the binary on PATH is the "condition" that gates
    auto-invoke; when it is missing (or the run errors) we report why so the caller can fall back
    to the default (print-the-skill) behaviour.

    The agent runs in **streaming** mode so its progress is visible live — a plain `-p` run
    prints nothing until the whole step is over, which for a multi-minute step is
    indistinguishable from a hang. Set DEV_CYCLE_AGENT_QUIET=1 (or pass your own
    `--output-format` in DEV_CYCLE_AGENT_ARGS) to keep the CLI's own output instead.
    """
    marker = agent_driven_run()
    if marker and not os.environ.get("DEV_CYCLE_ALLOW_NESTED_AGENT"):
        return False, (
            f"this run was started BY an agent (${marker} is set), so spawning another one would "
            f"put two agents on the same plan. YOU are the agent for this node: perform "
            f"'{skill}' yourself, then run the router again. "
            f"(Deliberate override: --allow-nested-agent.)"
        )
    agent_bin = os.environ.get("DEV_CYCLE_AGENT_BIN", "claude")
    exe = shutil.which(agent_bin)
    if not exe:
        return False, f"agent CLI '{agent_bin}' not found on PATH (set DEV_CYCLE_AGENT_BIN to override)"
    extra = shlex.split(os.environ.get("DEV_CYCLE_AGENT_ARGS", ""))
    prompt = (
        f"Invoke the {skill} skill now to advance the active implementation plan "
        f"(current dev-cycle node: {node}). Follow the skill exactly and keep the plan updated."
    )
    stream = not os.environ.get("DEV_CYCLE_AGENT_QUIET") and "--output-format" not in extra
    shown = " ".join([agent_bin, *extra, *(["--output-format stream-json --verbose"] if stream else []), "-p"])
    print(f"[dev-cycle] auto-invoke: `{shown}` → skill '{skill}'  (why: node {node} is an agent step)")
    # Attribution, stated before the child runs: whatever appears in `git status` afterwards was
    # caused by THIS command. Unlabelled, those diffs read as somebody else's work — which is
    # exactly how they were once reported.
    print("[dev-cycle] NOTE: a CHILD agent process is being started by this command. Every file it "
          "changes is a consequence of running this router, not of anything external.")
    if stream:
        print("[dev-cycle] streaming the agent's progress below (DEV_CYCLE_AGENT_QUIET=1 to silence)")
    try:
        if stream:
            rc, saw_events = _run_agent_streaming(exe, extra, prompt)
            if not saw_events:
                # This build doesn't speak stream-json — rerun plainly rather than report a
                # failure the user can't see the reason for.
                print("[dev-cycle] agent produced no stream events — retrying without streaming.")
                rc = subprocess.run([exe, *extra, "-p", prompt], cwd=str(REPO_ROOT)).returncode
        else:
            rc = subprocess.run([exe, *extra, "-p", prompt], cwd=str(REPO_ROOT)).returncode
    except Exception as e:  # noqa: BLE001 — surface any spawn failure as a fallback reason
        return False, f"agent invocation failed to start: {e}"
    if rc != 0:
        return False, f"agent '{agent_bin}' exited {rc}"
    return True, None


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


def active_plan() -> Path | None:
    if not PLANS_DIR.is_dir():
        return None
    plans = sorted(PLANS_DIR.glob("*.md"), key=_plan_order, reverse=True)
    return plans[0] if plans else None


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


def _subset_table_bounds(lines: list[str]) -> tuple[int, int] | None:
    """(first_row_index, last_row_index) of the sub-set table's data rows, or None."""
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().split("|")]
        if line.strip().startswith("|") and "Description" in cells and "State" in cells:
            start = i + 2  # skip the header separator
            end = start
            while end < len(lines) and lines[end].strip().startswith("|"):
                end += 1
            return (start, end - 1) if end > start else None
    return None


def subsets(text: str) -> list[dict]:
    """The sub-set rows, in declared order: {index, description, state, line}."""
    lines = text.splitlines()
    bounds = _subset_table_bounds(lines)
    if not bounds:
        return []
    out = []
    for i in range(bounds[0], bounds[1] + 1):
        cells = [c.strip() for c in lines[i].strip().split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) < 2 or set(cells[0]) <= set("-: "):
            continue
        description, state = (cells[-2], cells[-1]) if len(cells) >= 3 else (cells[0], cells[1])
        out.append({"index": len(out), "description": description, "state": state, "line": i})
    return out


def current_subset(text: str) -> dict | None:
    """The one sub-set that is executing — its State is a node label, not `Done` or `—`."""
    for row in subsets(text):
        if row["state"] in _LABEL_TO_NODE:
            return row
    return None


def set_subset_state(text: str, index: int, state: str) -> str:
    """Rewrite one sub-set row's State cell, preserving the rest of the row verbatim."""
    lines = text.splitlines(keepends=True)
    rows = subsets(text)
    if index >= len(rows):
        return text
    i = rows[index]["line"]
    raw = lines[i].rstrip("\n")
    parts = raw.split("|")
    # The State cell is the last non-empty cell; a trailing "|" leaves an empty final element.
    for pos in range(len(parts) - 1, -1, -1):
        if parts[pos].strip():
            parts[pos] = f" {state} "
            break
    lines[i] = "|".join(parts) + "\n"
    return "".join(lines)


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
        step = f"{node} ({driver})"
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


def _state_path(plan: Path, node: str, unique: bool) -> Path:
    """Target file `<date> - <time> - <description> (<state>).md`, where date/time are stamped
    **now** (the moment of this execution) and the description comes from the active plan's name.

    The filename therefore answers "what happened last, and when"; the plan's creation timestamp
    is not lost — it lives in the Overall view's `Created at` line inside the file. With `unique`
    (--keep-history) a same-second collision is disambiguated so no state overwrites an earlier
    one; otherwise the single plan file is simply renamed."""
    parts = _plan_parts(plan.stem)
    desc = parts[2] if parts else re.sub(r"\s*\([^()]*\)\s*$", "", plan.stem).strip()
    date, time = _now_stamp()
    base = f"{date} - {time} - {desc}"
    target = PLANS_DIR / f"{base} ({node}).md"
    if not unique:
        return target
    i = 2
    while target.exists():
        target = PLANS_DIR / f"{base} ({node} {i}).md"
        i += 1
    return target


def _write_plan(plan: Path, text: str, node: str, keep_history: bool) -> Path:
    """Apply the `node` highlight to `text` and write it to `<now> - <description> (<state>).md`.
    By default the plan is a single rolling file that is *renamed* on each transition (the
    previous name is removed), so its name always carries the latest execution's date/time and
    state; with keep_history each transition lands in its own file so all are preserved.
    Returns the path written."""
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
    print(f"[dev-cycle] {('→ ' + target.name) if renamed else target.name}: "
          f"current node → {node}  (updated {_now()})")
    return target


def set_node(plan: Path, node: str, keep_history: bool = False) -> Path:
    return _write_plan(plan, plan.read_text(encoding="utf-8"), node, keep_history)


# --- Test-result → plan bookkeeping (folded in after the deterministic Testing run) ----------

def latest_summary() -> Path | None:
    d = REPO_ROOT / "TEST_REPORTS"
    if not d.is_dir():
        return None
    sums = sorted(d.glob("*-SUMMARY.md"), key=lambda p: p.stat().st_mtime, reverse=True)
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
    tool = REPO_ROOT / "scripts" / "dev" / "tool.sh"
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


def _status_line(results: dict[str, dict[str, tuple[int, int, int]]], text: str = "") -> str:
    """One short, truthful Status-summary line for this run's results.

    Failing runs always overwrite the line — the failure must be stated where a reader looks
    first. A green line only replaces a previous *generated* failure line (see the caller), so a
    skill's own summary is never clobbered by a passing run.

    Green does not mean complete: a plan carrying things that were deferred or blocked says so on
    the same line, or "all tests passing" reads as "everything asked for was done".
    """
    failed_suites = [
        (mod, suite, counts[1])
        for mod, suites in results.items() for suite, counts in suites.items() if counts[1]
    ]
    if failed_suites:
        total = sum(n for _, _, n in failed_suites)
        detail = ", ".join(f"{mod} {suite}: {n} failed" for mod, suite, n in sorted(failed_suites))
        line = (f"❌ {total} test{'s' if total != 1 else ''} failing ({detail}) — "
                f"things with a failing suite are marked 🛠️ below; fixing in progress")
    else:
        passed = sum(c[0] for suites in results.values() for c in suites.values())
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
    line = _status_line(results, new_text)
    current = status_summary(new_text) or ""
    # Rewrite when this run failed, or when the existing line is one we generated (it starts
    # with ✅/❌). A human-written summary starts with neither and is left alone.
    if line.startswith("❌") or current.startswith(("❌", "✅")):
        new_text, n = re.subn(r"(#+\s*(?:\d+\.\s*)?Status summary\s*\n+)[^\n]+",
                              lambda m: m.group(1) + line, new_text, count=1)
        logs.append("status summary: " + (line if n else "NOT updated (section not found)"))
    return new_text, logs


def plan_commits(base: str = "main") -> list[tuple[str, str, set[str]]]:
    """Commits on this branch that `base` doesn't have: (sha, subject, modules touched).

    Modules are derived from the paths each commit touches (`modules/<name>/…`), so a commit can
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
        mods = {p.split("/")[1] for p in (files.stdout or "").splitlines()
                if p.startswith("modules/") and len(p.split("/")) > 2}
        out.append((sha, subject, mods))
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
    that is a human-confirmed state the router cannot observe. Returns (new_text, log lines).
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
        mine = [(sha, subj) for sha, subj, mods in commits if module in mods]
        if not mine:
            continue
        cells[4] = _commit_cell(mine)
        lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
        logs.append(f"repo {module}: {len(mine)} commit(s) → Committed")
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
    parts = _plan_parts(plan.stem)
    desc = parts[2] if parts else re.sub(r"\s*\([^()]*\)\s*$", "", plan.stem).strip()
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", desc).strip("-").lower() or "unnamed"
    return f"plan/{slug}"


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
    """Checkpoint the whole working tree on the plan branch (never on main); skip if clean."""
    if not _git_enabled():
        return
    cur = _current_branch()
    if not (cur and cur.startswith("plan/")):
        return  # only ever commit on a plan branch
    _git("add", "-A")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return  # nothing staged
    msg = f"chore(dev-cycle): {cur} → {node}"
    if _git("commit", "-q", "-m", msg).returncode == 0:
        print(f"[dev-cycle] git: committed progress on '{cur}' — {msg}")


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
    print("[dev-cycle]   ./scripts/dev-cycle.sh deliver --dry-run     # see the message, touch nothing")
    print("[dev-cycle]   ./scripts/dev-cycle.sh deliver               # confirm, squash, push")
    print("[dev-cycle]   ./scripts/dev-cycle.sh deliver --target release/1.4")
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


def documenting_gate(plan: Path) -> tuple[bool, int]:
    """The two things that must hold before a plan may leave `Documenting`.

    Called from BOTH paths. `run` refuses on a failure; `set` — the human override — warns and
    proceeds, the same asymmetry `set Done` already has. The gate used to live inline in the
    auto-invoke branch of `run`, which meant it was skipped entirely whenever the node was
    performed by the agent driving the router rather than by one it spawned — and that is the
    normal case for an agent-driven run. A gate that only fires on one of two paths is a gate that
    reports which path you took.
    """
    text = plan.read_text(encoding="utf-8")
    executing = current_subset(text)
    left = (undocumented_in_subset(text, executing["description"])
            if executing else undocumented_things(text))
    if left:
        print(f"[dev-cycle] {len(left)} thing(s) still have a Docs cell to do:")
        for name in left[:10]:
            print(f"[dev-cycle]     - {name}")
        print("[dev-cycle] `➖` is the honest mark for a thing no spec or doc describes — but it "
              "is a claim, so make it deliberately.")
        return False, 0
    rc, how, ran = run_docs_gate()
    if rc != 0:
        print(f"[dev-cycle] docs gate FAILED (exit {rc}, {how}).")
        return False, rc
    if not ran:
        # Never "passed" — nothing was asked. `scripts/TESTS/` is maintainer-only, so in a remote
        # module project the step's guarantees rest on the skill's judgement and the `Docs` column.
        print(f"[dev-cycle] docs gate DID NOT RUN ({how}). The Docs cells are the only artifact "
              "here — the framework's doc checks are maintainer-only.")
        return True, 0
    print(f"[dev-cycle] docs gate passed ({how}).")
    return True, 0


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


def do_deliver(plan: Path, target: str, dry_run: bool, assume_yes: bool,
               do_push: bool, keep_history: bool, open_pr: bool = False) -> int:
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
                  "`./scripts/dev-cycle.sh set Testing && ./scripts/dev-cycle.sh run` — "
                  "then deliver again. Nothing has been landed.")
            return 1

    if open_pr:
        if do_push:
            print("[deliver] --pr and --push contradict each other: --pr never commits to "
                  f"'{target}', so there is nothing there to push. Drop one.")
            return 1

    card = _kanban_card(plan)
    card_dest = (REPO_ROOT / "kanban" / "done" / card.name) if card else None
    kanban_ref = card_dest.relative_to(REPO_ROOT).as_posix() if card_dest else None

    message = plan_delivery_message(plan, target, branch, kanban_ref)
    print("\n" + "-" * 72)
    print(message, end="")
    print("-" * 72 + "\n")

    if dry_run:
        print("[deliver] --dry-run: nothing was changed.")
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

    # 1. Final bookkeeping ON THE BRANCH, so the delivered commit carries it. The plan file is the
    #    only surviving record of per-thing detail once the branch is gone, so it must be the
    #    (Merged) version that lands, not the (Done) one.
    delivered_plan = _write_plan(plan, plan.read_text(encoding="utf-8"), "Merged", keep_history)
    delivered_plan.write_text(_mark_repos_pushed(delivered_plan.read_text(encoding="utf-8")),
                              encoding="utf-8")
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
    if do_push or _confirm(f"Push '{target}'?", assume_yes):
        if _git("push", "origin", target).returncode != 0:
            print("[deliver] The push failed. The commit is on your local "
                  f"'{target}'; the plan branch is kept until it lands.")
            return 1
        _git("branch", "-D", branch)
        _git("push", "origin", "--delete", branch)
        print(f"[deliver] Pushed, and deleted '{branch}' locally and on origin.")
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
        mark = "▶ runnable here" if runnable else "→ agent/human step"
        print(f"   {target:<11} via {drv}   [{mark}]")


def _run_one(plan: Path, auto_invoke: bool, keep_history: bool) -> tuple[bool, int]:
    """Execute the plan's current node once and advance the highlight.

    Returns (advanced, rc): `advanced` is True when the highlight moved on (so a chaining
    caller should continue), False when the run stopped at this node (terminal, blocked, a
    deterministic failure, or an agent step that was not auto-invoked). `rc` is the exit code
    of whatever ran (0 when nothing external ran).
    """
    node = current_node(plan.read_text(encoding="utf-8"))
    if not node:
        print("[dev-cycle] No current node highlighted — nothing to run.")
        return False, 0
    if node == "Done":
        print("[dev-cycle] Plan is at Done — nothing to run. "
              "Land it with `./scripts/dev-cycle.sh deliver` when you are ready.")
        return False, 0
    if node == "Merged":
        print("[dev-cycle] Plan is at Merged — delivered and pushed. Nothing to run.")
        return False, 0
    if node == "Blocked":
        print("[dev-cycle] Plan is Blocked (human decision required) — stopping, per decision-authority.")
        return False, 0

    drv, runnable = DRIVER.get(node, ("?", None))

    # --- Deterministic node: run its runner, branch/advance on the exit code. ---
    if runnable:
        if not os.path.exists(runnable):
            sys.exit(f"Runner not found: {runnable}")
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
        ok, why = invoke_skill_headless(node, skill)
        if ok:
            nxt = NEXT_SINGLE[node]
            print(f"[dev-cycle] '{skill}' completed → advancing to {nxt}.")
            if node == "Documenting":
                ok, rc_docs = documenting_gate(plan)
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
        print(f"[dev-cycle] auto-invoke not possible: {why}.")
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

    ensure_plan_branch(plan)  # branch-per-plan: work on plan/<description>

    steps = 0
    last_rc = 0
    while steps < budget:
        # Re-resolve each step: with --keep-history the previous step wrote a NEW file, which is
        # now the most-recent (active) plan; without it this returns the same file.
        plan = active_plan()
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
                    "(most-recently-modified *.md in implementation-plans/) holds the highlight.\n"
                    "Nodes: Implementing → BuildDeploy → Testing → (Documenting | Fixing) →\n"
                    "Committing → Done → Merged; Blocked is a human gate.\n"
                    "See rules/implementation-plan.md for the canonical graph.",
        epilog=(
            "actions:\n"
            "  status            show the active plan, current node, and the next transition (default)\n"
            "  set <NODE>        recolour the plan's graph + set Current step / Last updated to <NODE>\n"
            "                    (NODE ∈ Implementing, BuildDeploy, Testing, Fixing, Documenting,\n"
            "                     Committing, Done, Merged, Blocked)\n"
            "  run               execute the current node and advance the highlight one step\n"
            "  deliver           land a Done plan on the target as ONE squashed commit whose\n"
            "                    message is the plan's abstract, then delete the plan branch\n"
            "                    (--dry-run to see the message and change nothing)\n"
            "\n"
            "run behaviour:\n"
            "  Deterministic nodes run their runner (BuildDeploy → redeploy.sh,\n"
            "  Testing → run_enabled_tests.sh; Testing then branches: pass → Documenting, fail → Fixing).\n"
            "  LLM nodes (Implementing/Fixing/Documenting/Committing) are performed automatically via a\n"
            "  headless\n"
            "  agent by default (falling back to suggesting the skill when the CLI is unavailable);\n"
            "  with --deterministic they are NOT run — the router suggests the skill and stops.\n"
            "\n"
            "examples:\n"
            "  ./scripts/dev-cycle.sh                      # = status\n"
            "  ./scripts/dev-cycle.sh set Testing          # move the highlight to Testing\n"
            "  ./scripts/dev-cycle.sh run                  # run current node (auto-invokes agent nodes)\n"
            "  ./scripts/dev-cycle.sh run --auto-advance   # drive to Done (safety-capped)\n"
            "  ./scripts/dev-cycle.sh run --auto-advance 3 # advance exactly 3 steps\n"
            "  ./scripts/dev-cycle.sh run --deterministic --auto-advance   # only deterministic nodes; suggest skills\n"
            "  ./scripts/dev-cycle.sh run --auto-advance --keep-history     # keep a file per state transition\n"
            "\n"
            "git (branch-per-plan, always on):\n"
            "  run works on the plan's `plan/<description>` branch (created if missing), commits the\n"
            "  working tree there after each execution, and suggests the merge once the plan is Done.\n"
            "  Committing step runs (deferred when non-interactive).\n"
            "\n"
            "environment:\n"
            "  DEV_CYCLE_AGENT_BIN    agent CLI used to auto-invoke LLM nodes (default: claude)\n"
            "  DEV_CYCLE_AGENT_ARGS   extra flags for that CLI, e.g. '--permission-mode acceptEdits'\n"
            "                         or '--dangerously-skip-permissions' for headless/untrusted runs\n"
            "  DEV_CYCLE_AGENT_QUIET  set to stop streaming the agent's progress (default: the\n"
            "                         agent's messages and tool calls are printed as they happen)\n"
            "  DEV_CYCLE_NO_GIT       set to disable the branch/commit/merge git flow for a run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "action", nargs="?", default="status", choices=["status", "set", "run", "deliver"],
        help="what to do: status (default) · set · run · deliver — see 'actions' below",
    )
    ap.add_argument("node", nargs="?", default=None, help="target NODE for `set`")
    ap.add_argument(
        "--target", default=DEFAULT_TARGET, metavar="BRANCH",
        help=f"deliver only: the branch to land on (default: {DEFAULT_TARGET}).",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="deliver only: compose and print the message, then stop. Changes nothing.",
    )
    ap.add_argument(
        "--yes", action="store_true",
        help="deliver only: grant both decisions (land it, push it) up front. A non-interactive "
             "run without this stops and says what to pass — it never assumes.",
    )
    ap.add_argument(
        "--push", action="store_true",
        help="deliver only: push the target without asking a second time.",
    )
    ap.add_argument(
        "--pr", action="store_true", dest="pr",
        help="deliver only: open a PULL REQUEST instead of committing to the target. The plan's "
             "bookkeeping commit is made on the branch, the branch is pushed, and the PR carries "
             "the composed message as its title and body. The target is untouched and the branch "
             "is kept. Required for plan-driven work by rules/version-control.md § Git Workflow. "
             "Needs `gh`; refuses when the target has moved past the branch.",
    )
    ap.add_argument(
        "--deterministic", action="store_true",
        help="run only: advance ONLY deterministic nodes (BuildDeploy/Testing); at an LLM node "
             "(Implementing/Fixing/Documenting/Committing) suggest the skill to invoke and stop. Default "
             "(without this flag): LLM nodes are performed automatically via a headless agent CLI "
             "(`claude`, or $DEV_CYCLE_AGENT_BIN), falling back to suggesting the skill when the "
             "CLI is unavailable — EXCEPT when this router is itself run by an agent, where "
             "nesting is refused; see --allow-nested-agent.",
    )
    ap.add_argument(
        "--allow-nested-agent", action="store_true",
        help="run only: permit spawning a headless agent even though THIS run was started by an "
             "agent. Refused by default, because it puts two agents on one plan: they edit the "
             "tree concurrently and each sees the other's diffs as coming from nowhere.",
    )
    ap.add_argument(
        "--auto-advance", nargs="?", const=-1, type=int, default=None, metavar="N",
        help="run only: advance multiple steps. Omitted = a single node; bare = until Done "
             "(safety-capped); integer N = exactly N steps.",
    )
    ap.add_argument(
        "--keep-history", action="store_true",
        help="set/run: keep EVERY state transition as its own file, so the whole run's history "
             "is preserved in implementation-plans/. Default: a single plan file, renamed to "
             "`<date> - <time> - <description> (<state>).md` at each transition (date/time = the "
             "moment of that execution).",
    )
    args = ap.parse_args()

    # The flag and the env var are one switch; the guard reads the env so it works for a nested
    # call too.
    if getattr(args, "allow_nested_agent", False):
        os.environ["DEV_CYCLE_ALLOW_NESTED_AGENT"] = "1"

    plan = active_plan()
    if plan is None:
        print("No active implementation plan in implementation-plans/. "
              "Create one via ideable-implement-specs (or ideable-bugfixing-and-changes).")
        return 0

    if args.action == "status":
        do_status(plan)
    elif args.action == "set":
        if not args.node:
            sys.exit("`set` requires a node, e.g. `scripts/dev-cycle.sh set Documenting`")
        # `set` is the human override, so unfinished scope WARNS here rather than refusing — unlike
        # `run`, which is automated and stops. Removing the override entirely would take away the
        # escape hatch; leaving it silent is how a plan reaches Done with most of its scope unstarted.
        if args.node == "Done":
            pending = unfinished_things(plan.read_text(encoding="utf-8"))
            if pending:
                print(f"[dev-cycle] WARNING: setting Done while {len(pending)} thing(s) are still "
                      f"{TODO} to do or {DOING} in progress:")
                for name in pending[:10]:
                    print(f"[dev-cycle]     - {name}")
                if len(pending) > 10:
                    print(f"[dev-cycle]     … and {len(pending) - 10} more")
                print("[dev-cycle] If they are not going to be done in this run, mark them ⏭️ "
                      "(deferred by decision) or ⛔ (blocked) so the plan says so.")
        if current_node(plan.read_text(encoding="utf-8")) == "Documenting" \
                and args.node not in ("Documenting", "Blocked"):
            ok, _ = documenting_gate(plan)
            if not ok:
                print("[dev-cycle] WARNING: leaving Documenting with the docs gate red. `set` is "
                      "the human override, so it proceeds — but the documents are not aligned.")
        set_node(plan, args.node, keep_history=args.keep_history)
    elif args.action == "run":
        # Auto-invoking LLM nodes is the default; --deterministic opts out.
        do_run(plan, auto_invoke=not args.deterministic, auto_advance=args.auto_advance,
               keep_history=args.keep_history)
    elif args.action == "deliver":
        return do_deliver(plan, target=args.target, dry_run=args.dry_run, assume_yes=args.yes,
                          do_push=args.push, keep_history=args.keep_history, open_pr=args.pr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
