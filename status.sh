#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_STATUS="${SCRIPT_DIR}/deployment_root/status.sh"

if [[ ! -x "${DEPLOYMENT_STATUS}" ]]; then
  echo "[status.sh] ERROR: ${DEPLOYMENT_STATUS} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_STATUS}" "$@"
