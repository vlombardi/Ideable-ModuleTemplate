#!/bin/bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

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
    if status.lower() == 'enabled':
        mods.append(name)
print(' '.join(mods))
PY
)

if [ -z "$enabled_modules" ]; then
  echo "No enabled modules found in modules/enabled.md"
  exit 0
fi

for m in $enabled_modules; do
  module_tests_dir="modules/$m/TESTS"
  if [ ! -d "$module_tests_dir" ]; then
    echo "\n=== Skipping (no module TESTS): $m ==="
    continue
  fi

  echo "\n=== Running module tests: $module_tests_dir ==="

  report_dir="TEST_REPORTS/${ts}-${m}"
  mkdir -p "$report_dir"
  report_path="$report_dir/test-report.md"

  tmp_out=$(mktemp)
  set +e
  pytest "$module_tests_dir" -v --tb=short 2>&1 | tee "$tmp_out"
  pytest_rc=${PIPESTATUS[0]}
  set -e

  python3 - <<PY
import datetime
import pathlib
import re

module = ${m!r}
ts = ${ts!r}
tmp_out = pathlib.Path(${tmp_out!r})
report_path = pathlib.Path(${report_path!r})

text = tmp_out.read_text(errors="replace")

failed_tests = []
for line in text.splitlines():
    if line.startswith("FAILED "):
        failed_tests.append(line[len("FAILED "):].strip())

def extract_failure_block(text: str, test_nodeid: str) -> str:
    idx = text.find(test_nodeid)
    if idx == -1:
        return "(Could not locate failure block in pytest output; see raw output below.)"
    start = max(0, text.rfind("\n", 0, idx) - 2000)
    end = min(len(text), idx + 6000)
    snippet = text[start:end]
    return snippet.strip()

lines = []
lines.append(f"# Test Report — {module}")
lines.append("")
lines.append(f"- Timestamp: `{ts}`")
lines.append("")

summary_line = None
for line in reversed(text.splitlines()):
    if re.search(r"=+ .* in [0-9.]+s", line):
        summary_line = line.strip()
        break
if summary_line:
    lines.append("## Pytest summary")
    lines.append("")
    lines.append(f"`{summary_line}`")
    lines.append("")

if failed_tests:
    lines.append(f"## Failed tests ({len(failed_tests)})")
    lines.append("")
    for i, nodeid in enumerate(failed_tests, 1):
        lines.append(f"### {i}. `{nodeid}`")
        lines.append("")
        block = extract_failure_block(text, nodeid)
        lines.append("```")
        lines.append(block)
        lines.append("```")
        lines.append("")
else:
    lines.append("## Failed tests")
    lines.append("")
    lines.append("None")
    lines.append("")

lines.append("## Raw pytest output")
lines.append("")
lines.append("```")
lines.append(text.strip())
lines.append("```")
lines.append("")

report_path.write_text("\n".join(lines))
print(f"Wrote report: {report_path}")
PY

  rm -f "$tmp_out"
  if [ $pytest_rc -ne 0 ]; then
    echo "Module $m tests failed (exit code: $pytest_rc). See: $report_path"
  fi

done
