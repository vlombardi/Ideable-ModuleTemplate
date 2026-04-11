#!/bin/bash

# Script: start_module.sh
# Purpose: Starts a specific module by name
# Usage: ./scripts/start_module.sh <module_name>

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if module name provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: Module name required${NC}"
    echo ""
    echo "Usage: $0 <module_name>"
    echo ""
    echo "Available modules:"
    echo "  - HostApp"
    exit 1
fi

MODULE_NAME="$1"

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Validate module exists
MODULE_PATH="modules/$MODULE_NAME"
if [ ! -d "$MODULE_PATH" ]; then
    echo -e "${RED}Error: Module '$MODULE_NAME' not found${NC}"
    echo ""
    echo "Available modules:"
    ls -1 modules/
    exit 1
fi

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}Starting Module: $MODULE_NAME${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

# Start the module using its start script
cd "$MODULE_PATH"

# Check for module-specific start script
START_SCRIPT=""
if [ -f "start_services.sh" ]; then
    START_SCRIPT="start_services.sh"
elif [ -f "start_adapter.sh" ]; then
    START_SCRIPT="start_adapter.sh"
else
    echo -e "${RED}Error: No start script found in $MODULE_PATH${NC}"
    echo "Looked for: start_services.sh, start_adapter.sh"
    exit 1
fi

echo -e "${YELLOW}Executing: ./$START_SCRIPT${NC}"
./"$START_SCRIPT"

echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}Module $MODULE_NAME started${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""
echo -e "${YELLOW}To view logs:${NC}"
echo "  cd $MODULE_PATH && docker compose logs -f"
echo ""
echo -e "${YELLOW}To stop this module:${NC}"
echo "  ./scripts/stop_module.sh $MODULE_NAME"
echo ""
