#!/usr/bin/env bash
# Authorization operations at a deployed site — no redeploy, no rebuild.
#
# At production the deployables come from the registry as-is and a devops has only the runtime
# scripts, so everything that changes authorization has to be reachable from here. This wraps the
# backend's own CLI (`python -m app.authz_migrate`) and the directory reconciliation.
#
# Usage:
#   ./authz.sh seed [--module NAME]... [--force] [--dry-run]
#       Apply each enabled module's authorization contract. A module already seeded at its current
#       contract version is skipped, so this is safe to re-run: it never reverts a change an
#       operator made through the UI. --force re-applies anyway.
#
#   ./authz.sh sync [--dry-run]
#       Reconcile against the directory: create users that appeared upstream, reapply the profiles
#       their directory groups map to, and deactivate users that are gone. Refuses to act if the
#       directory returns no users at all.
#
#   ./authz.sh reconcile [--dry-run]
#       Deprovisioning only — strip authorization from users that no longer exist upstream.
#
#   ./authz.sh test-users --provision | --purge [--dry-run]
#       Create or remove the e2e personas from config/test-users.yaml. The test runner does both
#       automatically; this is for cleaning up by hand after an interrupted run. --purge also
#       removes the per-run identities the suites mint (e2e-tenant-*, e2e-priv-*), which otherwise
#       accumulate and show up in an access review next to real accounts.
#
# What each run did is recorded in Admin -> System messages, not only in this terminal.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() { sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

[[ $# -ge 1 ]] || usage 1
case "${1:-}" in -h|--help) usage 0 ;; esac

COMMAND="$1"; shift

# The horizontal-scale work removed container_name, so the backend is located by its image label rather than by name.
BACKEND_CONTAINER="$(docker ps --filter "label=com.docker.compose.service=backend" \
                                --filter "status=running" --format '{{.ID}}' | head -1)"
if [[ -z "$BACKEND_CONTAINER" ]]; then
    BACKEND_CONTAINER="$(docker ps --format '{{.ID}} {{.Image}}' \
                          | awk '/hostapp[._-]backend/ {print $1; exit}')"
fi
if [[ -z "$BACKEND_CONTAINER" ]]; then
    echo "✗ host_app backend container is not running — start the system first (./start.sh)" >&2
    exit 1
fi

case "$COMMAND" in
    seed)
        docker exec "$BACKEND_CONTAINER" python -m app.authz_migrate --seed "$@"
        ;;
    reconcile)
        docker exec "$BACKEND_CONTAINER" python -m app.authz_migrate --reconcile "$@"
        ;;
    test-users)
        docker exec \
            -e E2E_TEST_USERS_ENABLED="${E2E_TEST_USERS_ENABLED:-true}" \
            -e E2E_TEST_PASSWORD="${E2E_TEST_PASSWORD:-}" \
            "$BACKEND_CONTAINER" python -m app.test_users "$@"
        ;;
    sync)
        DRY_RUN="False"
        for arg in "$@"; do [[ "$arg" == "--dry-run" ]] && DRY_RUN="True"; done
        docker exec "$BACKEND_CONTAINER" python -c "
import json
from app.database import SessionLocal
from app.services.authentik import get_authentik_service
from app.services.provisioning import reconcile_directory

db = SessionLocal()
try:
    report = reconcile_directory(db, get_authentik_service(), dry_run=${DRY_RUN})
finally:
    db.close()
print(json.dumps(report, indent=2))
raise SystemExit(1 if report.get('error') else 0)
"
        ;;
    *)
        echo "✗ unknown command: $COMMAND" >&2
        usage 1
        ;;
esac
