#!/bin/bash
# Wrapper script to execute the Python build and deploy logic

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Auto-load module .env files so Vite build-time variables (VITE_*) and other
# module-scoped env vars are available during docker builds.
set -a
if [[ -d "${SCRIPT_DIR}/modules" ]]; then
  for env_file in "${SCRIPT_DIR}"/modules/*/.env; do
    if [[ -f "${env_file}" ]]; then
      echo "[deploy_all.sh] Loading env: ${env_file}"
      # shellcheck disable=SC1090
      source "${env_file}"
    fi
  done
fi
set +a

DEPLOYMENT_ROOT_COMPOSE="${SCRIPT_DIR}/deployment_root/docker-compose.yml"
if [[ -t 0 ]]; then
  echo
  read -r -p "[deploy_all.sh] Wipe deployment volumes now? (Y/n): " wipe_answer
  case "${wipe_answer}" in
    n|N|no|NO)
      echo "[deploy_all.sh] Skipping wipe."
      ;;
    *)
      if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
        echo "[deploy_all.sh] Wiping deployment volumes..."
        docker compose -f "${DEPLOYMENT_ROOT_COMPOSE}" down -v --remove-orphans
      else
        echo "[deploy_all.sh] Compose file not found at ${DEPLOYMENT_ROOT_COMPOSE}; skipping wipe."
      fi
      ;;
  esac
fi

BUILD_SCRIPT=""
for candidate in \
    "${SCRIPT_DIR}/scripts/common/build_and_deploy.py" \
    "${SCRIPT_DIR}/scripts/module_only/build_and_deploy.py" \
    "${SCRIPT_DIR}/scripts/master_only/build_and_deploy.py"; do
  if [[ -f "$candidate" ]]; then
    BUILD_SCRIPT="$candidate"
    break
  fi
done
if [[ -z "$BUILD_SCRIPT" ]]; then
  echo "[deploy_all.sh] ERROR: build_and_deploy.py not found in scripts/common/, scripts/module_only/, or scripts/master_only/"
  exit 1
fi
python3 "${BUILD_SCRIPT}"

DEPLOYMENT_ROOT="${SCRIPT_DIR}/deployment_root"
if [[ -x "${DEPLOYMENT_ROOT}/stop.sh" && -x "${DEPLOYMENT_ROOT}/start.sh" ]]; then
  (
    cd "${DEPLOYMENT_ROOT}"
    ./stop.sh
    ./start.sh
  )
else
  echo "[deploy_all.sh] Restart scripts not found or not executable in ${DEPLOYMENT_ROOT}."
  echo "[deploy_all.sh] You can restart manually with: (cd deployment_root && ./stop.sh && ./start.sh)"
fi

EXTERNAL_HOST="${EXTERNAL_BASE_HOST:-localhost}"

echo
echo "Endpoint Reference"
echo "------------------"
echo "HostApp"
echo "- https://${EXTERNAL_HOST}/health"
echo "- https://${EXTERNAL_HOST}/api"
echo "- https://${EXTERNAL_HOST}/api/docs"
echo "- https://${EXTERNAL_HOST}/api/openapi.json"

# Print endpoints for each enabled non-HostApp module
for module_json in "${SCRIPT_DIR}"/modules/*/module.json; do
  [[ -f "$module_json" ]] || continue
  mod_name=$(python3 -c "import json,sys; d=json.load(open('${module_json}')); print(d.get('name',''))" 2>/dev/null)
  mod_slug=$(python3 -c "import json,sys; d=json.load(open('${module_json}')); print(d.get('slug',''))" 2>/dev/null)
  [[ -z "$mod_name" || -z "$mod_slug" || "$mod_name" == "HostApp" ]] && continue
  echo
  echo "${mod_name} (slug: ${mod_slug})"
  echo "- https://${EXTERNAL_HOST}/module/${mod_slug}/health"
  echo "- https://${EXTERNAL_HOST}/module/${mod_slug}/api"
  echo "- https://${EXTERNAL_HOST}/module/${mod_slug}/api/docs"
  echo "- https://${EXTERNAL_HOST}/module/${mod_slug}/api/openapi.json"
  echo
  echo "Module Federation (${mod_slug})"
  echo "- https://${EXTERNAL_HOST}/module-registry.json"
  echo "- https://${EXTERNAL_HOST}/remotes/${mod_slug}/mf-manifest.json"
done
