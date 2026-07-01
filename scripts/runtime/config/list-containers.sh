#!/usr/bin/env bash
# List all running containers for this project.
# Usage: ./scripts/runtime/list-containers.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Lists all running Docker Compose containers for this project,"
    echo "showing container ID, name, image, and version."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Detect context: deployed (script in scripts/) vs source repo (script in scripts/runtime/config/)
# In deployed context: use split .env.config + .env.secrets
# In source context: use project.env.config + project.env.secrets
if [[ -f "$SCRIPT_DIR/../.env.secrets" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$SCRIPT_DIR/../.env.secrets"
  set +a
  set -u
fi
if [[ -f "$SCRIPT_DIR/../.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$SCRIPT_DIR/../.env.config"
  set +a
  set -u
elif [[ -f "$SCRIPT_DIR/../../project.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  if [[ -f "$SCRIPT_DIR/../../project.env.secrets" ]]; then
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/../../project.env.secrets"
  fi
  source "$SCRIPT_DIR/../../project.env.config"
  set +a
  set -u
fi

PROJECT_NAME="${APP_SLUG:-$(basename "$(cd "$SCRIPT_DIR/.." && pwd)")}"

printf "%-14s %-35s %-55s %-25s\n" "CONTAINER ID" "NAME" "IMAGE" "VERSION"
printf "%s\n" "-------------------------------------------------------------------------------------------"

docker ps \
  --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
  --format "{{.ID}}\t{{.Names}}\t{{.Image}}" \
  | while IFS=$'\t' read -r cid name image; do
      if [[ "$image" == *":"* ]]; then
        img_name="${image%:*}"
        version="${image##*:}"
      else
        img_name="$image"
        version="latest"
      fi
      printf "%-14s %-35s %-55s %-25s\n" "$cid" "$name" "$img_name" "$version"
    done
