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
  # There used to be ad-hoc recovery advice here: it grepped the backend logs for
  # "Token invalid/expired" and the bootstrap logs for "Already initialized (blueprint exists)", then
  # told the operator to delete a stale blueprint by hand.
  #
  # It was DEAD CODE — and worse, it was cited as evidence that the startup chain is fragile. Neither
  # string is emitted by anything in this repository:
  #
  #  - the 403-on-a-fresh-volume cause it was written for is fixed at the source. The bootstrap polls
  #    `core/tokens/` until the token Authentik creates from AUTHENTIK_BOOTSTRAP_TOKEN is actually
  #    accepted (60 attempts, 5s apart) and fails with the last validation error if it never is — see
  #    authentik/SPECS/general_bug_avoider.md § "Bootstrap token 403 on fresh volume wipe".
  #  - "Already initialized (blueprint exists)" is emitted by no code at all, so the second half of
  #    the condition could never be true even when the first was.
  #
  # A conditional that cannot fire is not a safety net; it is a claim that the system needs one.
  # Deleted rather than "absorbed into the bootstrap" because there is nothing to absorb:
  # the bootstrap already retries what transiently fails, and a module backend no longer waits on it
  # at all, so a bootstrap failure degrades the identity plane instead of blocking startup.
  echo ""
  echo "[start.sh] 'docker compose up' exited non-zero. Check the one-shot jobs first:"
  echo "  docker compose --project-name ${PROJECT_NAME} ps -a"
  echo "  docker logs ${APP_SLUG}.hostapp.authentik-bootstrap"
  echo "  docker logs ${APP_SLUG}.hostapp.migrations"
  echo ""
  echo "A failing identity bootstrap no longer stops the module backends: they start and report"
  echo "'identity_sync' on /ready, retrying on their own. See docs/RUNBOOK.md § Identity plane."
  echo ""
fi

# Propagate the failure. Two different questions are being answered here and they must not share an
# answer:
#
#   "is the system serving?"  -- possibly yes. The identity-plane split decoupled the module backends from the
#                                identity plane on purpose, so they start and retry regardless.
#   "did the deploy succeed?" -- no. A one-shot job failed, and whoever ran this needs to know.
#
# Returning 0 answered the second question with the first one's answer. The consequence was not
# hypothetical: with the identity bootstrap dead on a NameError, `redeploy.sh` reported success and
# the dev-cycle router advanced straight to Testing, exactly as it would have on a real deploy.
exit "$UP_EXIT"
