---
description: Run tests for all enabled modules (modules/enabled.md) — run full suite or a specific module/suite
---

# Workflow: Run Tests

Executes test suites for **all enabled modules** listed in `modules/enabled.md`.

Each module may have:
- a module-level test suite in `modules/<MODULE>/TESTS/`
- optional sub-module suites in `modules/<MODULE>/<SUBMODULE>/TESTS/`

## Prerequisites

1. Containers must be running. If not, start them first:
```bash
cd deployment_root && ./start.sh
```

2. Install test dependencies (first time only):
```bash
pip install -r modules/HostApp/TESTS/requirements.txt
```

3. Install Playwright browser (first time only, only needed for frontend suite):
```bash
playwright install chromium
```

## Step 1 — Determine scope

Ask the user (or infer from context) what to run:
- **all enabled modules** (default) — run `pytest` for every enabled module that has a `TESTS/` folder
- **one module** — e.g. `HostApp`
- **one suite inside a module** — module-specific, depends on folder layout (example below for `HostApp`)

## Step 2 — Set environment

The tests read connection parameters from `modules/<MODULE>/.env` automatically via `python-dotenv`.
If the file is not present or values differ, export overrides before running:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5433
export POSTGRES_USER=vinz
export POSTGRES_PASSWORD=vinz
export POSTGRES_DB=vinz
export BACKEND_URL=http://localhost:8001
export AUTHENTIK_URL=http://localhost:9000
export AUTHENTIK_BOOTSTRAP_TOKEN=authentik-bootstrap-token
export TRAEFIK_DASHBOARD_URL=http://localhost:8088
export FRONTEND_URL=http://localhost:3000
export EXTERNAL_BASE_HOST=localhost
# Optional explicit full URL used by endpoint-reference smoke tests
# export EXTERNAL_BASE_URL=https://casa-cataplano.duckdns.org
```

## Step 3 — Run tests

### All enabled modules
// turbo
```bash
set -e

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

for m in $enabled_modules; do
  if [ -d "modules/$m/TESTS" ]; then
    echo "\n=== Running module tests: modules/$m/TESTS ==="

    report_dir="TEST_REPORTS/${ts}-${m}"
    mkdir -p "$report_dir"
    report_path="$report_dir/test-report.md"

    tmp_out=$(mktemp)
    set +e
    pytest "modules/$m/TESTS" -v --tb=short 2>&1 | tee "$tmp_out"
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
    # Try to extract the failure section for a nodeid. Pytest uses headers like:
    # ________ test_name ________
    # or includes nodeid in the header depending on verbosity.
    # We keep it simple: locate the first occurrence of the nodeid and grab a window around it.
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
    lines.append(f"## Pytest summary")
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
  else
    echo "\n=== Skipping (no module TESTS): $m ==="
  fi
done
```

### One module (example: HostApp)
// turbo
```bash
pytest modules/HostApp/TESTS/ -v --tb=short
```

### One suite inside a module (example: HostApp)

Database suite only:
// turbo
```bash
pytest modules/HostApp/TESTS/database/ -v --tb=short
```

Backend suite only:
// turbo
```bash
pytest modules/HostApp/TESTS/backend/ -v --tb=short
```

Authentik + Traefik suite only:
// turbo
```bash
pytest modules/HostApp/TESTS/authentik_traefik/ -v --tb=short
```

Authentik + Traefik endpoint-reference smoke tests only:
// turbo
```bash
pytest modules/HostApp/TESTS/authentik_traefik/test_authentik_traefik.py -v --tb=short -k TestExternalEndpointReference
```

Notes:
- `TestExternalEndpointReference` validates the endpoint URLs printed by `redeploy.sh`:
  - `/health`, `/api`, `/api/docs`, `/api/openapi.json`
  - `/module/template/health`, `/module/template/api`, `/module/template/api/docs`, `/module/template/api/openapi.json`
  - `/module-registry.json`, `/remotes/template/mf-manifest.json`
- These tests run automatically when running all HostApp tests or the whole `authentik_traefik` suite.

Frontend E2E suite only:
// turbo
```bash
pytest modules/HostApp/TESTS/frontend/ -v --tb=short
```

## Step 4 — Interpret results

After the run completes, report:
- Total tests collected, passed, failed, skipped
- For each failure: test name, error message, and likely cause
- Common failure patterns and their meaning:

| Failure pattern | Likely cause |
|---|---|
| `psycopg2.OperationalError` | Database container not running or wrong port |
| `requests.exceptions.ConnectionError` on backend | Backend container not running or wrong `BACKEND_URL` |
| `AssertionError: 401` on backend CRUD | Auth headers not forwarded — check `conftest.py` `backend_headers` fixture |
| `AssertionError: No application with slug` | Authentik bootstrap container did not complete successfully |
| `AssertionError: Traefik dashboard returned 4xx` | Traefik not running or dashboard port not exposed |
| `TimeoutError` in Playwright | Frontend container not running, page not loading, or selector mismatch |
| `AssertionError` on nav link / heading | Frontend routing or component changed — re-check `App.tsx` routes and page headings |

## Step 5 — Create bug-fix plan (interactive)

After running tests, open the generated report(s):
- `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md`

Then ask:
- **Do you want to fix the reported bugs now?**

If the user confirms:
- Fix the bugs.
- For each fixed bug, add a short, specific entry to the appropriate bug avoider/spec file (e.g. `modules/<MODULE>/<SUBMODULE>/SPECS/general_bug_avoider.md`) describing:
  - what failed
  - root cause
  - the fix
  - how to avoid regression when implementing from specs again

## Step 6 — Generate report (optional)

To produce a timestamped HTML report:
```bash
pip install pytest-html
pytest modules/HostApp/TESTS/ -v --tb=short \
  --html=modules/HostApp/TESTS/$(date +%Y-%m-%d-%H-%M-%S)-test-report.html \
  --self-contained-html
```
