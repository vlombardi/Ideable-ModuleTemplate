#!/bin/bash

# Script: stop_module.sh
# Purpose: Stops a specific module by name
# Usage: ./scripts/stop_module.sh <module_name> [--force] [--remove-volumes]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
REMOVE_VOLUMES=false
MODULE_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--force)
            FORCE=true
            shift
            ;;
        -v|--remove-volumes)
            REMOVE_VOLUMES=true
            shift
            ;;
        *)
            if [ -z "$MODULE_NAME" ]; then
                MODULE_NAME="$1"
                shift
            else
                echo "Unknown option: $1"
                echo "Usage: $0 <module_name> [--force] [--remove-volumes]"
                exit 1
            fi
            ;;
    esac
done

# Check if module name provided
if [ -z "$MODULE_NAME" ]; then
    echo -e "${RED}Error: Module name required${NC}"
    echo ""
    echo "Usage: $0 <module_name> [--force] [--remove-volumes]"
    echo ""
    echo "Available modules:"
    echo "  - HostApp"
    exit 1
fi

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

# Confirmation prompt unless forced
if [ "$FORCE" = false ]; then
    echo -e "${YELLOW}This will stop module: $MODULE_NAME${NC}"
    if [ "$REMOVE_VOLUMES" = true ]; then
        echo -e "${RED}WARNING: This will also remove volumes and data for this module!${NC}"
    fi
    echo ""
    read -p "Continue? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}Stopping Module: $MODULE_NAME${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

# Stop the module using its stop script
cd "$MODULE_PATH"

# Check for module-specific stop script
STOP_SCRIPT=""
if [ -f "stop_services.sh" ]; then
    STOP_SCRIPT="stop_services.sh"
elif [ -f "stop_adapter.sh" ]; then
    STOP_SCRIPT="stop_adapter.sh"
else
    echo -e "${RED}Error: No stop script found in $MODULE_PATH${NC}"
    echo "Looked for: stop_services.sh, stop_adapter.sh"
    exit 1
fi

echo -e "${YELLOW}Executing: ./$STOP_SCRIPT${NC}"

# Build the command with appropriate flags
CMD="./$STOP_SCRIPT"
if [ "$FORCE" = true ]; then
    CMD="$CMD --force"
fi
if [ "$REMOVE_VOLUMES" = true ]; then
    CMD="$CMD -v"
fi

eval "$CMD"

echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}Module $MODULE_NAME stopped${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

if [ "$REMOVE_VOLUMES" = false ]; then
    echo -e "${YELLOW}Data volumes preserved. To remove volumes:${NC}"
    echo "  $0 $MODULE_NAME --remove-volumes"
fi
echo ""
