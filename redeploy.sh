#!/bin/bash
# Wrapper script to execute the Python build and deploy logic

set -euo pipefail

# Track overall execution time
SCRIPT_START_TIME=$(date +%s)

# Parse arguments
FROM_SCRATCH=""
JUST_RESTART=""
FORCE_BOOTSTRAP=""
INTERACTIVE="y"
VERBOSE=""

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
    --force-bootstrap)
      FORCE_BOOTSTRAP="1"
      shift
      ;;
    -v|--verbose)
      VERBOSE="1"
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--from-scratch|--just-restart] [--force-bootstrap] [-v|--verbose]"
      echo ""
      echo "Options:"
      echo "  --from-scratch    Force rebuild all images with no cache and recreate containers"
      echo "                    (implies --force-bootstrap and removes volumes)"
      echo "  --just-restart    Just restart containers (no rebuild)"
      echo "  --force-bootstrap Force Authentik bootstrap to re-run even if the blueprint exists"
      echo "  -v, --verbose     Print all build and deploy details"
      echo "  -h, --help        Show this help message"
      echo "  (no options)      Interactive mode with prompts, concise output"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--from-scratch|--just-restart] [--force-bootstrap] [-v|--verbose]"
      echo "  Run '$0 --help' for details."
      exit 1
      ;;
  esac
done

# Format elapsed seconds as "Xm Ys" or "Ys".
_format_elapsed() {
  local secs="$1"
  local mins=$((secs / 60))
  local rem=$((secs % 60))
  if [[ "$mins" -gt 0 ]]; then
    echo "${mins}m ${rem}s"
  else
    echo "${rem}s"
  fi
}

# Run a command with progress tracking and spinner.
# In non-verbose mode, detects special markers in the command's output:
#   PROGRESS_HEADER:Label  — prints a top-level header (e.g. "Building module HostApp")
#   PROGRESS_SUB:Label     — prints an indented sub-step with spinner (e.g. "    sub-module backend ...")
#   PROGRESS:Label         — prints a standalone step with spinner (no header)
#   PROGRESS_DONE          — marks the current standalone step as done
# The spinner rotates until the next marker arrives or the command finishes.
# Each finished step prints "...done in Xs" (or "Xm Ys").
# In verbose mode: prints the step label and streams all output.
# Usage: run_quiet "Step description" command args...
run_quiet() {
  local step="$1"
  shift
  if [[ "$VERBOSE" == "1" ]]; then
    echo "$step ..."
    "$@"
    return $?
  fi

  local tmpfile
  tmpfile=$(mktemp)

  # Disable set -e inside this function so we can always print the captured
  # error output before the script exits.
  set +e

  # Run command in background, capturing stdout and stderr.
  # Errors are visible only on failure via the captured output block below.
  "$@" >"$tmpfile" 2>&1 &
  local cmd_pid=$!

  local chars='|/-\'
  local i=0
  local lines_shown=0
  local current_label=""
  local current_indent=""
  local has_spinner=""
  local step_start_time=""
  local fallback_start_time
  fallback_start_time=$(date +%s)

  _finish_current() {
    if [[ -n "$has_spinner" && "$has_spinner" != "fallback" ]]; then
      local now
      now=$(date +%s)
      local elapsed=$((now - step_start_time))
      printf "\r%s%s ... done in %s\n" "$current_indent" "$current_label" "$(_format_elapsed "$elapsed")"
      has_spinner=""
    fi
  }

  while kill -0 "$cmd_pid" 2>/dev/null; do
    local total_lines
    total_lines=$(wc -l < "$tmpfile" 2>/dev/null || echo 0)
    if [[ "$total_lines" -gt "$lines_shown" ]]; then
      while IFS= read -r line; do
        if [[ "$line" == PROGRESS_HEADER:* ]]; then
          _finish_current
          current_label="${line#PROGRESS_HEADER:}"
          current_indent=""
          printf "%s\n" "$current_label"
          has_spinner=""
        elif [[ "$line" == PROGRESS_SUB:* ]]; then
          _finish_current
          current_label="${line#PROGRESS_SUB:}"
          current_indent="    "
          has_spinner="1"
          i=0
          step_start_time=$(date +%s)
        elif [[ "$line" == PROGRESS:* ]]; then
          _finish_current
          current_label="${line#PROGRESS:}"
          current_indent=""
          has_spinner="1"
          i=0
          step_start_time=$(date +%s)
        elif [[ "$line" == "PROGRESS_DONE" ]]; then
          _finish_current
        fi
        lines_shown=$((lines_shown + 1))
      done < <(tail -n +$((lines_shown + 1)) "$tmpfile" 2>/dev/null)
    fi
    if [[ -n "$has_spinner" && "$has_spinner" != "fallback" ]]; then
      printf "\r%s%s ... %s" "$current_indent" "$current_label" "${chars:$((i % 4)):1}"
    elif [[ -z "$current_label" ]]; then
      printf "\r%s ... %s" "$step" "${chars:$((i % 4)):1}"
      has_spinner="fallback"
    fi
    i=$((i + 1))
    sleep 0.2
  done

  # Flush any remaining markers
  local total_lines
  total_lines=$(wc -l < "$tmpfile" 2>/dev/null || echo 0)
  if [[ "$total_lines" -gt "$lines_shown" ]]; then
    while IFS= read -r line; do
      if [[ "$line" == PROGRESS_HEADER:* ]]; then
        _finish_current
        current_label="${line#PROGRESS_HEADER:}"
        current_indent=""
        printf "%s\n" "$current_label"
        has_spinner=""
      elif [[ "$line" == PROGRESS_SUB:* ]]; then
        _finish_current
        current_label="${line#PROGRESS_SUB:}"
        current_indent="    "
        has_spinner="1"
        step_start_time=$(date +%s)
      elif [[ "$line" == PROGRESS:* ]]; then
        _finish_current
        current_label="${line#PROGRESS:}"
        current_indent=""
        has_spinner="1"
        step_start_time=$(date +%s)
      elif [[ "$line" == "PROGRESS_DONE" ]]; then
        _finish_current
      fi
      lines_shown=$((lines_shown + 1))
    done < <(tail -n +$((lines_shown + 1)) "$tmpfile" 2>/dev/null)
  fi

  wait "$cmd_pid"
  local exit_code=$?

  if [[ "$exit_code" -ne 0 ]]; then
    if [[ -n "$has_spinner" && "$has_spinner" != "fallback" ]]; then
      printf "\r%s%s ... FAILED\n" "$current_indent" "$current_label" >&2
    elif [[ "$has_spinner" == "fallback" ]]; then
      printf "\r%s ... FAILED\n" "$step" >&2
    fi
    # Ensure we start a fresh line before printing the captured output.
    printf "\n" >&2
    printf "=== ERROR: %s failed (captured output, last 100 lines) ===\n" "$step" >&2
    tail -n 100 "$tmpfile" >&2
    printf "=== end of captured output ===\n" >&2
    rm -f "$tmpfile"
    exit 1
  fi
  _finish_current
  # If no markers were emitted at all, show the fallback done line with timing
  if [[ -z "$current_label" && "$has_spinner" == "fallback" ]]; then
    local now
    now=$(date +%s)
    local elapsed=$((now - fallback_start_time))
    printf "\r%s ... done in %s\n" "$step" "$(_format_elapsed "$elapsed")"
  fi
  rm -f "$tmpfile"
  # Re-enable set -e for the caller (it is inherited by the caller's scope).
  set -e
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="${SCRIPT_DIR}/deployment_root"
DEPLOYMENT_ROOT_COMPOSE="${DEPLOYMENT_ROOT}/docker-compose.yml"
PROJECT_ENV_CONFIG="${SCRIPT_DIR}/project.env.config"
PROJECT_ENV_SECRETS="${SCRIPT_DIR}/project.env.secrets"
if [[ ! -f "${PROJECT_ENV_CONFIG}" ]]; then
  echo "ERROR: project.env.config not found at ${PROJECT_ENV_CONFIG}"
  exit 1
fi

# Load project-wide env first so APP_SLUG / APP_NAME / project paths remain stable for the whole project.
# Source secrets before config because config files may reference secret variables.
if [[ -f "${PROJECT_ENV_SECRETS}" ]]; then
  # shellcheck disable=SC1090
  source "${PROJECT_ENV_SECRETS}"
fi
# shellcheck disable=SC1090
source "${PROJECT_ENV_CONFIG}"

PROJECT_APP_SLUG="${APP_SLUG:-}"
LEGACY_DEPLOYMENT_PROJECT_NAME="$(basename "${DEPLOYMENT_ROOT}")"

# Default values
REBUILD_IMAGES="y"
REMOVE_VOLUMES="n"
START_CONTAINERS="y"

if [[ -n "$FROM_SCRATCH" && -n "$JUST_RESTART" ]]; then
  echo "ERROR: --from-scratch and --just-restart are mutually exclusive."
  exit 1
fi

if [[ "$FROM_SCRATCH" == "1" ]]; then
  REMOVE_VOLUMES="y"
  FORCE_BOOTSTRAP="1"
fi

# Function to cleanup unused resources related to this project
cleanup_project_resources() {
  local _cleanup_start
  _cleanup_start=$(date +%s)
  local _spinner_pid=""
  local project_name

  if [[ "$VERBOSE" != "1" ]]; then
    # Start a spinner so the user sees the task has initiated.
    (
      local chars='|/-\'
      local i=0
      while true; do
        printf "\rCleaning up Docker resources ... %s" "${chars:$((i % 4)):1}"
        i=$((i + 1))
        sleep 0.2
      done
    ) &
    _spinner_pid=$!
    # Ensure the spinner is killed if the function returns early.
    # shellcheck disable=SC2064
    trap "kill ${_spinner_pid} 2>/dev/null || true; wait ${_spinner_pid} 2>/dev/null || true" RETURN
  fi

  for project_name in "${PROJECT_APP_SLUG}" "${LEGACY_DEPLOYMENT_PROJECT_NAME}"; do
    if [[ -z "${project_name}" ]]; then
      continue
    fi
    if [[ "$VERBOSE" == "1" ]]; then
      echo "Cleaning up unused resources for project: ${project_name}..."
      echo "Removing stopped containers for project ${project_name}..."
    fi
    docker container prune -f --filter "label=com.docker.compose.project=${project_name}" >/dev/null 2>&1 || true
    if [[ "$VERBOSE" == "1" ]]; then
      echo "Removing unused networks for project ${project_name}..."
    fi
    docker network prune -f --filter "label=com.docker.compose.project=${project_name}" >/dev/null 2>&1 || true
  done

  docker image prune -f >/dev/null 2>&1 || true
  docker builder prune -f >/dev/null 2>&1 || true

  if [[ -n "$_spinner_pid" ]]; then
    kill "$_spinner_pid" 2>/dev/null || true
    wait "$_spinner_pid" 2>/dev/null || true
  fi

  if [[ "$VERBOSE" == "1" && "$REBUILD_IMAGES" == "y" ]]; then
    echo "Old project images are removed through dangling-image cleanup; no additional image sweep needed."
  elif [[ "$VERBOSE" != "1" ]]; then
    local _elapsed
    _elapsed=$(( $(date +%s) - _cleanup_start ))
    printf "\rCleaning up Docker resources ... done in %s\n" "$(_format_elapsed "$_elapsed")"
  fi
}

remove_deployment_volumes() {
  if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
    for project_name in "${PROJECT_APP_SLUG}" "${LEGACY_DEPLOYMENT_PROJECT_NAME}"; do
      if [[ -z "${project_name}" ]]; then
        continue
      fi
      if [[ "$VERBOSE" == "1" ]]; then
        echo "Removing deployment volumes for project ${project_name}..."
      fi
      (
        cd "${DEPLOYMENT_ROOT}"
        if [[ "$VERBOSE" == "1" ]]; then
          docker compose --project-directory "$PWD" --project-name "${project_name}" -f docker-compose.yml down -v --remove-orphans
        else
          docker compose --project-directory "$PWD" --project-name "${project_name}" -f docker-compose.yml down -v --remove-orphans >/dev/null 2>&1
        fi
      )
    done
  elif [[ "$VERBOSE" == "1" ]]; then
    echo "Compose file not found at ${DEPLOYMENT_ROOT_COMPOSE}; skipping volume removal."
  fi
  # Also clear bind-mounted blueprint files so bootstrap re-runs on fresh DB.
  local blueprints_dir="${DEPLOYMENT_ROOT}/modules/HostApp/authentik/blueprints"
  if [[ -d "${blueprints_dir}" ]]; then
    rm -f "${blueprints_dir}"/*
  fi
}

start_deployment_stack() {
  if [[ -x "${DEPLOYMENT_ROOT}/start.sh" ]]; then
    (
      cd "${DEPLOYMENT_ROOT}"
      if [[ -x "./stop.sh" ]]; then
        if [[ "$VERBOSE" == "1" ]]; then
          ./stop.sh 2>/dev/null || true
        else
          ./stop.sh >/dev/null 2>&1 || true
        fi
      fi
      ./start.sh
    )
    return
  fi

  if [[ -f "${DEPLOYMENT_ROOT_COMPOSE}" ]]; then
    echo "start.sh not found; starting from merged docker-compose.yml instead..."
    (
      cd "${DEPLOYMENT_ROOT}"
      docker compose --project-directory "$PWD" --project-name "${PROJECT_APP_SLUG}" -f docker-compose.yml down --remove-orphans 2>/dev/null || true
      docker compose --project-directory "$PWD" --project-name "${PROJECT_APP_SLUG}" -f docker-compose.yml up -d --remove-orphans
    )
    return
  fi

  echo "ERROR: Neither ${DEPLOYMENT_ROOT}/start.sh nor ${DEPLOYMENT_ROOT_COMPOSE} exists."
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

# Auto-load module .env.secrets + .env.config files so Vite build-time variables (VITE_*) and other
# module-scoped env vars are available during docker builds.
# Source .env.secrets first because .env.config files may reference secret variables.
set -a
if [[ -d "${SCRIPT_DIR}/modules" ]]; then
  for env_file in "${SCRIPT_DIR}"/modules/*/.env.secrets "${SCRIPT_DIR}"/modules/*/.env.config; do
    if [[ -f "${env_file}" ]]; then
      if [[ "$VERBOSE" == "1" ]]; then
        echo "Loading env: ${env_file}"
      fi
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
  echo "ERROR: build_and_deploy.py not found in scripts/common/, scripts/module_only/, or scripts/master_only/"
  exit 1
fi
# Validate enabled modules before building/deploying.
VALIDATE_SCRIPT="${SCRIPT_DIR}/scripts/common/validate_modules.sh"
if [[ -x "${VALIDATE_SCRIPT}" ]]; then
  run_quiet "Validating modules" "${VALIDATE_SCRIPT}"
elif [[ "$VERBOSE" == "1" ]]; then
  echo "WARNING: validate_modules.sh not found at ${VALIDATE_SCRIPT}; skipping validation."
fi

# Clean up old images before building so we don't accumulate unused layers
if [[ "$REBUILD_IMAGES" == "y" ]]; then
  cleanup_project_resources
fi

# Build images if requested
if [[ "$REBUILD_IMAGES" == "y" ]]; then
  run_quiet "Building and deploying" env -i PATH="$PATH" HOME="$HOME" AUTHORIZATION_PLAN_FORCE_REBUILD=1 PYTHONUNBUFFERED=1 python3 -u "${BUILD_SCRIPT}"
fi

# Force bootstrap regeneration if requested (same procedure on dev and deploy)
if [[ "$FORCE_BOOTSTRAP" == "1" ]]; then
  if [[ -x "${DEPLOYMENT_ROOT}/scripts/generate_authentik_blueprint_from_authorization_files.sh" ]]; then
    run_quiet "Regenerating Authentik bootstrap" "${DEPLOYMENT_ROOT}/scripts/generate_authentik_blueprint_from_authorization_files.sh"
  elif [[ "$VERBOSE" == "1" ]]; then
    echo "WARNING: generate_authentik_blueprint_from_authorization_files.sh not found in ${DEPLOYMENT_ROOT}/scripts. Skipping forced bootstrap."
  fi
fi

# Regenerate merged .env.config, .env.secrets and docker-compose.yml from per-module deployed files
MERGE_SCRIPT="${DEPLOYMENT_ROOT}/scripts/create-merged-configuration.sh"
if [[ -x "${MERGE_SCRIPT}" ]]; then
  run_quiet "Regenerating merged configuration" "${MERGE_SCRIPT}"
elif [[ "$VERBOSE" == "1" ]]; then
  echo "WARNING: create-merged-configuration.sh not found at ${MERGE_SCRIPT}; merged config regeneration skipped."
fi

if [[ "${START_CONTAINERS}" == "y" ]]; then
  if [[ "$FORCE_BOOTSTRAP" == "1" ]]; then
    export FORCE_BOOTSTRAP=1
  fi
  start_deployment_stack
else
  echo "Containers not started (as requested). To start manually: ./start.sh"
fi

# Print overall execution time
SCRIPT_END_TIME=$(date +%s)
ELAPSED=$((SCRIPT_END_TIME - SCRIPT_START_TIME))
echo "----------------------------------------------"
echo "Total execution time: $(_format_elapsed "$ELAPSED")"
echo "----------------------------------------------"
echo
