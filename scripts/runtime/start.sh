#!/usr/bin/env bash
# Start all Docker Compose containers for this project.
# Usage: ./start.sh [-h|--help]
set -euo pipefail

START_EPOCH="$(date +%s)"
START_TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

print_startup_duration() {
    local exit_code=$?
    local end_epoch
    local end_timestamp
    local elapsed
    local hours
    local minutes
    local seconds

    end_epoch="$(date +%s)"
    end_timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    elapsed=$((end_epoch - START_EPOCH))
    hours=$((elapsed / 3600))
    minutes=$(((elapsed % 3600) / 60))
    seconds=$((elapsed % 60))

    echo ""
    echo "=== Startup timing ==="
    echo "  Started:  ${START_TIMESTAMP}"
    echo "  Finished: ${end_timestamp}"
    printf '  Duration: %02dh %02dm %02ds\n' "$hours" "$minutes" "$seconds"

    return "$exit_code"
}

trap print_startup_duration EXIT

REPULL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            echo "Usage: $0 [-h|--help] [--repull]"
            echo ""
            echo "Starts all Docker Compose containers for this project (up -d)."
            echo ""
            echo "Options:"
            echo "  -h, --help   Show this help message"
            echo "  --repull     Force-pull all images before starting (uses --pull always)"
            exit 0
            ;;
        --repull)
            REPULL=1
            shift
            ;;
        *)
            echo "Error: unknown option $1" >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Require .env.secrets before trying to start containers.
# The .env.secrets file is host-specific and must not be committed to the deployable repo.
if [[ ! -f "$SCRIPT_DIR/.env.secrets" ]]; then
    echo "ERROR: $SCRIPT_DIR/.env.secrets is missing."
    echo ""
    echo "To create it from the example template and set real secret values, run:"
    echo ""
    echo "  cp $SCRIPT_DIR/.env.secrets.example $SCRIPT_DIR/.env.secrets"
    echo "  ./scripts/change_secrets.sh"
    echo ""
    exit 1
fi

# Source split env files for compose interpolation and project identity.
# Source .env.secrets before .env.config because config files may reference secret variables.
if [[ -f "$SCRIPT_DIR/.env.secrets" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$SCRIPT_DIR/.env.secrets"
  set +a
  set -u
fi
if [[ -f "$SCRIPT_DIR/.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$SCRIPT_DIR/.env.config"
  set +a
  set -u
fi
PROJECT_NAME="${APP_SLUG:-$(basename "$SCRIPT_DIR")}"

set +e
PULL_POLICY="missing"
if [[ "$REPULL" -eq 1 ]]; then
    PULL_POLICY="always"
    echo "[start.sh] --repull: forcing image pull"
fi

docker compose \
  --project-directory "$SCRIPT_DIR" \
  --project-name "$PROJECT_NAME" \
  up -d --remove-orphans --pull "$PULL_POLICY"
UP_EXIT=$?
set -e

if [[ $UP_EXIT -ne 0 ]]; then
  BACKEND_CONTAINER="${APP_SLUG}.hostapp.backend"
  BOOTSTRAP_CONTAINER="${APP_SLUG}.hostapp.authentik-bootstrap"

  if docker ps -a --format '{{.Names}}' | grep -qx "$BACKEND_CONTAINER" && \
     docker ps -a --format '{{.Names}}' | grep -qx "$BOOTSTRAP_CONTAINER"; then
    if docker logs "$BACKEND_CONTAINER" 2>&1 | grep -q "Token invalid/expired" && \
       docker logs "$BOOTSTRAP_CONTAINER" 2>&1 | grep -q "Already initialized (blueprint exists)"; then
      echo ""
      echo "Detected stale Authentik bootstrap state."
      echo "The generated blueprint file exists from a previous deployment, but the database"
      echo "has been reset (or the token no longer matches), so the bootstrap container is"
      echo "skipping the token seeding step."
      echo ""
      echo "To fix, remove the stale blueprint and restart:"
      echo ""
      echo "  rm -f ${SCRIPT_DIR}/modules/host_app/authentik/blueprints/authz-plan.generated.yaml"
      echo "  ./stop.sh && ./start.sh"
      echo ""
    fi
  fi
  exit $UP_EXIT
fi
