#!/bin/bash
# Rebuild and restart only the frontend container.
# Usage: ./update_frontend.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [-h|--help]"
  echo ""
  echo "Rebuilds and restarts only the frontend container."
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

# WHERE THIS SCRIPT REALLY LIVES. The repo root carries a symlink to this file, and the symlink is
# how it is normally invoked (`./update_frontend.sh`). Bash sets BASH_SOURCE[0] to the path AS INVOKED, so
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
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
unset _src _dir
DEPLOYMENT_ROOT="${PROJECT_ROOT}/deployment_root"
DEPLOYMENT_ROOT_COMPOSE="${DEPLOYMENT_ROOT}/docker-compose.yml"
PROJECT_ENV_CONFIG="${PROJECT_ROOT}/project.env.config"
PROJECT_ENV_SECRETS="${PROJECT_ROOT}/project.env.secrets"
if [[ ! -f "${PROJECT_ENV_CONFIG}" ]]; then
  echo "[update_frontend.sh] ERROR: project.env.config not found at ${PROJECT_ENV_CONFIG}"
  exit 1
fi

# Source secrets before config because config files may reference secret variables.
if [[ -f "${PROJECT_ENV_SECRETS}" ]]; then
  # shellcheck disable=SC1090
  source "${PROJECT_ENV_SECRETS}"
fi
# shellcheck disable=SC1090
source "${PROJECT_ENV_CONFIG}"

PROJECT_APP_SLUG="${APP_SLUG:-deployment_root}"

# Auto-load module .env.secrets + .env.config files so Vite build-time variables (VITE_*) and other
# module-scoped env vars are available during docker builds.
# Source .env.secrets first because .env.config files may reference secret variables.
set -a
if [[ -d "${PROJECT_ROOT}/modules" ]]; then
  for env_file in "${PROJECT_ROOT}"/modules/*/.env.secrets "${PROJECT_ROOT}"/modules/*/.env.config; do
    if [[ -f "${env_file}" ]]; then
      echo "[update_frontend.sh] Loading env: ${env_file}"
      # shellcheck disable=SC1090
      source "${env_file}"
    fi
  done
fi
set +a

echo "[update_frontend.sh] Building + deploying frontend only..."
env -i PATH="$PATH" HOME="$HOME" python3 "${PROJECT_ROOT}/scripts/dev/common/build_and_deploy.py" \
  --only-submodules frontend \
  --skip-module-root-deploy

echo "[update_frontend.sh] Recreating frontend container only (to use the newly built image)..."
if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
  (
    cd "${DEPLOYMENT_ROOT}"
    env -i PATH="$PATH" HOME="$HOME" \
      docker compose --project-directory "$PWD" --project-name "${PROJECT_APP_SLUG}" rm -sf frontend || true
    env -i PATH="$PATH" HOME="$HOME" \
      docker compose --project-directory "$PWD" --project-name "${PROJECT_APP_SLUG}" up -d --no-deps frontend
  )
else
  echo "[update_frontend.sh] Compose file not found at ${DEPLOYMENT_ROOT_COMPOSE}; cannot restart frontend."
  exit 1
fi

echo "[update_frontend.sh] Done."
