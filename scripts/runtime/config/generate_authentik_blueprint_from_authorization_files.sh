#!/usr/bin/env bash
# Regenerate Authentik blueprint from authorization files and re-apply bootstrap.
# Usage: ./scripts/runtime/generate_authentik_blueprint_from_authorization_files.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Regenerates the Authentik blueprint from authorization files and re-applies"
    echo "the Authentik bootstrap via docker compose."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source secrets before config because config files may reference secret variables.
if [[ -f "${DEPLOYMENT_ROOT}/.env.secrets" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "${DEPLOYMENT_ROOT}/.env.secrets"
  set +a
  set -u
fi
if [[ -f "${DEPLOYMENT_ROOT}/.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "${DEPLOYMENT_ROOT}/.env.config"
  set +a
  set -u
fi

if [[ -z "${APP_SLUG:-}" ]]; then
  echo "ERROR: APP_SLUG is not set. Ensure deployment_root/.env.config is present." >&2
  exit 1
fi

echo "[blueprint] Regenerating blueprint and re-applying Authentik bootstrap..."

cd "$DEPLOYMENT_ROOT"
docker compose run --rm -e FORCE_BOOTSTRAP=1 authentik-bootstrap

echo "[blueprint] Done."
echo "  Blueprint: ${DEPLOYMENT_ROOT}/modules/HostApp/authentik/blueprints/authz-plan.generated.yaml"
echo "  Log:       ${DEPLOYMENT_ROOT}/modules/HostApp/authentik/blueprints/blueprint_generation.log"
