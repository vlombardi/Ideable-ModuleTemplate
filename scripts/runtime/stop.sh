#!/usr/bin/env bash
# Stop and remove all Docker Compose containers for this project.
# Usage: ./stop.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Stops and removes all Docker Compose containers for this project (down)."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# THE DEPLOYMENT ROOT, AND WHY IT IS NOT JUST "BESIDE THIS FILE".
# `scripts/runtime/` IS the deployed scripts folder, copied whole — so this file lands at a site
# twice: at the deployment root (the copy a devops runs) and inside `scripts/` beside its siblings.
# Both copies must work, so the root is the directory holding `docker-compose.yml`, looked for
# beside this file and then one level above it. Neither means this is not a deployed tree, which is
# reported rather than guessed at: the source copy under `scripts/runtime/` is not meant to run,
# the project root's wrapper of the same name is.
if [[ -f "$_SELF_DIR/docker-compose.yml" ]]; then
  DEPLOY_ROOT="$_SELF_DIR"
elif [[ -f "$_SELF_DIR/../docker-compose.yml" ]]; then
  DEPLOY_ROOT="$(cd "$_SELF_DIR/.." && pwd)"
else
  echo "ERROR: no docker-compose.yml beside $_SELF_DIR or in its parent, so this is not a deployed" >&2
  echo "       tree. Run the deployment root's copy (deployment_root/$(basename "${BASH_SOURCE[0]}"))," >&2
  echo "       or the project root's wrapper of the same name." >&2
  exit 1
fi

# Source split env files for compose interpolation and project identity.
# Source .env.secrets before .env.config because config files may reference secret variables.
if [[ -f "$DEPLOY_ROOT/.env.secrets" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$DEPLOY_ROOT/.env.secrets"
  set +a
  set -u
fi
if [[ -f "$DEPLOY_ROOT/.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$DEPLOY_ROOT/.env.config"
  set +a
  set -u
fi
PROJECT_NAME="${APP_SLUG:-$(basename "$DEPLOY_ROOT")}"

exec docker compose \
  --project-directory "$DEPLOY_ROOT" \
  --project-name "$PROJECT_NAME" \
  down --remove-orphans
