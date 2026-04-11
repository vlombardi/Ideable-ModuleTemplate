#!/bin/bash

# Script: stop_all.sh
# Purpose: Stops all module containers gracefully
# Usage: ./scripts/stop_all.sh [--force] [--remove-volumes]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
REMOVE_VOLUMES=false

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
            echo "Unknown option: $1"
            echo "Usage: $0 [--force] [--remove-volumes]"
            exit 1
            ;;
    esac
done

# Confirmation prompt unless forced
if [ "$FORCE" = false ]; then
    echo -e "${YELLOW}This will stop all Ideable containers.${NC}"
    if [ "$REMOVE_VOLUMES" = true ]; then
        echo -e "${RED}WARNING: This will also remove all volumes and data!${NC}"
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
echo -e "${GREEN}Stopping Ideable Platform${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Stop modules in reverse order of dependencies

# 1. Stop HostApp module
if [ -f "modules/HostApp/stop_services.sh" ]; then
    echo -e "${YELLOW}[1/1] Stopping HostApp module...${NC}"
    cd "$PROJECT_ROOT/modules/HostApp"
    if [ "$REMOVE_VOLUMES" = true ]; then
        ./stop_services.sh --force -v
    else
        ./stop_services.sh --force
    fi
    echo -e "${GREEN}✓ HostApp stopped${NC}"
    echo ""
else
    echo -e "${YELLOW}Info: HostApp stop script not found, skipping${NC}"
fi

# Return to project root
cd "$PROJECT_ROOT"

echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}All modules stopped successfully${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

if [ "$REMOVE_VOLUMES" = true ]; then
    echo -e "${RED}Volumes have been removed. All data is lost.${NC}"
else
    echo -e "${YELLOW}Data volumes preserved. To remove volumes, use:${NC}"
    echo "  $0 --remove-volumes"
fi
echo ""
