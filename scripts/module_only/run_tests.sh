#!/bin/bash
# Run tests for a module
# Usage: ./scripts/module_only/run_tests.sh [module_name] [-h|--help]

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [module_name] [-h|--help]"
    echo ""
    echo "Runs backend and frontend tests for the specified module."
    echo "If no module name is given, auto-detects from modules/ directory."
    echo ""
    echo "Arguments:"
    echo "  module_name  Module to test (auto-detected if omitted)"
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# --- This runs inside the dev tools container ---------------------------------------------------
if [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" != "1" && "${IDEABLE_NO_CONTAINER:-0}" != "1" ]]; then
  if [[ ! -x "${PROJECT_ROOT}/scripts/dev/tool.sh" ]]; then
    echo "scripts/dev/tool.sh is missing — it is how this project obtains its toolchain." >&2
    exit 1
  fi
  exec "${PROJECT_ROOT}/scripts/dev/tool.sh" bash "${SCRIPT_DIR}/run_tests.sh" "$@"
fi

# This is a QUICK, UNRECORDED run for one module. The official path — the only one that writes
# TEST_REPORTS/ — is `scripts/common/run_enabled_tests.sh` (rules/testing-guidelines.md § "How tests
# must be run"). `IDEABLE_UNRECORDED_RUN=1` is that rule's documented escape for exactly this case.
#
# Without it this script could not run a single test: the repo-root `conftest.py` rejects a direct
# pytest, and the invocations below swallowed the rejection (`2>/dev/null || echo "No pytest tests
# found"`), so a guard refusal, a failing suite and a module with no tests all printed the same
# reassuring line. Measured: nothing in the repository calls this script, which is presumably why
# nobody noticed it had stopped being able to test anything.
export IDEABLE_UNRECORDED_RUN=1

# Where the running stack is, seen from inside the container — the SAME definition the sanctioned
# runner uses, not a copy of it. Without these the stack-touching suites reach for `localhost` and
# find this container: measured here as 20 failed / 13 errors before it was wired in.
cd "$PROJECT_ROOT"
# shellcheck source=scripts/common/container_stack_env.sh
source "${PROJECT_ROOT}/scripts/common/container_stack_env.sh"
container_stack_addresses
# The per-module addresses need MODULE_NAME, which is resolved further down — see the call there.

MODULE_NAME="${1:-}"

# Auto-detect if not provided
if [[ -z "$MODULE_NAME" ]]; then
    for dir in "$PROJECT_ROOT"/modules/*/; do
        if [[ -d "$dir" ]]; then
            name=$(basename "$dir")
            if [[ "$name" != "module_template" && "$name" != "host_app" ]]; then
                MODULE_NAME="$name"
                break
            fi
        fi
    done
fi

if [[ -z "$MODULE_NAME" ]]; then
    echo "Error: Could not detect module. Please provide module name."
    echo "Usage: $0 [module_name]"
    exit 1
fi

# This module's own addresses, which its conftest reads under a runtime-built name
# (`<SLUG>_API_URL`). Here rather than beside container_stack_addresses above, because the module
# is only known once the auto-detection has run.
container_module_addresses "$MODULE_NAME"

MODULE_DIR="$PROJECT_ROOT/modules/$MODULE_NAME"
TESTS_DIR="$MODULE_DIR/TESTS"

echo "========================================"
echo "Running tests for module: $MODULE_NAME"
echo "========================================"
echo ""

if [[ ! -d "$TESTS_DIR" ]]; then
    echo "Warning: No TESTS directory found at $TESTS_DIR"
    echo "Creating TESTS directory structure..."
    mkdir -p "$TESTS_DIR"/backend
    mkdir -p "$TESTS_DIR"/frontend
    echo "Created TESTS directory. Add your tests here."
    exit 0
fi

# Run backend tests if they exist.
#
# `modules/<m>/backend/TESTS`, not `modules/<m>/TESTS/backend`. The sub-module layout is the one
# `rules/testing-guidelines.md` § Test Organization defines and the one every module actually uses;
# this script looked for the other shape, found nothing, and — because the pytest call swallowed its
# own errors — said so in a way indistinguishable from success. It has therefore never run a test in
# this layout.
if [[ -d "$MODULE_DIR/backend/TESTS" ]]; then
    echo "Running backend tests..."
    if [[ -f "$MODULE_DIR/backend/TESTS/test.sh" ]]; then
        cd "$MODULE_DIR/backend/TESTS"
        ./test.sh
    elif [[ -f "$MODULE_DIR/backend/SOURCES/requirements.txt" ]]; then
        cd "$MODULE_DIR/backend/SOURCES"
        # Failures are reported as failures. Errors are not discarded, and "no tests collected"
        # (pytest exit 5) is the one case that legitimately means what the old message claimed.
        python3 -m pytest ../TESTS/ -v; rc=$?
        [[ $rc -eq 5 ]] && echo "No backend tests found for $MODULE_NAME"
        [[ $rc -ne 0 && $rc -ne 5 ]] && exit $rc
    fi
fi

# Run frontend tests if they exist
if [[ -d "$MODULE_DIR/frontend/TESTS" ]]; then
    echo ""
    echo "Running frontend tests..."
    if [[ -f "$MODULE_DIR/frontend/TESTS/test.sh" ]]; then
        cd "$MODULE_DIR/frontend/TESTS"
        ./test.sh
    elif [[ -f "$MODULE_DIR/frontend/SOURCES/package.json" ]]; then
        cd "$MODULE_DIR/frontend/SOURCES"
        # Same reasoning as the backend above: only an ABSENT script is "no tests configured".
        if node -e 'process.exit(require("./package.json").scripts?.test ? 0 : 1)' 2>/dev/null; then
            npm test
        else
            echo "No test script configured in $MODULE_NAME's package.json"
        fi
    fi
fi

echo ""
echo "========================================"
echo "Test run complete"
echo "========================================"
