#!/bin/bash
# Stop all deployment containers.
# Usage: ./stop.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [-h|--help]"
  echo ""
  echo "Stops and removes all containers defined in deployment_root/docker-compose.yml."
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_STOP="${SCRIPT_DIR}/deployment_root/stop.sh"

if [[ ! -x "${DEPLOYMENT_STOP}" ]]; then
  echo "[stop.sh] ERROR: ${DEPLOYMENT_STOP} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_STOP}" "$@"
