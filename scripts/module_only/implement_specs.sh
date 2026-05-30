#!/bin/bash
# Implement SPECS for a module using /ImplementSpecs workflow
# Module-level authorization contracts such as modules/<module>/SPECS/authorization.yaml
# are included in the SPECS-to-SOURCES implementation step.
# Usage: ./scripts/module_only/implement_specs.sh [module_name]

set -euo pipefail

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

if [[ ! -d "$MODULE_DIR" ]]; then
    echo "Error: Module not found: $MODULE_DIR"
    exit 1
fi

echo "========================================"
echo "Implement SPECS for module: $MODULE_NAME"
echo "========================================"
echo ""

# Check for SPECS directory
if [[ ! -d "$MODULE_DIR/SPECS" ]]; then
    echo "Error: No SPECS directory found at $MODULE_DIR/SPECS"
    exit 1
fi

# Find all spec files
echo "Found specifications:"
find "$MODULE_DIR/SPECS" -name "*.md" -type f | while read -r spec; do
    echo "  - $(basename "$spec")"
done

echo ""
echo "To implement these specs:"
echo "1. Use the /ImplementSpecs workflow in your IDE"
echo "2. Or run with Windsurf agent: ./scripts/module_only/implement_specs.sh $MODULE_NAME"
echo ""
echo "Module directory: $MODULE_DIR"
