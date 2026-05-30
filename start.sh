#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_START="${SCRIPT_DIR}/deployment_root/start.sh"

if [[ ! -x "${DEPLOYMENT_START}" ]]; then
  echo "[start.sh] ERROR: ${DEPLOYMENT_START} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_START}" "$@"
