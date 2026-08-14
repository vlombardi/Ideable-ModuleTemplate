#!/bin/bash
# Show status of all deployment containers.
# Usage: ./status.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [-h|--help]"
  echo ""
  echo "Shows the status of all containers in deployment_root."
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_STATUS="${SCRIPT_DIR}/deployment_root/status.sh"

if [[ ! -x "${DEPLOYMENT_STATUS}" ]]; then
  echo "[status.sh] ERROR: ${DEPLOYMENT_STATUS} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_STATUS}" "$@"
