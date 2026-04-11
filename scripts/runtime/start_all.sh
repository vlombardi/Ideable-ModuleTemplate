#!/bin/bash

# Script: start_all.sh
# Purpose: Starts all module containers in the correct dependency order
# Usage: ./scripts/start_all.sh [--force]

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--force)
            FORCE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--force]"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}Starting Ideable Platform${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

# Get the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Module startup order (respecting dependencies)
# Based on SPECS dependencies: database -> backend -> frontend

# 1. Start HostApp module
if [ -f "modules/HostApp/start_services.sh" ]; then
    echo -e "${YELLOW}[1/1] Starting HostApp module...${NC}"
    cd "$PROJECT_ROOT/modules/HostApp"
    ./start_services.sh
    echo -e "${GREEN}✓ HostApp started${NC}"
    echo ""
else
    echo -e "${RED}Warning: HostApp start script not found${NC}"
fi

# Return to project root
cd "$PROJECT_ROOT"

echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}All modules started successfully${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""
echo -e "${YELLOW}Service Overview:${NC}"
echo "  HostApp:"
echo "    - Database (TimescaleDB): localhost:5432"
echo "    - Backend API: http://localhost:8001/docs"
echo "    - Frontend: http://localhost (via Traefik)"
echo ""
echo -e "${YELLOW}To view logs:${NC}"
echo "  docker compose -f modules/<module>/docker-compose.yml logs -f"
echo ""
echo -e "${YELLOW}To check status:${NC}"
echo "  ./scripts/status_all.sh"
echo ""
