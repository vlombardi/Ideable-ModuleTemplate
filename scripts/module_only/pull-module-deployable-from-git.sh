#!/bin/bash
# Pull a module deployable bundle from a git remote into the current
# deployment_root folder.
#
# Usage:
#   ./scripts/module_only/pull-module-deployable-from-git.sh <MODULE_SLUG> [-t|--tag TAG] [--include-all] [-u|--user GIT_USER] [-g|--git-remote URL]
#
# This script is supposed to be executed from a deployment_root folder.
#
# Arguments:
#   MODULE_SLUG         The module slug (e.g., "sra", "template")
#   -t, --tag TAG       Pull a specific git tag instead of main
#   --include-all       Pull the whole repo content (modules/host_app, scripts/,
#                       root files like .env.config, .env.secrets, docker-compose.yml, start.sh, etc.)
#                       By default only modules/<MODULE_SLUG> is pulled.
#   -u, --user USER     Override the git user (default: current git config user.name)
#   -g, --git-remote URL  Override the full git remote URL
#
# Environment variables:
#   PUBLISHING_GIT_USER     Default git user if not set via -u
#   PUBLISHING_GIT_REMOTE   Full remote URL override (highest precedence)

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────
MODULE_SLUG=""
GIT_TAG=""
INCLUDE_ALL=""
GIT_USER_ARG=""
GIT_REMOTE_ARG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    -t|--tag)
      GIT_TAG="$2"
      shift 2
      ;;
    --include-all)
      INCLUDE_ALL="1"
      shift
      ;;
    -u|--user)
      GIT_USER_ARG="$2"
      shift 2
      ;;
    -g|--git-remote)
      GIT_REMOTE_ARG="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 <MODULE_SLUG> [-t|--tag TAG] [--include-all] [-u|--user GIT_USER] [-g|--git-remote URL]"
      echo ""
      echo "Arguments:"
      echo "  MODULE_SLUG             The module slug (e.g., sra, template)"
      echo "  -t, --tag TAG           Pull a specific git tag instead of main"
      echo "  --include-all           Pull entire repo (host_app, scripts, root files)"
      echo "                          Default: only modules/<MODULE_SLUG> is pulled"
      echo "  -u, --user GIT_USER     Override git user (default: current git config user.name)"
      echo "  -g, --git-remote URL    Override full git remote URL"
      echo ""
      echo "Environment variables:"
      echo "  PUBLISHING_GIT_USER     Default git user if not set via -u"
      echo "  PUBLISHING_GIT_REMOTE   Full remote URL override (highest precedence)"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1"
      exit 1
      ;;
    *)
      if [[ -z "$MODULE_SLUG" ]]; then
        MODULE_SLUG="$1"
      else
        echo "Unexpected argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$MODULE_SLUG" ]]; then
  echo "ERROR: MODULE_SLUG is required."
  echo "Usage: $0 <MODULE_SLUG> [-t|--tag TAG] [--include-all]"
  exit 1
fi

# ── Determine current directory (should be deployment_root) ──
DEPLOYMENT_ROOT="$(pwd)"

# Basic sanity check — deployment_root should have a docker-compose.yml or
# at least be a recognizable deployment directory.
if [[ ! -f "${DEPLOYMENT_ROOT}/docker-compose.yml" && ! -d "${DEPLOYMENT_ROOT}/modules" ]]; then
  echo "ERROR: This script must be run from a deployment_root folder."
  echo "       Current directory: $DEPLOYMENT_ROOT"
  echo "       Expected: docker-compose.yml or modules/ directory present."
  exit 1
fi

# ── Determine repo name and remote URL ───────────────────────
REPO_NAME="${MODULE_SLUG}-module-deployable"

# Determine git user: -u arg > PUBLISHING_GIT_USER env > git config user.name
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
if [[ -n "$GIT_USER_ARG" ]]; then
  GIT_USER="$GIT_USER_ARG"
elif [[ -n "${PUBLISHING_GIT_USER:-}" ]]; then
  GIT_USER="$PUBLISHING_GIT_USER"
else
  GIT_USER="$(git -C "$PROJECT_ROOT" config user.name 2>/dev/null || echo "")"
fi

if [[ -z "$GIT_USER" ]]; then
  echo "ERROR: Could not determine git user."
  echo "       Set it via -u/--user, PUBLISHING_GIT_USER env var, or git config user.name"
  exit 1
fi

# Determine remote URL: -g arg > PUBLISHING_GIT_REMOTE env > constructed from user
if [[ -n "$GIT_REMOTE_ARG" ]]; then
  GIT_REMOTE="$GIT_REMOTE_ARG"
elif [[ -n "${PUBLISHING_GIT_REMOTE:-}" ]]; then
  GIT_REMOTE="$PUBLISHING_GIT_REMOTE"
else
  GIT_REMOTE="git@github.com:${GIT_USER}/${REPO_NAME}.git"
fi

# Determine ref to fetch
GIT_REF="main"
if [[ -n "$GIT_TAG" ]]; then
  GIT_REF="$GIT_TAG"
fi

echo "=========================================="
echo "Pull module deployable from git"
echo "=========================================="
echo "  Module slug:       $MODULE_SLUG"
echo "  Repo name:         $REPO_NAME"
echo "  Remote URL:        $GIT_REMOTE"
echo "  Ref:               $GIT_REF"
echo "  Include all:       ${INCLUDE_ALL:-no}"
echo "  Target directory:  $DEPLOYMENT_ROOT"
echo ""

# ── Clone repo to temp dir ───────────────────────────────────
TEMP_DIR="$(mktemp -d)"
echo "  Cloning to temp dir: $TEMP_DIR"

if ! git clone --depth 1 --branch "$GIT_REF" "$GIT_REMOTE" "$TEMP_DIR" 2>/dev/null; then
  echo "ERROR: Failed to clone $GIT_REMOTE (ref: $GIT_REF)"
  echo "       Check that the repo exists and the ref is valid."
  rm -rf "$TEMP_DIR"
  exit 1
fi

# ── Pull content ─────────────────────────────────────────────
if [[ -n "$INCLUDE_ALL" ]]; then
  echo ""
  echo "  Pulling entire repo content..."
  # Copy everything from the repo into the current deployment_root
  # Use rsync-like behavior: cp -r and overwrite
  cp -r "${TEMP_DIR}/." "${DEPLOYMENT_ROOT}/"
  echo "  Done. All files pulled."
else
  MODULE_SRC_DIR="${TEMP_DIR}/modules/${MODULE_SLUG}"
  MODULE_DST_DIR="${DEPLOYMENT_ROOT}/modules/${MODULE_SLUG}"

  if [[ ! -d "$MODULE_SRC_DIR" ]]; then
    echo "ERROR: modules/${MODULE_SLUG} not found in the remote repo."
    echo "       Available modules in repo:"
    ls -1 "${TEMP_DIR}/modules/" 2>/dev/null | sed 's/^/         /' || echo "         (none)"
    rm -rf "$TEMP_DIR"
    exit 1
  fi

  echo ""
  echo "  Pulling modules/${MODULE_SLUG}..."
  rm -rf "${MODULE_DST_DIR}"
  mkdir -p "$(dirname "${MODULE_DST_DIR}")"
  cp -r "$MODULE_SRC_DIR" "$MODULE_DST_DIR"

  if [[ -d "${MODULE_DST_DIR}/${MODULE_SLUG}" && -f "${MODULE_DST_DIR}/${MODULE_SLUG}/module.json" && ! -f "${MODULE_DST_DIR}/module.json" ]]; then
    echo "  Flattening nested ${MODULE_SLUG} directory"
    shopt -s dotglob
    mv "${MODULE_DST_DIR}/${MODULE_SLUG}/"* "${MODULE_DST_DIR}/"
    rmdir "${MODULE_DST_DIR}/${MODULE_SLUG}"
    shopt -u dotglob
  fi

  echo "  Done. Module files pulled to modules/${MODULE_SLUG}/"
fi

# ── Cleanup ──────────────────────────────────────────────────
rm -rf "$TEMP_DIR"

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "  Module slug:       $MODULE_SLUG"
echo "  Repo name:         $REPO_NAME"
echo "  Ref:               $GIT_REF"
echo "  Include all:       ${INCLUDE_ALL:-no}"
echo "  Target directory:  $DEPLOYMENT_ROOT"
echo ""
echo "=========================================="
echo "Pull completed successfully!"
echo ""
echo "Next steps:"
if [[ -n "$INCLUDE_ALL" ]]; then
  echo "  - Review .env.config, .env.secrets and other root config files for placeholders"
  echo "  - Run ./start.sh to start the deployment"
else
  echo "  - Review modules/${MODULE_SLUG}/.env.config and .env.secrets for placeholders"
  echo "  - Run scripts/create-merged-configuration.sh to regenerate merged config"
  echo "  - Run ./start.sh to start the deployment"
fi
echo ""
