#!/bin/bash
# Initialize a new module from ModuleTemplate
# Usage: ./scripts/module-init.sh NewModuleName

set -euo pipefail

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

# Update .env.example and create .env
ENV_EXAMPLE="${MODULE_DIR}/.env.example"
ENV_FILE="${MODULE_DIR}/.env"

if [[ -f "$ENV_EXAMPLE" ]]; then
    if [[ ! -f "$ENV_FILE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        echo "Created .env from .env.example"
    fi
    
    # Update module identity and VITE_* variables in .env
    UPPER_SLUG=$(echo "$NEW_SLUG" | tr '[:lower:]' '[:upper:]')
    sed -i.bak "s/VITE_TEMPLATE_/VITE_${UPPER_SLUG}_/g" "$ENV_FILE"
    sed -i.bak "s/TEMPLATE_/${UPPER_SLUG}_/g" "$ENV_FILE"
    sed -i.bak "s/${OLD_SLUG}/${NEW_SLUG}/g" "$ENV_FILE"
    sed -i.bak "s/${OLD_NAME}/${NEW_NAME}/g" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
    echo "Updated .env with module identity (${NEW_NAME}, ${NEW_SLUG}) and ${UPPER_SLUG}_* variables"
fi

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

# Create modules/HostApp/.env from .env.example if not already present
HOSTAPP_ENV_EXAMPLE="${PROJECT_ROOT}/modules/HostApp/.env.example"
HOSTAPP_ENV="${PROJECT_ROOT}/modules/HostApp/.env"
if [[ -f "$HOSTAPP_ENV_EXAMPLE" ]]; then
    if [[ ! -f "$HOSTAPP_ENV" ]]; then
        cp "$HOSTAPP_ENV_EXAMPLE" "$HOSTAPP_ENV"
        echo "Created modules/HostApp/.env from .env.example"
    else
        while IFS= read -r line; do
            if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
                continue
            fi

            key=$(printf '%s' "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
            [[ -z "$key" ]] && continue

            if ! grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$HOSTAPP_ENV"; then
                printf '\n%s\n' "$line" >> "$HOSTAPP_ENV"
                echo "Added missing env var to modules/HostApp/.env: ${key}"
            fi
        done < "$HOSTAPP_ENV_EXAMPLE"
    fi
fi

# Create or merge repo-root project.env from project.env.example
PROJECT_ENV_EXAMPLE="${PROJECT_ROOT}/project.env.example"
PROJECT_ENV="${PROJECT_ROOT}/project.env"

if [[ ! -f "$PROJECT_ENV_EXAMPLE" ]]; then
    echo "Error: project.env.example not found at ${PROJECT_ENV_EXAMPLE}"
    exit 1
fi

if [[ ! -f "$PROJECT_ENV" ]]; then
    cp "$PROJECT_ENV_EXAMPLE" "$PROJECT_ENV"
    echo "Created project.env from project.env.example"
else
    while IFS= read -r line; do
        if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
            continue
        fi

        key=$(printf '%s' "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
        [[ -z "$key" ]] && continue

        if ! grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$PROJECT_ENV"; then
            printf '\n%s\n' "$line" >> "$PROJECT_ENV"
            echo "Added missing env var to project.env: ${key}"
        fi
    done < "$PROJECT_ENV_EXAMPLE"
fi

if [[ -f "$PROJECT_ENV" ]]; then
    PROJECT_ROOT_ESCAPED="${PROJECT_ROOT//\\/\\\\}"
    PROJECT_ROOT_ESCAPED="${PROJECT_ROOT_ESCAPED//&/\\&}"
    DATA_FOLDER_VALUE="${PROJECT_ROOT}/deployment_root/data"
    DATA_FOLDER_ESCAPED="${DATA_FOLDER_VALUE//\\/\\\\}"
    DATA_FOLDER_ESCAPED="${DATA_FOLDER_ESCAPED//&/\\&}"

    if grep -qE '^(export[[:space:]]+)?PROJECT_ROOT[[:space:]]*=' "$PROJECT_ENV"; then
        sed -i.bak -e "s|^PROJECT_ROOT=.*|PROJECT_ROOT=${PROJECT_ROOT_ESCAPED}|" "$PROJECT_ENV"
    else
        printf '\nPROJECT_ROOT=%s\n' "$PROJECT_ROOT_ESCAPED" >> "$PROJECT_ENV"
    fi

    if grep -qE '^(export[[:space:]]+)?DATA_FOLDER[[:space:]]*=' "$PROJECT_ENV"; then
        sed -i.bak -e "s|^DATA_FOLDER=.*|DATA_FOLDER=${DATA_FOLDER_ESCAPED}|" "$PROJECT_ENV"
    else
        printf '\nDATA_FOLDER=%s\n' "$DATA_FOLDER_ESCAPED" >> "$PROJECT_ENV"
    fi

    rm -f "${PROJECT_ENV}.bak"
fi

echo ""
echo "========================================"
echo "Module initialization complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Review project.env — project-wide APP_SLUG/APP_NAME are editable; PROJECT_ROOT/DATA_FOLDER are auto-filled"
echo "2. Edit modules/$(basename "$MODULE_DIR")/.env — configure module-specific settings"
echo "3. Run ./redeploy.sh to build and deploy"
echo ""
