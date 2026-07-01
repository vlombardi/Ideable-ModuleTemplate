#!/bin/bash
# Sync updates from Ideable-ModuleTemplate to a customized module
# Usage: ./scripts/sync-template-updates.sh [OPTIONS]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MODULES_DIR="${PROJECT_ROOT}/modules"
TEMPLATE_URL="https://github.com/vlombardi/Ideable-ModuleTemplate.git"
SELECTIVE_MODE=false
FILES_TO_SYNC=""
LIST_CHANGES=false
SYNC_ALL=false
SYNC_REPORT_ENTRIES=()

record_sync_result() {
    local status="$1"
    local file="$2"
    SYNC_REPORT_ENTRIES+=("${status}|${file}")
}

print_sync_report() {
    local total=${#SYNC_REPORT_ENTRIES[@]}
    local untouched_count=0
    local updated_count=0
    local added_count=0
    local removed_count=0
    local skipped_count=0
    local missing_count=0
    echo ""
    echo "Final sync report"
    echo "=================="

    if [[ $total -eq 0 ]]; then
        echo "  [info] No files were processed."
        return
    fi

    local entry status file
    for entry in "${SYNC_REPORT_ENTRIES[@]}"; do
        status="${entry%%|*}"
        file="${entry#*|}"
        case "$status" in
            untouched)
                untouched_count=$((untouched_count + 1))
                echo "  [untouched] $file"
                ;;
            updated)
                updated_count=$((updated_count + 1))
                echo "  [updated]   $file"
                ;;
            added)
                added_count=$((added_count + 1))
                echo "  [added]     $file"
                ;;
            removed)
                removed_count=$((removed_count + 1))
                echo "  [removed]   $file"
                ;;
            skipped)
                skipped_count=$((skipped_count + 1))
                echo "  [skipped]   $file"
                ;;
            missing)
                missing_count=$((missing_count + 1))
                echo "  [missing]   $file"
                ;;
            *)
                echo "  [${status}] $file"
                ;;
        esac
    done

    echo ""
    echo "Summary"
    echo "-------"
    echo "  Processed: $total"
    echo "  Untouched: $untouched_count"
    echo "  Updated:   $updated_count"
    echo "  Added:     $added_count"
    echo "  Removed:   $removed_count"
    echo "  Skipped:   $skipped_count"
    echo "  Missing:    $missing_count"
}

# Detect the actual module name by finding a modules/* directory whose module.json
# has "role": "remote". Falls back to any non-framework directory with a module.json.
DETECT_MODULE_NAME() {
    local module_name=""
    local fallback_name=""
    for dir in "$MODULES_DIR"/*/; do
        if [[ -d "$dir" ]]; then
            local name=$(basename "$dir")
            local module_json="${dir}module.json"
            if [[ -f "$module_json" ]]; then
                if grep -q '"role"[[:space:]]*:[[:space:]]*"remote"' "$module_json" 2>/dev/null; then
                    module_name="$name"
                    break
                fi
                if [[ "$name" != "ModuleTemplate" && "$name" != "HostApp" && -z "$fallback_name" ]]; then
                    fallback_name="$name"
                fi
            fi
        fi
    done
    echo "${module_name:-$fallback_name}"
}

MODULE_NAME=$(DETECT_MODULE_NAME)
TEMPLATE_MODULE_NAME="ModuleTemplate"

if [[ -z "$MODULE_NAME" ]]; then
    MODULE_NAME="ModuleTemplate"
fi

echo "Detected module: $MODULE_NAME"

# Guard: this script is for derived module repos, not the main project or the raw template repo.
if [[ -d "${PROJECT_ROOT}/modules/ModuleTemplate" ]]; then
    echo "ERROR: This script must not be run inside the Ideable main project or the ModuleTemplate repo."
    echo "It is designed for derived module repos (e.g., modules/SRA, modules/MyModule)."
    echo "Running it here would delete maintainer-only files that are not present in the template."
    exit 1
fi

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Sync updates from Ideable-ModuleTemplate template to your module.

OPTIONS:
    --selective          Interactive mode
    --file FILE          Sync a specific file
    --list-changes       Show what differs without applying
    -a, --all            Also overwrite branding files (favicon.*, login_bg.png, home.html)
                         that are otherwise preserved to allow per-project customization
    --help               Show this help

EXAMPLES:
    $0 --list-changes
    $0 --file scripts/module-init.sh
    $0 --selective
    $0 --all
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --selective)
            SELECTIVE_MODE=true
            shift
            ;;
        --file)
            FILES_TO_SYNC="$2"
            shift 2
            ;;
        --list-changes)
            LIST_CHANGES=true
            shift
            ;;
        -a|--all)
            SYNC_ALL=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Add template remote if not exists
if ! git remote | grep -q "^template$"; then
    echo "Adding template remote: $TEMPLATE_URL"
    git remote add template "$TEMPLATE_URL"
fi

echo "Fetching latest template changes..."
git fetch template main

# Use FETCH_HEAD directly as the template ref — no checkout needed
TEMP_BRANCH="FETCH_HEAD"

echo ""
echo "Your module: $MODULE_NAME"
echo "Template: $TEMPLATE_MODULE_NAME"
echo ""

# Branding files that are typically customized per project.
# Synced only when --all is passed; skipped by default.
is_branding_file() {
    local file="$1"
    [[ "$file" == modules/HostApp/config/favicon.* ]] || \
    [[ "$file" == modules/HostApp/config/login_bg.png ]] || \
    [[ "$file" == modules/HostApp/config/home.html ]] || \
    [[ "$file" == modules/HostApp/config/modules_menu_mapping.json ]] || \
    [[ "$file" == modules/HostApp/config/module-registry.json ]]
}

# HostApp config files are free for developers to customize; never remove them.
is_hostapp_config_file() {
    local file="$1"
    [[ "$file" == modules/HostApp/config/* ]]
}

# Infrastructure detection
is_template_module_file() {
    local file="$1"
    [[ "$file" == modules/${TEMPLATE_MODULE_NAME}/* ]]
}

is_infrastructure() {
    local file="$1"
    [[ "$file" == scripts/* ]] || \
    [[ "$file" == "AGENTS.md" ]] || \
    [[ "$file" == "CLAUDE.md" ]] || \
    [[ "$file" == "IDEABLE-README.md" ]] || \
    [[ "$file" == "MODULE-README.md" ]] || \
    [[ "$file" == ".agents/"* ]] || \
    [[ "$file" == ".kiro/"* ]] || \
    [[ "$file" == ".claude/"* ]] || \
    [[ "$file" == ".devin/"* ]] || \
    [[ "$file" == ".cursor/"* ]] || \
    [[ "$file" == ".github/"* ]] || \
    [[ "$file" == "rules/"* ]] || \
    [[ "$file" == "redeploy.sh" ]] || \
    [[ "$file" == "start.sh" ]] || \
    [[ "$file" == "stop.sh" ]] || \
    [[ "$file" == "status.sh" ]] || \
    [[ "$file" == "update_backend.sh" ]] || \
    [[ "$file" == "update_frontend.sh" ]] || \
    [[ "$file" == ".gitignore" ]] || \
    [[ "$file" == modules/*/.env.example ]] || \
    [[ "$file" == modules/*/.env.config.example ]] || \
    [[ "$file" == modules/*/.env.secrets.example ]] || \
    [[ "$file" == modules/HostApp/.env.example ]] || \
    [[ "$file" == modules/HostApp/module.json ]] || \
    [[ "$file" == modules/HostApp/docker-compose.yml ]] || \
    [[ "$file" == modules/HostApp/config/* ]] || \
    [[ "$file" == modules/HostApp/database/* ]] || \
    [[ "$file" == "project.env.example" ]] || \
    [[ "$file" == "project.env.config.example" ]] || \
    [[ "$file" == "project.env.secrets.example" ]] && ! is_template_module_file "$file"
}

is_shared_template_spec_file() {
    local file="$1"
    [[ "$file" == "modules/ModuleTemplate/SPECS/ideable-framework-specs/base-specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/SPECS/ideable-framework-specs/auth-specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/SPECS/ideable-framework-specs/module-integration-specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/SPECS/ideable-framework-specs/infrastructure-file-list.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/backend/SPECS/ideable-framework-specs/base-specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/database/SPECS/ideable-framework-specs/base-specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/base_specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md" ]] || \
    [[ "$file" == "modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md" ]]
}

# .env merge: add vars from template that are missing locally; preserve existing values.
# Lines that are comments or blank are added only if the key block is new.
is_env_file() {
    local file="$1"
    if [[ "$file" == modules/*/.env.example ]] || \
       [[ "$file" == modules/*/.env.config.example ]] || \
       [[ "$file" == modules/*/.env.secrets.example ]] || \
       [[ "$file" == "project.env.config.example" ]] || \
       [[ "$file" == "project.env.secrets.example" ]]; then
        is_template_module_file "$file" && return 1
        return 0
    fi
    return 1
}

is_module_env_example_path() {
    local file="$1"
    [[ "$file" == "modules/${MODULE_NAME}/.env.example" ]] || \
    [[ "$file" == "modules/${MODULE_NAME}/.env.config.example" ]] || \
    [[ "$file" == "modules/${MODULE_NAME}/.env.secrets.example" ]]
}

is_template_env_example_path() {
    local file="$1"
    [[ "$file" == "modules/${TEMPLATE_MODULE_NAME}/.env.example" ]] || \
    [[ "$file" == "modules/${TEMPLATE_MODULE_NAME}/.env.config.example" ]] || \
    [[ "$file" == "modules/${TEMPLATE_MODULE_NAME}/.env.secrets.example" ]]
}

resolve_template_env_example_source() {
    local file="$1"
    if is_module_env_example_path "$file"; then
        local filename
        filename="${file##*/}"
        echo "modules/${TEMPLATE_MODULE_NAME}/${filename}"
        return 0
    fi
    echo "$file"
}

resolve_local_env_example_destination() {
    local file="$1"
    if is_template_env_example_path "$file"; then
        local filename
        filename="${file##*/}"
        echo "modules/${MODULE_NAME}/${filename}"
        return 0
    fi
    echo "$file"
}

is_custom_readme() {
    local file="$1"
    [[ "$file" == "README.md" ]] || [[ "$file" == "modules/${MODULE_NAME}/README.md" ]]
}

is_module_readme() {
    local file="$1"
    [[ "$file" == "modules/${MODULE_NAME}/README.md" ]]
}

should_create_missing_infrastructure_file() {
    local file="$1"

    if is_custom_readme "$file"; then
        return 1
    fi

    if is_module_readme "$file"; then
        return 1
    fi

    if is_hostapp_config_file "$file"; then
        return 0
    fi

    if is_infrastructure "$file" || is_shared_template_spec_file "$file"; then
        return 0
    fi

    return 1
}

merge_env_file() {
    local template_content="$1"   # content of template .env (as string)
    local local_file="$2"         # path to local .env

    if [[ ! -f "$local_file" ]]; then
        echo "$template_content" > "$local_file"
        echo "  [created]  $local_file"
        return
    fi

    local added=0
    local pending_comments=""

    while IFS= read -r line; do
        # Blank line or comment — buffer for context
        if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
            pending_comments="${pending_comments}${line}"$'\n'
            continue
        fi

        # Extract key (handle KEY=value and export KEY=value)
        local key
        key=$(echo "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
        [[ -z "$key" ]] && { pending_comments=""; continue; }

        # Check if key already exists locally (with or without export prefix)
        if grep -qE "^(export[[:space:]]+)?${key}[[:space:]]*=" "$local_file" 2>/dev/null; then
            pending_comments=""
            continue
        fi

        # New key — append comment block + the line
        {
            echo ""
            printf '%s' "$pending_comments"
            echo "$line"
        } >> "$local_file"
        added=$((added + 1))
        pending_comments=""
    done <<< "$template_content"

    if [[ $added -gt 0 ]]; then
        echo "  [merged]   $local_file ($added new var(s) added)"
    else
        echo "  [up-to-date] $local_file"
    fi
}

sync_env_content_to_file() {
    local template_content="$1"
    local local_path="$2"

    if [[ ! -f "$local_path" ]]; then
        mkdir -p "$(dirname "$local_path")"
        printf '%s\n' "$template_content" > "$local_path"
        echo "  [added]    $local_path"
        record_sync_result "added" "$local_path"
        return 0
    fi

    local before_tmp after_tmp
    before_tmp=$(mktemp)
    after_tmp=$(mktemp)
    cp "$local_path" "$before_tmp"

    merge_env_file "$template_content" "$local_path"

    cp "$local_path" "$after_tmp"
    if cmp -s "$before_tmp" "$after_tmp"; then
        record_sync_result "untouched" "$local_path"
    else
        record_sync_result "updated" "$local_path"
    fi

    rm -f "$before_tmp" "$after_tmp"
}

sync_regular_file_from_template() {
    local template_path="$1"
    local local_path="$2"

    local template_tmp local_tmp
    template_tmp=$(mktemp)

    local template_exists=true

    if ! git show "${TEMP_BRANCH}:${template_path}" > "$template_tmp" 2>/dev/null; then
        rm -f "$template_tmp"
        template_exists=false
    fi

    if [[ "$template_exists" == false ]]; then
        if should_create_missing_infrastructure_file "$local_path"; then
            mkdir -p "$(dirname "$local_path")"
            if [[ -f "$local_path" ]]; then
                echo "  [up-to-date] $local_path"
                record_sync_result "untouched" "$local_path"
                return 0
            fi

            : > "$local_path"
            echo "  [added]    $local_path (created empty infrastructure placeholder because template file is missing)"
            record_sync_result "added" "$local_path"
            return 0
        fi

        echo "  [missing]  $local_path (not in template, skipping)"
        record_sync_result "missing" "$local_path"
        return 1
    fi

    if [[ -f "$local_path" ]]; then
        # Skip custom README.md files if they already exist locally
        if is_custom_readme "$local_path"; then
            echo "  [skipped]  $local_path (custom README already exists, preserving local version)"
            record_sync_result "skipped" "$local_path"
            rm -f "$template_tmp"
            return 0
        fi

        if is_module_readme "$local_path"; then
            echo "  [skipped]  $local_path (module README is custom content and is never overwritten by template sync)"
            record_sync_result "skipped" "$local_path"
            rm -f "$template_tmp"
            return 0
        fi

        # HostApp authorization.yaml may be customized by the operator after initial sync;
        # pull from template only when the file is missing locally.
        if [[ "$local_path" == "modules/HostApp/config/authorization.yaml" ]]; then
            echo "  [skipped]  $local_path (already exists locally; skipping to preserve operator customizations)"
            record_sync_result "skipped" "$local_path"
            rm -f "$template_tmp"
            return 0
        fi

        local_tmp=$(mktemp)
        cp "$local_path" "$local_tmp"
        if cmp -s "$template_tmp" "$local_tmp"; then
            echo "  [up-to-date] $local_path"
            record_sync_result "untouched" "$local_path"
            rm -f "$template_tmp" "$local_tmp"
            return 0
        fi
        rm -f "$local_tmp"
        cp "$template_tmp" "$local_path"
        chmod +x "$local_path" 2>/dev/null || true
        echo "  [updated]  $local_path"
        record_sync_result "updated" "$local_path"
    else
        mkdir -p "$(dirname "$local_path")"
        cp "$template_tmp" "$local_path"
        chmod +x "$local_path" 2>/dev/null || true
        echo "  [added]    $local_path"
        record_sync_result "added" "$local_path"
    fi

    rm -f "$template_tmp"
}

force_sync_regular_file_from_template() {
    local template_path="$1"
    local local_path="$2"

    local template_tmp
    template_tmp=$(mktemp)
    local template_exists=true

    if ! git show "${TEMP_BRANCH}:${template_path}" > "$template_tmp" 2>/dev/null; then
        rm -f "$template_tmp"
        template_exists=false
    fi

    if [[ "$template_exists" == false ]]; then
        if should_create_missing_infrastructure_file "$local_path"; then
            mkdir -p "$(dirname "$local_path")"
            if [[ -f "$local_path" ]]; then
                echo "  [up-to-date] $local_path"
                record_sync_result "untouched" "$local_path"
                return 0
            fi

            : > "$local_path"
            echo "  [added]    $local_path (created empty infrastructure placeholder because template file is missing)"
            record_sync_result "added" "$local_path"
            return 0
        fi

        echo "  [missing]  $local_path (not in template, skipping)"
        record_sync_result "missing" "$local_path"
        return 1
    fi

    if [[ -f "$local_path" ]]; then
        local local_tmp
        local_tmp=$(mktemp)
        cp "$local_path" "$local_tmp"
        if cmp -s "$template_tmp" "$local_tmp"; then
            echo "  [up-to-date] $local_path"
            record_sync_result "untouched" "$local_path"
            rm -f "$template_tmp" "$local_tmp"
            return 0
        fi
        rm -f "$local_tmp"
        cp "$template_tmp" "$local_path"
        chmod +x "$local_path" 2>/dev/null || true
        echo "  [updated]  $local_path"
        record_sync_result "updated" "$local_path"
    else
        mkdir -p "$(dirname "$local_path")"
        cp "$template_tmp" "$local_path"
        chmod +x "$local_path" 2>/dev/null || true
        echo "  [added]    $local_path"
        record_sync_result "added" "$local_path"
    fi

    rm -f "$template_tmp"
}

sync_env_file_from_template() {
    local template_path="$1"
    local local_path="$2"

    local template_content
    template_content=$(git show "${TEMP_BRANCH}:${template_path}" 2>/dev/null) || {
        echo "  [missing]  $local_path (not in template, skipping)"
        record_sync_result "missing" "$local_path"
        return 1
    }

    sync_env_content_to_file "$template_content" "$local_path"
}

get_module_slug() {
    local module_json="modules/${MODULE_NAME}/module.json"
    local slug

    if [[ -f "$module_json" ]]; then
        slug=$(grep -o '"slug"[[:space:]]*:[[:space:]]*"[^"]*"' "$module_json" 2>/dev/null | head -1 | sed 's/.*"slug"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
        if [[ -n "$slug" ]]; then
            echo "$slug"
            return 0
        fi
    fi

    echo "$MODULE_NAME" | tr '[:upper:]-' '[:lower:]_'
}

get_module_db_prefix() {
    local env_file prefix

    for env_file in "modules/${MODULE_NAME}/.env.config" "modules/${MODULE_NAME}/.env.config.example"; do
        if [[ -f "$env_file" ]]; then
            prefix=$(awk -F= '/^[A-Z0-9_]+_ENTITIES_DB_HOST[[:space:]]*=/ { sub(/_ENTITIES_DB_HOST[[:space:]]*$/, "", $1); print $1; exit }' "$env_file")
            if [[ -n "$prefix" ]]; then
                echo "$prefix"
                return 0
            fi
        fi
    done

    echo "$(get_module_slug | tr '[:lower:]-' '[:upper:]_')"
}

render_managed_compose_block() {
    local template_compose_path="$1"
    local marker_name="$2"
    local module_slug="$3"
    local module_db_prefix="$4"

    awk -v marker_name="$marker_name" '
        index($0, "SYNC-MANAGED-BEGIN: " marker_name) { in_block = 1; print; next }
        in_block { print; if (index($0, "SYNC-MANAGED-END: " marker_name)) exit }
    ' "$template_compose_path" |
        sed \
            -e "s/TEMPLATE_/${module_db_prefix}_/g" \
            -e "s/template/${module_slug}/g" \
            -e "s/template_datamodel_v1/${module_slug}_datamodel_v1/g" \
            -e "s/template_seed_v1/${module_slug}_seed_v1/g"
}

sync_managed_compose_block() {
    local template_compose_path="$1"
    local local_compose_path="$2"
    local marker_name="$3"
    local module_slug="$4"
    local module_db_prefix="$5"

    [[ -f "$template_compose_path" && -f "$local_compose_path" ]] || return 0

    if ! grep -q "SYNC-MANAGED-BEGIN: ${marker_name}" "$local_compose_path" 2>/dev/null; then
        return 0
    fi

    local block_tmp before_tmp after_tmp
    block_tmp=$(mktemp)
    before_tmp=$(mktemp)
    after_tmp=$(mktemp)

    render_managed_compose_block "$template_compose_path" "$marker_name" "$module_slug" "$module_db_prefix" > "$block_tmp"
    cp "$local_compose_path" "$before_tmp"

    awk -v block_file="$block_tmp" -v marker_name="$marker_name" '
        BEGIN {
            while ((getline line < block_file) > 0) {
                block[++count] = line
            }
            close(block_file)
            begin_marker = "SYNC-MANAGED-BEGIN: " marker_name
            end_marker = "SYNC-MANAGED-END: " marker_name
            in_managed = 0
            replaced = 0
        }
        index($0, begin_marker) {
            for (i = 1; i <= count; i++) print block[i]
            replaced = 1
            in_managed = 1
            next
        }
        in_managed {
            if (index($0, end_marker)) {
                in_managed = 0
            }
            next
        }
        { print }
        END {
            if (!replaced) exit 1
        }
    ' "$local_compose_path" > "$after_tmp"

    if cmp -s "$before_tmp" "$after_tmp"; then
        record_sync_result "untouched" "$local_compose_path"
    else
        cp "$after_tmp" "$local_compose_path"
        chmod +x "$local_compose_path" 2>/dev/null || true
        record_sync_result "updated" "$local_compose_path"
        echo "  [updated]  $local_compose_path (synced managed compose block: ${marker_name})"
    fi

    rm -f "$block_tmp" "$before_tmp" "$after_tmp"
}

sync_managed_compose_sections() {
    local template_compose_path="$1"
    local local_compose_path="$2"
    local module_slug="$3"
    local module_db_prefix="$4"

    local markers=(
        "bootstrap-service"
        "database-service"
        "backend-service"
        "frontend-service"
        "top-level-networks"
        "top-level-volumes"
    )

    local marker_name
    for marker_name in "${markers[@]}"; do
        sync_managed_compose_block "$template_compose_path" "$local_compose_path" "$marker_name" "$module_slug" "$module_db_prefix"
    done
}

sync_example_to_matching_env() {
    local example_file="$1"
    local local_env_file="${example_file%.example}"

    if [[ ! -f "$example_file" ]]; then
        return
    fi

    local example_content
    example_content=$(cat "$example_file")
    sync_env_content_to_file "$example_content" "$local_env_file"
}

get_env_value() {
    local file="$1"
    local key="$2"

    awk -v wanted_key="$key" '
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            split(line, parts, "=")
            current_key = parts[1]
            sub(/^[[:space:]]+/, "", current_key)
            sub(/[[:space:]]+$/, "", current_key)
            if (current_key == wanted_key) {
                value = $0
                sub(/^[[:space:]]*export[[:space:]]+/, "", value)
                sub("^[[:space:]]*" wanted_key "[[:space:]]*=[[:space:]]*", "", value)
                print value
                exit
            }
        }
    ' "$file"
}

set_env_key_value() {
    local file="$1"
    local key="$2"
    local value="$3"

    local tmp
    tmp=$(mktemp)

    awk -v wanted_key="$key" -v wanted_value="$value" '
        BEGIN { replaced = 0 }
        /^[[:space:]]*#/ { print; next }
        /^[[:space:]]*$/ { print; next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            split(line, parts, "=")
            current_key = parts[1]
            sub(/[[:space:]]+$/, "", current_key)
            sub(/^[[:space:]]+/, "", current_key)
            if (current_key == wanted_key) {
                print wanted_key "=" wanted_value
                replaced = 1
            } else {
                print $0
            }
        }
        END {
            if (!replaced) {
                print wanted_key "=" wanted_value
            }
        }
    ' "$file" > "$tmp"

    mv "$tmp" "$file"
}

remove_env_key() {
    local file="$1"
    local key="$2"

    local tmp
    tmp=$(mktemp)

    awk -v wanted_key="$key" '
        /^[[:space:]]*#/ { print; next }
        /^[[:space:]]*$/ { print; next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            split(line, parts, "=")
            current_key = parts[1]
            sub(/[[:space:]]+$/, "", current_key)
            sub(/^[[:space:]]+/, "", current_key)
            if (current_key != wanted_key) {
                print $0
            }
        }
    ' "$file" > "$tmp"

    mv "$tmp" "$file"
}

reconcile_env_example_with_matching_env() {
    local example_file="$1"
    local env_file="${example_file%.example}"

    if [[ ! -f "$env_file" ]]; then
        return 0
    fi

    local example_keys_tmp env_keys_tmp common_keys removed_keys key
    example_keys_tmp=$(mktemp)
    env_keys_tmp=$(mktemp)

    extract_env_keys "$example_file" > "$example_keys_tmp"
    extract_env_keys "$env_file" > "$env_keys_tmp"

    common_keys=$(comm -12 "$example_keys_tmp" "$env_keys_tmp" || true)
    removed_keys=$(comm -23 "$env_keys_tmp" "$example_keys_tmp" || true)

    if [[ -z "$common_keys" && -z "$removed_keys" ]]; then
        rm -f "$example_keys_tmp" "$env_keys_tmp"
        return 0
    fi

    echo ""
    echo "Reconciling ${env_file} against ${example_file}"

    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        local example_value env_value choice
        example_value=$(get_env_value "$example_file" "$key")
        env_value=$(get_env_value "$env_file" "$key")

        if [[ "$example_value" != "$env_value" ]]; then
            echo "  [changed] $key"
            echo "    .env.example: $example_value"
            echo "    .env:         $env_value"
            read -rp "    Overwrite .env with .env.example value? [y/N]: " choice
            if [[ "$choice" =~ ^[Yy]$ ]]; then
                set_env_key_value "$env_file" "$key" "$example_value"
                echo "    -> overwritten"
            else
                echo "    -> kept"
            fi
        fi
    done <<< "$common_keys"

    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        local choice
        echo "  [removed] $key is no longer present in .env.example"
        read -rp "    Remove it from .env? [y/N]: " choice
        if [[ "$choice" =~ ^[Yy]$ ]]; then
            remove_env_key "$env_file" "$key"
            echo "    -> removed"
        else
            echo "    -> kept"
        fi
    done <<< "$removed_keys"

    rm -f "$example_keys_tmp" "$env_keys_tmp"
}

extract_env_keys() {
    local file="$1"

    awk '
        /^[[:space:]]*$/ { next }
        /^[[:space:]]*#/ { next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            sub(/[[:space:]]+#.*$/, "", line)
            split(line, parts, "=")
            key = parts[1]
            sub(/^[[:space:]]+/, "", key)
            sub(/[[:space:]]+$/, "", key)
            if (key != "") print key
        }
    ' "$file" | sort -u
}

report_env_key_differences() {
    local left_label="$1"
    local left_file="$2"
    local right_label="$3"
    local right_file="$4"
    local heading="${5:-}"
    local left_tmp right_tmp left_only right_only

    if [[ ! -f "$left_file" ]]; then
        echo "  [missing] $left_label not found: $left_file"
        return
    fi

    if [[ ! -f "$right_file" ]]; then
        echo "  [missing] $right_label not found: $right_file"
        return
    fi

    left_tmp=$(mktemp)
    right_tmp=$(mktemp)

    extract_env_keys "$left_file" > "$left_tmp"
    extract_env_keys "$right_file" > "$right_tmp"

    left_only=$(comm -23 "$left_tmp" "$right_tmp" || true)
    right_only=$(comm -13 "$left_tmp" "$right_tmp" || true)

    rm -f "$left_tmp" "$right_tmp"

    if [[ -n "$heading" ]]; then
        echo "$heading"
    fi

    if [[ -z "$left_only" && -z "$right_only" ]]; then
        echo "  [ok] $left_label and $right_label are aligned"
        return
    fi

    if [[ -n "$left_only" ]]; then
        echo "  - Present only in $left_label (remove these to match $right_label):"
        while IFS= read -r key; do
            [[ -n "$key" ]] && echo "    - $key"
        done <<< "$left_only"
    fi

    if [[ -n "$right_only" ]]; then
        echo "  - Present only in $right_label (add these to $left_label to match $right_label):"
        while IFS= read -r key; do
            [[ -n "$key" ]] && echo "    - $key"
        done <<< "$right_only"
    fi
}

report_env_alignment() {
    local module_config_example="${PROJECT_ROOT}/modules/${MODULE_NAME}/.env.config.example"
    local module_config="${PROJECT_ROOT}/modules/${MODULE_NAME}/.env.config"
    local module_secrets_example="${PROJECT_ROOT}/modules/${MODULE_NAME}/.env.secrets.example"
    local module_secrets="${PROJECT_ROOT}/modules/${MODULE_NAME}/.env.secrets"
    local project_config_example="${PROJECT_ROOT}/project.env.config.example"
    local project_config="${PROJECT_ROOT}/project.env.config"
    local project_secrets_example="${PROJECT_ROOT}/project.env.secrets.example"
    local project_secrets="${PROJECT_ROOT}/project.env.secrets"
    local template_module_config_example_tmp
    local template_module_secrets_example_tmp

    echo ""
    echo "Environment variable alignment report"
    echo "====================================="

    # Compare .env.config.example
    template_module_config_example_tmp=$(mktemp)
    if git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/.env.config.example" > "$template_module_config_example_tmp" 2>/dev/null; then
        report_env_key_differences \
            "Local module: .env.config.example" \
            "$module_config_example" \
            "ModuleTemplate repo: .env.config.example" \
            "$template_module_config_example_tmp" \
            "Comparison: ModuleTemplate repo .env.config.example vs local module .env.config.example"
    else
        echo "  [missing] modules/${TEMPLATE_MODULE_NAME}/.env.config.example not found in template"
    fi
    rm -f "$template_module_config_example_tmp"

    echo ""
    # Compare .env.config (local) vs .env.config.example (template)
    template_module_config_example_tmp=$(mktemp)
    if git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/.env.config.example" > "$template_module_config_example_tmp" 2>/dev/null; then
        report_env_key_differences \
            "Local module: .env.config" \
            "$module_config" \
            "ModuleTemplate repo: .env.config.example" \
            "$template_module_config_example_tmp" \
            "Comparison: ModuleTemplate repo .env.config.example vs local module .env.config"
    else
        echo "  [missing] modules/${TEMPLATE_MODULE_NAME}/.env.config.example not found in template"
    fi
    rm -f "$template_module_config_example_tmp"

    echo ""
    # Compare .env.secrets.example
    template_module_secrets_example_tmp=$(mktemp)
    if git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/.env.secrets.example" > "$template_module_secrets_example_tmp" 2>/dev/null; then
        report_env_key_differences \
            "Local module: .env.secrets.example" \
            "$module_secrets_example" \
            "ModuleTemplate repo: .env.secrets.example" \
            "$template_module_secrets_example_tmp" \
            "Comparison: ModuleTemplate repo .env.secrets.example vs local module .env.secrets.example"
    else
        echo "  [missing] modules/${TEMPLATE_MODULE_NAME}/.env.secrets.example not found in template"
    fi
    rm -f "$template_module_secrets_example_tmp"

    echo ""
    # Compare project.env.config.example vs project.env.config
    report_env_key_differences \
        "Project config: project.env.config.example" \
        "$project_config_example" \
        "Project config: project.env.config" \
        "$project_config" \
        "Comparison: project.env.config.example vs project.env.config"

    echo ""
    # Compare project.env.secrets.example vs project.env.secrets
    report_env_key_differences \
        "Project secrets: project.env.secrets.example" \
        "$project_secrets_example" \
        "Project secrets: project.env.secrets" \
        "$project_secrets" \
        "Comparison: project.env.secrets.example vs project.env.secrets"
}

# List changed files
if $LIST_CHANGES; then
    echo "Files that differ between your module and template:"
    echo "================================================"
    
    git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null | while IFS= read -r line; do
        status="${line%%$'\t'*}"
        rest="${line#*$'\t'}"
        if [[ "$status" == R* || "$status" == C* ]]; then
            file="${rest#*$'\t'}"
        else
            file="$rest"
        fi
        if [[ "$file" == *"$TEMPLATE_MODULE_NAME"* ]]; then
            echo "[RENAMED] $file"
            continue
        fi
        
        if is_branding_file "$file"; then
            echo "[BRANDING] $file (skipped by default, use --all to sync)"
        elif is_infrastructure "$file"; then
            echo "[INFRASTRUCTURE] $file"
        else
            echo "[MODULE] $file"
        fi
    done
    
    echo ""
    echo "Run with --file to sync specific files"
    
    exit 0
fi

report_env_alignment

# Sync specific file
if [[ -n "$FILES_TO_SYNC" ]]; then
    echo "Syncing file: $FILES_TO_SYNC"

    if [[ "$FILES_TO_SYNC" == "README.md" ]] || [[ "$FILES_TO_SYNC" == "modules/${MODULE_NAME}/README.md" ]]; then
        echo "Skipping custom README file in consumer repo: $FILES_TO_SYNC"
        true  # FETCH_HEAD ref needs no cleanup
        exit 0
    fi

    if is_template_module_file "$FILES_TO_SYNC"; then
        echo "Skipping template module file in consumer repo: $FILES_TO_SYNC"
        true  # FETCH_HEAD ref needs no cleanup
        exit 0
    fi
    
    LOCAL_PATH="$FILES_TO_SYNC"
    
    # Determine template path
    if [[ "$FILES_TO_SYNC" == *"sync-template-updates.sh" ]]; then
        TEMPLATE_PATH="$FILES_TO_SYNC"
        echo "Note: Self-update requires special handling"
        TEMP_FILE=$(mktemp)
        git show "$TEMP_BRANCH:$TEMPLATE_PATH" > "$TEMP_FILE" 2>/dev/null || {
            echo "Error: File not found in template: $TEMPLATE_PATH"
            true  # FETCH_HEAD ref needs no cleanup
            rm -f "$TEMP_FILE"
            exit 1
        }
        cp "$TEMP_FILE" "$LOCAL_PATH"
        rm -f "$TEMP_FILE"
        chmod +x "$LOCAL_PATH"
        echo "File synced: $FILES_TO_SYNC"
        echo "WARNING: Script updated. Please re-run to use new version."
        record_sync_result "updated" "$LOCAL_PATH"
    elif is_env_file "$FILES_TO_SYNC"; then
        if is_infrastructure "$FILES_TO_SYNC"; then
            TEMPLATE_PATH="$FILES_TO_SYNC"
        else
            TEMPLATE_PATH="modules/$TEMPLATE_MODULE_NAME/$FILES_TO_SYNC"
        fi
        TEMPLATE_PATH="$(resolve_template_env_example_source "$TEMPLATE_PATH")"
        LOCAL_PATH="$FILES_TO_SYNC"
        LOCAL_PATH="$(resolve_local_env_example_destination "$LOCAL_PATH")"
        template_env_content=$(git show "$TEMP_BRANCH:$TEMPLATE_PATH" 2>/dev/null) || {
            echo "Error: File not found in template: $TEMPLATE_PATH"
            true  # FETCH_HEAD ref needs no cleanup
            exit 1
        }
        sync_env_content_to_file "$template_env_content" "${PROJECT_ROOT}/$LOCAL_PATH"
        if [[ "$LOCAL_PATH" == *.env.example ]]; then
            sync_example_to_matching_env "${PROJECT_ROOT}/$LOCAL_PATH"
            reconcile_env_example_with_matching_env "${PROJECT_ROOT}/$LOCAL_PATH"
        fi
    else
        if is_infrastructure "$FILES_TO_SYNC"; then
            TEMPLATE_PATH="$FILES_TO_SYNC"
        else
            TEMPLATE_PATH="modules/$TEMPLATE_MODULE_NAME/$FILES_TO_SYNC"
        fi
        # Extract file from template
        if ! sync_regular_file_from_template "$TEMPLATE_PATH" "$LOCAL_PATH"; then
            true  # FETCH_HEAD ref needs no cleanup
            exit 1
        fi
    fi
    
    echo "Review changes and commit when ready."
    print_sync_report
    true  # FETCH_HEAD ref needs no cleanup
    exit 0
fi

# Default mode: auto-sync all infrastructure files from template
if ! $SELECTIVE_MODE && [[ -z "$FILES_TO_SYNC" ]]; then
    echo "Auto-syncing all infrastructure files from template..."
    echo "======================================================="

    SYNCED=0
    FAILED=0

    while IFS= read -r line; do
        status="${line%%$'\t'*}"
        rest="${line#*$'\t'}"

        # Handle renames (R*) and copies (C*): three tab-separated fields.
        # git diff --name-status FETCH_HEAD reports renames from the template
        # (FETCH_HEAD) to the working tree: R100\t<template_path>\t<working_tree_path>.
        # We mirror the template, so we remove the working-tree path and sync the template path.
        if [[ "$status" == R* || "$status" == C* ]]; then
            template_path="${rest%%$'\t'*}"
            local_path="${rest#*$'\t'}"
            # Remove the working-tree path if it exists and is managed infrastructure
            if is_infrastructure "$local_path" && ! is_template_module_file "$local_path" && ! is_branding_file "$local_path" && ! is_hostapp_config_file "$local_path"; then
                if [[ -e "$local_path" ]]; then
                    rm -rf "$local_path"
                    echo "  [removed]  $local_path (renamed in template)"
                    record_sync_result "removed" "$local_path"
                fi
            fi
            file="$template_path"
        elif [[ "$status" == "A" ]]; then
            # File exists locally but not in the template.
            file="$rest"
            if is_env_file "$file"; then
                template_env_path="$(resolve_template_env_example_source "$file")"
                local_env_path="${PROJECT_ROOT}/$file"
                if sync_env_file_from_template "$template_env_path" "$local_env_path"; then
                    if [[ "$file" == *.env.example ]]; then
                        sync_example_to_matching_env "$local_env_path"
                        reconcile_env_example_with_matching_env "$local_env_path"
                    fi
                    SYNCED=$((SYNCED + 1))
                else
                    FAILED=$((FAILED + 1))
                fi
                continue
            fi

            if is_infrastructure "$file" && ! is_template_module_file "$file" && ! is_branding_file "$file" && ! is_hostapp_config_file "$file"; then
                if [[ -e "$file" ]]; then
                    rm -rf "$file"
                    echo "  [removed]  $file"
                    record_sync_result "removed" "$file"
                    SYNCED=$((SYNCED + 1))
                fi
            fi
            continue
        elif [[ "$status" == "D" || "$status" == "M" ]]; then
            # File exists in the template but not in the working tree (D), or differs (M) — sync from template
            file="$rest"
        else
            continue
        fi

        # Only sync infrastructure files; skip module-specific paths
        if ! is_infrastructure "$file" && ! is_shared_template_spec_file "$file"; then
            continue
        fi

        if is_template_module_file "$file" && ! is_shared_template_spec_file "$file"; then
            continue
        fi

        # Skip branding files unless --all was passed
        if is_branding_file "$file" && ! $SYNC_ALL; then
            echo "  [skipped]  $file (branding file — run with --all to overwrite)"
            record_sync_result "skipped" "$file"
            continue
        fi

        TEMPLATE_PATH="$file"
        LOCAL_PATH="$file"
        if is_env_file "$file"; then
            TEMPLATE_PATH="$(resolve_template_env_example_source "$TEMPLATE_PATH")"
            LOCAL_PATH="$(resolve_local_env_example_destination "$LOCAL_PATH")"
        fi
        if is_shared_template_spec_file "$file"; then
            LOCAL_PATH="${file/modules\/ModuleTemplate/modules/$MODULE_NAME}"
        fi

        # Ensure parent directory exists
        mkdir -p "$(dirname "$LOCAL_PATH")"

        if is_env_file "$file"; then
            local_env_path="${PROJECT_ROOT}/$LOCAL_PATH"
            if sync_env_file_from_template "$TEMPLATE_PATH" "$local_env_path"; then
                if [[ "$LOCAL_PATH" == *.env.example ]]; then
                    sync_example_to_matching_env "$local_env_path"
                    reconcile_env_example_with_matching_env "$local_env_path"
                fi
                SYNCED=$((SYNCED + 1))
            else
                FAILED=$((FAILED + 1))
            fi
        elif sync_regular_file_from_template "$TEMPLATE_PATH" "$LOCAL_PATH"; then
            SYNCED=$((SYNCED + 1))
        else
            FAILED=$((FAILED + 1))
        fi
    done < <(git diff --name-status "$TEMP_BRANCH" 2>/dev/null)

    # Shared contract test files are not always visible in git diff (e.g. newly
    # added files in the template that don't yet exist locally). Always attempt
    # to sync them.
    echo ""
    echo "Syncing shared contract test files..."
    SHARED_TESTS=(
        "frontend/TESTS/test_module_manifest_contract.py"
        "frontend/TESTS/test_i18n_contract.py"
        "frontend/TESTS/test_lf_parity_contract.py"
        "frontend/TESTS/test_template_items_table_contract.py"
        "backend/TESTS/test_auth_permissions_payload.py"
        "database/TESTS/test_datamodel_source_sync.py"
        "database/TESTS/test_authorization_source_sync.py"
        "database/TESTS/test_bootstrap_compose_contract.py"
    )
    for test_file in "${SHARED_TESTS[@]}"; do
        LOCAL_FILE="modules/${MODULE_NAME}/${test_file}"
        TEMPLATE_FILE="modules/ModuleTemplate/${test_file}"
        if sync_regular_file_from_template "$TEMPLATE_FILE" "$LOCAL_FILE"; then
            SYNCED=$((SYNCED + 1))
        else
            FAILED=$((FAILED + 1))
        fi
    done

    echo ""
    echo "Syncing shared framework specs from ideable-framework-specs folders..."
    echo "Skipping non-framework SPECS files so module-specific specs remain untouched."

    SHARED_FRAMEWORK_SPECS=(
        "SPECS/ideable-framework-specs/base-specs.md"
        "SPECS/ideable-framework-specs/auth-specs.md"
        "SPECS/ideable-framework-specs/module-integration-specs.md"
        "SPECS/ideable-framework-specs/infrastructure-file-list.md"
    )
    if [[ -d "modules/${MODULE_NAME}/backend" ]]; then
        SHARED_FRAMEWORK_SPECS+=("backend/SPECS/ideable-framework-specs/base-specs.md")
    fi
    if [[ -d "modules/${MODULE_NAME}/database" ]]; then
        SHARED_FRAMEWORK_SPECS+=("database/SPECS/ideable-framework-specs/base-specs.md")
    fi
    if [[ -d "modules/${MODULE_NAME}/frontend" ]]; then
        SHARED_FRAMEWORK_SPECS+=(
            "frontend/SPECS/ideable-framework-specs/base_specs.md"
            "frontend/SPECS/ideable-framework-specs/shared-ui-specs.md"
            "frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md"
        )
    fi

    for shared_spec in "${SHARED_FRAMEWORK_SPECS[@]}"; do
        echo ""
        echo "Syncing shared framework spec: ${shared_spec}"
        if force_sync_regular_file_from_template "modules/ModuleTemplate/${shared_spec}" "modules/${MODULE_NAME}/${shared_spec}"; then
            SYNCED=$((SYNCED + 1))
        else
            FAILED=$((FAILED + 1))
        fi
    done

    # Force-sync IDEABLE-README.md (root README from template)
    echo ""
    echo "Syncing IDEABLE-README.md..."
    if force_sync_regular_file_from_template "IDEABLE-README.md" "IDEABLE-README.md"; then
        SYNCED=$((SYNCED + 1))
    else
        FAILED=$((FAILED + 1))
    fi

    # Update container naming in module docker-compose.yml to dotted format
    MODULE_COMPOSE="modules/${MODULE_NAME}/docker-compose.yml"
    if [[ -f "$MODULE_COMPOSE" ]]; then
        echo ""
        echo "Checking container naming format in ${MODULE_COMPOSE}..."
        MODULE_COMPOSE_BEFORE_TMP=$(mktemp)
        cp "$MODULE_COMPOSE" "$MODULE_COMPOSE_BEFORE_TMP"
        # Get module slug from module.json for pattern matching
        MODULE_SLUG=$(grep -o '"slug": "[^"]*"' "modules/${MODULE_NAME}/module.json" 2>/dev/null | head -1 | sed 's/.*"slug": "\([^"]*\)".*/\1/')
        if [[ -n "$MODULE_SLUG" ]]; then
            # Transform old hyphenated patterns to new dotted format
            # Old: container_name: ${APP_SLUG}-${MODULE_SLUG}-<name>
            # New: container_name: ${APP_SLUG}.${MODULE_SLUG}.<name>
            UPDATED=false
            if grep -q "container_name: \${APP_SLUG}-${MODULE_SLUG}-" "$MODULE_COMPOSE" 2>/dev/null; then
                sed -i.bak "s/container_name: \${APP_SLUG}-${MODULE_SLUG}-/container_name: \${APP_SLUG}.\${MODULE_SLUG}./g" "$MODULE_COMPOSE"
                rm -f "${MODULE_COMPOSE}.bak"
                UPDATED=true
            fi
            if grep -qE "container_name: [a-z]+-${MODULE_SLUG}-" "$MODULE_COMPOSE" 2>/dev/null; then
                # Handle hardcoded project slug (e.g., secriskass-sra-backend)
                sed -i.bak -E "s/container_name: ([a-z]+)-${MODULE_SLUG}-/container_name: \${APP_SLUG}.\${MODULE_SLUG}./g" "$MODULE_COMPOSE"
                rm -f "${MODULE_COMPOSE}.bak"
                UPDATED=true
            fi
            if grep -qE "^    container_name: ${MODULE_SLUG}-" "$MODULE_COMPOSE" 2>/dev/null; then
                # Handle missing project prefix (e.g., sra-backend -> ${APP_SLUG}.${MODULE_SLUG}.backend)
                sed -i.bak -E "s/^    container_name: ${MODULE_SLUG}-/    container_name: \${APP_SLUG}.\${MODULE_SLUG}./g" "$MODULE_COMPOSE"
                rm -f "${MODULE_COMPOSE}.bak"
                UPDATED=true
            fi
            if $UPDATED; then
                echo "  [updated] Container names to dotted format (${APP_SLUG}.${MODULE_SLUG}.<name>)"
            else
                echo "  [ok] Container naming already in dotted format or no update needed"
            fi
        fi

        TEMPLATE_COMPOSE_PATH="modules/${TEMPLATE_MODULE_NAME}/docker-compose.yml"
        MODULE_SLUG_VALUE=$(get_module_slug)
        MODULE_DB_PREFIX=$(get_module_db_prefix)
        sync_managed_compose_sections "$TEMPLATE_COMPOSE_PATH" "$MODULE_COMPOSE" "$MODULE_SLUG_VALUE" "$MODULE_DB_PREFIX"

        if cmp -s "$MODULE_COMPOSE_BEFORE_TMP" "$MODULE_COMPOSE"; then
            record_sync_result "untouched" "$MODULE_COMPOSE"
        else
            record_sync_result "updated" "$MODULE_COMPOSE"
        fi
        rm -f "$MODULE_COMPOSE_BEFORE_TMP"
    fi

    echo ""
    echo "Done. $SYNCED file(s) synced, $FAILED skipped."
    echo "Review with 'git diff' and commit when ready."
    print_sync_report

    true  # FETCH_HEAD ref needs no cleanup
    exit 0
fi

# Selective mode
if $SELECTIVE_MODE; then
    echo "Selective sync mode. Review each file:"
    echo "======================================="
    
    while IFS= read -r status file; do
        is_template_module_file "$file" && continue
        
        echo ""
        echo "File: $file"
        echo "Status: $status"
        
        git diff HEAD.."$TEMP_BRANCH" -- "$file" 2>/dev/null | head -30
        
        read -rp "Sync this file? (y/n/q): " choice
        case "$choice" in
            y|Y)
                if is_infrastructure "$file"; then
                    TEMPLATE_PATH="$file"
                else
                    TEMPLATE_PATH="modules/$TEMPLATE_MODULE_NAME/$file"
                fi
                if is_env_file "$file"; then
                    TEMPLATE_PATH="$(resolve_template_env_example_source "$TEMPLATE_PATH")"
                    LOCAL_PATH="$file"
                    LOCAL_PATH="$(resolve_local_env_example_destination "$LOCAL_PATH")"
                    local_env_path="${PROJECT_ROOT}/$LOCAL_PATH"
                    if ! sync_env_file_from_template "$TEMPLATE_PATH" "$local_env_path"; then
                        continue
                    fi
                    if [[ "$LOCAL_PATH" == *.env.example ]]; then
                        sync_example_to_matching_env "$local_env_path"
                        reconcile_env_example_with_matching_env "$local_env_path"
                    fi
                else
                    if ! sync_regular_file_from_template "$TEMPLATE_PATH" "$file"; then
                        continue
                    fi
                fi
                ;;
            q|Q)
                echo "Aborted."
                print_sync_report
                true  # FETCH_HEAD ref needs no cleanup
                exit 0
                ;;
            *)
                echo "  -> Skipped"
                record_sync_result "skipped" "$file"
                ;;
        esac
    done < <(git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null)
    
    echo ""
    echo "Sync complete. Review with 'git status' and commit."
    print_sync_report
fi

# No cleanup needed — FETCH_HEAD is a ref, not a branch
