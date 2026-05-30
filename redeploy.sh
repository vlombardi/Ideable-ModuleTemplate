#!/bin/bash
# Wrapper script to execute the Python build and deploy logic

set -euo pipefail

# Parse arguments
FROM_SCRATCH=""
JUST_RESTART=""
INTERACTIVE="y"

while [[ $# -gt 0 ]]; do
  case $1 in
    --from-scratch)
      FROM_SCRATCH="1"
      INTERACTIVE="n"
      shift
      ;;
    --just-restart)
      JUST_RESTART="1"
      INTERACTIVE="n"
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--from-scratch|--just-restart]"
      echo "  --from-scratch   Force rebuild all images with no cache and recreate containers"
      echo "  --just-restart   Just restart containers (no rebuild)"
      echo "  (no options)     Interactive mode with prompts"
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="${SCRIPT_DIR}/deployment_root"
DEPLOYMENT_ROOT_COMPOSE="${DEPLOYMENT_ROOT}/docker-compose.yml"
PROJECT_ENV_FILE="${SCRIPT_DIR}/project.env"
if [[ ! -f "${PROJECT_ENV_FILE}" ]]; then
  echo "[redeploy.sh] ERROR: project.env not found at ${PROJECT_ENV_FILE}"
  exit 1
fi

# Load project-wide env first so APP_SLUG / APP_NAME / project paths remain stable for the whole project.
# shellcheck disable=SC1090
source "${PROJECT_ENV_FILE}"

PROJECT_APP_SLUG="${APP_SLUG:-}"
PROJECT_COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-${PROJECT_APP_SLUG}}"

# Default values
REBUILD_IMAGES="y"
REMOVE_VOLUMES="n"
START_CONTAINERS="y"

if [[ -n "$FROM_SCRATCH" && -n "$JUST_RESTART" ]]; then
  echo "[redeploy.sh] ERROR: --from-scratch and --just-restart are mutually exclusive."
  exit 1
fi

if [[ "$FROM_SCRATCH" == "1" ]]; then
  REMOVE_VOLUMES="y"
fi

# Function to cleanup unused resources related to this project
cleanup_project_resources() {
  echo "[redeploy.sh] Cleaning up unused resources for project: ${PROJECT_COMPOSE_PROJECT_NAME}..."

  # Remove stopped containers from this project
  echo "[redeploy.sh] Removing stopped containers for project ${PROJECT_COMPOSE_PROJECT_NAME}..."
  docker container prune -f --filter "label=com.docker.compose.project=${PROJECT_COMPOSE_PROJECT_NAME}"

  # Remove unused networks from this project
  echo "[redeploy.sh] Removing unused networks for project ${PROJECT_COMPOSE_PROJECT_NAME}..."
  docker network prune -f --filter "label=com.docker.compose.project=${PROJECT_COMPOSE_PROJECT_NAME}"

  # Remove dangling images (not specific to project, but safe to remove)
  echo "[redeploy.sh] Removing dangling images..."
  docker image prune -f

  # If rebuilding images, also remove old images of this project
  if [[ "$REBUILD_IMAGES" == "y" ]]; then
    echo "[redeploy.sh] Removing old images for project ${PROJECT_COMPOSE_PROJECT_NAME}..."
    # Find and remove images related to this project (those containing the project name)
    local project_images
    project_images=$(docker images --format "{{.Repository}}:{{.Tag}}\t{{.ID}}" | grep -i "${PROJECT_COMPOSE_PROJECT_NAME}" | awk '{print $2}' | uniq) || true
    if [[ -n "$project_images" ]]; then
      echo "[redeploy.sh] Removing old project images: $project_images"
      echo "$project_images" | xargs -r docker rmi -f || true
    fi
  fi
}

remove_deployment_volumes() {
  if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
    echo "[redeploy.sh] Removing deployment volumes for project ${PROJECT_COMPOSE_PROJECT_NAME}..."
    (
      cd "${DEPLOYMENT_ROOT}"
      docker compose --project-directory "$PWD" --project-name "${PROJECT_COMPOSE_PROJECT_NAME}" -f docker-compose.yml down -v --remove-orphans
    )
  else
    echo "[redeploy.sh] Compose file not found at ${DEPLOYMENT_ROOT_COMPOSE}; skipping volume removal."
  fi
}

start_deployment_stack() {
  if [[ -x "${DEPLOYMENT_ROOT}/start.sh" ]]; then
    (
      cd "${DEPLOYMENT_ROOT}"
      if [[ -x "./stop.sh" ]]; then
        ./stop.sh 2>/dev/null || true
      fi
      ./start.sh
    )
    return
  fi

  if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
    echo "[redeploy.sh] start.sh not found; starting from merged docker-compose.yml instead..."
    (
      cd "${DEPLOYMENT_ROOT}"
      docker compose --project-directory "$PWD" --project-name "${PROJECT_COMPOSE_PROJECT_NAME}" -f docker-compose.yml down --remove-orphans 2>/dev/null || true
      docker compose --project-directory "$PWD" --project-name "${PROJECT_COMPOSE_PROJECT_NAME}" -f docker-compose.yml up -d --remove-orphans
    )
    return
  fi

  echo "[redeploy.sh] ERROR: Neither ${DEPLOYMENT_ROOT}/start.sh nor ${DEPLOYMENT_ROOT_COMPOSE} exists."
  exit 1
}

# Interactive mode: ask all questions at once
if [[ "$INTERACTIVE" == "y" && -t 0 ]]; then
  echo
  echo "=============================================="
  echo "    Deployment Options"
  echo "=============================================="
  echo
  
  # Question 1: Rebuild images
  echo -n "Do you want to rebuild images and recreate containers? (Y/n): "
  read -r answer1
  answer1_lower=$(echo "$answer1" | tr '[:upper:]' '[:lower:]')
  case "$answer1_lower" in
    n|no) REBUILD_IMAGES="n" ;;
    *)    REBUILD_IMAGES="y" ;;
  esac
  
  # Question 2: Remove volumes
  echo -n "Do you want to remove volumes? (y/N): "
  read -r answer2
  answer2_lower=$(echo "$answer2" | tr '[:upper:]' '[:lower:]')
  case "$answer2_lower" in
    y|yes) REMOVE_VOLUMES="y" ;;
    *)     REMOVE_VOLUMES="n" ;;
  esac
  
  # Question 3: Start containers
  echo -n "Do you want to start containers? (Y/n): "
  read -r answer3
  answer3_lower=$(echo "$answer3" | tr '[:upper:]' '[:lower:]')
  case "$answer3_lower" in
    n|no) START_CONTAINERS="n" ;;
    *)    START_CONTAINERS="y" ;;
  esac
  
  echo
  echo "=============================================="
  echo "  Rebuild images: $REBUILD_IMAGES"
  echo "  Remove volumes: $REMOVE_VOLUMES"
  echo "  Start containers: $START_CONTAINERS"
  echo "=============================================="
  echo
fi

if [[ "$REMOVE_VOLUMES" == "y" ]]; then
  remove_deployment_volumes
fi

# Handle --just-restart mode
if [[ "$JUST_RESTART" == "1" ]]; then
  REBUILD_IMAGES="n"
  START_CONTAINERS="y"
fi

# Auto-load module .env files so Vite build-time variables (VITE_*) and other
# module-scoped env vars are available during docker builds.
set -a
if [[ -d "${SCRIPT_DIR}/modules" ]]; then
  for env_file in "${SCRIPT_DIR}"/modules/*/.env; do
    if [[ -f "${env_file}" ]]; then
      echo "[redeploy.sh] Loading env: ${env_file}"
      # shellcheck disable=SC1090
      source "${env_file}"
    fi
  done
fi
set +a

BUILD_SCRIPT=""
for candidate in \
    "${SCRIPT_DIR}/scripts/common/build_and_deploy.py" \
    "${SCRIPT_DIR}/scripts/module_only/build_and_deploy.py" \
    "${SCRIPT_DIR}/scripts/master_only/build_and_deploy.py"; do
  if [[ -f "$candidate" ]]; then
    BUILD_SCRIPT="$candidate"
    break
  fi
done
if [[ -z "$BUILD_SCRIPT" ]]; then
  echo "[redeploy.sh] ERROR: build_and_deploy.py not found in scripts/common/, scripts/module_only/, or scripts/master_only/"
  exit 1
fi
# Clean up old images before building so we don't accumulate unused layers
if [[ "$REBUILD_IMAGES" == "y" ]]; then
  cleanup_project_resources
fi

# Build images if requested
if [[ "$REBUILD_IMAGES" == "y" ]]; then
  AUTHORIZATION_PLAN_FORCE_REBUILD=1 python3 "${BUILD_SCRIPT}"
fi

if [[ "${START_CONTAINERS}" == "y" ]]; then
  start_deployment_stack
else
  echo "[redeploy.sh] Containers not started (as requested). To start manually: (cd deployment_root && ./start.sh)"
fi
