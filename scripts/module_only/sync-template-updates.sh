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

# Detect the actual module name
DETECT_MODULE_NAME() {
    local module_name=""
    for dir in "$MODULES_DIR"/*/; do
        if [[ -d "$dir" ]]; then
            local name=$(basename "$dir")
            if [[ "$name" != "ModuleTemplate" && "$name" != "HostApp" && "$name" != "SRA" ]]; then
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
    --help               Show this help

EXAMPLES:
    $0 --list-changes
    $0 --file scripts/module-init.sh
    $0 --selective
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

# Infrastructure detection
is_infrastructure() {
    local file="$1"
    [[ "$file" == scripts/* ]] || \
    [[ "$file" == ".agents/"* ]] || \
    [[ "$file" == ".windsurf/"* ]] || \
    [[ "$file" == ".kiro/"* ]] || \
    [[ "$file" == ".claude/"* ]] || \
    [[ "$file" == "rules/"* ]] || \
    [[ "$file" == "redeploy.sh" ]] || \
    [[ "$file" == "README.md" ]] || \
    [[ "$file" == ".gitignore" ]] || \
    [[ "$file" == "docs/"* ]] || \
    [[ "$file" == modules/*/.env ]] || \
    [[ "$file" == modules/HostApp/.env ]]
}

# .env merge: add vars from template that are missing locally; preserve existing values.
# Lines that are comments or blank are added only if the key block is new.
is_env_file() {
    local file="$1"
    [[ "$file" == modules/*/.env ]] || [[ "$file" == modules/HostApp/.env ]]
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

# List changed files
if $LIST_CHANGES; then
    echo "Files that differ between your module and template:"
    echo "================================================"
    
    git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null | while read -r status file; do
        if [[ "$file" == *"$TEMPLATE_MODULE_NAME"* ]]; then
            echo "[RENAMED] $file"
            continue
        fi
        
        if is_infrastructure "$file"; then
            echo "[INFRASTRUCTURE] $file"
        else
            echo "[MODULE] $file"
        fi
    done
    
    echo ""
    echo "Run with --file to sync specific files"
    
    exit 0
fi

# Sync specific file
if [[ -n "$FILES_TO_SYNC" ]]; then
    echo "Syncing file: $FILES_TO_SYNC"
    
    LOCAL_PATH="$FILES_TO_SYNC"
    
    # Determine template path
    if is_infrastructure "$FILES_TO_SYNC"; then
        TEMPLATE_PATH="$FILES_TO_SYNC"
    else
        TEMPLATE_PATH="modules/$TEMPLATE_MODULE_NAME/$FILES_TO_SYNC"
    fi
    
    # Special handling for self-update
    if [[ "$FILES_TO_SYNC" == *"sync-template-updates.sh"* ]]; then
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
    elif is_env_file "$FILES_TO_SYNC"; then
        template_env_content=$(git show "$TEMP_BRANCH:$TEMPLATE_PATH" 2>/dev/null) || {
            echo "Error: File not found in template: $TEMPLATE_PATH"
            true  # FETCH_HEAD ref needs no cleanup
            exit 1
        }
        merge_env_file "$template_env_content" "${PROJECT_ROOT}/$LOCAL_PATH"
    else
        # Extract file from template
        git show "$TEMP_BRANCH:$TEMPLATE_PATH" > "$LOCAL_PATH" 2>/dev/null || {
            echo "Error: File not found in template: $TEMPLATE_PATH"
            true  # FETCH_HEAD ref needs no cleanup
            exit 1
        }
        echo "File synced: $FILES_TO_SYNC"
    fi
    
    echo "Review changes and commit when ready."
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

        TEMPLATE_PATH="$file"

        if [[ "$status" == "D" ]]; then
            # File deleted in template — remove locally if present
            if [[ -f "$file" ]]; then
                rm -f "$file"
                echo "  [deleted]  $file"
                SYNCED=$((SYNCED + 1))
            fi
            continue
        fi

        # Ensure parent directory exists
        mkdir -p "$(dirname "$file")"

        if is_env_file "$file"; then
            local_env_path="${PROJECT_ROOT}/$file"
            template_env_content=$(git show "${TEMP_BRANCH}:${TEMPLATE_PATH}" 2>/dev/null) || {
                echo "  [missing]  $file (not in template, skipping)"
                FAILED=$((FAILED + 1))
                continue
            }
            merge_env_file "$template_env_content" "$local_env_path"
            SYNCED=$((SYNCED + 1))
        elif git show "${TEMP_BRANCH}:${TEMPLATE_PATH}" > "$file" 2>/dev/null; then
            chmod +x "$file" 2>/dev/null || true
            echo "  [updated]  $file"
            SYNCED=$((SYNCED + 1))
        else
            echo "  [missing]  $file (not in template, skipping)"
            FAILED=$((FAILED + 1))
        fi
    done < <(git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null)

    echo ""
    echo "Done. $SYNCED file(s) synced, $FAILED skipped."
    echo "Review with 'git diff' and commit when ready."

    true  # FETCH_HEAD ref needs no cleanup
    exit 0
fi

# Selective mode
if $SELECTIVE_MODE; then
    echo "Selective sync mode. Review each file:"
    echo "======================================="
    
    git diff --name-status HEAD.."$TEMP_BRANCH" 2>/dev/null | while read -r status file; do
        [[ "$file" == *"$TEMPLATE_MODULE_NAME"* ]] && continue
        
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
                git show "$TEMP_BRANCH:$TEMPLATE_PATH" > "$file" 2>/dev/null && echo "  -> Synced"
                ;;
            q|Q)
                echo "Aborted."
                true  # FETCH_HEAD ref needs no cleanup
                exit 0
                ;;
            *)
                echo "  -> Skipped"
                ;;
        esac
    done
    
    echo ""
    echo "Sync complete. Review with 'git status' and commit."
fi

# No cleanup needed — FETCH_HEAD is a ref, not a branch
