#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="${SCRIPT_DIR}/deployment_root"
DEPLOYMENT_ROOT_COMPOSE="${DEPLOYMENT_ROOT}/docker-compose.yml"
PROJECT_ENV_FILE="${SCRIPT_DIR}/project.env"
if [[ ! -f "${PROJECT_ENV_FILE}" ]]; then
  echo "[update_backend.sh] ERROR: project.env not found at ${PROJECT_ENV_FILE}"
  exit 1
fi

# shellcheck disable=SC1090
source "${PROJECT_ENV_FILE}"

PROJECT_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-${APP_SLUG:-deployment_root}}"

# Auto-load module .env files so Vite build-time variables (VITE_*) and other
# module-scoped env vars are available during docker builds.
set -a
if [[ -d "${SCRIPT_DIR}/modules" ]]; then
  for env_file in "${SCRIPT_DIR}"/modules/*/.env; do
    if [[ -f "${env_file}" ]]; then
      echo "[update_backend.sh] Loading env: ${env_file}"
      # shellcheck disable=SC1090
      source "${env_file}"
    fi
  done
fi
set +a

if [[ -t 0 ]]; then
  echo
  read -r -p "[update_backend.sh] Wipe backend-related volumes now? (y/N): " wipe_answer
  case "${wipe_answer}" in
    y|Y|yes|YES)
      echo "[update_backend.sh] Default is no volume wipe; skipping wipe."
      ;;
    *)
      echo "[update_backend.sh] Skipping wipe."
      ;;
  esac
fi

echo "[update_backend.sh] Building + deploying backend only..."
env -i PATH="$PATH" HOME="$HOME" python3 "${SCRIPT_DIR}/scripts/common/build_and_deploy.py" \
  --only-submodules backend \
  --skip-module-root-deploy \
  --skip-generate-scripts

echo "[update_backend.sh] Restarting backend container only..."
if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
  (
    cd "${DEPLOYMENT_ROOT}"
    env -i PATH="$PATH" HOME="$HOME" COMPOSE_PROJECT_NAME="${PROJECT_COMPOSE_PROJECT_NAME}" \
      docker compose --project-directory "$PWD" --project-name "${PROJECT_COMPOSE_PROJECT_NAME}" restart backend
  )
else
  echo "[update_backend.sh] Compose file not found at ${DEPLOYMENT_ROOT_COMPOSE}; cannot restart backend."
  exit 1
fi

echo "[update_backend.sh] Done."
