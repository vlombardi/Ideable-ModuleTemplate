#!/usr/bin/env bash
# Show status of all Docker Compose containers for this project.
# Usage: ./status.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Shows the status of all Docker Compose containers for this project (ps)."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

exec docker compose \
  --project-directory "$SCRIPT_DIR" \
  --project-name "${APP_SLUG:-$(basename "$SCRIPT_DIR")}" \
  ps
