#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_STOP="${SCRIPT_DIR}/deployment_root/stop.sh"

if [[ ! -x "${DEPLOYMENT_STOP}" ]]; then
  echo "[stop.sh] ERROR: ${DEPLOYMENT_STOP} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_STOP}" "$@"
