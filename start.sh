#!/bin/bash
# Start all deployment containers.
# Usage: ./start.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [-h|--help]"
  echo ""
  echo "Starts all containers defined in deployment_root/docker-compose.yml."
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_START="${SCRIPT_DIR}/deployment_root/start.sh"

if [[ ! -x "${DEPLOYMENT_START}" ]]; then
  echo "[start.sh] ERROR: ${DEPLOYMENT_START} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_START}" "$@"
