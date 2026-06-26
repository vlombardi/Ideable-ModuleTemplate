#!/bin/sh
set -e

SCRIPT_DIR=/bootstrap/scripts

if [ -f /bootstrap/assets/blueprints/authz-plan.generated.yaml ] && [ -z "${FORCE_BOOTSTRAP:-}" ]; then
    echo "[authentik-bootstrap] Already initialized (blueprint exists). Use FORCE_BOOTSTRAP=1 to re-run."
    exit 0
fi

echo "[authentik-bootstrap] Generating authorization blueprint..."
python "${SCRIPT_DIR}/generate_authentik_blueprint.py" \
    --hostapp-auth-yaml /bootstrap/config/authorization.yaml \
    --modules-root /modules \
    --output-blueprint /bootstrap/assets/blueprints/authz-plan.generated.yaml \
    --log-path /bootstrap/assets/blueprints/blueprint_generation.log

echo "[authentik-bootstrap] Running Authentik bootstrap..."
python "${SCRIPT_DIR}/bootstrap_authentik.py"
