#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec docker compose \
  --project-directory "$SCRIPT_DIR" \
  --project-name "${COMPOSE_PROJECT_NAME:-$(basename "$SCRIPT_DIR")}" \
  down
