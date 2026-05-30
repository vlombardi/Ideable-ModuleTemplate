#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="${SCRIPT_DIR}"
HOSTAPP_AUTH_YAML="${DEPLOYMENT_ROOT}/modules/HostApp/config/authorization.yaml"
MODULES_ROOT="${DEPLOYMENT_ROOT}/modules"
BLUEPRINT_OUTPUT="${DEPLOYMENT_ROOT}/modules/HostApp/authentik/blueprints/authz-plan.generated.yaml"
LOG_OUTPUT="${DEPLOYMENT_ROOT}/logs/blueprint_generation.log"
GENERATOR="${DEPLOYMENT_ROOT}/modules/HostApp/authentik/generate_authentik_blueprint.py"

if [[ -f "${DEPLOYMENT_ROOT}/.env" ]]; then
  # Export merged deployment variables so Python imports that read APP_SLUG at
  # module-import time see the project identity configured during deployment.
  set -a
  # shellcheck disable=SC1090
  source "${DEPLOYMENT_ROOT}/.env"
  set +a
fi

if [[ ! -f "$GENERATOR" ]]; then
  echo "ERROR: generator not found: $GENERATOR" >&2
  exit 1
fi

resolve_python() {
  local candidate
  for candidate in "${DEPLOYMENT_ROOT}/../.venv/bin/python" "$(command -v python3 || true)" "$(command -v python || true)"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if "$candidate" - <<'PY' >/dev/null 2>&1
import yaml
PY
    then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(resolve_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: no Python interpreter with PyYAML found. Install PyYAML in .venv or make it available on PATH." >&2
  exit 1
fi

mkdir -p "${DEPLOYMENT_ROOT}/logs"
mkdir -p "$(dirname "$BLUEPRINT_OUTPUT")"

"$PYTHON_BIN" "$GENERATOR" \
  --hostapp-auth-yaml "$HOSTAPP_AUTH_YAML" \
  --modules-root "$MODULES_ROOT" \
  --output-blueprint "$BLUEPRINT_OUTPUT" \
  --log-path "$LOG_OUTPUT"
