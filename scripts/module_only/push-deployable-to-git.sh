#!/bin/bash
# Push the deployment_root content to a git remote as a deployable bundle.
#
# Usage:
#   ./scripts/module_only/push-deployable-to-git.sh [MODULE_NAME] [-n|--name REPO_NAME] [-t|--tag TAG] [-u|--user GIT_USER] [-g|--git-remote GIT_REMOTE]
#
# Defaults:
#   - MODULE_NAME: auto-detected from modules/ (first non-host_app, non-module_template module)
#   - REPO_NAME:   <MODULE_SLUG>-module-deployable
#   - GIT_REMOTE:  <GIT_USER>@github.com:<GIT_USER>/<REPO_NAME>.git
#   - GIT_USER:    current git config user.name (or PUBLISHING_GIT_USER env var)
#
# Options:
#   -n, --name NAME       Override the remote repository name
#   -t, --tag TAG         Create and push a git tag
#   -u, --user GIT_USER   Override the git user (default: current git config user.name)
#   -g, --git-remote URL  Override the full git remote URL
#
# Environment variables:
#   PUBLISHING_GIT_USER     Default git user if not set via -u
#   PUBLISHING_GIT_REMOTE   Full remote URL override (takes precedence over -u and -g)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DEPLOYMENT_ROOT="${PROJECT_ROOT}/deployment_root"

# ── Parse arguments ──────────────────────────────────────────
MODULE_NAME=""
REPO_NAME=""
GIT_TAG=""
GIT_USER_ARG=""
GIT_REMOTE_ARG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    -n|--name)
      REPO_NAME="$2"
      shift 2
      ;;
    -t|--tag)
      GIT_TAG="$2"
      shift 2
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
      echo "Usage: $0 [MODULE_NAME] [-n|--name REPO_NAME] [-t|--tag TAG] [-u|--user GIT_USER] [-g|--git-remote URL]"
      echo ""
      echo "Arguments:"
      echo "  MODULE_NAME             Module name (auto-detected if omitted)"
      echo "  -n, --name NAME         Override remote repository name (default: <MODULE_SLUG>-module-deployable)"
      echo "  -t, --tag TAG           Create and push a git tag"
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
      if [[ -z "$MODULE_NAME" ]]; then
        MODULE_NAME="$1"
      else
        echo "Unexpected argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

# ── Auto-detect module name ──────────────────────────────────
if [[ -z "$MODULE_NAME" ]]; then
  for dir in "$PROJECT_ROOT"/modules/*/; do
    name=$(basename "$dir")
    if [[ "$name" != "host_app" && "$name" != "module_template" ]]; then
      MODULE_NAME="$name"
      break
    fi
  done
fi

if [[ -z "$MODULE_NAME" ]]; then
  echo "ERROR: Could not auto-detect module name. Please provide it explicitly."
  echo "Usage: $0 [MODULE_NAME] [-n|--name REPO_NAME] [-t|--tag TAG]"
  exit 1
fi

# ── Derive module slug ───────────────────────────────────────
MODULE_JSON="${PROJECT_ROOT}/modules/${MODULE_NAME}/module.json"
MODULE_SLUG=""
if [[ -f "$MODULE_JSON" ]]; then
  MODULE_SLUG=$(grep -o '"slug": "[^"]*"' "$MODULE_JSON" 2>/dev/null | head -1 | sed 's/.*"slug": "\([^"]*\)".*/\1/')
fi
if [[ -z "$MODULE_SLUG" ]]; then
  MODULE_SLUG=$(echo "$MODULE_NAME" | tr '[:upper:]' '[:lower:]')
fi

# ── Determine repo name and remote URL ───────────────────────
if [[ -z "$REPO_NAME" ]]; then
  REPO_NAME="${MODULE_SLUG}-module-deployable"
fi

# Determine git user: -u arg > PUBLISHING_GIT_USER env > gh authenticated user > git config user.name
if [[ -n "$GIT_USER_ARG" ]]; then
  GIT_USER="$GIT_USER_ARG"
elif [[ -n "${PUBLISHING_GIT_USER:-}" ]]; then
  GIT_USER="$PUBLISHING_GIT_USER"
else
  # Prefer gh CLI authenticated user when available
  if command -v gh &>/dev/null; then
    GIT_USER="$(gh api user --jq .login 2>&1 || echo "")"
    # gh may return error JSON on stdout when credentials are invalid
    if [[ "$GIT_USER" == *"{\""* || "$GIT_USER" == *"Bad credentials"* || -z "$GIT_USER" ]]; then
      GIT_USER=""
    fi
  fi
  if [[ -z "$GIT_USER" ]]; then
    GIT_USER="$(git -C "$PROJECT_ROOT" config user.name 2>/dev/null || echo "")"
  fi
fi

if [[ -z "$GIT_USER" ]]; then
  echo "ERROR: Could not determine git user."
  echo "       Set it via -u/--user, PUBLISHING_GIT_USER env var,"
  echo "       authenticate with 'gh auth login', or set git config user.name"
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

echo "=========================================="
echo "Push deployable to git"
echo "=========================================="
echo "  Module:      $MODULE_NAME (slug: $MODULE_SLUG)"
echo "  Repo name:   $REPO_NAME"
echo "  Remote URL:  $GIT_REMOTE"
echo "  Tag:         ${GIT_TAG:-none}"
echo ""

# ── Validate deployment_root ─────────────────────────────────
if [[ ! -d "$DEPLOYMENT_ROOT" ]]; then
  echo "ERROR: deployment_root not found at $DEPLOYMENT_ROOT"
  exit 1
fi

if [[ ! -f "${DEPLOYMENT_ROOT}/docker-compose.yml" ]]; then
  echo "ERROR: docker-compose.yml not found in deployment_root."
  echo "       Run ./redeploy.sh first to generate deployment artifacts."
  exit 1
fi

# ── Step 1: Confirm deployment has been tested ───────────────
echo "=========================================="
echo "Step 1: Verify deployment"
echo "=========================================="
echo ""
echo "Before pushing, you MUST test the project in deployment_root."
echo "Make sure all containers start correctly and the module works."
echo ""
read -r -p "Have you tested the deployment and confirmed it works? (y/N): " answer
answer_lower=$(echo "$answer" | tr '[:upper:]' '[:lower:]')
if [[ "$answer_lower" != "y" && "$answer_lower" != "yes" ]]; then
  echo "Aborting: deployment has not been confirmed as working."
  exit 1
fi
echo ""

# ── Step 2: Confirm no secrets in config files ───────────────
echo "=========================================="
echo "Step 2: Verify no secrets in config files"
echo "=========================================="
echo ""
echo "Ensure that deployment_root config files do NOT contain any"
echo "sensible secret or password. Only placeholders or elements"
echo "that must be substituted in a real deployment environment"
echo "should be pushed."
echo ""
echo "Check these files in particular:"
echo "  - deployment_root/.env.secrets"
echo "  - deployment_root/modules/*/.env.secrets"
echo "  - deployment_root/modules/*/config/*"
echo ""
read -r -p "Have you verified no secrets are present in config files? (y/N): " answer
answer_lower=$(echo "$answer" | tr '[:upper:]' '[:lower:]')
if [[ "$answer_lower" != "y" && "$answer_lower" != "yes" ]]; then
  echo "Aborting: secrets check has not been confirmed."
  exit 1
fi
echo ""

# ── Step 3: Prepare temp dir and copy deployment_root ────────
echo "=========================================="
echo "Step 3: Preparing git repository"
echo "=========================================="
TEMP_DIR="$(mktemp -d)"
echo "  Temp dir: $TEMP_DIR"
echo ""

# Copy entire deployment_root content
cp -r "${DEPLOYMENT_ROOT}/." "${TEMP_DIR}/"

# Remove legacy PascalCase module directories left over from the old naming
# convention. Current modules use snake_case names (host_app, module_template);
# leaving empty HostApp/ModuleTemplate directories in the deployable repo is
# confusing and can break case-sensitive filesystems.
for legacy_dir in "modules/HostApp" "modules/ModuleTemplate"; do
    if [[ -d "${TEMP_DIR}/${legacy_dir}" ]]; then
        rm -rf "${TEMP_DIR}/${legacy_dir}"
        echo "  Removed legacy ${legacy_dir}/ from deployable bundle"
    fi
done

# Add registry prefix to locally-built module images so consumers pull from the
# registry instead of failing because the local image is missing.
# For each module in the bundle, read MODULE_DOCKER_REGISTRY_PREFIX from the
# deployed .env.config and the module slug from module.json, then rewrite any
# image reference like <slug>.<submodule>:<tag> to
# <registry_prefix>/<slug>.<submodule>:<tag> in all docker-compose.yml files.
# Images that are already prefixed (contain a '/' before the slug) are skipped.
rewritten=0
for module_dir in "${TEMP_DIR}/modules"/*/; do
    [[ -d "$module_dir" ]] || continue
    module_name=$(basename "$module_dir")
    module_json="${module_dir}/module.json"
    env_config="${module_dir}/.env.config"
    [[ -f "$module_json" && -f "$env_config" ]] || continue

    module_slug=$(grep -o '"slug"[[:space:]]*:[[:space:]]*"[^"]*"' "$module_json" 2>/dev/null | head -1 | sed 's/.*"slug"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || true)
    if [[ -z "$module_slug" ]]; then
        echo "ERROR: could not determine module slug from ${module_json}" >&2
        exit 1
    fi
    registry_prefix=$(grep -E '^[[:space:]]*MODULE_DOCKER_REGISTRY_PREFIX[[:space:]]*=' "$env_config" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -z "$registry_prefix" ]]; then
        echo "ERROR: missing MODULE_DOCKER_REGISTRY_PREFIX in ${env_config}" >&2
        exit 1
    fi

    # Strip optional surrounding quotes and trailing slash from prefix
    registry_prefix=$(echo "$registry_prefix" | sed 's/^["'"'"']*//;s/["'"'"']*$//')
    registry_prefix="${registry_prefix%/}"

    # Escape regex metacharacters in module slug before using it in sed patterns
    module_slug_escaped=$(printf '%s' "$module_slug" | sed 's/[.\[\*^$()+?{|]/\\&/g')

    while IFS= read -r compose_file; do
        [[ -f "$compose_file" ]] || continue
        sed -i.bak -E "s|^([[:space:]]*image:[[:space:]]*)(${module_slug_escaped}\.[a-zA-Z0-9_-]+:.*)$|\1${registry_prefix}/\2|g" "$compose_file"
        if ! cmp -s "$compose_file" "${compose_file}.bak"; then
            rewritten=$((rewritten + 1))
            echo "  Prefixed ${module_name} images in ${compose_file#${TEMP_DIR}/}"
        fi
        rm -f "${compose_file}.bak"
    done < <(find "${TEMP_DIR}" -name 'docker-compose.yml' -type f)
done
if [[ "$rewritten" -eq 0 ]]; then
    echo "  No registry prefix applied (no MODULE_DOCKER_REGISTRY_PREFIX found)"
fi

# Re-template APP_SLUG (and APP_NAME) so the deployable bundle keeps these
# project-level variables as literal references. build_and_deploy.py substitutes
# ${APP_SLUG}.${MODULE_SLUG} with concrete values for local deployment, but a
# consumer of the bundle must be able to set their own APP_SLUG and APP_NAME at
# deployable side. MODULE_SLUG and module-specific image references remain
# concrete.
re_templated=0
root_env_config="${TEMP_DIR}/.env.config"
app_name=$(grep -E '^[[:space:]]*APP_NAME[[:space:]]*=' "$root_env_config" 2>/dev/null | head -1 | cut -d= -f2- || true)
app_name=$(echo "$app_name" | sed 's/^["'"'']*//;s/["'"'']*$//')
app_name_escaped=$(printf '%s' "$app_name" | sed 's/[.\[\*^$()+?{|]/\\&/g')
for module_dir in "${TEMP_DIR}/modules"/*/; do
    [[ -d "$module_dir" ]] || continue
    module_name=$(basename "$module_dir")
    env_config="${module_dir}/.env.config"
    [[ -f "$env_config" ]] || continue

    app_slug=$(grep -E '^[[:space:]]*APP_SLUG[[:space:]]*=' "$root_env_config" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -z "$app_slug" ]]; then
        echo "ERROR: missing APP_SLUG in merged root ${root_env_config}" >&2
        exit 1
    fi
    module_slug=$(grep -E '^[[:space:]]*MODULE_SLUG[[:space:]]*=' "$env_config" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -z "$module_slug" ]]; then
        echo "ERROR: missing MODULE_SLUG in ${env_config}" >&2
        exit 1
    fi

    app_slug=$(echo "$app_slug" | sed 's/^["'"'"']*//;s/["'"'"']*$//')
    module_slug=$(echo "$module_slug" | sed 's/^["'"'"']*//;s/["'"'"']*$//')

    # Escape regex metacharacters in slugs before using them in sed patterns
    app_slug_escaped=$(printf '%s' "$app_slug" | sed 's/[.\[\*^$()+?{|]/\\&/g')
    module_slug_escaped=$(printf '%s' "$module_slug" | sed 's/[.\[\*^$()+?{|]/\\&/g')

    while IFS= read -r compose_file; do
        [[ -f "$compose_file" ]] || continue
        compose_file_before=$(mktemp)
        cp "$compose_file" "$compose_file_before"

        # 1. Container names: <APP_SLUG>.<MODULE_SLUG>. -> ${APP_SLUG}.<MODULE_SLUG>.
        sed -i.bak -E "s|^([[:space:]]*container_name:[[:space:]]*)${app_slug_escaped}(\.${module_slug_escaped}\.)|\1\${APP_SLUG}\2|g" "$compose_file"

        # 2. Volume names: name: <APP_SLUG>_... -> name: ${APP_SLUG}_...
        sed -i.bak -E "s|^([[:space:]]*name:[[:space:]]*)${app_slug_escaped}_|\1\${APP_SLUG}_|g" "$compose_file"

        # 3. Direct APP_SLUG / APP_NAME assignments (map and list formats).
        sed -i.bak -E "s|^([[:space:]]*APP_SLUG[[:space:]]*:[[:space:]]*)${app_slug_escaped}$|\1\${APP_SLUG}|g" "$compose_file"
        sed -i.bak -E "s|^([[:space:]]*-[[:space:]]*APP_SLUG[[:space:]]*[:=][[:space:]]*)${app_slug_escaped}$|\1\${APP_SLUG}|g" "$compose_file"
        if [[ -n "$app_name" ]]; then
            sed -i.bak -E "s|^([[:space:]]*APP_NAME[[:space:]]*:[[:space:]]*)${app_name_escaped}$|\1\${APP_NAME}|g" "$compose_file"
            sed -i.bak -E "s|^([[:space:]]*-[[:space:]]*APP_NAME[[:space:]]*[:=][[:space:]]*)${app_name_escaped}$|\1\${APP_NAME}|g" "$compose_file"
        fi

        # 4. Other project-level references to APP_SLUG in values (environment
        # URLs, hostnames, etc.). Keep image lines untouched so module-specific
        # image references like <slug>.backend remain concrete, and skip
        # container_name / volume_name lines because they are handled above.
        sed -i.bak -E "/^[[:space:]]*(image|container_name|name):/! s|${app_slug_escaped}\.|\${APP_SLUG}.|g" "$compose_file"
        sed -i.bak -E "/^[[:space:]]*(image|container_name|name):/! s|/${app_slug_escaped}/|/\${APP_SLUG}/|g" "$compose_file"
        rm -f "${compose_file}.bak"

        if ! cmp -s "$compose_file" "$compose_file_before"; then
            re_templated=$((re_templated + 1))
            echo "  Re-templated ${module_name} project-level references in ${compose_file#${TEMP_DIR}/}"
        fi
        rm -f "$compose_file_before"
    done < <(find "${TEMP_DIR}" -name 'docker-compose.yml' -type f)
done
if [[ "$re_templated" -eq 0 ]]; then
    echo "  No project-level prefixes needed re-templating"
fi

# Create .gitignore to exclude secrets files from the deployable repo
# Example secrets (.env.secrets.example) are intentionally kept so consumers
# know which secrets are required and can bootstrap real .env.secrets files.
cat > "${TEMP_DIR}/.gitignore" <<'GITIGNORE'
# Actual secrets — never push to deployable repo
.env.secrets
modules/*/.env.secrets
# Example secrets are OK to push
!.env.secrets.example
!modules/*/.env.secrets.example

# Runtime-generated Authentik blueprints (regenerated by redeploy/bootstrap)
modules/host_app/authentik/blueprints/authz-plan.generated.yaml
modules/host_app/authentik/blueprints/blueprint_generation.log
GITIGNORE

# Initialize git repo
cd "$TEMP_DIR"
git init
git add -A

COMMIT_MSG="chore: deployable bundle for ${MODULE_NAME} (slug: ${MODULE_SLUG})"
git commit -m "$COMMIT_MSG"

# ── Step 4: Push to remote ───────────────────────────────────
echo ""
echo "=========================================="
echo "Step 4: Pushing to remote"
echo "=========================================="

# Try to fetch existing remote to check if repo already exists
REMOTE_EXISTS="0"
if git remote add origin "$GIT_REMOTE" 2>/dev/null; then
  if git fetch origin main 2>/dev/null; then
    REMOTE_EXISTS="1"
    echo "  Remote repo already exists. Pushing update..."
    git push origin HEAD:main --force
  else
    REMOTE_EXISTS="0"
    echo "  Remote repo is new (or empty). Pushing initial commit..."
    if ! git push -u origin HEAD:main 2>&1; then
      # Push failed — likely repo doesn't exist. Offer to create it.
      echo ""
      echo "  Push failed. The remote repository may not exist."
      if command -v gh &>/dev/null; then
        echo "  GitHub CLI (gh) is available."
        read -r -p "  Create the repository '${GIT_USER}/${REPO_NAME}' on GitHub? (y/N): " create_answer
        create_lower=$(echo "$create_answer" | tr '[:upper:]' '[:lower:]')
        if [[ "$create_lower" == "y" || "$create_lower" == "yes" ]]; then
          echo "  Creating repository..."
          if gh repo create "${GIT_USER}/${REPO_NAME}" --private 2>&1; then
            echo "  Repository created. Retrying push..."
            git push -u origin HEAD:main
          else
            echo "ERROR: Failed to create repository."
            exit 1
          fi
        else
          echo "Aborting: repository does not exist and was not created."
          exit 1
        fi
      else
        echo "ERROR: Push failed and GitHub CLI (gh) is not installed."
        echo "       Create the repository manually on GitHub, then re-run this script."
        echo "       Or install gh: https://cli.github.com/"
        exit 1
      fi
    fi
  fi
else
  echo "  Remote repo is new. Pushing initial commit..."
  if ! git push -u origin HEAD:main 2>&1; then
    echo ""
    echo "  Push failed. The remote repository may not exist."
    if command -v gh &>/dev/null; then
      echo "  GitHub CLI (gh) is available."
      read -r -p "  Create the repository '${GIT_USER}/${REPO_NAME}' on GitHub? (y/N): " create_answer
      create_lower=$(echo "$create_answer" | tr '[:upper:]' '[:lower:]')
      if [[ "$create_lower" == "y" || "$create_lower" == "yes" ]]; then
        echo "  Creating repository..."
        if gh repo create "${GIT_USER}/${REPO_NAME}" --private 2>&1; then
          echo "  Repository created. Retrying push..."
          git push -u origin HEAD:main
        else
          echo "ERROR: Failed to create repository."
          exit 1
        fi
      else
        echo "Aborting: repository does not exist and was not created."
        exit 1
      fi
    else
      echo "ERROR: Push failed and GitHub CLI (gh) is not installed."
      echo "       Create the repository manually on GitHub, then re-run this script."
      echo "       Or install gh: https://cli.github.com/"
      exit 1
    fi
  fi
fi

# ── Step 5: Create and push tag if requested ─────────────────
if [[ -n "$GIT_TAG" ]]; then
  echo ""
  echo "  Creating tag: $GIT_TAG"
  git tag "$GIT_TAG"
  git push origin "$GIT_TAG"
  echo "  Tag '$GIT_TAG' pushed."
fi

# ── Cleanup ──────────────────────────────────────────────────
cd "$PROJECT_ROOT"
rm -rf "$TEMP_DIR"

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "  Module:      $MODULE_NAME (slug: $MODULE_SLUG)"
echo "  Repo name:   $REPO_NAME"
echo "  Remote URL:  $GIT_REMOTE"
echo "  Tag:         ${GIT_TAG:-none}"
echo ""
echo "=========================================="
echo "Push completed successfully!"
