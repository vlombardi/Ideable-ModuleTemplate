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

# WHERE THIS SCRIPT REALLY LIVES. The repo root carries a symlink to this file, and the symlink is
# how it is normally invoked (`./stop.sh`). Bash sets BASH_SOURCE[0] to the path AS INVOKED, so
# `dirname` of the link yields the repo root and the walk to `../../..` lands one level ABOVE the
# repo — silently, because `cd` succeeds on any ancestor that exists. Measured 2026-09-08 before the
# link was created. So the link is resolved first, and only then is the root computed.
#
# Resolved inline rather than sourced from a helper: finding a helper needs the resolved directory
# this block exists to produce.
_src="${BASH_SOURCE[0]}"
while [ -L "${_src}" ]; do
  _dir="$(cd -P "$(dirname "${_src}")" && pwd)"
  _src="$(readlink "${_src}")"
  case "${_src}" in /*) ;; *) _src="${_dir}/${_src}" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "${_src}")" && pwd)"
unset _src _dir
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEPLOYMENT_STOP="${PROJECT_ROOT}/deployment_root/stop.sh"

if [[ ! -x "${DEPLOYMENT_STOP}" ]]; then
  echo "[stop.sh] ERROR: ${DEPLOYMENT_STOP} not found or not executable." >&2
  exit 1
fi

exec "${DEPLOYMENT_STOP}" "$@"
