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
    highlight moves on (Testing branches on the exit code). After a `Testing` run it folds the
    latest TEST_REPORTS SUMMARY into the plan — setting each thing's BE/FE test cell (BE ⇐ the
    module's pytest suite, FE ⇐ its playwright suite) and the Repos `Tests` counts. LLM nodes
    (`Implementing`/`Fixing`/`Committing`) are **performed automatically** via a headless agent
    CLI (`claude`, or DEV_CYCLE_AGENT_BIN) **by default**, falling back to suggesting the skill
    when the CLI is unavailable; with `--deterministic` they are not run — the router suggests
    the skill and stops. `--auto-advance` chains steps so one command drives the plan forward;
    `--keep-history` writes each transition to its own state-suffixed plan file.
  - is **branch-per-plan** (always on; `DEV_CYCLE_NO_GIT=1` disables it): `run` works on the
    plan's `plan/<description>` branch (creating it if missing), commits the working tree there
    after each execution, and — when the `Committing` step runs — asks whether to merge into
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
  scripts/dev-cycle.sh run --auto-advance --keep-history   # one plan file per state transition
"""
from __future__ import annotations

import argparse
import datetime
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
NODES = ["Implementing", "BuildDeploy", "Testing", "Fixing", "Committing", "Done", "Blocked"]

# node -> (which skill/tool drives leaving it, is it deterministic-runnable by this script)
DRIVER = {
    "Implementing": ("ideable-implement-specs (agent)", None),
    "BuildDeploy": ("ideable-build-and-deploy / ./redeploy.sh", str(REPO_ROOT / "redeploy.sh")),
    "Testing": ("ideable-test-and-fix / run_enabled_tests.sh",
                str(REPO_ROOT / "scripts" / "common" / "run_enabled_tests.sh")),
    "Fixing": ("ideable-test-and-fix (fix) / ideable-bugfixing-and-changes → ideable-spec-driven-edit (agent)", None),
    "Committing": ("ideable-commit-changes (agent)", None),
    "Done": ("— (terminal)", None),
    "Blocked": ("— (human decision required)", None),
}

# Recommended next node(s) from each node (the graph edges).
NEXT = {
    "Implementing": ["BuildDeploy"],
    "BuildDeploy": ["Testing"],
    "Testing": ["Committing (if pass)", "Fixing (if fail)"],
    "Fixing": ["BuildDeploy"],
    "Committing": ["Done"],
    "Done": [],
    "Blocked": [],
}

# Unconditional single successor (used when advancing after a node completes). `Testing`
# is intentionally absent — it branches on the test runner's exit code (see `next_after`).
NEXT_SINGLE = {
    "Implementing": "BuildDeploy",
    "BuildDeploy": "Testing",
    "Fixing": "BuildDeploy",
    "Committing": "Done",
}

# LLM nodes → the single skill the router auto-invokes for them (unless --deterministic).
# (Deterministic nodes are absent — they run their runner, not a skill.)
SKILL_CMD = {
    "Implementing": "ideable-implement-specs",
    "Fixing": "ideable-bugfixing-and-changes",
    "Committing": "ideable-commit-changes",
}

# Safety bound for `--auto-advance` (until-Done): stops a runaway Testing→Fixing→…→Testing loop.
HARD_CAP = 100


def next_after(node: str, rc: int) -> str:
    """The node to advance to after `node` finishes. `Testing` branches on the runner exit
    code (0 → Committing, non-zero → Fixing); every other node has one successor."""
    if node == "Testing":
        return "Committing" if rc == 0 else "Fixing"
    return NEXT_SINGLE[node]


def invoke_skill_headless(node: str, skill: str) -> tuple[bool, str | None]:
    """Try to perform an LLM node by invoking its skill through a headless agent CLI.

    Returns (ok, reason_if_not). The agent binary is `claude` by default, overridable via
    the DEV_CYCLE_AGENT_BIN env var; extra CLI flags can be injected via DEV_CYCLE_AGENT_ARGS
    (e.g. `--permission-mode acceptEdits` or `--dangerously-skip-permissions` for a headless run
    in an untrusted workspace). Availability of the binary on PATH is the "condition" that gates
    auto-invoke; when it is missing (or the run errors) we report why so the caller can fall back
    to the default (print-the-skill) behaviour.
    """
    agent_bin = os.environ.get("DEV_CYCLE_AGENT_BIN", "claude")
    exe = shutil.which(agent_bin)
    if not exe:
        return False, f"agent CLI '{agent_bin}' not found on PATH (set DEV_CYCLE_AGENT_BIN to override)"
    extra = shlex.split(os.environ.get("DEV_CYCLE_AGENT_ARGS", ""))
    prompt = (
        f"Invoke the {skill} skill now to advance the active implementation plan "
        f"(current dev-cycle node: {node}). Follow the skill exactly and keep the plan updated."
    )
    shown = " ".join([agent_bin, *extra, "-p"])
    print(f"[dev-cycle] auto-invoke: `{shown}` → skill '{skill}'  (why: node {node} is an agent step)")
    try:
        rc = subprocess.run([exe, *extra, "-p", prompt], cwd=str(REPO_ROOT)).returncode
    except Exception as e:  # noqa: BLE001 — surface any spawn failure as a fallback reason
        return False, f"agent invocation failed to start: {e}"
    if rc != 0:
        return False, f"agent '{agent_bin}' exited {rc}"
    return True, None


def active_plan() -> Path | None:
    if not PLANS_DIR.is_dir():
        return None
    plans = sorted(PLANS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return plans[0] if plans else None


def current_node(text: str) -> str | None:
    m = re.search(r"^\s*class\s+(\w+)\s+current\s*;", text, re.MULTILINE)
    return m.group(1) if m else None


def line_value(text: str, label: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(label)}\*\*\s*[:—-]\s*(.+)", text)
    return m.group(1).strip() if m else None


def status_summary(text: str) -> str | None:
    # The very short line under a "## ... Status summary" / "### N. Status summary" heading.
    m = re.search(r"#+\s*(?:\d+\.\s*)?Status summary\s*\n+([^\n]+)", text)
    return m.group(1).strip() if m else None


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


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
    new_text = re.sub(r"(\*\*Current step\*\*\s*[:—-]\s*).+",
                      rf"\g<1>{node} ({driver})", new_text, count=1)
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


def _history_path(plan: Path, node: str) -> Path:
    """Target file for --keep-history: `<date> - <time> - <description> (<state>).md`, derived
    from the active plan's name (existing ` (state)` suffix stripped). Disambiguates collisions
    (e.g. Fixing↔BuildDeploy loops) so no state overwrites an earlier one."""
    parts = _plan_parts(plan.stem)
    base = f"{parts[0]} - {parts[1]} - {parts[2]}" if parts else re.sub(r"\s*\([^()]*\)\s*$", "", plan.stem).strip()
    target = PLANS_DIR / f"{base} ({node}).md"
    i = 2
    while target.exists():
        target = PLANS_DIR / f"{base} ({node} {i}).md"
        i += 1
    return target


def _write_plan(plan: Path, text: str, node: str, keep_history: bool) -> Path:
    """Apply the `node` highlight to `text` and write it: overwrite `plan` in place, or (when
    keep_history) to a new `<…> (<state>).md` file so every transition is preserved. Returns
    the path written."""
    new_text, ok = _apply_highlight(text, node)
    if not ok:
        sys.exit("Could not find the two `class … idle;` / `class … current;` lines to rewrite. "
                 "Is the canonical dev-cycle graph present in the plan's Overall view?")
    target = _history_path(plan, node) if keep_history else plan
    target.write_text(new_text, encoding="utf-8")
    print(f"[dev-cycle] {'→ ' + target.name if keep_history else target.name}: "
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


def parse_summary(path: Path) -> dict[str, dict[str, tuple[int, int, int]]]:
    """Parse the cross-module SUMMARY into module -> suite -> (passed, failed, skipped)."""
    res: dict[str, dict[str, tuple[int, int, int]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*\S+\s+([\w.\-]+)\s*\|\s*(pytest|playwright)\s*\|"
                     r"\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)", line)
        if m:
            res.setdefault(m.group(1), {})[m.group(2)] = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
    return res


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


def apply_test_results(text: str) -> tuple[str, list[str]]:
    """Fold the latest TEST_REPORTS SUMMARY into the plan: set each thing's BE/FE test cell
    (BE ⇐ the module's pytest suite, FE ⇐ its playwright suite) and the Repos `Tests` counts.
    Deterministic and best-effort — cells marked ➖ and rows whose module can't be identified
    are left untouched (and reported). Returns (new_text, log lines)."""
    summ = latest_summary()
    if summ is None:
        return text, ["no TEST_REPORTS *-SUMMARY.md found — test columns left unchanged"]
    results = parse_summary(summ)
    logs = [f"using {summ.name}"]
    lines = text.splitlines()
    in_main = in_repos = False
    for i, line in enumerate(lines):
        st = line.strip()
        if st.startswith("#"):
            low = st.lower()
            in_main = low.endswith("main implementation summary table")
            in_repos = "repos updates summary" in low
            continue
        if not st.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 4 or set(cells[1]) <= set("-: "):
            continue  # separator row or too few columns
        if in_main:
            if "Impl" in line and "BE test" in line:
                continue  # header
            thing = cells[1]
            mod = thing.split("—")[0].split("/")[0].strip().split(" ")[0] if thing else ""
            mres = results.get(mod, {})
            be, fe = cells[3], cells[4] if len(cells) > 4 else "➖"
            new_be = _verdict(mres.get("pytest")) if be != "➖" else None
            new_fe = _verdict(mres.get("playwright")) if fe != "➖" else None
            changed = False
            if new_be and new_be != be:
                cells[3] = new_be; changed = True
            if new_fe and new_fe != fe and len(cells) > 4:
                cells[4] = new_fe; changed = True
            if changed:
                lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
                logs.append(f"{thing[:44]}: BE {be}→{cells[3]}, FE {fe}→{cells[4] if len(cells) > 4 else fe}")
            elif mod and mod not in results:
                logs.append(f"{thing[:44]}: module '{mod}' not in SUMMARY — left unchanged")
        elif in_repos:
            if "Repo" in line and "Tests" in line:
                continue  # header
            mres = results.get(cells[1], {})
            if mres and len(cells) > 3:
                passed = sum(v[0] for v in mres.values())
                failed = sum(v[1] for v in mres.values())
                cells[3] = f"{passed} passed / {failed} failed / 0 pending"
                lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
                logs.append(f"repo {cells[1]}: {passed} passed / {failed} failed")
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


def merge_prompt(plan: Path) -> None:
    """At the commit step, ask whether to merge the plan branch into main and act on the answer.
    Human decision gate: in a non-interactive run the merge is deferred, never automatic."""
    if not _git_enabled():
        return
    br = plan_branch(plan)
    if not sys.stdin.isatty():
        print(f"[dev-cycle] git: commit step reached on '{br}'. Merging into main is a human "
              f"decision — run interactively, or merge manually "
              f"(`git checkout main && git merge --no-ff {br}`).")
        return
    ans = input(f"[dev-cycle] Merge plan branch '{br}' into main now? [y/N] ").strip().lower()
    if ans not in ("y", "yes"):
        print(f"[dev-cycle] git: left '{br}' unmerged.")
        return
    if _git("checkout", "main").returncode != 0:
        print("[dev-cycle] git: could not switch to main — merge skipped.")
        return
    if _git("merge", "--no-ff", br).returncode == 0:
        print(f"[dev-cycle] git: merged '{br}' into main.")
    else:
        print(f"[dev-cycle] git: merge of '{br}' hit conflicts — resolve manually.")


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
        print("[dev-cycle] Plan is at Done — nothing to run.")
        return False, 0
    if node == "Blocked":
        print("[dev-cycle] Plan is Blocked (human decision required) — stopping, per decision-authority.")
        return False, 0

    drv, runnable = DRIVER.get(node, ("?", None))

    # --- Deterministic node: run its runner, branch/advance on the exit code. ---
    if runnable:
        if not os.path.exists(runnable):
            sys.exit(f"Runner not found: {runnable}")
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
    committing_ran = False
    while steps < budget:
        # Re-resolve each step: with --keep-history the previous step wrote a NEW file, which is
        # now the most-recent (active) plan; without it this returns the same file.
        plan = active_plan()
        if plan is None:
            break
        node_before = current_node(plan.read_text(encoding="utf-8"))
        advanced, last_rc = _run_one(plan, auto_invoke, keep_history)
        if not advanced:
            break
        steps += 1
        if node_before == "Committing":
            committing_ran = True
        latest = active_plan()
        if latest is not None and current_node(latest.read_text(encoding="utf-8")) == "Done":
            print("[dev-cycle] Reached Done.")
            break
    if steps >= budget and budget == HARD_CAP:
        print(f"[dev-cycle] Stopped at the safety cap ({HARD_CAP} steps).")
    print(f"[dev-cycle] Advanced {steps} step(s).")

    # Commit this execution's progress on the plan branch, then (if the commit step ran) offer
    # to merge into main. Order matters: checkpoint on the plan branch BEFORE any merge switches
    # away from it.
    if steps:
        commit_progress(active_plan() or plan, current_node((active_plan() or plan).read_text(encoding="utf-8")) or "?")
    if committing_ran:
        merge_prompt(active_plan() or plan)
    sys.exit(last_rc)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="dev-cycle.sh",
        description="Thin, deterministic router over the Ideable dev-cycle skill graph.\n"
                    "Nodes are dev-cycle states, arcs are the Ideable skills; the active plan\n"
                    "(most-recently-modified *.md in implementation-plans/) holds the highlight.\n"
                    "Nodes: Implementing → BuildDeploy → Testing → (Committing | Fixing) → Done;\n"
                    "Blocked is a human gate. See rules/implementation-plan.md for the canonical graph.",
        epilog=(
            "actions:\n"
            "  status            show the active plan, current node, and the next transition (default)\n"
            "  set <NODE>        recolour the plan's graph + set Current step / Last updated to <NODE>\n"
            "                    (NODE ∈ Implementing, BuildDeploy, Testing, Fixing, Committing, Done, Blocked)\n"
            "  run               execute the current node and advance the highlight one step\n"
            "\n"
            "run behaviour:\n"
            "  Deterministic nodes run their runner (BuildDeploy → redeploy.sh,\n"
            "  Testing → run_enabled_tests.sh; Testing then branches: pass → Committing, fail → Fixing).\n"
            "  LLM nodes (Implementing/Fixing/Committing) are performed automatically via a headless\n"
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
            "  working tree there after each execution, and asks whether to merge into main when the\n"
            "  Committing step runs (deferred when non-interactive).\n"
            "\n"
            "environment:\n"
            "  DEV_CYCLE_AGENT_BIN    agent CLI used to auto-invoke LLM nodes (default: claude)\n"
            "  DEV_CYCLE_AGENT_ARGS   extra flags for that CLI, e.g. '--permission-mode acceptEdits'\n"
            "                         or '--dangerously-skip-permissions' for headless/untrusted runs\n"
            "  DEV_CYCLE_NO_GIT       set to disable the branch/commit/merge git flow for a run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "action", nargs="?", default="status", choices=["status", "set", "run"],
        help="what to do: status (default) · set · run — see 'actions' below",
    )
    ap.add_argument("node", nargs="?", default=None, help="target NODE for `set`")
    ap.add_argument(
        "--deterministic", action="store_true",
        help="run only: advance ONLY deterministic nodes (BuildDeploy/Testing); at an LLM node "
             "(Implementing/Fixing/Committing) suggest the skill to invoke and stop. Default "
             "(without this flag): LLM nodes are performed automatically via a headless agent CLI "
             "(`claude`, or $DEV_CYCLE_AGENT_BIN), falling back to suggesting the skill when the "
             "CLI is unavailable.",
    )
    ap.add_argument(
        "--auto-advance", nargs="?", const=-1, type=int, default=None, metavar="N",
        help="run only: advance multiple steps. Omitted = a single node; bare = until Done "
             "(safety-capped); integer N = exactly N steps.",
    )
    ap.add_argument(
        "--keep-history", action="store_true",
        help="set/run: instead of overwriting the active plan in place, write each state "
             "transition to a NEW file `<date> - <time> - <description> (<state>).md`, so the "
             "whole run's history is preserved in implementation-plans/. Default: overwrite.",
    )
    args = ap.parse_args()

    plan = active_plan()
    if plan is None:
        print("No active implementation plan in implementation-plans/. "
              "Create one via ideable-implement-specs (or ideable-bugfixing-and-changes).")
        return 0

    if args.action == "status":
        do_status(plan)
    elif args.action == "set":
        if not args.node:
            sys.exit("`set` requires a node, e.g. `scripts/dev-cycle.sh set Testing`")
        set_node(plan, args.node, keep_history=args.keep_history)
    elif args.action == "run":
        # Auto-invoking LLM nodes is the default; --deterministic opts out.
        do_run(plan, auto_invoke=not args.deterministic, auto_advance=args.auto_advance,
               keep_history=args.keep_history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
