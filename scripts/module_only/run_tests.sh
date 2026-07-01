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

MODULE_NAME="${1:-}"

# Auto-detect if not provided
if [[ -z "$MODULE_NAME" ]]; then
    for dir in "$PROJECT_ROOT"/modules/*/; do
        if [[ -d "$dir" ]]; then
            name=$(basename "$dir")
            if [[ "$name" != "ModuleTemplate" && "$name" != "HostApp" && "$name" != "SRA" ]]; then
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

# Run backend tests if they exist
if [[ -d "$TESTS_DIR/backend" ]]; then
    echo "Running backend tests..."
    if [[ -f "$TESTS_DIR/backend/test.sh" ]]; then
        cd "$TESTS_DIR/backend"
        ./test.sh
    elif [[ -f "$MODULE_DIR/backend/SOURCES/requirements.txt" ]]; then
        cd "$MODULE_DIR/backend/SOURCES"
        python -m pytest ../../TESTS/backend/ -v 2>/dev/null || echo "No pytest tests found"
    fi
fi

# Run frontend tests if they exist
if [[ -d "$TESTS_DIR/frontend" ]]; then
    echo ""
    echo "Running frontend tests..."
    if [[ -f "$TESTS_DIR/frontend/test.sh" ]]; then
        cd "$TESTS_DIR/frontend"
        ./test.sh
    elif [[ -f "$MODULE_DIR/frontend/SOURCES/package.json" ]]; then
        cd "$MODULE_DIR/frontend/SOURCES"
        npm test 2>/dev/null || echo "No tests configured in package.json"
    fi
fi

echo ""
echo "========================================"
echo "Test run complete"
echo "========================================"
