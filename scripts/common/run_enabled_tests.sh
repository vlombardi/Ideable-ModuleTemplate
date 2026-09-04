#!/bin/bash
# Run tests for all local modules listed in modules/enabled.md.
# Usage: ./scripts/common/run_enabled_tests.sh [-h|--help]
#
# Per module it runs, independently:
#   - pytest over modules/<m>/TESTS               (backend / integration)
#   - Playwright over modules/<m>/frontend/TESTS/playwright  (frontend UI / E2E)
# The Playwright phase runs the stack-free suites by default (e.g. the @ideable/ui
# Widget Gallery, which boots its own dev server). Stack-requiring specs (L&F
# parity, authenticated pages) run only when RUN_STACK_E2E=1 is exported. See
# rules/testing-guidelines.md § "Frontend UI / E2E tests (Playwright)".
set -euo pipefail

# host_app's backend, located by its compose service label. The horizontal-scale work removed container_name, so a
# fixed name finds nothing.
_hostapp_backend_container() {
  docker ps --filter "label=com.docker.compose.service=backend" --filter "status=running" \
    --format '{{.ID}}' 2>/dev/null | head -1
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [-h|--help]"
  echo ""
  echo "Runs, for every local module in modules/enabled.md:"
  echo "  - pytest over modules/<m>/TESTS"
  echo "  - Playwright over modules/<m>/frontend/TESTS/playwright (if present)"
  echo "Test reports are written to TEST_REPORTS/<timestamp>-<module>/."
  echo ""
  echo "Env:"
  echo "  RUN_STACK_E2E=1  also run Playwright specs that need a running stack"
  echo "                   (set HOSTAPP_FRONTEND_URL / TEMPLATE_FRONTEND_URL + auth env)"
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

cd "$(git rev-parse --show-toplevel)"

# --- The suite runs inside the dev tools container ----------------------------------------------
#
# Re-exec ONCE, at the top, rather than wrapping each of the ~48 tool invocations below. Everything
# after this line then runs against the published image's toolchain — the same ruff, mypy, pytest,
# node and browsers for every developer — so "the tests passed" means the same thing everywhere.
#
# `IDEABLE_IN_TOOL_CONTAINER=1` is set by the image, and `tool.sh` execs directly when it sees it,
# so this is not recursive. Set `IDEABLE_NO_CONTAINER=1` to run on the host toolchain — an escape
# hatch for a broken Docker, not a supported way to work: the host has no version guarantees, which
# is the entire reason the container exists.
if [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" != "1" && "${IDEABLE_NO_CONTAINER:-0}" != "1" ]]; then
  if [ ! -x scripts/dev/tool.sh ]; then
    echo "scripts/dev/tool.sh is missing — it is how this project obtains its toolchain." >&2
    exit 1
  fi
  exec scripts/dev/tool.sh bash scripts/common/run_enabled_tests.sh "$@"
fi

# Where the running stack is, seen from inside the container. One definition, shared with
# scripts/module_only/run_tests.sh — see that file for the whole reasoning.
# shellcheck source=scripts/common/container_stack_env.sh
source "$(dirname "$0")/container_stack_env.sh"
container_stack_addresses

# Mark this as the sanctioned test run. The repo-root conftest.py (pytest) and each
# module's playwright.config.ts refuse to run WITHOUT this marker (unless the dev sets
# IDEABLE_UNRECORDED_RUN=1 for unrecorded local iteration), so the only path that produces
# TEST_REPORTS/ is this runner. Exported => inherited by every pytest / npx child.
export IDEABLE_TEST_RUNNER=1

# Enable this repo's git hooks if they are not on yet. `core.hooksPath` is per-clone and does not
# travel with a checkout, so leaving it to "run one command" made the push gate exist only for
# whoever set it up. Wiring it into the entry points a developer runs anyway removes the manual step.
if [ -x "$(dirname "$0")/ensure_hooks.sh" ]; then "$(dirname "$0")/ensure_hooks.sh" || true; fi


ts=$(date +%Y-%m-%d-%H-%M-%S)

# The tree state is sampled HERE, before a single test runs.
#
# `- Working tree:` answers "did the suite run against committed code?", and the only moment that
# can be answered is before the suite starts. Sampling it at report-writing time folded in the very
# files the run had just produced — the summary and the renamed plan — so every run recorded
# `dirty` (measured 2026-09-01: 6 of 6) and the field said nothing about what it claimed to.
# `.githooks/pre-push` and `dev-cycle.sh deliver` both read it, and a field that is always `dirty`
# is a field neither can use.
tree_at_start="clean"
[ -n "$(git status --porcelain 2>/dev/null)" ] && tree_at_start="dirty"
export IDEABLE_TREE_AT_START="$tree_at_start"

enabled_modules=$(python3 - <<'PY'
import pathlib
mods = []
for line in pathlib.Path('modules/enabled.md').read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    if ':' not in line:
        continue
    name, status = [x.strip() for x in line.split(':', 1)]
    if status.lower() == 'local':
        mods.append(name)
print(' '.join(mods))
PY
)

if [ -z "$enabled_modules" ]; then
  echo "No local modules found in modules/enabled.md"
  exit 0
fi

overall_rc=0

# Aggregate rows (module, suite, pass, fail, skip, total, report) — one line per suite,
# consumed after the loop to build the cross-module run summary.
agg=$(mktemp)

# Frontend dependencies, before anything needs them.
#
# Inside the container each `frontend/SOURCES/node_modules` is a separate host-cache mount (tool.sh)
# and starts empty, because those trees carry COMPILED binaries built for the host's platform and
# cannot be shared. Both the static gate (`npx tsc` per module) and Playwright's dev server need
# them, so the install belongs here — ahead of both — rather than inside the Playwright block, where
# it left `tsc` with no types and failed the gate for every module that was not being tested.
if [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" == "1" ]]; then
  for _fe in modules/*/frontend/SOURCES; do
    [ -f "$_fe/package.json" ] || continue
    if [ ! -d "$_fe/node_modules" ] || [ -z "$(ls -A "$_fe/node_modules" 2>/dev/null)" ]; then
      echo "  · installing $_fe dependencies (first run in this environment)"
      (cd "$_fe" && npm ci --install-links --legacy-peer-deps) || {
        echo "  ✗ could not install $_fe dependencies — the gate and the UI suite need them" >&2
        exit 1
      }
    fi
  done
  unset _fe
fi

# ── Static analysis gate ───────────────────────────────────────────────────────────────────────
#
# Lint and type errors fail the run, for BOTH languages. The TypeScript half is not an afterthought:
# the frontends are transpiled without typechecking, and 27 errors accumulated unseen — including a
# widget generic that made every association table a type error — until someone ran `tsc` by hand.
# A gate covering only Python would leave the half that already failed unguarded.
#
# On its first run the Python half found a live defect: the keyset-pagination predicate in
# module_template's history query was built, bound and then dropped, so every cursor page returned
# the first page.
#
# Skipped, loudly, when a tool is absent — a missing linter must not look like a passing one.
gate_rc=0

# ruff covers ALL of the repository's Python, not just the application packages.
#
# It used to lint three directories — the two backend `app/` trees and the identity script — and
# print "All checks passed!". That sentence was true of those three directories and false of the
# repository: 18 findings sat in `scripts/` and in the TESTS trees, unseen, including two dead
# locals of exactly the kind that had already exposed a live cursor-pagination defect (F841) and a
# test whose assertion checked a different region than its name claimed.
#
# A gate that reports a pass without naming its scope is indistinguishable from a gate that checked
# everything. Widening it is cheaper than remembering the caveat, so the scope is now "the Python in
# this repo" and it is printed.
_py_dirs="modules scripts"

# Resolve the gate's tools from PATH, and FAIL when one is absent.
#
# They used to be looked up at `.venv/bin/<tool>`, and a missing one printed "NOT checked" and moved
# on with `gate_rc` untouched — a gate that skipped itself while reporting success. That was a
# defensible trade when the toolchain was whatever the developer happened to have installed. It is
# not defensible now: this runs inside the dev tools container, `--doctor` asserts every one of these
# is present, so an absence means the image is broken and every check that needs it is worthless.
#
# `IDEABLE_NO_CONTAINER=1` still lands here on a host toolchain, where a missing tool is the
# developer's own affair — but it is still reported as a failure rather than a footnote, because a
# gate that did not run proves nothing either way.
# Read one key out of a deployment env file, or nothing at all when there is no such file.
#
# WHY IT IS A FUNCTION AND NOT A `grep`. `grep` on a missing file exits 2, `set -o pipefail` carries
# that out of the pipeline, and `set -e` then ends the RUN — not the lookup. Both call sites below
# hit it, and the first one killed the runner outright: it printed
# `=== Running frontend UI tests: … ===` and stopped, with no error (the `2>/dev/null` suppressed
# the only message that explained it), no summary written, and an exit code that reads as a test
# failure. The second is the same shape and would have taken over five lines later.
#
# A checkout with no `deployment_root/` is not exotic — it is every fresh clone and every git
# worktree, which is the normal way to work on a branch while another session keeps the primary
# checkout. Absence is the documented case here: with no password the authenticated specs skip and
# say so. This makes the lookup total so that path is reachable.
_env_file_value() {  # <file> <key>
  [ -f "$1" ] || return 0
  grep -h "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

_require_tool() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "  ✗ $1 not found — $2 NOT checked. Inside the dev tools container this means the image is"
  echo "    incomplete: run scripts/dev/tool.sh --doctor."
  gate_rc=1
  return 1
}

if _require_tool ruff "Python lint"; then
  echo "\n=== ruff ($_py_dirs) ==="
  if ! ruff check $_py_dirs; then gate_rc=1; fi
fi

if _require_tool mypy "Python types"; then
  # DISCOVERED, not named — and the scope is printed with the result.
  #
  # This runner syncs to every remote module project, where `modules/host_app/` holds only
  # module.json and config/ (no backend at all) and the module's directory carries the module's own
  # name, not `module_template`. Naming those two paths meant the step matched nothing in a remote
  # and printed "=== mypy ===" followed by silence — a gate that checked NOTHING, indistinguishable
  # from one that checked everything. Same failure shape as the ruff scope above, one section later.
  #
  # Every backend faces the same gate, no exceptions. host_app carried a scoped
  # `--disable-error-code=arg-type,assignment,misc` while its models still used SQLAlchemy's legacy
  # `Column(...)` declarations (70 findings, one pattern). The typed-model migration migrated them to `Mapped[...]`,
  # which removed the findings and the exception together.
  _mypy_dirs=""
  for d in modules/*/backend/SOURCES/app; do
    [ -d "$d" ] || continue
    _mypy_dirs="${_mypy_dirs:+$_mypy_dirs }$d"
  done
  if [ -z "$_mypy_dirs" ]; then
    echo "\n=== mypy ==="
    echo "  ✗ modules/*/backend/SOURCES/app matched nothing — mypy checked NOTHING"
    gate_rc=1
  else
    echo "\n=== mypy ($_mypy_dirs) ==="
    for d in $_mypy_dirs; do
      if ! mypy "$d"; then gate_rc=1; fi
    done
  fi
fi

if _require_tool npx "TypeScript types"; then
  # DISCOVERED for the same reason as mypy above: a remote project has no host_app frontend and its
  # own frontend lives under the module's name. The `continue` on a missing tsconfig used to make an
  # empty scope silent, so a remote ran the TypeScript half of the gate over zero files and said
  # nothing about it. Unlike mypy this is not an error — a module may legitimately have no frontend —
  # but it must be STATED rather than inferred from an absence of output.
  _tsc_found=0
  for fe in modules/*/frontend/SOURCES; do
    [ -f "$fe/tsconfig.json" ] || continue
    _tsc_found=$((_tsc_found + 1))
    echo "\n=== tsc --noEmit: $fe ==="
    # A checkout with no `node_modules` — a fresh clone, or a git worktree — has no local
    # TypeScript, so `npx` resolves `tsc` to the unrelated placeholder package of that name and the
    # failure reads "This is not the tsc command you are looking for", which names neither the
    # project nor the missing dependency. Say what it is before it happens rather than leaving the
    # reader with that. The dev tools container mounts a node_modules cache, so this is reachable
    # only on the host path.
    if [ ! -d "$fe/node_modules" ]; then
      echo "  · $fe has no node_modules: 'npx tsc' resolves the placeholder package, not TypeScript."
      echo "    Run 'npm ci' there (or use the dev tools container) to type-check this module."
    fi
    if ! (cd "$fe" && npx --no-install tsc --noEmit -p tsconfig.json); then gate_rc=1; fi
  done
  if [ "$_tsc_found" -eq 0 ]; then
    echo "  · no modules/*/frontend/SOURCES/tsconfig.json found — TypeScript NOT checked"
  fi
fi

if [ "$gate_rc" -ne 0 ]; then
  echo "\n✗ Static analysis failed — fix the findings above. The gate runs before the suites so a"
  echo "  type or lint error is reported as itself, not as a downstream test failure."
  overall_rc=1
fi

container_module_addresses $enabled_modules

for m in $enabled_modules; do
  report_dir="TEST_REPORTS/${ts}-${m}"
  ran_something=0

  # ---------------------------------------------------------------------------
  # Backend / integration tests (pytest)
  # ---------------------------------------------------------------------------
  # Collect module-level (modules/<m>/TESTS) AND sub-module-level
  # (modules/<m>/<sub>/TESTS, e.g. frontend/TESTS) pytest dirs — module_template keeps
  # its contract tests at the sub-module level, which a bare modules/<m>/TESTS target
  # would silently skip. node_modules (Playwright harness) is excluded.
  # One pytest run PER SUITE, so the plan's columns can say which kind of test covered what.
  # A single run reported everything as "backend", which put compose and bootstrap contracts in
  # the backend column and left rows about configuration or tooling with nothing to fill them.
  #
  #   backend  ← <m>/backend/TESTS
  #   frontend ← <m>/frontend/TESTS   (its pytest contract tests; playwright is reported below)
  #   config   ← <m>/TESTS and every other sub-module's TESTS (database, authentik, traefik…)
  #
  # `config` is the module's own configuration and deployment contracts. Framework tooling lives
  # in scripts/TESTS and is reported once for the whole run, not per module.
  for suite in backend frontend config; do
  test_dirs=()
  while IFS= read -r d; do
    case "$suite" in
      backend)  [[ "$d" == "modules/$m/backend/TESTS" ]] && test_dirs+=("$d") ;;
      frontend) [[ "$d" == "modules/$m/frontend/TESTS" ]] && test_dirs+=("$d") ;;
      config)   [[ "$d" == "modules/$m/backend/TESTS" || "$d" == "modules/$m/frontend/TESTS" ]] || test_dirs+=("$d") ;;
    esac
  done < <(find "modules/$m" -type d -name TESTS -not -path '*/node_modules/*' | sort)
  if [ ${#test_dirs[@]} -gt 0 ]; then
    echo "\n=== Running $suite tests: ${test_dirs[*]} ==="
    ran_something=1

    mkdir -p "$report_dir"
    report_path="$report_dir/test-report-${suite}.md"

    tmp_out=$(mktemp)
    set +e
    # -rs: pytest's -v line prints `SKIPPED [ 28%]` with NO reason. The reason exists only in
    # the "short test summary info" block, which -rs emits. Without it the skip-reason report
    # could only say "(no reason given)" — an explanation-shaped hole where the explanation goes.
    pytest "${test_dirs[@]}" -v -rs --tb=short --ignore-glob='*/node_modules/*' 2>&1 | tee "$tmp_out"
    pytest_rc=${PIPESTATUS[0]}
    set -e

    MODULE="$m" SUITE="$suite" TS="$ts" TMP_OUT="$tmp_out" REPORT_PATH="$report_path" AGG="$agg" \
      PYTEST_RC="$pytest_rc" python3 - <<'PY'
import os
import pathlib
import re

module = os.environ["MODULE"]
suite = os.environ["SUITE"]
ts = os.environ["TS"]
tmp_out = pathlib.Path(os.environ["TMP_OUT"])
report_path = pathlib.Path(os.environ["REPORT_PATH"])
agg = pathlib.Path(os.environ["AGG"])
text = tmp_out.read_text(errors="replace")

PASS, FAIL, SKIP = "✅ Passed", "❌ Failed", "🔵 Skipped"


def cell(s):
    """Make a value safe for a markdown table cell."""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def humanize(nodeid):
    """test_entity_x_creation -> 'Entity x creation' (a quick-glance description)."""
    func = nodeid.split("::")[-1]
    func = re.sub(r"\[.*\]$", "", func)              # strip parametrization id
    name = re.sub(r"^test_", "", func).replace("_", " ").strip()
    return (name[:1].upper() + name[1:]) if name else func


# Per-test results from the pytest -v output: "path::test STATUS [ pct%]".
row_re = re.compile(r"^(\S+::\S+?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b(?:\s*\((.*?)\))?")
results, seen = [], set()
for line in text.splitlines():
    m = row_re.match(line.strip())
    if not m or m.group(1) in seen:
        continue
    seen.add(m.group(1))
    results.append((m.group(1), m.group(2), humanize(m.group(1)), m.group(3) or ""))


def badge(st):
    if st in ("PASSED", "XPASS"):
        return PASS
    if st in ("FAILED", "ERROR"):
        return FAIL
    return SKIP


n_pass = sum(1 for r in results if r[1] in ("PASSED", "XPASS"))
n_fail = sum(1 for r in results if r[1] in ("FAILED", "ERROR"))
n_skip = sum(1 for r in results if r[1] in ("SKIPPED", "XFAIL"))
total = len(results)
failed = [r for r in results if r[1] in ("FAILED", "ERROR")]

# A suite can fail WITHOUT emitting a single `path::test STATUS` line, and that used to be
# reported as "⚪ No tests collected" — indistinguishable from a suite that legitimately has no
# tests. The canonical case is a COLLECTION ERROR: one unimportable test module makes pytest exit
# 2 with "Interrupted: N error during collection", the tests it had already collected never run,
# and the suite contributes 0/0/0 to a run whose summary then reports PASSED. That is exactly how
# 102 already-collected host_app backend tests vanished from a green run in the identity-plane split.
#
# Exit 5 is pytest's own "no tests collected" and is the only honest zero; exit 0 with no rows
# means the same. Any OTHER non-zero exit that yields no countable failure is unaccounted for and
# must be surfaced as a failure rather than averaged away as an absence.
rc = int(os.environ["PYTEST_RC"])
unaccounted = rc not in (0, 5) and n_fail == 0


def unaccounted_detail():
    """Why pytest bailed — the report's test rows cannot say it, because there are none."""
    out = [m.group(0).strip() for m in re.finditer(r"^!+ .+ !+$", text, re.M)]
    out += [m.group(0).strip() for m in re.finditer(r"^(?:ERROR|INTERNALERROR)\b.*$", text, re.M)]
    return out or [f"pytest exited {rc} with no diagnostic line this parser recognises."]


if unaccounted:
    overall = f"{FAIL} — pytest exited {rc} without reporting a single failing test"
else:
    overall = FAIL if n_fail else (PASS if n_pass else (SKIP if n_skip else "⚪ No tests collected"))


def failure_block(nodeid):
    """Return the actual traceback for a failed test from pytest's FAILURES/ERRORS
    section (not the verbose run line), so the fix phase has the real error."""
    method = re.sub(r"\[.*\]$", "", nodeid.split("::")[-1])
    sec = re.search(r"^=+ (FAILURES|ERRORS) =+\s*$", text, re.M)
    region = text[sec.start():] if sec else text
    cut = re.search(r"^=+ short test summary", region, re.M)
    if cut:
        region = region[:cut.start()]
    headers = list(re.finditer(r"^_+ .+? _+\s*$", region, re.M))
    for i, h in enumerate(headers):
        if method in h.group(0):
            end = headers[i + 1].start() if i + 1 < len(headers) else len(region)
            return region[h.start():end].strip()
    return "(failure detail not isolated — see raw pytest output below)"


L = [f"# Test Report — {module} (backend / integration)", "",
     f"- Timestamp: `{ts}`", "- Suite: pytest", "",
     "## Summary", "", f"**Overall: {overall}**", "",
     "| ✅ Passed | ❌ Failed | 🔵 Skipped | Total |",
     "|---:|---:|---:|---:|",
     f"| {n_pass} | {n_fail} | {n_skip} | {total} |", "",
     "_Legend: ✅ Passed · ❌ Failed · 🔵 Skipped_", ""]

if unaccounted:
    L += [f"## ⛔ Suite did not run to completion (pytest exit {rc})", "",
          "Every count above is **zero because no test produced a result** — this is NOT "
          "'no tests collected'. Tests that were already collected did not run. pytest reported:",
          "", "```"] + unaccounted_detail() + ["```", ""]

order = {"FAILED": 0, "ERROR": 0, "SKIPPED": 1, "XFAIL": 1, "PASSED": 2, "XPASS": 2}
if results:
    L += ["## What was tested", "", "| Result | Test | Location |", "|:--|:--|:--|"]
    for nodeid, st, human, reason in sorted(results, key=lambda r: (order.get(r[1], 3), r[2].lower())):
        extra = f" — {reason}" if reason else ""
        L += [f"| {badge(st)} | {cell(human + extra)} | `{cell(nodeid)}` |"]
    L += [""]

if failed:
    L += [f"## ❌ Failures — details for the fix phase ({len(failed)})", ""]
    for i, (nodeid, st, human, reason) in enumerate(failed, 1):
        L += [f"### {i}. {human}", "", f"`{nodeid}`", "", "```", failure_block(nodeid), "```", ""]

L += ["<details><summary>Raw pytest output</summary>", "", "```", text.strip(), "```", "", "</details>", ""]
report_path.write_text("\n".join(L))

with agg.open("a") as f:
    f.write(f"{module}\t{suite}\t{n_pass}\t{n_fail}\t{n_skip}\t{total}\t{report_path}"
            f"\t{int(unaccounted)}\n")

# Publish WHY things were skipped, not just how many.
#
# A skip count is not information. "19 skipped" inside "840 passed" read as a healthy suite for as
# long as it existed, while those 19 authenticated tests had never executed even once -- nothing set
# the environment variable they were waiting for. The number could not distinguish "this test does
# not apply here" from "the runner failed to configure this test", and only the second is a defect.
#
# So the reasons travel to the final summary, where they are printed. A listed reason cannot be
# mistaken for coverage the way a bare integer can.
skips = pathlib.Path(str(agg) + ".skips")
seen_reasons = {}

# Reasons come from the `-rs` short-summary block: `SKIPPED [n] path:line: reason`. The verbose run
# line carries no reason at all, so parsing only that produced "(no reason given)" for every pytest
# skip — a report whose whole purpose is to say WHY, saying nothing.
for _m in re.finditer(r"^SKIPPED \[(\d+)\]\s+(?:[^\s:]+:\d+:\s*)?(.*)$", text, re.M):
    _count = int(_m.group(1))
    _reason = (_m.group(2) or "").strip().replace("\t", " ") or "(no reason given)"
    seen_reasons[_reason] = seen_reasons.get(_reason, 0) + _count

# Fall back to the run lines only for statuses the block does not cover (XFAIL), and never
# double-count what the block already accounted for.
if sum(seen_reasons.values()) < n_skip:
    _unexplained = n_skip - sum(seen_reasons.values())
    seen_reasons["(no reason given)"] = seen_reasons.get("(no reason given)", 0) + _unexplained
with skips.open("a") as f:
    for reason, count in sorted(seen_reasons.items(), key=lambda kv: -kv[1]):
        f.write(f"{module}\t{suite}\t{count}\t{reason}\n")
print(f"Wrote report: {report_path}")
PY

    rm -f "$tmp_out"
    if [ $pytest_rc -eq 5 ]; then
      echo "Module $m: no $suite tests collected (exit 5) — not treated as a failure."
    elif [ $pytest_rc -ne 0 ]; then
      echo "Module $m $suite tests failed (exit code: $pytest_rc). See: $report_path"
      overall_rc=1
    fi
  fi
  done

  # ---------------------------------------------------------------------------
  # Frontend UI / E2E tests (Playwright)
  # ---------------------------------------------------------------------------
  pw_dir="modules/$m/frontend/TESTS/playwright"
  # RUN_STACK_E2E=0 means "do not run the browser layer", and it has to mean that HERE rather than
  # inside the specs. Letting Playwright start and having each spec `test.skip()` itself does not
  # work: global-setup runs first, refuses without a frontend URL and credentials it was never
  # given, and Playwright then exits non-zero having collected nothing. Measured before this guard,
  # `RUN_STACK_E2E=0` produced a failed step, exit 1, and a summary still reading
  # "Overall: ✅ PASSED" -- barely faster than running the specs, and wrong.
  if [ -f "$pw_dir/package.json" ] && [ "${RUN_STACK_E2E:-}" = "0" ]; then
    ran_something=1
    echo "\n=== Skipping frontend UI tests for $m (RUN_STACK_E2E=0) ==="
    echo "  · the browser layer is the slow half of this suite and it is OFF for this run."
    echo "  · this run cannot gate a push: the pre-push hook wants one that included it."
  elif [ -f "$pw_dir/package.json" ]; then
    ran_something=1
    if ! command -v npm >/dev/null 2>&1; then
      echo "\n=== Skipping frontend UI tests for $m (npm not found) ==="
    else
      echo "\n=== Running frontend UI tests: $pw_dir ==="
      mkdir -p "$report_dir"
      pw_report_path="$report_dir/ui-test-report.md"

      # Derive the module's route slug from its manifest so slug-parameterized specs
      # (e.g. /<slug>/gallery) target the right routes for any module. Falls back to
      # any MODULE_SLUG already exported, then to 'template'.
      manifest="modules/$m/frontend/SOURCES/src/moduleManifest.ts"
      module_slug="${MODULE_SLUG:-}"
      if [ -z "$module_slug" ] && [ -f "$manifest" ]; then
        module_slug=$(grep -oE "slug:[[:space:]]*['\"][^'\"]+['\"]" "$manifest" | head -1 | sed -E "s/.*['\"]([^'\"]+)['\"].*/\1/")
      fi
      module_slug="${module_slug:-template}"

      # ── Authenticated E2E: enabled automatically when the ingredients are present ──────────
      #
      # These specs (module authorization, entity pages, CRUD) drive a real browser through a real
      # login, and they are the only layer that sees what a USER sees. They were opt-in behind
      # RUN_STACK_E2E, and the cost of that was concrete: a thin-token regression hid the Items page
      # from every authorized user, shipped, and was reported from the browser -- while this suite
      # reported "3 passed" with 19 skipped and the gate went green.
      #
      # So the opt-in is inverted. They run whenever they CAN run, and are skipped only when
      # something they need is genuinely missing:
      #
      #   E2E_TEST_PASSWORD          the dedicated personas' password (config/test-users.yaml)
      #   HOSTAPP_FRONTEND_URL       the shell to log in against
      #
      # A deployment that does not provision the e2e accounts simply has no password, and the specs
      # skip exactly as before. RUN_STACK_E2E=1 still forces them on; RUN_STACK_E2E=0 forces off.
      if [ -z "${RUN_STACK_E2E:-}" ]; then
        e2e_pw="${E2E_TEST_PASSWORD:-}"
        [ -n "$e2e_pw" ] || e2e_pw=$(_env_file_value deployment_root/.env.secrets E2E_TEST_PASSWORD)
        e2e_url="${HOSTAPP_FRONTEND_URL:-}"
        if [ -z "$e2e_url" ]; then
          ext_host=$(_env_file_value deployment_root/.env.config EXTERNAL_BASE_HOST)
          [ -n "$ext_host" ] && e2e_url="https://${ext_host}"
        fi
        if [ -n "$e2e_pw" ] && [ -n "$e2e_url" ]; then
          export RUN_STACK_E2E=1 E2E_TEST_PASSWORD="$e2e_pw" HOSTAPP_FRONTEND_URL="$e2e_url"
          echo "  · authenticated E2E enabled (personas from config/test-users.yaml, shell $e2e_url)"
          # Create the personas if they are absent. Idempotent, and paired with the purge at the
          # end of this script: the accounts exist for the duration of the run and no longer, so a
          # test run leaves the system as it found it. Without this the purge would work exactly
          # once — the accounts are otherwise created at deploy time.
          _be=$(_hostapp_backend_container)
          if [ -n "$_be" ]; then
            docker exec -e E2E_TEST_USERS_ENABLED=true -e E2E_TEST_PASSWORD="$e2e_pw" \
              "$_be" python -m app.test_users --provision >/dev/null 2>&1 \
              || echo "  · warning: could not provision the e2e personas"
          fi
        else
          echo "  · authenticated E2E skipped: no E2E_TEST_PASSWORD and/or no frontend URL resolvable"
        fi
      fi

      pw_out=$(mktemp)
      set +e
      (
        cd "$pw_dir"
        export MODULE_SLUG="$module_slug"
        # `npm ci` from the committed lock, so the e2e harness cannot drift under the suite the
        # way the frontend images used to. `npm install` here re-resolved every version
        # whenever node_modules was absent — a test harness that changes behaviour between runs
        # makes a red build ambiguous.
        # Non-EMPTY, not merely present. Inside the dev tools container this path is a named volume
        # (see tool.sh): the directory always exists, and on its first run it is empty. A bare
        # `[ -d node_modules ]` accepted it and skipped the install, so the suite started with no
        # packages at all.
        if [ ! -d node_modules ] || [ -z "$(ls -A node_modules 2>/dev/null)" ]; then npm ci; fi

        # The dev server Playwright starts (`npm run dev`, cwd SOURCES — see webServer in
        # playwright.config.ts) uses a SECOND dependency tree, the module frontend's own. Inside the
        # dev tools container that tree is a separate host-cache mount (tool.sh) and starts empty, so
        # it needs the same treatment. Fixing only the harness's node_modules moved the failure here
        # rather than resolving it: `@rspack/binding` is compiled, and the host's build is darwin.
        _fe_src="$(cd ../../SOURCES 2>/dev/null && pwd || true)"
        if [ -n "$_fe_src" ] && [ -f "$_fe_src/package.json" ]; then
          if [ ! -d "$_fe_src/node_modules" ] || [ -z "$(ls -A "$_fe_src/node_modules" 2>/dev/null)" ]; then
            echo "  · installing frontend dependencies for the dev server (first run in this environment)"
            (cd "$_fe_src" && npm ci --install-links --legacy-peer-deps)
          fi
        fi
        # Browser download only; CI images are expected to carry the system libs
        # (or run inside the official Playwright image). '|| true' keeps a cached
        # browser from turning an offline re-run into a hard failure.
        npx playwright install chromium >/dev/null 2>&1 || true
        # Force the list reporter so the per-test lines the report parser reads are
        # deterministic across local/CI environments.
        npx playwright test --reporter=list
      ) 2>&1 | tee "$pw_out"
      pw_rc=${PIPESTATUS[0]}
      set -e

      MODULE="$m" TS="$ts" PW_OUT="$pw_out" PW_REPORT_PATH="$pw_report_path" AGG="$agg" \
        PW_RC="$pw_rc" python3 - <<'PY'
import os, pathlib, re
module = os.environ["MODULE"]
ts = os.environ["TS"]
pw_out = pathlib.Path(os.environ["PW_OUT"])
report_path = pathlib.Path(os.environ["PW_REPORT_PATH"])
agg = pathlib.Path(os.environ["AGG"])
text = pw_out.read_text(errors="replace")

PASS, FAIL, SKIP = "✅ Passed", "❌ Failed", "🔵 Skipped"


def cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


# Per-test results from the Playwright list reporter.
res_re = re.compile(r"^\s*(✓|✔|✘|✕|-)\s+\d+\s+(.*\S)\s*$")


def parse_desc(desc):
    """'[chromium] › tests/x.spec.ts:22:3 › suite › title (12ms)' -> ('title', 'tests/x.spec.ts:22:3')."""
    loc = ""
    m = re.search(r"([\w./-]+\.spec\.ts:\d+:\d+)", desc)
    if m:
        loc = m.group(1)
    parts = desc.split(" › ")
    title = parts[-1] if parts else desc
    title = re.sub(r"\s*\(\d+(?:\.\d+)?\s*m?s\)\s*$", "", title).strip()
    return title, loc


tests = []
for line in text.splitlines():
    m = res_re.match(line.rstrip())
    if not m:
        continue
    sym = m.group(1)
    title, loc = parse_desc(m.group(2))
    st = PASS if sym in ("✓", "✔") else (FAIL if sym in ("✘", "✕") else SKIP)
    tests.append((st, title, loc))

n_pass = sum(1 for t in tests if t[0] == PASS)
n_fail = sum(1 for t in tests if t[0] == FAIL)
n_skip = sum(1 for t in tests if t[0] == SKIP)
total = len(tests)

# Playwright's own summary line (fallback for counts if the list lines weren't parsed).
summary = None
for line in reversed(text.splitlines()):
    if re.search(r"\b\d+ (passed|failed|skipped)\b", line):
        summary = line.strip()
        break
if total == 0 and summary:
    def grab(key):
        mm = re.search(rf"(\d+) {key}", summary)
        return int(mm.group(1)) if mm else 0
    n_pass, n_fail, n_skip = grab("passed"), grab("failed"), grab("skipped")
    total = n_pass + n_fail + n_skip

overall = FAIL if n_fail else (PASS if n_pass else (SKIP if n_skip else "⚪ No tests"))

# Explicit per-operation CRUD log (crud-endpoints.spec.ts / *-crud.spec.ts emit `[CRUD] ...`)
# so a maintainer sees exactly what was created/read/updated/deleted, with data + ids.
crud = []
for ln in text.splitlines():
    if "[CRUD]" in ln:
        op = ln.split("[CRUD]", 1)[1].strip()
        up = op.upper()
        st = FAIL if "FAILED" in up else (SKIP if "SKIPPED" in up else PASS)
        crud.append((st, op))

L = [f"# UI Test Report — {module} (Playwright)", "",
     f"- Timestamp: `{ts}`", "- Suite: Playwright (frontend/TESTS/playwright)", "",
     "## Summary", "", f"**Overall: {overall}**", "",
     "| ✅ Passed | ❌ Failed | 🔵 Skipped | Total |",
     "|---:|---:|---:|---:|",
     f"| {n_pass} | {n_fail} | {n_skip} | {total} |", ""]
if summary:
    L += [f"_Playwright: `{summary}`_", ""]
L += ["_Legend: ✅ Passed · ❌ Failed · 🔵 Skipped_", ""]

if crud:
    L += ["## CRUD operations (create / read / update / delete)", "",
          "| Result | Operation |", "|:--|:--|"]
    L += [f"| {st} | {cell(op)} |" for st, op in crud]
    L += [""]

if tests:
    order = {FAIL: 0, SKIP: 1, PASS: 2}
    L += ["## What was tested", "", "| Result | Test | Location |", "|:--|:--|:--|"]
    for st, title, loc in sorted(tests, key=lambda t: (order.get(t[0], 3), t[1].lower())):
        L += [f"| {st} | {cell(title)} | {('`' + cell(loc) + '`') if loc else ''} |"]
    L += [""]

# Failure detail for the fix phase: Playwright prints "  N) tests/...\n   Error ..." blocks.
fm = re.search(r"\n\s*1\) ", text)
if fm:
    tail = text[fm.start():]
    ms = re.search(r"\n\s*\d+ (passed|failed|skipped)", tail)
    detail = tail[:ms.start()] if ms else tail
    L += ["## ❌ Failures — details for the fix phase", "", "```", detail.strip(), "```", ""]

L += ["<details><summary>Raw Playwright output</summary>", "", "```", text.strip(), "```", "", "</details>", ""]
report_path.write_text("\n".join(L))

# Field 8 is the "this suite never reported a result" flag, exactly as the pytest path writes it.
# Without it a Playwright run that exited non-zero contributed 0/0/0 to the totals, and the summary
# read "Overall: ✅ PASSED" while the script exited 1 -- the two disagreeing, with the wrong one in
# larger type. That is the same defect the collection-error and static-analysis flags were added to
# fix; the browser layer simply had no flag of its own.
_pw_rc = os.environ.get("PW_RC", "0").strip()
_no_result = (_pw_rc not in ("", "0")) and total == 0

with agg.open("a") as f:
    f.write(f"{module}\tplaywright\t{n_pass}\t{n_fail}\t{n_skip}\t{total}\t{report_path}"
            f"\t{int(_no_result)}\n")

# Playwright's line output does not carry the `test.skip()` reason, only the title. Publishing the
# titles is still the point: they name which coverage is absent, which an integer cannot. The
# reconciliation in the final summary is what guarantees this block cannot silently contribute
# nothing while skips exist.
if n_skip:
    _skips = pathlib.Path(str(agg) + ".skips")
    with _skips.open("a") as f:
        for _t in tests:
            if _t[0] == SKIP:
                _title = str(_t[1]).replace("\t", " ")[:100]
                f.write(f"{module}\tplaywright\t1\tskipped by the spec: {_title}\n")
print(f"Wrote report: {report_path}")
PY

      rm -f "$pw_out"
      if [ $pw_rc -ne 0 ]; then
        echo "Module $m UI tests failed (exit code: $pw_rc). See: $pw_report_path"
        overall_rc=1
      fi
    fi
  fi

  if [ $ran_something -eq 0 ]; then
    echo "\n=== Skipping (no module TESTS or frontend/TESTS/playwright): $m ==="
  fi
done

# ---------------------------------------------------------------------------
# Cross-module run summary — a single quick-glance report + colored console output.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Framework tooling tests (scripts/TESTS) — once for the whole run, not per module
# ---------------------------------------------------------------------------
# scripts/ is framework-owned: every module consumes it, none may modify it. So its tests belong
# to no module, and reporting them under one would misstate both that module's coverage and the
# framework's. In a remote module project this directory does not exist and the suite is simply
# absent — which is the honest signal that a remote does not own this code.
if [ -d "scripts/TESTS" ]; then
  fw_report_dir="TEST_REPORTS/${ts}-framework"
  mkdir -p "$fw_report_dir"
  fw_report_path="$fw_report_dir/test-report-scripts.md"
  echo "\n=== Running framework tooling tests: scripts/TESTS ==="
  fw_out=$(mktemp)
  set +e
  pytest scripts/TESTS -v --tb=short 2>&1 | tee "$fw_out"
  fw_rc=${PIPESTATUS[0]}
  set -e
  MODULE="framework" SUITE="scripts" TS="$ts" TMP_OUT="$fw_out" REPORT_PATH="$fw_report_path" AGG="$agg" \
    FW_RC="$fw_rc" python3 - <<'PYFW'
import os, pathlib, re

text = pathlib.Path(os.environ["TMP_OUT"]).read_text(errors="replace")
report_path = pathlib.Path(os.environ["REPORT_PATH"])
agg = pathlib.Path(os.environ["AGG"])

def count(word):
    m = re.search(rf"(\d+) {word}", text)
    return int(m.group(1)) if m else 0

n_pass, n_fail, n_skip = count("passed"), count("failed"), count("skipped")
total = n_pass + n_fail + n_skip

# Same guard as the per-module suites, and here the old behaviour was worse: a collection error in
# scripts/TESTS emits no "N passed" line at all, so every count was 0 and the status read
# "✅ Passed" — a green report for a suite that never ran. See the per-suite block for the full note.
rc = int(os.environ["FW_RC"])
unaccounted = rc not in (0, 5) and n_fail == 0
status = (f"❌ Failed — pytest exited {rc} without reporting a single failing test"
          if unaccounted else ("❌ Failed" if n_fail else "✅ Passed"))
report_path.write_text("\n".join([
    "# Test Report — framework tooling (scripts/TESTS)",
    "",
    f"- Timestamp: `{os.environ['TS']}`",
    "- Suite: pytest over `scripts/TESTS`",
    "",
    f"**Overall: {status}**",
    "",
    "| ✅ Passed | ❌ Failed | 🔵 Skipped | Total |",
    "|---:|---:|---:|---:|",
    f"| {n_pass} | {n_fail} | {n_skip} | {total} |",
    "",
    "<details><summary>Raw pytest output</summary>",
    "",
    "```",
    text.strip(),
    "```",
    "",
    "</details>",
    "",
]))
with agg.open("a") as f:
    f.write(f"framework\tscripts\t{n_pass}\t{n_fail}\t{n_skip}\t{total}\t{report_path}"
            f"\t{int(unaccounted)}\n")
print(f"Wrote report: {report_path}")
PYFW
  rm -f "$fw_out"
  if [ $fw_rc -eq 5 ]; then
    echo "No framework tests collected (exit 5) — not treated as a failure."
  elif [ $fw_rc -ne 0 ]; then
    echo "Framework tooling tests failed (exit code: $fw_rc). See: $fw_report_path"
    overall_rc=1
  fi
fi

AGG="$agg" TS="$ts" GATE_RC="$gate_rc" python3 - <<'PY'
import os, pathlib, sys

agg = pathlib.Path(os.environ["AGG"])
ts = os.environ["TS"]
rows = [l.split("\t") for l in agg.read_text().splitlines() if l.strip()] if agg.exists() else []

tot_p = sum(int(r[2]) for r in rows)
tot_f = sum(int(r[3]) for r in rows)
tot_s = sum(int(r[4]) for r in rows)
tot_t = sum(int(r[5]) for r in rows)

# Field 7 is the per-suite "pytest never reported a result" flag. Without it this Overall was
# computed from counts alone, so a suite that died during collection contributed 0/0/0 and the run
# still read "✅ PASSED" — the counts cannot distinguish "nothing to test" from "nothing ran".
errored = [r for r in rows if len(r) > 7 and r[7].strip() == "1"]

# The STATIC ANALYSIS GATE is an input to this verdict, and it was not one.
#
# `gate_rc` correctly set the script's exit code, so CI would have caught a lint or type failure.
# The line a human reads did not: with ruff/mypy/tsc failing and every test passing, the runner
# printed "Overall: ✅ PASSED" and exited 1 -- the two disagreeing, with the wrong one in larger
# type. Three green results were reported from this summary while mypy was failing.
#
# Same defect as the collection-error case above, same fix: make the input visible to the verdict
# instead of trusting that whoever reads it also reads the scrollback.
gate_failed = os.environ.get("GATE_RC", "0").strip() not in ("", "0")

if gate_failed and (tot_f or errored):
    overall = "❌ FAILED — tests failed AND static analysis failed"
elif gate_failed:
    overall = "❌ FAILED — static analysis (ruff / mypy / tsc); every test passed"
elif tot_f or errored:
    overall = "❌ FAILED"
else:
    overall = "✅ PASSED" if tot_p else "🔵 SKIPPED / no assertions"

# Record WHAT was tested, not just the outcome. A green summary that cannot be tied to a commit
# cannot gate anything: "the tests passed" is only useful alongside "on this tree". The pre-push
# hook compares these two lines to the working tree and refuses a push whose code was never run.
import subprocess
def _git(*a):
    try:
        return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""
_head = _git("rev-parse", "HEAD")
# Sampled by the shell before the suite started -- see `tree_at_start` above. Recomputing it here
# would describe the tree AFTER the run wrote its own reports, which is not the question.
_dirty = os.environ.get("IDEABLE_TREE_AT_START") or ("dirty" if _git("status", "--porcelain") else "clean")

L = [f"# Test Run Summary — {ts}", "",
     f"**Overall: {overall}**", "",
     f"- Commit: `{_head or 'unknown'}`",
     f"- Working tree: `{_dirty}`", "",
     "| ✅ Passed | ❌ Failed | 🔵 Skipped | Total |",
     "|---:|---:|---:|---:|",
     f"| {tot_p} | {tot_f} | {tot_s} | {tot_t} |", "",
     "_Legend: ✅ Passed · ❌ Failed · 🔵 Skipped_", "",
     "## Per module", "",
     "| Module | Suite | ✅ | ❌ | 🔵 | Total | Report |",
     "|:--|:--|--:|--:|--:|--:|:--|"]
for module, suite, p, f, s, t, path, *rest in rows:
    err = bool(rest) and rest[0].strip() == "1"
    verdict = "❌" if (int(f) or err) else ("✅" if int(p) else "🔵")
    L.append(f"| {verdict} {module} | {suite} | {p} | {f} | {s} | {t} | `{path}` |")
L.append("")

if errored:
    L += ["## ⛔ Suites that did not run to completion", "",
          "These show **zero** counts above because pytest never reported a test result — a "
          "collection error, an internal error, or an interrupted run. A zero here does not mean "
          "'no tests'; tests that were already collected did not run.", "",
          "| Module | Suite | Report |", "|:--|:--|:--|"]
    L += [f"| {r[0]} | {r[1]} | `{r[6]}` |" for r in errored]
    L.append("")

_skips_path = pathlib.Path(str(agg) + ".skips")
if _skips_path.exists():
    _rows = [ln.split("\t") for ln in _skips_path.read_text().splitlines()]
    _rows = [r for r in _rows if len(r) == 4]
    if _rows:
        L += ["## Skipped, by reason", "",
              "A skip count on its own cannot distinguish *not applicable here* from *the runner "
              "did not configure this*. Only the second is a coverage gap, and it is the one that "
              "hid nineteen authenticated tests inside a green total until 2026-08-26.", "",
              "| Count | Module | Suite | Reason |", "|---:|:--|:--|:--|"]
        L += [f"| {r[2]} | {r[0]} | {r[1]} | {r[3]} |"
              for r in sorted(_rows, key=lambda r: -int(r[2]))]
        L.append("")

out = pathlib.Path("TEST_REPORTS") / f"{ts}-SUMMARY.md"
out.write_text("\n".join(L))
print(f"Wrote summary: {out}")

# Colored console glance (green pass / red fail / blue skip) when attached to a TTY.
tty = sys.stdout.isatty()
def c(code, s):
    return f"\033[{code}m{s}\033[0m" if tty else s

print()
print("==================== TEST RUN SUMMARY ====================")
for module, suite, p, f, s, t, path, *rest in rows:
    line = "  ".join([c("32", f"{p} passed"), c("31", f"{f} failed"), c("34", f"{s} skipped")])
    print(f"  {module:<16} {suite:<11} {line}")
print("  " + "-" * 54)
totals = "  ".join([c("32", f"{tot_p} passed"), c("31", f"{tot_f} failed"), c("34", f"{tot_s} skipped")])
print(f"  {'TOTAL':<16} {'':<11} {totals}")
for r in errored:
    print("  " + c("31", f"! {r[0]} {r[1]}: pytest did not run to completion — "
                        f"the zeros above are not 'no tests'"))
print("  Overall: " + (c("31", overall) if (tot_f or errored or gate_failed) else c("32", overall)))

# Skips, by reason -- and the two kinds are not the same kind of thing.
#
# "Not applicable here" is fine. "The runner did not configure it" means a test has never run, and
# reporting it as a skip inside a green total is how nineteen authenticated tests stayed dead
# indefinitely. Only the second kind is a defect, so only the second kind is called out -- printing
# both without distinction would train the reader to skim past it, which is the same failure in a
# different coat.
UNCONFIGURED = (
    "not set", "not configured", "unset", "no password", "not available",
    "not provided", "missing", "no credentials", "no token",
    # The runner's own wording when it declines to configure a suite, e.g.
    # "no E2E_TEST_PASSWORD and/or no frontend URL resolvable". An all-caps token name after "no"
    # is the runner naming a variable it could not find, which is always this category.
    "no e2e_", "not resolvable", "no url", "unavailable",
)
skips_path = pathlib.Path(str(agg) + ".skips")
skip_rows = []
if skips_path.exists():
    for line in skips_path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            skip_rows.append((parts[0], parts[1], int(parts[2]), parts[3]))

if skip_rows:
    print("  " + "-" * 54)
    print("  Skipped, by reason:")
    unconfigured = []
    for module_, suite_, count_, reason_ in sorted(skip_rows, key=lambda r: -r[2]):
        bad = any(tok in reason_.lower() for tok in UNCONFIGURED)
        mark = c("31", "!") if bad else " "
        print(f"  {mark} {count_:>3}  {module_}/{suite_}: {reason_[:88]}")
        if bad:
            unconfigured.append((module_, suite_, count_, reason_))
    if unconfigured:
        n = sum(r[2] for r in unconfigured)
        print("  " + c("31", f"! {n} test(s) were skipped because the RUNNER did not configure "
                             f"them, not because they do not apply."))
        print("  " + c("31", "  Those tests have not run. A skip here is a coverage gap, "
                             "not a passing result."))

# Reconcile: the reasons must account for every skip the counts reported.
#
# Deliberately OUTSIDE the `if skip_rows:` block above. Inside it, the check would be skipped in
# precisely the case it exists for — skips counted but no reasons published at all — which is the
# same shape of defect this whole section was added to prevent. Measured, not assumed.
explained = sum(r[2] for r in skip_rows)
if explained < tot_s:
    print("  " + "-" * 54)
    print("  " + c("31", f"! {tot_s - explained} skipped test(s) are NOT explained above "
                         f"({explained} of {tot_s} accounted for)."))
    print("  " + c("31", "  A suite reported skips without publishing their reasons — treat the "
                         "list as incomplete."))
elif explained > tot_s:
    # More reasons than counted skips is normal and worth stating rather than papering over: a
    # module skipped at IMPORT (a missing dependency, say) appears in pytest's short-summary block
    # but produces no `path::test SKIPPED` run line, so it is a reason without a counted test. The
    # earlier version subtracted and printed "! -1 skipped test(s)", which is worse than silence.
    print("  " + "-" * 54)
    print(f"  ({explained} reasons for {tot_s} counted skips — the extra "
          f"{explained - tot_s} are whole modules skipped at import, which have no per-test line)")
elif tot_s:
    print(f"  ({tot_s} of {tot_s} skips accounted for)")

print(f"  Reports: TEST_REPORTS/{ts}-*   (summary: {out})")
print("==========================================================")
PY
rm -f "$agg" "$agg.skips"

# ── Leave the system as we found it ────────────────────────────────────────────────────────────
#
# The e2e personas carry a known password, and the suites additionally mint their own per-run
# identities (`e2e-tenant-*`, `e2e-priv-*`). Left behind they accumulate — 27 had built up before
# this was added — and an access review then reports test identities next to real ones.
#
# Runs whatever the outcome: a failed run is exactly when residue is most likely, and least likely
# to be cleaned up by hand.
_be=$(_hostapp_backend_container)
if [ -n "$_be" ]; then
  if docker exec "$_be" python -m app.test_users --purge >/dev/null 2>&1; then
    echo "  · test accounts removed"
  else
    echo "  · warning: could not remove the test accounts — run ./authz.sh purge-test-users"
  fi
fi

exit $overall_rc
