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

# Mark this as the sanctioned test run. The repo-root conftest.py (pytest) and each
# module's playwright.config.ts refuse to run WITHOUT this marker (unless the dev sets
# IDEABLE_ALLOW_DIRECT=1 for unrecorded local iteration), so the only path that produces
# TEST_REPORTS/ is this runner. Exported => inherited by every pytest / npx child.
export IDEABLE_TEST_RUNNER=1

ts=$(date +%Y-%m-%d-%H-%M-%S)

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
  test_dirs=()
  while IFS= read -r d; do
    test_dirs+=("$d")
  done < <(find "modules/$m" -type d -name TESTS -not -path '*/node_modules/*' | sort)
  if [ ${#test_dirs[@]} -gt 0 ]; then
    echo "\n=== Running module tests: ${test_dirs[*]} ==="
    ran_something=1

    mkdir -p "$report_dir"
    report_path="$report_dir/test-report.md"

    tmp_out=$(mktemp)
    set +e
    pytest "${test_dirs[@]}" -v --tb=short --ignore-glob='*/node_modules/*' 2>&1 | tee "$tmp_out"
    pytest_rc=${PIPESTATUS[0]}
    set -e

    MODULE="$m" TS="$ts" TMP_OUT="$tmp_out" REPORT_PATH="$report_path" AGG="$agg" python3 - <<'PY'
import os
import pathlib
import re

module = os.environ["MODULE"]
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
overall = FAIL if n_fail else (PASS if n_pass else (SKIP if n_skip else "⚪ No tests collected"))
failed = [r for r in results if r[1] in ("FAILED", "ERROR")]


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
    f.write(f"{module}\tpytest\t{n_pass}\t{n_fail}\t{n_skip}\t{total}\t{report_path}\n")
print(f"Wrote report: {report_path}")
PY

    rm -f "$tmp_out"
    if [ $pytest_rc -eq 5 ]; then
      echo "Module $m: no pytest tests collected (exit 5) — not treated as a failure."
    elif [ $pytest_rc -ne 0 ]; then
      echo "Module $m tests failed (exit code: $pytest_rc). See: $report_path"
      overall_rc=1
    fi
  fi

  # ---------------------------------------------------------------------------
  # Frontend UI / E2E tests (Playwright)
  # ---------------------------------------------------------------------------
  pw_dir="modules/$m/frontend/TESTS/playwright"
  if [ -f "$pw_dir/package.json" ]; then
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

      pw_out=$(mktemp)
      set +e
      (
        cd "$pw_dir"
        export MODULE_SLUG="$module_slug"
        [ -d node_modules ] || npm install
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

      MODULE="$m" TS="$ts" PW_OUT="$pw_out" PW_REPORT_PATH="$pw_report_path" AGG="$agg" python3 - <<'PY'
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

with agg.open("a") as f:
    f.write(f"{module}\tplaywright\t{n_pass}\t{n_fail}\t{n_skip}\t{total}\t{report_path}\n")
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
AGG="$agg" TS="$ts" python3 - <<'PY'
import os, pathlib, sys

agg = pathlib.Path(os.environ["AGG"])
ts = os.environ["TS"]
rows = [l.split("\t") for l in agg.read_text().splitlines() if l.strip()] if agg.exists() else []

tot_p = sum(int(r[2]) for r in rows)
tot_f = sum(int(r[3]) for r in rows)
tot_s = sum(int(r[4]) for r in rows)
tot_t = sum(int(r[5]) for r in rows)
overall = "❌ FAILED" if tot_f else ("✅ PASSED" if tot_p else "🔵 SKIPPED / no assertions")

L = [f"# Test Run Summary — {ts}", "",
     f"**Overall: {overall}**", "",
     "| ✅ Passed | ❌ Failed | 🔵 Skipped | Total |",
     "|---:|---:|---:|---:|",
     f"| {tot_p} | {tot_f} | {tot_s} | {tot_t} |", "",
     "_Legend: ✅ Passed · ❌ Failed · 🔵 Skipped_", "",
     "## Per module", "",
     "| Module | Suite | ✅ | ❌ | 🔵 | Total | Report |",
     "|:--|:--|--:|--:|--:|--:|:--|"]
for module, suite, p, f, s, t, path in rows:
    verdict = "❌" if int(f) else ("✅" if int(p) else "🔵")
    L.append(f"| {verdict} {module} | {suite} | {p} | {f} | {s} | {t} | `{path}` |")
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
for module, suite, p, f, s, t, path in rows:
    line = "  ".join([c("32", f"{p} passed"), c("31", f"{f} failed"), c("34", f"{s} skipped")])
    print(f"  {module:<16} {suite:<11} {line}")
print("  " + "-" * 54)
totals = "  ".join([c("32", f"{tot_p} passed"), c("31", f"{tot_f} failed"), c("34", f"{tot_s} skipped")])
print(f"  {'TOTAL':<16} {'':<11} {totals}")
print("  Overall: " + (c("31", overall) if tot_f else c("32", overall)))
print(f"  Reports: TEST_REPORTS/{ts}-*   (summary: {out})")
print("==========================================================")
PY
rm -f "$agg"

exit $overall_rc
