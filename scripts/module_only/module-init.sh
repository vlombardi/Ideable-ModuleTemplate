#!/bin/bash
# Initialize a new module from module_template
# Usage: ./scripts/module-init.sh NewModuleName [-h|--help]

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 NewModuleName [-h|--help]"
    echo ""
    echo "Initializes a new module from module_template, renaming all references"
    echo "from module_template/template to the new module name."
    echo ""
    echo "Arguments:"
    echo "  new_module_name  Name for the new module (snake_case: must start with"
    echo "                   a letter, contain only letters, numbers, and underscores,"
    echo "                   e.g. digital_shelter)"
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEFAULT_TEMPLATE_REMOTE_URL="https://github.com/vlombardi/Ideable-ModuleTemplate.git"
ORIGINAL_ORIGIN_URL=""
if ORIGINAL_ORIGIN_URL=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null); then
    :
else
    ORIGINAL_ORIGIN_URL=""
fi

NEW_NAME="${1:-}"
if [[ -z "$NEW_NAME" ]]; then
    echo "Usage: $0 NewModuleName"
    echo "Example: $0 digital_shelter"
    exit 1
fi

# Validate module name (snake_case: letters, numbers, underscores)
if [[ ! "$NEW_NAME" =~ ^[a-z][a-z0-9_]*$ ]]; then
    echo "Error: Module name must be snake_case (lowercase letters, numbers, underscores; must start with a letter)"
    exit 1
fi

OLD_NAME="module_template"
OLD_SLUG="template"
OLD_SLUG_CAP="Template"
OLD_SLUG_UPPER="TEMPLATE"
OLD_CSS_PREFIX="template-"
NEW_SLUG=$(echo "$NEW_NAME" | tr -d '_')
NEW_SLUG_CAP="$(echo "${NEW_SLUG:0:1}" | tr '[:lower:]' '[:upper:]')${NEW_SLUG:1}"
NEW_SLUG_UPPER=$(echo "$NEW_SLUG" | tr '[:lower:]' '[:upper:]')
NEW_CSS_PREFIX="${NEW_SLUG}-"

# Extract "owner/repo" from a GitHub remote URL (https or ssh). Empty string if unsupported.
extract_github_owner_repo_from_url() {
    local url="$1"
    local owner repo
    owner=""
    repo=""

    if [[ -z "$url" ]]; then
        return
    fi

    if [[ "$url" =~ ^git@github\.com:([^/]+)/([^/]+?)(\.git)?$ ]]; then
        owner="${BASH_REMATCH[1]}"
        repo="${BASH_REMATCH[2]}"
    elif [[ "$url" =~ ^https?://github\.com/([^/]+)/([^/]+?)(\.git)?$ ]]; then
        owner="${BASH_REMATCH[1]}"
        repo="${BASH_REMATCH[2]}"
    fi

    repo="${repo%.git}"

    if [[ -n "$owner" && -n "$repo" ]]; then
        printf '%s/%s' "$owner" "$repo"
    fi
}

configure_git_remotes() {
    ensure_template_remote

    local suggested_remote
    suggested_remote=$(derive_suggested_remote_url "$ORIGINAL_ORIGIN_URL")
    if [[ -z "$suggested_remote" ]]; then
        suggested_remote="https://github.com/vlombardi/Ideable-${NEW_SLUG}.git"
    fi

    echo ""
    echo "--- Git remote configuration ---"
    echo "This repo needs an 'origin' remote pointing to your new module repository."
    echo "Suggested remote URL: $suggested_remote"

    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
        echo "Error: cannot prompt for git remote; /dev/tty is not available. Run this script from an interactive terminal." >&2
        exit 1
    fi

    local remote_input
    printf 'Origin remote URL [%s]: ' "$suggested_remote" > /dev/tty
    if ! IFS= read -r remote_input < /dev/tty; then
        remote_input=""
    fi
    local remote_url="${remote_input:-$suggested_remote}"
    remote_url="${remote_url// /}"

    if [[ -z "$remote_url" ]]; then
        echo "Error: remote URL cannot be empty." >&2
        exit 1
    fi

    if git -C "$PROJECT_ROOT" remote | grep -q '^origin$'; then
        git -C "$PROJECT_ROOT" remote set-url origin "$remote_url"
    else
        git -C "$PROJECT_ROOT" remote add origin "$remote_url"
    fi
    echo "Configured git remote 'origin' -> $remote_url"

    if git -C "$PROJECT_ROOT" ls-remote "$remote_url" >/dev/null 2>&1; then
        return
    fi

    echo "  Unable to reach $remote_url (repository may be missing or you lack access)."
    if maybe_create_remote_repo "$remote_url"; then
        if git -C "$PROJECT_ROOT" ls-remote "$remote_url" >/dev/null 2>&1; then
            echo "  Verified repository $remote_url is reachable."
            return
        fi
        echo "  [warn] Repository still unreachable. Verify credentials and that the repo exists."
    else
        echo "  [warn] Repository creation skipped or failed. Ensure $remote_url exists before pushing."
    fi
}

derive_suggested_remote_url() {
    local base_url="$1"
    local candidate="$base_url"
    local new_repo_token="${NEW_SLUG}"

    if [[ -z "$candidate" ]]; then
        candidate="$DEFAULT_TEMPLATE_REMOTE_URL"
    fi

    # Replace various module_template spellings with the module slug.
    candidate="${candidate//module_template/${new_repo_token}}"
    candidate="${candidate//moduletemplate/${new_repo_token}}"
    candidate="${candidate//MODULETEMPLATE/${new_repo_token}}"

    if [[ "$candidate" == "$base_url" || -z "$candidate" ]]; then
        local owner_repo owner
        owner_repo=$(extract_github_owner_repo_from_url "$base_url")
        owner="${owner_repo%/*}"
        if [[ -z "$owner" ]]; then
            owner="vlombardi"
        fi

        local repo_name="Ideable-${NEW_SLUG}"
        if [[ "$base_url" == git@github.com:* ]]; then
            candidate="git@github.com:${owner}/${repo_name}.git"
        else
            candidate="https://github.com/${owner}/${repo_name}.git"
        fi
    fi

    if [[ "$candidate" != *.git ]]; then
        candidate="${candidate}.git"
    fi

    echo "$candidate"
}

ensure_template_remote() {
    if git -C "$PROJECT_ROOT" remote | grep -q '^template$'; then
        return
    fi
    git -C "$PROJECT_ROOT" remote add template "$DEFAULT_TEMPLATE_REMOTE_URL"
    echo "Configured 'template' git remote for sync-template-updates: $DEFAULT_TEMPLATE_REMOTE_URL"
}

maybe_create_remote_repo() {
    local remote_url="$1"

    local owner_repo
    owner_repo=$(extract_github_owner_repo_from_url "$remote_url")

    if [[ -z "$owner_repo" ]]; then
        echo "  [warn] Unable to parse GitHub owner/repo from '$remote_url'. If the repository is new, create it manually."
        return 1
    fi

    if ! command -v gh >/dev/null 2>&1; then
        echo "  [warn] GitHub CLI (gh) is not installed. Install it or create ${owner_repo} manually, then re-run this script."
        return 1
    fi

    if gh repo view "$owner_repo" >/dev/null 2>&1; then
        echo "  Remote ${owner_repo} already exists but could not be reached via git. Ensure you have access (gh auth/login) and rerun if needed."
        return 0
    fi

    echo "  Remote repository '${owner_repo}' was not found."
    read -rp "  Create it on GitHub now? [Y/n]: " create_answer
    create_answer="${create_answer,,}"
    if [[ -n "$create_answer" && "$create_answer" != "y" && "$create_answer" != "yes" ]]; then
        echo "  Skipping automatic repository creation. Create ${owner_repo} manually and rerun if needed."
        return 1
    fi

    if gh repo create "$owner_repo" --private --confirm >/dev/null 2>&1; then
        echo "  Created GitHub repository ${owner_repo}."
        return 0
    fi

    echo "  [error] Failed to create GitHub repository ${owner_repo}. Please create it manually and rerun this script."
    return 1
}

MODULE_DIR="${PROJECT_ROOT}/modules/${OLD_NAME}"
NEW_MODULE_DIR="${PROJECT_ROOT}/modules/${NEW_NAME}"

# Check if already initialized or resuming
if [[ -d "$NEW_MODULE_DIR" && ! -d "$MODULE_DIR" ]]; then
    echo "Module ${NEW_NAME} already initialized. Re-running for potential updates."
    MODULE_DIR="$NEW_MODULE_DIR"
elif [[ ! -d "$MODULE_DIR" ]]; then
    echo "Error: ${OLD_NAME} module not found at ${MODULE_DIR}"
    exit 1
elif [[ "$MODULE_DIR" != "$NEW_MODULE_DIR" ]]; then
    echo "Initializing new module: ${NEW_NAME} (slug: ${NEW_SLUG})"
    echo "Renaming folder: modules/${OLD_NAME} -> modules/${NEW_NAME}"
    mv "$MODULE_DIR" "$NEW_MODULE_DIR"
    MODULE_DIR="$NEW_MODULE_DIR"
else
    echo "Module ${NEW_NAME} already initialized. Re-running for potential updates."
fi

echo "Processing files in ${MODULE_DIR}..."

# Update module.json
MODULE_JSON="${MODULE_DIR}/module.json"
if [[ -f "$MODULE_JSON" ]]; then
    sed -i.bak "s/\"name\": \"${OLD_NAME}\"/\"name\": \"${NEW_NAME}\"/g" "$MODULE_JSON"
    sed -i.bak "s/\"slug\": \"${OLD_SLUG}\"/\"slug\": \"${NEW_SLUG}\"/g" "$MODULE_JSON"
    rm -f "${MODULE_JSON}.bak"
    echo "Updated module.json"
fi

# Update package.json files
find "$MODULE_DIR" -name "package.json" -type f | while read -r file; do
    sed -i.bak "s/\"name\": \"@ideable\/${OLD_SLUG}\"/\"name\": \"@ideable\/${NEW_SLUG}\"/g" "$file"
    rm -f "${file}.bak"
    echo "Updated $(basename "$file")"
done

# Update docker-compose.yml
COMPOSE_FILE="${MODULE_DIR}/docker-compose.yml"
if [[ -f "$COMPOSE_FILE" ]]; then
    sed -i.bak "s/container_name: ${OLD_SLUG}/container_name: ${NEW_SLUG}/g" "$COMPOSE_FILE"
    sed -i.bak "s/service: ${OLD_SLUG}/service: ${NEW_SLUG}/g" "$COMPOSE_FILE"
    rm -f "${COMPOSE_FILE}.bak"
    echo "Updated docker-compose.yml"
fi

# Update host_app modules_menu_mapping.json to reference the new module
HOSTAPP_MAPPING="${PROJECT_ROOT}/modules/host_app/config/modules_menu_mapping.json"
if [[ -f "$HOSTAPP_MAPPING" ]]; then
    sed -i.bak \
        -e "s/\"menu_item_code\": \"${OLD_SLUG_UPPER}\"/\"menu_item_code\": \"${NEW_SLUG_UPPER}\"/g" \
        -e "s/\"menu_item_name\": \"${OLD_SLUG_CAP}\"/\"menu_item_name\": \"${NEW_SLUG_CAP}\"/g" \
        -e "s/\"authorization_claim\": \"${OLD_SLUG}:menu_access\"/\"authorization_claim\": \"${NEW_SLUG}:menu_access\"/g" \
        -e "s/\"module\": \"${OLD_SLUG}\"/\"module\": \"${NEW_SLUG}\"/g" \
        -e "s/\"module_menu_item_code_path\": \"${OLD_SLUG_UPPER}\"/\"module_menu_item_code_path\": \"${NEW_SLUG_UPPER}\"/g" \
        "$HOSTAPP_MAPPING"
    rm -f "${HOSTAPP_MAPPING}.bak"
    echo "Updated host_app modules_menu_mapping.json"
fi

# Update all source files for name/slug replacements (SPECS are generic, no substitution needed)
find "$MODULE_DIR" -type f \( -name "*.py" -o -name "*.tsx" -o -name "*.ts" -o -name "*.js" -o -name "*.css" -o -name "*.json" -o -name "*.yml" -o -name "*.yaml" -o -name "*.sh" \) | while read -r file; do
    # Skip binary files
    if file "$file" | grep -q "binary"; then
        continue
    fi
    
    # Replace OLD_NAME with NEW_NAME
    sed -i.bak "s/${OLD_NAME}/${NEW_NAME}/g" "$file" 2>/dev/null || true
    
    # Replace uppercase slug (e.g. TEMPLATE_ -> SRA_ for env var names)
    sed -i.bak "s/${OLD_SLUG_UPPER}/${NEW_SLUG_UPPER}/g" "$file" 2>/dev/null || true
    
    # Replace capitalized slug (e.g. TemplateItems -> SraItems)
    sed -i.bak "s/${OLD_SLUG_CAP}/${NEW_SLUG_CAP}/g" "$file" 2>/dev/null || true
    
    # Replace OLD_SLUG with NEW_SLUG
    sed -i.bak "s/${OLD_SLUG}/${NEW_SLUG}/g" "$file" 2>/dev/null || true
    
    # Replace CSS prefix
    sed -i.bak "s/${OLD_CSS_PREFIX}/${NEW_CSS_PREFIX}/g" "$file" 2>/dev/null || true
    
    rm -f "${file}.bak" 2>/dev/null || true
done

echo "Processed source files"

# Rename files whose names contain OLD_SLUG (any case) or OLD_NAME
# Process deepest paths first to avoid renaming parent dirs before children
find "$MODULE_DIR" -depth \( -name "*${OLD_SLUG}*" -o -name "*${OLD_SLUG_CAP}*" -o -name "*${OLD_NAME}*" \) | while read -r old_path; do
    dir="$(dirname "$old_path")"
    base="$(basename "$old_path")"
    new_base="${base//${OLD_NAME}/${NEW_NAME}}"
    new_base="${new_base//${OLD_SLUG_CAP}/${NEW_SLUG_CAP}}"
    new_base="${new_base//${OLD_SLUG}/${NEW_SLUG}}"
    if [[ "$new_base" != "$base" ]]; then
        mv "$old_path" "${dir}/${new_base}"
        echo "  Renamed: $base -> $new_base"
    fi
done
echo "Renamed files containing old slug/name"

# Update .env.config.example/.env.secrets.example and create .env.config/.env.secrets
ENV_CONFIG_EXAMPLE="${MODULE_DIR}/.env.config.example"
ENV_CONFIG_FILE="${MODULE_DIR}/.env.config"
ENV_SECRETS_EXAMPLE="${MODULE_DIR}/.env.secrets.example"
ENV_SECRETS_FILE="${MODULE_DIR}/.env.secrets"

UPPER_SLUG=$(echo "$NEW_SLUG" | tr '[:lower:]' '[:upper:]')

for pair in "$ENV_CONFIG_EXAMPLE:$ENV_CONFIG_FILE" "$ENV_SECRETS_EXAMPLE:$ENV_SECRETS_FILE"; do
    EXAMPLE_FILE="${pair%%:*}"
    DEST_FILE="${pair##*:}"
    if [[ -f "$EXAMPLE_FILE" ]]; then
        if [[ ! -f "$DEST_FILE" ]]; then
            cp "$EXAMPLE_FILE" "$DEST_FILE"
            echo "Created $(basename "$DEST_FILE") from $(basename "$EXAMPLE_FILE")"
        fi
        sed -i.bak "s/VITE_TEMPLATE_/VITE_${UPPER_SLUG}_/g" "$DEST_FILE"
        sed -i.bak "s/TEMPLATE_/${UPPER_SLUG}_/g" "$DEST_FILE"
        sed -i.bak "s/${OLD_SLUG}/${NEW_SLUG}/g" "$DEST_FILE"
        sed -i.bak "s/${OLD_NAME}/${NEW_NAME}/g" "$DEST_FILE"
        rm -f "${DEST_FILE}.bak"
        echo "Updated $(basename "$DEST_FILE") with module identity (${NEW_NAME}, ${NEW_SLUG}) and ${UPPER_SLUG}_* variables"
    fi
done

# Rewrite modules/enabled.md: host_app remote + NEW_NAME local (idempotent)
ENABLED_MD="${PROJECT_ROOT}/modules/enabled.md"
printf '%s\n' \
    '# Enabled Modules' \
    '' \
    '# List modules that should be built, deployed, executed, and tested' \
    '# Comment out or remove modules that should be disabled' \
    '# Use local for modules built from source and remote for modules using pre-built images' \
    '' \
    'host_app: remote' \
    "${NEW_NAME}: local" \
    > "$ENABLED_MD"
echo "Updated modules/enabled.md"

configure_git_remotes

# Create modules/host_app/.env.config + .env.secrets from examples if not already present
HOSTAPP_ENV_CONFIG_EXAMPLE="${PROJECT_ROOT}/modules/host_app/.env.config.example"
HOSTAPP_ENV_CONFIG="${PROJECT_ROOT}/modules/host_app/.env.config"
HOSTAPP_ENV_SECRETS_EXAMPLE="${PROJECT_ROOT}/modules/host_app/.env.secrets.example"
HOSTAPP_ENV_SECRETS="${PROJECT_ROOT}/modules/host_app/.env.secrets"

for pair in "$HOSTAPP_ENV_CONFIG_EXAMPLE:$HOSTAPP_ENV_CONFIG" "$HOSTAPP_ENV_SECRETS_EXAMPLE:$HOSTAPP_ENV_SECRETS"; do
    EXAMPLE_FILE="${pair%%:*}"
    DEST_FILE="${pair##*:}"
    if [[ -f "$EXAMPLE_FILE" ]]; then
        if [[ ! -f "$DEST_FILE" ]]; then
            cp "$EXAMPLE_FILE" "$DEST_FILE"
            echo "Created modules/host_app/$(basename "$DEST_FILE") from $(basename "$EXAMPLE_FILE")"
        else
            while IFS= read -r line; do
                if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
                    continue
                fi

                key=$(printf '%s' "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
                [[ -z "$key" ]] && continue

                if ! grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$DEST_FILE"; then
                    printf '\n%s\n' "$line" >> "$DEST_FILE"
                    echo "Added missing env var to modules/host_app/$(basename "$DEST_FILE"): ${key}"
                fi
            done < "$EXAMPLE_FILE"
        fi
    fi
done

# Create or merge repo-root project.env.config + project.env.secrets from examples
PROJECT_ENV_CONFIG_EXAMPLE="${PROJECT_ROOT}/project.env.config.example"
PROJECT_ENV_CONFIG="${PROJECT_ROOT}/project.env.config"
PROJECT_ENV_SECRETS_EXAMPLE="${PROJECT_ROOT}/project.env.secrets.example"
PROJECT_ENV_SECRETS="${PROJECT_ROOT}/project.env.secrets"

if [[ ! -f "$PROJECT_ENV_CONFIG_EXAMPLE" ]]; then
    echo "Error: project.env.config.example not found at ${PROJECT_ENV_CONFIG_EXAMPLE}"
    exit 1
fi

for pair in "$PROJECT_ENV_CONFIG_EXAMPLE:$PROJECT_ENV_CONFIG" "$PROJECT_ENV_SECRETS_EXAMPLE:$PROJECT_ENV_SECRETS"; do
    EXAMPLE_FILE="${pair%%:*}"
    DEST_FILE="${pair##*:}"
    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        continue
    fi
    if [[ ! -f "$DEST_FILE" ]]; then
        cp "$EXAMPLE_FILE" "$DEST_FILE"
        echo "Created $(basename "$DEST_FILE") from $(basename "$EXAMPLE_FILE")"
    else
        while IFS= read -r line; do
            if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
                continue
            fi

            key=$(printf '%s' "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
            [[ -z "$key" ]] && continue

            if ! grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$DEST_FILE"; then
                printf '\n%s\n' "$line" >> "$DEST_FILE"
                echo "Added missing env var to $(basename "$DEST_FILE"): ${key}"
            fi
        done < "$EXAMPLE_FILE"
    fi
done

if [[ -f "$PROJECT_ENV_CONFIG" ]]; then
    PROJECT_ROOT_ESCAPED="${PROJECT_ROOT//\\/\\\\}"
    PROJECT_ROOT_ESCAPED="${PROJECT_ROOT_ESCAPED//&/\\&}"
    DATA_FOLDER_VALUE="${PROJECT_ROOT}/deployment_root/data"
    DATA_FOLDER_ESCAPED="${DATA_FOLDER_VALUE//\\/\\\\}"
    DATA_FOLDER_ESCAPED="${DATA_FOLDER_ESCAPED//&/\\&}"

    if grep -qE '^(export[[:space:]]+)?PROJECT_ROOT[[:space:]]*=' "$PROJECT_ENV_CONFIG"; then
        sed -i.bak -e "s|^PROJECT_ROOT=.*|PROJECT_ROOT=${PROJECT_ROOT_ESCAPED}|" "$PROJECT_ENV_CONFIG"
    else
        printf '\nPROJECT_ROOT=%s\n' "$PROJECT_ROOT_ESCAPED" >> "$PROJECT_ENV_CONFIG"
    fi

    if grep -qE '^(export[[:space:]]+)?DATA_FOLDER[[:space:]]*=' "$PROJECT_ENV_CONFIG"; then
        sed -i.bak -e "s|^DATA_FOLDER=.*|DATA_FOLDER=${DATA_FOLDER_ESCAPED}|" "$PROJECT_ENV_CONFIG"
    else
        printf '\nDATA_FOLDER=%s\n' "$DATA_FOLDER_ESCAPED" >> "$PROJECT_ENV_CONFIG"
    fi

    rm -f "${PROJECT_ENV_CONFIG}.bak"
fi

# Prompt for project identity and external host if not already customized
prompt_env_value() {
    local key="$1" prompt_text="$2" default_val="$3"
    local current_val=""

    if grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$PROJECT_ENV_CONFIG" 2>/dev/null; then
        current_val=$(grep -E "^(export[[:space:]]+)?${key}[[:space:]]*=" "$PROJECT_ENV_CONFIG" | head -1 | sed 's/^export[[:space:]]*//' | cut -d= -f2-)
    fi

    # Strip quotes from current value for display
    current_val="$(echo "$current_val" | sed 's/^["'"'"']*//;s/["'"'"']*$//')"

    local effective_default="${current_val:-$default_val}"
    if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
        echo "Error: cannot prompt for ${key}; /dev/tty is not available. Run this script from an interactive terminal." >&2
        exit 1
    fi

    printf '%s [%s]: ' "${prompt_text}" "${effective_default}" > /dev/tty
    if ! IFS= read -r answer < /dev/tty; then
        answer=""
    fi
    answer="${answer:-$effective_default}"

    # Escape for sed
    local escaped_val="${answer//\/\\}"
    escaped_val="${escaped_val//&/\&}"

    if grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$PROJECT_ENV_CONFIG"; then
        sed -i.bak "s|^${key}=.*|${key}=${escaped_val}|" "$PROJECT_ENV_CONFIG"
    else
        printf '\n%s=%s\n' "$key" "$escaped_val" >> "$PROJECT_ENV_CONFIG"
    fi
    rm -f "${PROJECT_ENV_CONFIG}.bak"
}

if [[ -f "$PROJECT_ENV_CONFIG" ]]; then
    echo ""
    echo "--- Project-wide configuration ---"
    prompt_env_value "APP_SLUG"    "Project slug (used for container prefixes, image tags)"        "ideable"
    prompt_env_value "APP_NAME"    "Project name (human-readable, used in UI labels)"           "Ideable"
    prompt_env_value "EXTERNAL_BASE_HOST" "Public DNS / hostname for external access"                "localhost"

fi

echo ""
echo "========================================"
echo "Module initialization complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Review project.env.config — project-wide APP_SLUG/APP_NAME/EXTERNAL_BASE_HOST are editable"
echo "2. Edit modules/$(basename "$MODULE_DIR")/.env.config + .env.secrets — configure module-specific settings"
echo "3. Run ./redeploy.sh to build and deploy"
echo ""
