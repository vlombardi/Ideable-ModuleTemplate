#!/bin/bash
# Initialize a new module from ModuleTemplate
# Usage: ./scripts/module-init.sh NewModuleName [-h|--help]

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 NewModuleName [-h|--help]"
    echo ""
    echo "Initializes a new module from ModuleTemplate, renaming all references"
    echo "from ModuleTemplate/template to the new module name."
    echo ""
    echo "Arguments:"
    echo "  NewModuleName  Name for the new module (must start with a letter,"
    echo "                 contain only letters and numbers, e.g. DigitalShelter)"
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

NEW_NAME="${1:-}"
if [[ -z "$NEW_NAME" ]]; then
    echo "Usage: $0 NewModuleName"
    echo "Example: $0 DigitalShelter"
    exit 1
fi

# Validate module name (alphanumeric only)
if [[ ! "$NEW_NAME" =~ ^[A-Za-z][A-Za-z0-9]*$ ]]; then
    echo "Error: Module name must start with letter and contain only letters and numbers"
    exit 1
fi

OLD_NAME="ModuleTemplate"
OLD_SLUG="template"
OLD_SLUG_CAP="Template"
OLD_SLUG_UPPER="TEMPLATE"
OLD_CSS_PREFIX="template-"
NEW_SLUG=$(echo "$NEW_NAME" | tr '[:upper:]' '[:lower:]')
NEW_SLUG_CAP="$(echo "${NEW_SLUG:0:1}" | tr '[:lower:]' '[:upper:]')${NEW_SLUG:1}"
NEW_SLUG_UPPER=$(echo "$NEW_SLUG" | tr '[:lower:]' '[:upper:]')
NEW_CSS_PREFIX="${NEW_SLUG}-"

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

# Update HostApp modules_menu_mapping.json to reference the new module
HOSTAPP_MAPPING="${PROJECT_ROOT}/modules/HostApp/config/modules_menu_mapping.json"
if [[ -f "$HOSTAPP_MAPPING" ]]; then
    sed -i.bak \
        -e "s/\"menu_item_code\": \"${OLD_SLUG_UPPER}\"/\"menu_item_code\": \"${NEW_SLUG_UPPER}\"/g" \
        -e "s/\"menu_item_name\": \"${OLD_SLUG_CAP}\"/\"menu_item_name\": \"${NEW_SLUG_CAP}\"/g" \
        -e "s/\"authorization_claim\": \"${OLD_SLUG}:menu_access\"/\"authorization_claim\": \"${NEW_SLUG}:menu_access\"/g" \
        -e "s/\"module\": \"${OLD_SLUG}\"/\"module\": \"${NEW_SLUG}\"/g" \
        -e "s/\"module_menu_item_code_path\": \"${OLD_SLUG_UPPER}\"/\"module_menu_item_code_path\": \"${NEW_SLUG_UPPER}\"/g" \
        "$HOSTAPP_MAPPING"
    rm -f "${HOSTAPP_MAPPING}.bak"
    echo "Updated HostApp modules_menu_mapping.json"
fi

# Update all source files for name/slug replacements (SPECS are generic, no substitution needed)
find "$MODULE_DIR" -type f \( -name "*.py" -o -name "*.tsx" -o -name "*.ts" -o -name "*.json" -o -name "*.yml" -o -name "*.yaml" -o -name "*.sh" \) | while read -r file; do
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

# Rewrite modules/enabled.md: HostApp remote + NEW_NAME local (idempotent)
ENABLED_MD="${PROJECT_ROOT}/modules/enabled.md"
printf '%s\n' \
    '# Enabled Modules' \
    '' \
    '# List modules that should be built, deployed, executed, and tested' \
    '# Comment out or remove modules that should be disabled' \
    '# Use enabled-remote for modules without local SOURCES/ (pre-built images)' \
    '' \
    'HostApp: enabled-remote' \
    "${NEW_NAME}: enabled" \
    > "$ENABLED_MD"
echo "Updated modules/enabled.md"

# Create modules/HostApp/.env.config + .env.secrets from examples if not already present
HOSTAPP_ENV_CONFIG_EXAMPLE="${PROJECT_ROOT}/modules/HostApp/.env.config.example"
HOSTAPP_ENV_CONFIG="${PROJECT_ROOT}/modules/HostApp/.env.config"
HOSTAPP_ENV_SECRETS_EXAMPLE="${PROJECT_ROOT}/modules/HostApp/.env.secrets.example"
HOSTAPP_ENV_SECRETS="${PROJECT_ROOT}/modules/HostApp/.env.secrets"

for pair in "$HOSTAPP_ENV_CONFIG_EXAMPLE:$HOSTAPP_ENV_CONFIG" "$HOSTAPP_ENV_SECRETS_EXAMPLE:$HOSTAPP_ENV_SECRETS"; do
    EXAMPLE_FILE="${pair%%:*}"
    DEST_FILE="${pair##*:}"
    if [[ -f "$EXAMPLE_FILE" ]]; then
        if [[ ! -f "$DEST_FILE" ]]; then
            cp "$EXAMPLE_FILE" "$DEST_FILE"
            echo "Created modules/HostApp/$(basename "$DEST_FILE") from $(basename "$EXAMPLE_FILE")"
        else
            while IFS= read -r line; do
                if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
                    continue
                fi

                key=$(printf '%s' "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
                [[ -z "$key" ]] && continue

                if ! grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$DEST_FILE"; then
                    printf '\n%s\n' "$line" >> "$DEST_FILE"
                    echo "Added missing env var to modules/HostApp/$(basename "$DEST_FILE"): ${key}"
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
