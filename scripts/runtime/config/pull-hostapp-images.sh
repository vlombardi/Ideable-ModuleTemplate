#!/usr/bin/env bash
# Check and pull host_app images referenced in modules/host_app/docker-compose.yml.
# Compares local image digests against the remote registry so only outdated or
# missing images are pulled. Useful after publishing a new version to a registry
# so the next deployment/root compose run uses the fresh layers.
#
# Usage:
#   ./scripts/runtime/config/pull-hostapp-images.sh [TAG]
#   ./scripts/runtime/config/pull-hostapp-images.sh --registry ghcr.io/org [TAG]
#
# Options:
#   [TAG]         Image tag to pull (defaults to "latest")
#   --registry    Override MODULE_DOCKER_REGISTRY_PREFIX from .env.config
#   -h|--help     Show this help

set -euo pipefail

show_help() {
  cat <<'EOF'
Usage: pull-hostapp-images.sh [options] [TAG]

Options:
  --registry <value>  Override registry prefix (default: value from modules/host_app/.env.config)
  --tag <value>       Explicit tag to pull (alternative to positional TAG)
  -h, --help          Show this help message

Arguments:
  TAG                 Image tag to pull; defaults to "latest" when omitted
EOF
}

TAG="latest"
REGISTRY_OVERRIDE=""
POSITIONAL_TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    --registry)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --registry requires a value" >&2
        exit 1
      fi
      REGISTRY_OVERRIDE="$2"
      shift 2
      ;;
    --tag)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --tag requires a value" >&2
        exit 1
      fi
      TAG="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "ERROR: Unknown option $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$POSITIONAL_TAG" ]]; then
        POSITIONAL_TAG="$1"
      else
        echo "ERROR: Multiple positional arguments provided: '$POSITIONAL_TAG' and '$1'" >&2
        exit 1
      fi
      shift
      ;;
  esac
  done

if [[ -n "$POSITIONAL_TAG" ]]; then
  TAG="$POSITIONAL_TAG"
fi

if [[ -z "$TAG" ]]; then
  TAG="latest"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker command not found. Install Docker or ensure it is on PATH." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT=""
CURRENT_DIR="$SCRIPT_DIR"
for _ in $(seq 1 6); do
  if [[ -d "$CURRENT_DIR/modules/host_app" ]]; then
    PROJECT_ROOT="$CURRENT_DIR"
    break
  fi
  CURRENT_DIR="$(cd "$CURRENT_DIR/.." && pwd)"
  done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "ERROR: Could not locate modules/host_app relative to $SCRIPT_DIR" >&2
  exit 1
fi

ENV_FILE="$PROJECT_ROOT/modules/host_app/.env.config"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi

trim_value() {
  local value="$1"
  value="${value%\r}"
  value="${value%\n}"
  value="${value%\"}"
  value="${value#\"}"
  echo "$value"
}

MODULE_SLUG=$(grep -E '^MODULE_SLUG=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- || true)
MODULE_SLUG=$(trim_value "${MODULE_SLUG:-}")
if [[ -z "$MODULE_SLUG" ]]; then
  echo "ERROR: MODULE_SLUG not found in $ENV_FILE" >&2
  exit 1
fi

REGISTRY_PREFIX="$REGISTRY_OVERRIDE"
if [[ -z "$REGISTRY_PREFIX" ]]; then
  REGISTRY_PREFIX=$(grep -E '^MODULE_DOCKER_REGISTRY_PREFIX=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2- || true)
  REGISTRY_PREFIX=$(trim_value "${REGISTRY_PREFIX:-}")
fi

COMPONENTS=(database backend frontend authentik-bootstrap traefik)
REGISTRY_SEGMENT=""
if [[ -n "$REGISTRY_PREFIX" ]]; then
  REGISTRY_SEGMENT="$REGISTRY_PREFIX/"
fi

IMAGES=()
for component in "${COMPONENTS[@]}"; do
  IMAGES+=("${REGISTRY_SEGMENT}${MODULE_SLUG}.${component}:${TAG}")
  done

get_local_digest() {
  local image="$1"
  docker inspect --format='{{index .RepoDigests 0}}' "$image" 2>/dev/null | sed 's/.*@//'
}

get_remote_digest() {
  local image="$1"
  docker manifest inspect "$image" 2>/dev/null | sed -n 's/.*"digest": "\([^"]*\)".*/\1/p' | head -1
}

PULLED=0
UP_TO_DATE=0
FAILED=0

printf 'Checking host_app images with tag "%s"...\n\n' "$TAG"
for image in "${IMAGES[@]}"; do
  local_digest=$(get_local_digest "$image")
  if [[ -z "$local_digest" ]]; then
    echo "  [missing]  $image — not present locally, pulling..."
    if docker pull "$image" >/dev/null 2>&1; then
      echo "  [pulled]   $image"
      PULLED=$((PULLED + 1))
    else
      echo "  [failed]   $image — pull failed"
      FAILED=$((FAILED + 1))
    fi
    echo ""
    continue
  fi

  remote_digest=$(get_remote_digest "$image")
  if [[ -z "$remote_digest" ]]; then
    echo "  [warning]  $image — could not inspect remote manifest; pulling to be safe..."
    if docker pull "$image" >/dev/null 2>&1; then
      echo "  [pulled]   $image"
      PULLED=$((PULLED + 1))
    else
      echo "  [failed]   $image — pull failed"
      FAILED=$((FAILED + 1))
    fi
    echo ""
    continue
  fi

  if [[ "$local_digest" == "$remote_digest" ]]; then
    echo "  [up-to-date] $image"
    echo "    local:  ${local_digest:0:19}..."
    echo "    remote: ${remote_digest:0:19}..."
    UP_TO_DATE=$((UP_TO_DATE + 1))
  else
    echo "  [outdated] $image — digests differ, pulling..."
    echo "    local:  ${local_digest:0:19}..."
    echo "    remote: ${remote_digest:0:19}..."
    if docker pull "$image" >/dev/null 2>&1; then
      echo "  [pulled]   $image"
      PULLED=$((PULLED + 1))
    else
      echo "  [failed]   $image — pull failed"
      FAILED=$((FAILED + 1))
    fi
  fi
  echo ""
done

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "  Up to date: $UP_TO_DATE"
echo "  Pulled:     $PULLED"
echo "  Failed:     $FAILED"
echo "  Total:      ${#IMAGES[@]}"
