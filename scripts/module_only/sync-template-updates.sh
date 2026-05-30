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

# Detect the actual module name by finding a modules/* directory that has a module.json
# but is neither ModuleTemplate nor HostApp (those are framework/infrastructure dirs).
DETECT_MODULE_NAME() {
    local module_name=""
    for dir in "$MODULES_DIR"/*/; do
        if [[ -d "$dir" ]]; then
            local name=$(basename "$dir")
            if [[ "$name" != "ModuleTemplate" && "$name" != "HostApp" && -f "${dir}module.json" ]]; then
                module_name="$name"
                break
            fi
        fi
    done
    echo "$module_name"
}

MODULE_NAME=$(DETECT_MODULE_NAME)
TEMPLATE_MODULE_NAME="ModuleTemplate"

if [[ -z "$MODULE_NAME" ]]; then
    MODULE_NAME="ModuleTemplate"
fi

echo "Detected module: $MODULE_NAME"

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

# Infrastructure detection
is_template_module_file() {
    local file="$1"
    [[ "$file" == modules/${TEMPLATE_MODULE_NAME}/* ]]
}

is_infrastructure() {
    local file="$1"
    [[ "$file" == scripts/* ]] || \
    [[ "$file" == "AGENTS.md" ]] || \
    [[ "$file" == "IDEABLE-README.md" ]] || \
    [[ "$file" == "MODULE-README.md" ]] || \
    [[ "$file" == ".agents/"* ]] || \
    [[ "$file" == ".windsurf/"* ]] || \
    [[ "$file" == ".kiro/"* ]] || \
    [[ "$file" == ".claude/"* ]] || \
    [[ "$file" == "rules/"* ]] || \
    [[ "$file" == "redeploy.sh" ]] || \
    [[ "$file" == "start.sh" ]] || \
    [[ "$file" == "stop.sh" ]] || \
    [[ "$file" == "status.sh" ]] || \
    [[ "$file" == "update_backend.sh" ]] || \
    [[ "$file" == "update_frontend.sh" ]] || \
    [[ "$file" == "README.md" ]] || \
    [[ "$file" == ".gitignore" ]] || \
    [[ "$file" == "docs/"* ]] || \
    [[ "$file" == modules/*/.env ]] || \
    [[ "$file" == modules/*/.env.example ]] || \
    [[ "$file" == modules/HostApp/.env ]] || \
    [[ "$file" == modules/HostApp/.env.example ]] || \
    [[ "$file" == modules/HostApp/module.json ]] || \
    [[ "$file" == modules/HostApp/docker-compose.yml ]] || \
    [[ "$file" == modules/HostApp/config/* ]] || \
    [[ "$file" == modules/HostApp/authentik/DIST/* ]] || \
    [[ "$file" == modules/HostApp/authentik/config/* ]] || \
    [[ "$file" == modules/HostApp/database/DIST/* ]] || \
    [[ "$file" == modules/HostApp/traefik/DIST/* ]] || \
    [[ "$file" == "project.env.example" ]] && ! is_template_module_file "$file"
}

# .env merge: add vars from template that are missing locally; preserve existing values.
# Lines that are comments or blank are added only if the key block is new.
is_env_file() {
    local file="$1"
    [[ "$file" == modules/*/.env ]] || [[ "$file" == modules/*/.env.example ]] || [[ "$file" == modules/HostApp/.env ]] || [[ "$file" == modules/HostApp/.env.example ]] || [[ "$file" == "project.env.example" ]]
    is_template_module_file "$file" && return 1
}

is_placeholder_readme() {
    local file="$1"
    [[ "$file" == "README.md" ]] || [[ "$file" == "modules/${MODULE_NAME}/README.md" ]]
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

    if ! git show "${TEMP_BRANCH}:${template_path}" > "$template_tmp" 2>/dev/null; then
        rm -f "$template_tmp"
        echo "  [missing]  $local_path (not in template, skipping)"
        record_sync_result "missing" "$local_path"
        return 1
    fi

    if [[ -f "$local_path" ]]; then
        # Skip placeholder README.md if it already exists locally
        if is_placeholder_readme "$local_path"; then
            echo "  [skipped]  $local_path (placeholder README already exists, preserving local version)"
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
    local module_example="${PROJECT_ROOT}/modules/${MODULE_NAME}/.env.example"
    local module_env="${PROJECT_ROOT}/modules/${MODULE_NAME}/.env"
    local project_example="${PROJECT_ROOT}/project.env.example"
    local project_env="${PROJECT_ROOT}/project.env"
    local template_module_example_tmp
    local template_module_env_tmp

    echo ""
    echo "Environment variable alignment report"
    echo "====================================="

    template_module_example_tmp=$(mktemp)
    if git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/.env.example" > "$template_module_example_tmp" 2>/dev/null; then
        report_env_key_differences \
            "Local module: .env.example" \
            "$module_example" \
            "ModuleTemplate repo: .env.example" \
            "$template_module_example_tmp" \
            "Comparison: ModuleTemplate repo .env.example vs local module .env.example"
    else
        echo "  [missing] modules/${TEMPLATE_MODULE_NAME}/.env.example not found in template"
    fi
    rm -f "$template_module_example_tmp"

    echo ""
    template_module_env_tmp=$(mktemp)
    if git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/.env.example" > "$template_module_env_tmp" 2>/dev/null; then
        report_env_key_differences \
            "Local module: .env" \
            "$module_env" \
            "ModuleTemplate repo: .env.example" \
            "$template_module_env_tmp" \
            "Comparison: ModuleTemplate repo .env.example vs local module .env"
    else
        echo "  [missing] modules/${TEMPLATE_MODULE_NAME}/.env.example not found in template"
    fi
    rm -f "$template_module_env_tmp"

    echo ""
    report_env_key_differences \
        "Project config: project.env.example" \
        "$project_example" \
        "Project config: project.env" \
        "$project_env" \
        "Comparison: project.env.example vs project.env"
}

# List changed files
if $LIST_CHANGES; then
    echo "Files that differ between your module and template:"
    echo "================================================"
    
    git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null | while read -r status file; do
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
        template_env_content=$(git show "$TEMP_BRANCH:$TEMPLATE_PATH" 2>/dev/null) || {
            echo "Error: File not found in template: $TEMPLATE_PATH"
            true  # FETCH_HEAD ref needs no cleanup
            exit 1
        }
        sync_env_content_to_file "$template_env_content" "${PROJECT_ROOT}/$LOCAL_PATH"
        if [[ "$FILES_TO_SYNC" == *.env.example ]]; then
            sync_example_to_matching_env "${PROJECT_ROOT}/$LOCAL_PATH"
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
        file="${line#*$'\t'}"

        # Only sync infrastructure files; skip module-specific paths
        if ! is_infrastructure "$file"; then
            continue
        fi

        if is_template_module_file "$file"; then
            continue
        fi

        # Skip branding files unless --all was passed
        if is_branding_file "$file" && ! $SYNC_ALL; then
            echo "  [skipped]  $file (branding file — run with --all to overwrite)"
            record_sync_result "skipped" "$file"
            continue
        fi

        TEMPLATE_PATH="$file"

        if [[ "$status" == "D" ]]; then
            # File deleted in template — remove locally if present
            if [[ -f "$file" ]]; then
                rm -f "$file"
            fi
            echo "  [removed]  $file"
            record_sync_result "removed" "$file"
            SYNCED=$((SYNCED + 1))
            continue
        fi

        # Ensure parent directory exists
        mkdir -p "$(dirname "$file")"

        if is_env_file "$file"; then
            local_env_path="${PROJECT_ROOT}/$file"
            if sync_env_file_from_template "$TEMPLATE_PATH" "$local_env_path"; then
                if [[ "$file" == *.env.example ]]; then
                    sync_example_to_matching_env "$local_env_path"
                fi
                SYNCED=$((SYNCED + 1))
            else
                FAILED=$((FAILED + 1))
            fi
        elif sync_regular_file_from_template "$TEMPLATE_PATH" "$file"; then
            SYNCED=$((SYNCED + 1))
        else
            FAILED=$((FAILED + 1))
        fi
    done < <(git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null)

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
    echo "Syncing baseline remote-module spec: SPECS/base-specs.md"
    echo "Skipping other SPECS files so module-specific specs remain untouched."

    # Keep the baseline remote-module spec itself in sync, but do not touch any
    # other SPECS files.
    BASE_SPECS_LOCAL="modules/${MODULE_NAME}/SPECS/base-specs.md"
    BASE_SPECS_TEMPLATE="modules/ModuleTemplate/SPECS/base-specs.md"
    if sync_regular_file_from_template "$BASE_SPECS_TEMPLATE" "$BASE_SPECS_LOCAL"; then
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
                    local_env_path="${PROJECT_ROOT}/$file"
                    if ! sync_env_file_from_template "$TEMPLATE_PATH" "$local_env_path"; then
                        continue
                    fi
                    if [[ "$file" == *.env.example ]]; then
                        sync_example_to_matching_env "$local_env_path"
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
