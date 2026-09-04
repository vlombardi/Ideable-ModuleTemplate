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

# How many things this run could NOT check because the template side was unreadable.
#
# `unavailable` is deliberately its own status, separate from `missing` and `skipped`. Those two
# are expected and repeat on every run for ever (a file the template does not have; a file
# preserved on purpose), so the convergence line forgives them. `unavailable` means the sync tried
# to align something and could not even look — the project may be out of date and this run cannot
# say. That must never be reported as convergence, and it must reach the caller as an exit code.
sync_report_unavailable_count() {
    (( ${#SYNC_REPORT_ENTRIES[@]} )) || { printf '0'; return 0; }
    local entry count=0
    for entry in "${SYNC_REPORT_ENTRIES[@]}"; do
        [[ "${entry%%|*}" == "unavailable" ]] && count=$((count + 1))
    done
    printf '%s' "$count"
}

print_sync_report() {
    local total=${#SYNC_REPORT_ENTRIES[@]}
    local untouched_count=0
    local updated_count=0
    local added_count=0
    local removed_count=0
    local skipped_count=0
    local missing_count=0
    local unavailable_count=0
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
            unavailable)
                unavailable_count=$((unavailable_count + 1))
                echo "  [UNAVAILABLE] $file"
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
    echo "  UNAVAILABLE: $unavailable_count"

    # Did this run finish the job, or does it need another?
    #
    # The work list is decided ONCE, by a `git diff` taken before anything is written (see the loops
    # below). Everything the run then changes is never re-examined — so a run that makes a
    # STRUCTURAL change can leave work behind. The measured case: converting `.claude/skills` and
    # `.kiro/skills` from real directories into symlinks removes ~80 tracked paths and adds two
    # links, and every file classified from the pre-change snapshot was classified against a tree
    # that no longer exists. A second run then reported "Updated: 2, Added: 1" with nothing having
    # happened in between, and the maintainer had no way to tell whether that was convergence or a
    # loop.
    #
    # `Missing` and `Skipped` are deliberately NOT convergence failures: a missing file is one the
    # template does not have (a second module's `.env.example`, say), and a skipped one is
    # preserved on purpose. Both repeat on every run, for ever, by design.
    #
    # `unavailable` is the third answer, and it came from a real silence. The managed compose
    # blocks were read from a FILESYSTEM path that exists only in the maintainer's own checkout,
    # so in every remote module project the guard was false, the function returned 0, and this
    # line printed "Converged — nothing left to align." while six force-synced compose blocks had
    # never been delivered. A run that could not look must not claim alignment.
    if [[ "$unavailable_count" -gt 0 ]]; then
        echo ""
        echo "  ✖ NOT aligned — $unavailable_count item(s) could not be checked at all."
        echo "    The template side was unreadable, so this run cannot say whether those parts of"
        echo "    the project are up to date. See the [UNAVAILABLE] lines above for what and why."
        echo "    This is NOT the same as Missing or Skipped, and NOT convergence."
    elif [[ "$updated_count" -gt 0 || "$added_count" -gt 0 || "$removed_count" -gt 0 ]]; then
        echo ""
        echo "  ▸ This run CHANGED files, so it may not have converged."
        echo "    The work list is computed once, before anything is written, so a change made"
        echo "    during the run is not re-examined. Run the sync again: when it reports"
        echo "    Updated/Added/Removed all 0, the project is aligned."
    else
        echo ""
        echo "  ✔ Converged — nothing left to align."
        if [[ "$missing_count" -gt 0 || "$skipped_count" -gt 0 ]]; then
            echo "    (The Missing/Skipped counts above are expected and repeat every run:"
            echo "     'missing' = not in the template at all, 'skipped' = preserved on purpose.)"
        fi
    fi

    # If any skill file was added/updated, the running AI agent will NOT pick it up:
    # skill name/description is snapshotted at session startup (cached prompt prefix) and the
    # SKILL.md body is only re-read on the next invocation. Remind the developer to reload.
    local skills_changed=false entry status file
    for entry in "${SYNC_REPORT_ENTRIES[@]}"; do
        status="${entry%%|*}"; file="${entry#*|}"
        if [[ "$file" == *"/skills/"* && ( "$status" == "updated" || "$status" == "added" ) ]]; then
            skills_changed=true; break
        fi
    done
    if $skills_changed; then
        echo ""
        echo "⚠️  Agent skills changed during this sync."
        echo "   A running AI agent will keep using the OLD skill until you reload:"
        echo "   run '/reload-skills' in Claude Code (or restart the session) before continuing."
    fi
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
                if [[ "$name" != "module_template" && "$name" != "host_app" && -z "$fallback_name" ]]; then
                    fallback_name="$name"
                fi
            fi
        fi
    done
    echo "${module_name:-$fallback_name}"
}

MODULE_NAME=$(DETECT_MODULE_NAME)
TEMPLATE_MODULE_NAME="module_template"

if [[ -z "$MODULE_NAME" ]]; then
    MODULE_NAME="module_template"
fi

echo "Detected module: $MODULE_NAME"

# Guard: this script is for derived module repos, not the main project or the raw template repo.
# In the main project, the detected module will be module_template (the only remote module).
# In a derived repo, module_template/ may exist as a leftover from sync, but the detected
# module will be the actual derived module (e.g., my_module, etc.).
if [[ "$MODULE_NAME" == "module_template" ]]; then
    echo "ERROR: This script must not be run inside the Ideable main project or the module_template repo."
    echo "It is designed for derived module repos (e.g., modules/my_module)."
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
    [[ "$file" == modules/host_app/config/favicon.* ]] || \
    [[ "$file" == modules/host_app/config/login_bg.png ]] || \
    [[ "$file" == modules/host_app/config/home.html ]] || \
    [[ "$file" == modules/host_app/config/modules_menu_mapping.json ]] || \
    [[ "$file" == modules/host_app/config/module-registry.json ]]
}

# host_app config files are free for developers to customize; never remove them.
is_hostapp_config_file() {
    local file="$1"
    [[ "$file" == modules/host_app/config/* ]]
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
    [[ "$file" == ".githooks/"* ]] || \
    [[ "$file" == "rules/"* ]] || \
    [[ "$file" == "reusable.ui/"* ]] || \
    [[ "$file" == "redeploy.sh" ]] || \
    [[ "$file" == "start.sh" ]] || \
    [[ "$file" == "stop.sh" ]] || \
    [[ "$file" == "status.sh" ]] || \
    [[ "$file" == "update_backend.sh" ]] || \
    [[ "$file" == "update_frontend.sh" ]] || \
    [[ "$file" == ".gitignore" ]] || \
    [[ "$file" == "pytest.ini" ]] || \
    [[ "$file" == "pyproject.toml" ]] || \
    [[ "$file" == "conftest.py" ]] || \
    [[ "$file" == "framework.env" ]] || \
    [[ "$file" == modules/*/.env.example ]] || \
    [[ "$file" == modules/*/.env.config.example ]] || \
    [[ "$file" == modules/*/.env.secrets.example ]] || \
    [[ "$file" == modules/host_app/.env.example ]] || \
    [[ "$file" == modules/host_app/module.json ]] || \
    [[ "$file" == modules/host_app/docker-compose.yml ]] || \
    [[ "$file" == modules/host_app/config/* ]] || \
    [[ "$file" == modules/host_app/database/* ]] || \
    [[ "$file" == "project.env.example" ]] || \
    [[ "$file" == "project.env.config.example" ]] || \
    [[ "$file" == "project.env.secrets.example" ]] && ! is_template_module_file "$file"
}

is_shared_template_spec_file() {
    local file="$1"
    [[ "$file" == "modules/module_template/SPECS/ideable-framework-specs/base-specs.md" ]] || \
    [[ "$file" == "modules/module_template/SPECS/ideable-framework-specs/auth-specs.md" ]] || \
    [[ "$file" == "modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md" ]] || \
    [[ "$file" == "modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md" ]] || \
    [[ "$file" == "modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md" ]] || \
    [[ "$file" == "modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md" ]] || \
    [[ "$file" == "modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md" ]] || \
    [[ "$file" == "modules/module_template/database/SPECS/ideable-framework-specs/base-specs.md" ]] || \
    [[ "$file" == "modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md" ]] || \
    [[ "$file" == "modules/module_template/frontend/SPECS/ideable-framework-specs/base_specs.md" ]] || \
    [[ "$file" == "modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md" ]] || \
    [[ "$file" == "modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md" ]] || \
    [[ "$file" == "modules/module_template/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md" ]] || \
    [[ "$file" == "modules/module_template/frontend/SPECS/ideable-framework-specs/framework-css-classes-reference.md" ]] || \
    [[ "$file" == "modules/module_template/frontend/SPECS/ideable-framework-specs/look-and-feel-branding.md" ]]
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

# Match any env example path (local module or template module). This is used for
# deletion guards and for mapping template module env examples to the local module.
is_env_example_file() {
    local file="$1"
    [[ "$file" == modules/*/.env.example ]] || \
    [[ "$file" == modules/*/.env.config.example ]] || \
    [[ "$file" == modules/*/.env.secrets.example ]] || \
    [[ "$file" == "project.env.config.example" ]] || \
    [[ "$file" == "project.env.secrets.example" ]]
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

# Apply TEMPLATE -> module-specific substitutions to env file content.
# TEMPLATE_ prefix becomes <MODULE_PREFIX>_, remaining TEMPLATE becomes <module_slug>.
apply_env_template_substitution() {
    local content="$1"
    local module_prefix="$2"
    local module_slug="$3"
    local template_token="TEMPLATE"

    echo "$content" | sed \
        -e "s/${template_token}_/${module_prefix}_/g" \
        -e "s/${template_token}/${module_slug}/g" \
        -e "s/template/${module_slug}/g"
}

# Merge a template module env example file into a local module env file.
# Preserves module-specific keys that start with the module prefix (e.g. SRA_),
# removes leftover generic TEMPLATE_ keys, and adds new template keys with
# TEMPLATE_ substituted by the module prefix.
merge_module_env_file() {
    local template_content="$1"
    local local_file="$2"
    local module_prefix="${3:-$(get_module_db_prefix)}"
    local module_slug="${4:-$(get_module_slug)}"
    local template_token="TEMPLATE"

    if [[ -z "$module_prefix" ]]; then
        module_prefix="$(echo "$module_slug" | tr '[:lower:]-' '[:upper:]_')"
    fi

    if [[ ! -f "$local_file" ]]; then
        mkdir -p "$(dirname "$local_file")"
        apply_env_template_substitution "$template_content" "$module_prefix" "$module_slug" > "$local_file"
        echo "  [created]  $local_file"
        return
    fi

    # Remove leftover generic TEMPLATE_* keys from the local file (they should
    # have been substituted to the module prefix in a previous sync).
    local cleaned_file
    cleaned_file=$(mktemp)
    awk -v token="$template_token" '
        /^[[:space:]]*$/ { print; next }
        /^[[:space:]]*#/ { print; next }
        {
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            split(line, parts, "=")
            key = parts[1]
            sub(/^[[:space:]]+/, "", key)
            sub(/[[:space:]]+$/, "", key)
            if (key !~ ("^" token "_")) { print $0 }
        }
    ' "$local_file" > "$cleaned_file"
    cp "$cleaned_file" "$local_file"

    # Build local key set from the cleaned file
    local local_keys_file
    local_keys_file=$(mktemp)
    extract_env_keys "$local_file" > "$local_keys_file" 2>/dev/null || true

    local added=0
    local pending_comments=""
    local new_content_file
    new_content_file=$(mktemp)

    while IFS= read -r line; do
        # Blank line or comment — buffer for context
        if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
            pending_comments="${pending_comments}${line}"$'\n'
            continue
        fi

        # Extract key (handle KEY=value and export KEY=value)
        local key local_key
        key=$(echo "$line" | sed 's/^export[[:space:]]*//' | cut -d= -f1 | tr -d '[:space:]')
        [[ -z "$key" ]] && { pending_comments=""; continue; }

        # Compute the module-specific key: TEMPLATE_ -> <PREFIX>_, then remaining TEMPLATE -> <slug>
        local_key="${key/${template_token}_/${module_prefix}_}"
        local_key="${local_key//${template_token}/${module_slug}}"

        # If the module-specific key already exists locally, preserve the local definition
        if grep -qFx "$local_key" "$local_keys_file" 2>/dev/null; then
            pending_comments=""
            continue
        fi

        # Substitute the whole line and append it
        local substituted_line
        substituted_line=$(apply_env_template_substitution "$line" "$module_prefix" "$module_slug")
        {
            echo ""
            printf '%s' "$pending_comments"
            echo "$substituted_line"
        } >> "$new_content_file"
        added=$((added + 1))
        pending_comments=""
    done <<< "$template_content"

    if [[ -s "$new_content_file" ]]; then
        cat "$new_content_file" >> "$local_file"
    fi

    if [[ $added -gt 0 ]]; then
        echo "  [merged]   $local_file ($added new module-specific var(s) added)"
    else
        echo "  [up-to-date] $local_file"
    fi

    rm -f "$cleaned_file" "$local_keys_file" "$new_content_file"
}

sync_env_content_to_file() {
    local template_content="$1"
    local local_path="$2"
    local relative_path="${local_path#${PROJECT_ROOT}/}"

    if [[ ! -f "$local_path" ]]; then
        mkdir -p "$(dirname "$local_path")"
        if [[ "$relative_path" == modules/${MODULE_NAME}/.env* ]]; then
            merge_module_env_file "$template_content" "$local_path"
        else
            printf '%s\n' "$template_content" > "$local_path"
            echo "  [added]    $local_path"
        fi
        record_sync_result "added" "$local_path"
        return 0
    fi

    local before_tmp after_tmp
    before_tmp=$(mktemp)
    after_tmp=$(mktemp)
    cp "$local_path" "$before_tmp"

    if [[ "$relative_path" == modules/${MODULE_NAME}/.env* ]]; then
        merge_module_env_file "$template_content" "$local_path"
    else
        merge_env_file "$template_content" "$local_path"
    fi

    cp "$local_path" "$after_tmp"
    if cmp -s "$before_tmp" "$after_tmp"; then
        record_sync_result "untouched" "$local_path"
    else
        record_sync_result "updated" "$local_path"
    fi

    rm -f "$before_tmp" "$after_tmp"
}

# --- Symlinks -----------------------------------------------------------------------------------
#
# `git show <rev>:<path>` prints a symlink's TARGET as bytes, indistinguishable from a one-line
# regular file. Everything below used to treat that text as content, and the damage was measured in
# a remote module project: the framework keeps `.claude/skills` and `.kiro/skills` as symlinks to
# `.agents/skills` (rules/authoring-guidelines.md § Where exactly), the remote still had real
# directories there, `[[ -f "$local_path" ]]` was false for a directory, and so the `else` branch
# ran `cp "$template_tmp" "$local_path"` — which copies INTO a directory. The result was 8 stray
# 17-byte `tmp.XXXXXXXXXX` files each containing the string `../.agents/skills`, 16 empty skill
# directories, and 80 deleted skill files, with the symlink never created. Skill discovery was
# broken in every remote that synced.
#
# Ask git for the entry's MODE, never infer the kind from the bytes.
template_entry_mode() {
    git ls-tree "${TEMP_BRANCH}" -- "$1" 2>/dev/null | awk 'NR==1 {print $1}'
}

template_entry_is_symlink() {
    [[ "$(template_entry_mode "$1")" == "120000" ]]
}

# True when any ANCESTOR directory of the path is a symlink.
#
# Deleting through one reaches the link's target, not the path named. Once `.claude/skills` is a
# symlink to `.agents/skills`, the `A`-status branch below — "exists locally, absent from the
# template, therefore remove" — is handed every `.claude/skills/**` path git can still see through
# the link, and `rm -rf` on them would destroy the CANONICAL skill copy in `.agents/skills` that the
# link exists to share. The paths are already gone as far as the working tree is concerned; there is
# nothing to remove and everything to lose.
path_crosses_a_symlink() {
    local dir
    dir="$(dirname "$1")"
    while [[ "$dir" != "." && "$dir" != "/" && -n "$dir" ]]; do
        [[ -L "$dir" ]] && return 0
        dir="$(dirname "$dir")"
    done
    return 1
}

# Reproduce a template symlink as a real symlink. Whatever stands in its place goes first —
# that removal is the whole point, and it is why this must run BEFORE any `cp`.
sync_symlink_from_template() {
    local template_path="$1"
    local local_path="$2"
    local target

    if ! target=$(git show "${TEMP_BRANCH}:${template_path}" 2>/dev/null); then
        echo "  [missing]  $local_path (not in template, skipping)"
        record_sync_result "missing" "$local_path"
        return 1
    fi

    if [[ -L "$local_path" && "$(readlink "$local_path")" == "$target" ]]; then
        echo "  [up-to-date] $local_path"
        record_sync_result "untouched" "$local_path"
        return 0
    fi

    if [[ -e "$local_path" || -L "$local_path" ]]; then
        rm -rf "$local_path"
    fi
    mkdir -p "$(dirname "$local_path")"
    ln -s "$target" "$local_path"
    echo "  [linked]   $local_path -> $target"
    record_sync_result "updated" "$local_path"
    return 0
}

# A regular-file copy onto a path that is a DIRECTORY is the failure above. Refuse it loudly rather
# than writing a stray file inside: an unexpected directory is a shape nobody decided on, and
# `rules/general-guidelines.md` § Decision Making Authority puts that call with the developer.
refuse_copy_onto_directory() {
    local local_path="$1"
    if [[ -d "$local_path" && ! -L "$local_path" ]]; then
        echo "  [FAILED]   $local_path (template has a file here, working tree has a directory —" >&2
        echo "             refusing to copy into it; remove or rename the directory and re-run)" >&2
        record_sync_result "failed" "$local_path"
        return 1
    fi
    return 0
}

sync_regular_file_from_template() {
    local template_path="$1"
    local local_path="$2"

    if template_entry_is_symlink "$template_path"; then
        sync_symlink_from_template "$template_path" "$local_path"
        return $?
    fi
    refuse_copy_onto_directory "$local_path" || return 1

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

        # host_app authorization.yaml may be customized by the operator after initial sync;
        # pull from template only when the file is missing locally.
        if [[ "$local_path" == "modules/host_app/config/authorization.yaml" ]]; then
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

    if template_entry_is_symlink "$template_path"; then
        sync_symlink_from_template "$template_path" "$local_path"
        return $?
    fi
    refuse_copy_onto_directory "$local_path" || return 1

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

    # The template side is materialised once by the caller and is a guarantee by the time we get
    # here (see sync_managed_compose_sections). An unreadable one at this point is a programming
    # error in this script, not a remote's situation, so it is loud rather than a quiet `return 0`.
    if [[ ! -f "$template_compose_path" ]]; then
        echo "  [ERROR] managed compose template not readable: $template_compose_path" >&2
        return 1
    fi
    [[ -f "$local_compose_path" ]] || return 2

    # The module's compose does not carry this marker. Distinct from "aligned": a compose generated
    # before the marker existed receives nothing, for ever, and the old `return 0` said the same
    # thing here as it did for an already-identical block. The caller collects these and names them.
    if ! grep -q "SYNC-MANAGED-BEGIN: ${marker_name}" "$local_compose_path" 2>/dev/null; then
        return 3
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

# The template's compose file, materialised from the FETCHED REF into a temp file.
#
# Every other template read in this script goes through `git show "${TEMP_BRANCH}:<path>"`. The
# managed-compose path was the one exception: it took `modules/module_template/docker-compose.yml`
# as a FILESYSTEM path, which exists only in the maintainer's own repository. A remote module
# project has no `modules/module_template/` directory at all, so the guard in
# `sync_managed_compose_block` was false and it returned 0 — indistinguishable from "already
# aligned". `render_managed_compose_block` never ran. The consequence, measured in a real remote:
# NO remote module has ever received a managed compose block from a sync, for any of the six
# markers, so every past change to those blocks was silently absent everywhere but here. The
# maintainer's checkout is the one place the defect cannot occur, which is why it went unnoticed —
# and why `scripts/TESTS/test_sync_delivers_managed_compose.py` runs against a fixture that has no
# `modules/module_template/`.
#
# Prints the temp file's path on success (the caller removes it). Returns 1 and prints nothing when
# the ref has no such file.
materialise_template_compose() {
    local out
    out=$(mktemp)
    if ! git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/docker-compose.yml" > "$out" 2>/dev/null \
       || [[ ! -s "$out" ]]; then
        rm -f "$out"
        return 1
    fi
    printf '%s' "$out"
}

sync_managed_compose_sections() {
    local local_compose_path="$1"
    local module_slug="$2"
    local module_db_prefix="$3"

    local markers=(
        "bootstrap-service"
        "database-service"
        "backend-service"
        "frontend-service"
        "top-level-networks"
        "top-level-volumes"
    )

    # Read the template side ONCE — it is the same file for all six markers — and treat its absence
    # as its own outcome. A `return 0` that means "nothing to do" and a `return 0` that means "I
    # could not find the template" must not look the same to the caller or in the report.
    local template_compose_path
    if ! template_compose_path=$(materialise_template_compose); then
        echo "  [UNAVAILABLE] modules/${TEMPLATE_MODULE_NAME}/docker-compose.yml is not in ${TEMP_BRANCH}"
        echo "                The managed compose blocks were NOT checked: ${markers[*]}"
        echo "                $local_compose_path may be missing framework changes to those blocks."
        record_sync_result "unavailable" "$local_compose_path (managed compose blocks)"
        return 1
    fi

    # A marker the module's compose does not carry is collected and named once, rather than being
    # swallowed six times over. A module generated before a marker existed never receives it, and
    # the sync is the only thing positioned to say so.
    local marker_name rc absent=()
    for marker_name in "${markers[@]}"; do
        rc=0
        sync_managed_compose_block "$template_compose_path" "$local_compose_path" \
            "$marker_name" "$module_slug" "$module_db_prefix" || rc=$?
        case "$rc" in
            0) ;;
            3) absent+=("$marker_name") ;;
            *) echo "  [ERROR] managed compose block ${marker_name} failed (rc=${rc})" >&2 ;;
        esac
    done
    rm -f "$template_compose_path"

    if (( ${#absent[@]} )); then
        echo "  [skipped]  $local_compose_path — no SYNC-MANAGED marker for: ${absent[*]}"
        echo "             Those blocks are force-synced, so a compose file that does not mark them"
        echo "             will never receive them. Add the marker pair to opt the block back in."
        record_sync_result "skipped" "$local_compose_path (unmarked: ${absent[*]})"
    fi
}

# --- Runtime Look & Feel override propagation (idempotent; preserves customizations) ---
# The runtime theme-override mechanism needs three pieces in a module's frontend:
#   1. an index.html <script> that appends /config/theme-override.css after the bundle,
#   2. an nginx `location = /config/theme-override.css` no-store rule,
#   3. a config/theme-override.css scaffold (deployed, edited live — no rebuild).
# Frontend SOURCES are developer-owned, so instead of overwriting these files we INJECT the
# hook only when absent (guarded by `grep -q theme-override.css`). This covers modules that
# were generated before the hook existed, without clobbering any developer customization.

ensure_theme_override_config() {
    local module_name="$1"
    local local_path="modules/${module_name}/config/theme-override.css"
    if [[ -f "$local_path" ]]; then
        echo "  [up-to-date] $local_path (present; customizations preserved)"
        record_sync_result "untouched" "$local_path"
        return 0
    fi
    local tmp; tmp=$(mktemp)
    if ! git show "${TEMP_BRANCH}:modules/${TEMPLATE_MODULE_NAME}/config/theme-override.css" > "$tmp" 2>/dev/null; then
        rm -f "$tmp"
        echo "  [missing]  template config/theme-override.css not found, skipping"
        return 1
    fi
    mkdir -p "$(dirname "$local_path")"
    cp "$tmp" "$local_path"; rm -f "$tmp"
    echo "  [added]    $local_path (runtime L&F override scaffold)"
    record_sync_result "added" "$local_path"
    return 0
}

ensure_theme_override_in_index_html() {
    local module_name="$1"
    local local_path="modules/${module_name}/frontend/SOURCES/index.html"
    [[ -f "$local_path" ]] || { echo "  [skip]     $local_path (not present)"; return 0; }
    if grep -q 'theme-override.css' "$local_path"; then
        echo "  [up-to-date] $local_path (hook already present)"
        record_sync_result "untouched" "$local_path"
        return 0
    fi
    local snippet; snippet=$(mktemp)
    cat > "$snippet" <<'EOF'
    <script>
      // Runtime Look & Feel override (no rebuild): load config/theme-override.css if present.
      // Appended after the compiled bundle; being unlayered it wins the cascade. Injected by template sync.
      ;(function () {
        var l = document.createElement('link')
        l.rel = 'stylesheet'
        l.href = 'config/theme-override.css?t=' + Date.now()
        document.head.appendChild(l)
      })()
    </script>
EOF
    local out; out=$(mktemp)
    if awk -v sf="$snippet" '
        BEGIN { while ((getline line < sf) > 0) blk[++n]=line; close(sf) }
        /<\/head>/ && !ins { for (i = 1; i <= n; i++) print blk[i]; ins = 1 }
        { print }
        END { if (!ins) exit 1 }
    ' "$local_path" > "$out"; then
        mv "$out" "$local_path"
        echo "  [updated]  $local_path (injected runtime L&F override hook)"
        record_sync_result "updated" "$local_path"
        rm -f "$snippet"
        return 0
    else
        rm -f "$out" "$snippet"
        echo "  [skip]     $local_path (no </head> anchor; left unchanged)"
        record_sync_result "untouched" "$local_path"
        return 1
    fi
}

ensure_theme_override_in_nginx() {
    local module_name="$1"
    local local_path="modules/${module_name}/frontend/SOURCES/nginx.conf"
    [[ -f "$local_path" ]] || { echo "  [skip]     $local_path (not present)"; return 0; }
    if grep -q 'theme-override.css' "$local_path"; then
        echo "  [up-to-date] $local_path (rule already present)"
        record_sync_result "untouched" "$local_path"
        return 0
    fi
    local snippet; snippet=$(mktemp)
    cat > "$snippet" <<'EOF'

    # Runtime Look & Feel override, edited live in the deployed config/ folder (no rebuild).
    # NOT content-hashed, so it must never be cached immutably. Exact-match location takes
    # priority over any regex static rule. 404 when absent is tolerated by the runtime <link>.
    location = /config/theme-override.css {
        add_header Cache-Control "no-store" always;
        try_files $uri =404;
    }
EOF
    local out; out=$(mktemp)
    if awk -v sf="$snippet" '
        BEGIN { while ((getline line < sf) > 0) blk[++n]=line; close(sf) }
        { print }
        /server[ \t]*\{/ && !ins { for (i = 1; i <= n; i++) print blk[i]; ins = 1 }
        END { if (!ins) exit 1 }
    ' "$local_path" > "$out"; then
        mv "$out" "$local_path"
        echo "  [updated]  $local_path (injected theme-override no-store rule)"
        record_sync_result "updated" "$local_path"
        rm -f "$snippet"
        return 0
    else
        rm -f "$out" "$snippet"
        echo "  [skip]     $local_path (no 'server {' anchor; left unchanged)"
        record_sync_result "untouched" "$local_path"
        return 1
    fi
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
            "module_template repo: .env.config.example" \
            "$template_module_config_example_tmp" \
            "Comparison: module_template repo .env.config.example vs local module .env.config.example"
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
            "module_template repo: .env.config.example" \
            "$template_module_config_example_tmp" \
            "Comparison: module_template repo .env.config.example vs local module .env.config"
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
            "module_template repo: .env.secrets.example" \
            "$template_module_secrets_example_tmp" \
            "Comparison: module_template repo .env.secrets.example vs local module .env.secrets.example"
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

    # Migration: remove legacy PascalCase modules/HostApp/ if it exists.
    # The template now uses modules/host_app/ (snake_case). Derived repos from
    # before the rename may still have the old folder.
    if [[ -d "${PROJECT_ROOT}/modules/HostApp" ]]; then
        echo "  [migrated]  modules/HostApp → modules/host_app (removing legacy PascalCase folder)"
        rm -rf "${PROJECT_ROOT}/modules/HostApp"
        record_sync_result "removed" "modules/HostApp/"
    fi
    if [[ -d "${PROJECT_ROOT}/modules/ModuleTemplate" ]]; then
        echo "  [migrated]  modules/ModuleTemplate → modules/module_template (removing legacy PascalCase folder)"
        rm -rf "${PROJECT_ROOT}/modules/ModuleTemplate"
        record_sync_result "removed" "modules/ModuleTemplate/"
    fi

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

            # Env example files are never renamed away; they must be merged from
            # the template into the local module path.
            if is_env_example_file "$local_path"; then
                TEMPLATE_PATH="$(resolve_template_env_example_source "$template_path")"
                LOCAL_PATH="$(resolve_local_env_example_destination "$local_path")"
                mkdir -p "$(dirname "$LOCAL_PATH")"
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
                continue
            fi

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

            if is_infrastructure "$file" && ! is_template_module_file "$file" && ! is_branding_file "$file" && ! is_hostapp_config_file "$file" && ! is_env_example_file "$file"; then
                if [[ -e "$file" ]] && ! path_crosses_a_symlink "$file"; then
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

            # Module env example files must be mapped from the template module path
            # to the local module path. Without this, they are treated as template-only
            # files and are skipped (or deleted) even though validate_modules.sh
            # requires them to exist in the local module.
            if is_env_example_file "$file"; then
                TEMPLATE_PATH="$(resolve_template_env_example_source "$file")"
                LOCAL_PATH="$(resolve_local_env_example_destination "$file")"
                mkdir -p "$(dirname "$LOCAL_PATH")"
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
                continue
            fi
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
            LOCAL_PATH="${file/modules\/module_template/modules/$MODULE_NAME}"
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
    # WHAT BELONGS HERE: a framework CONTRACT test — one that asserts a property the framework
    # owns and a module maintainer cannot meaningfully change. It is force-synced verbatim, with no
    # slug substitution, so it MUST be module-agnostic: it derives the module's name, slug, services
    # and entities from `module.json` and the module's own sources rather than writing `template`,
    # `template-backend`, `TEMPLATE_*` or `TemplateItems` into the file.
    #
    # WHAT DOES NOT: a reference-EXAMPLE test tied to the template's `items` entity. Those are copied
    # once by module-init.sh and then owned, adapted or deleted by the module maintainer — unless the
    # example can be abstracted to be entity-agnostic, in which case it becomes a contract and
    # belongs here (that is what happened to test_entity_table_contract.py).
    #
    # This list went unmaintained between 2026-04 and 2026-08 and nothing objected: four framework
    # contracts written in that window hardcoded `template`, which made them impossible to add, so
    # every remote kept a private fork that never received a fix. The remote-safe test work removed the hardcoding and
    # added them. `scripts/TESTS/test_shared_tests_is_complete.py` now fails when a gate-selected
    # framework test is missing from this list, so the same silence cannot recur.
    SHARED_TESTS=(
        "TESTS/test_module_dependency_resolver.py"
        "TESTS/test_compose_deps.py"
        "TESTS/test_registry_dep_projection.py"
        # Framework contracts, module-agnostic since the remote-safe test work: compose replicability, the
        # database -> migrations -> seed -> backend bootstrap chain, the tenancy-declaration gate,
        # and the rule that a frontend never derives permissions from the access token.
        "TESTS/test_horizontal_scale_contract.py"
        "TESTS/test_bootstrap_contract.py"
        "TESTS/test_tenancy_marker_gate.py"
        "frontend/TESTS/test_permission_source_contract.py"
        "frontend/TESTS/test_module_manifest_contract.py"
        "frontend/TESTS/test_i18n_contract.py"
        "frontend/TESTS/test_lf_parity_contract.py"
        # The companion to lf_parity, and it checks what that one structurally cannot: a module
        # defining a component @ideable/ui already exports. Parity compares rendered output, and a
        # local copy is pixel-identical the day it is written — it diverges later, when a platform
        # fix reaches every module except the one that copied it. So this check is about identity
        # of NAME, and its subject list is read from reusable.ui's own barrels at test time.
        "frontend/TESTS/test_shared_widgets_are_not_shadowed.py"
        # Slug-FREE name, deliberately. While it was called
        # test_template_items_table_contract.py, module-init.sh renamed it after the new
        # slug and this force-sync wrote the original straight back, so every remote
        # carried the same contract test TWICE under two names — verified: identical
        # content, both collected, every assertion running twice, and free to diverge the
        # moment either was edited. A force-synced file must not carry the slug in its name.
        "frontend/TESTS/test_entity_table_contract.py"
        "backend/TESTS/test_auth_permissions_payload.py"
        # The tenancy contract's static half, separate from the isolation suite on purpose: every
        # test in that suite is gated on a live stack, and a naming disagreement is a fact about
        # three files in the checkout. A remote must learn it from the earliest run it can make,
        # not only from the run it cannot make yet.
        "backend/TESTS/test_tenancy_contract_names.py"
        # Backend framework contracts. Force-synced verbatim, so every one of them is
        # slug-agnostic: nothing here names `template`, `TEMPLATE_*`, `template_items` or an entity
        # route. Each derives what it needs from what the module itself authors —
        #
        #   env prefix               <- module.json `slug`
        #   entity tables            <- app/models.py `__tablename__`
        #   cross-tenant entity,
        #   permission and role      <- config/authorization.yaml
        #   collection route, payload<- the running backend's own OpenAPI
        #
        # These are the MODULE's own contracts — health, migrations, audit retention, tenant
        # isolation — so shipping them is the template's job (rules/testing-guidelines.md § What
        # ships is tested here). The Items suites next to them are examples and are deliberately
        # NOT here: a real module deletes or adapts them.
        #
        # ENFORCED, not asserted here. This comment previously made the slug-agnostic claim on
        # behalf of files that did not honour it: test_tenant_isolation.py named `template.items`,
        # `/items` and `template_items` throughout, so it could not pass in any module without an
        # `items` entity — 39 tests red, in a file the module can neither adapt (force-synced) nor
        # exclude (pytest.ini and the root conftest.py are framework-owned). A comment cannot fail,
        # which is why the claim survived. `scripts/TESTS/test_force_synced_backend_contracts_are_slug_free.py`
        # now fails when a file listed below names the reference module or writes an entity route
        # as a literal, so the next contract added here cannot ship with the same defect.
        "backend/TESTS/conftest.py"
        "backend/TESTS/test_migrations.py"
        "backend/TESTS/test_audit_retention.py"
        "backend/TESTS/test_tenant_isolation.py"
        # Audit retention observability: every module has audit tables and a retention
        # policy, and the metric surface it asserts on is framework-owned. Slug-agnostic —
        # it derives the entity names from the module's own models.py.
        "backend/TESTS/test_audit_retention_is_observable.py"
        "database/TESTS/test_datamodel_source_sync.py"
        "database/TESTS/test_authorization_source_sync.py"
        "database/TESTS/test_bootstrap_compose_contract.py"
        # Framework Playwright UI/E2E harness (@ideable/ui gallery + seeded-session
        # specs). Slug-parameterized (MODULE_SLUG) so they are force-synced verbatim.
        # Baselines (tests/**/*-snapshots/) and node_modules are NOT listed — each
        # module owns its own per-brand baselines.
        "frontend/TESTS/playwright/package.json"
        "frontend/TESTS/playwright/playwright.config.ts"
        "frontend/TESTS/playwright/.gitignore"
        "frontend/TESTS/playwright/README.md"
        "frontend/TESTS/playwright/auth/personas.ts"
        "frontend/TESTS/playwright/auth/login.ts"
        "frontend/TESTS/playwright/auth/global-setup.ts"
        "frontend/TESTS/playwright/auth/session-fixture.ts"
        # Reusable FK dependency-tree helper for FK-aware CRUD ordering.
        "frontend/TESTS/playwright/lib/entity-graph.ts"
        # Generic, discovery-driven specs — read the module's OWN manifest / backend
        # OpenAPI and work for any module with zero edits, so they ARE force-synced:
        #  - entity-pages: every entity page loads authenticated.
        #  - crud-endpoints: create/read/update/delete round-trip per discovered resource,
        #    logging each op ([CRUD] …) into the test report.
        "frontend/TESTS/playwright/tests/entity-pages.spec.ts"
        "frontend/TESTS/playwright/tests/crud-endpoints.spec.ts"
        "frontend/TESTS/playwright/tests/entity-graph.spec.ts"
        "frontend/TESTS/playwright/tests/module-css-loaded.spec.ts"
        # NOTE: the module-agnostic HARNESS (config + auth/) and the generic
        # entity-pages spec are force-synced. The entity/page-specific specs under
        # tests/ (widget-gallery, lf-parity, items-crud) are REFERENCE examples — a
        # remote copies them at init and adapts/replaces them per its own entities (a
        # force-sync would push module_template's Items tests into modules that have no
        # Items entity, as observed in SRA). When ideable-implement-specs runs in a
        # remote, the defined path is to ship one CRUD suite per entity in THAT module's
        # datamodel and DELETE any example spec whose entity is absent (e.g. remove
        # items-crud.spec.ts when there is no items entity) — no manual decision needed.
        # See rules/testing-guidelines.md § "CRUD E2E tests per entity" and the
        # ideable-implement-specs skill, Step 6 ("Entity scoping").
    )
    for test_file in "${SHARED_TESTS[@]}"; do
        LOCAL_FILE="modules/${MODULE_NAME}/${test_file}"
        TEMPLATE_FILE="modules/module_template/${test_file}"
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
        "SPECS/ideable-framework-specs/audit-trail-specs.md"
        "SPECS/ideable-framework-specs/infrastructure-file-list.md"
    )
    if [[ -d "modules/${MODULE_NAME}/backend" ]]; then
        SHARED_FRAMEWORK_SPECS+=(
            "backend/SPECS/ideable-framework-specs/base-specs.md"
            "backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md"
        )
    fi
    if [[ -d "modules/${MODULE_NAME}/database" ]]; then
        SHARED_FRAMEWORK_SPECS+=(
            "database/SPECS/ideable-framework-specs/base-specs.md"
            "database/SPECS/ideable-framework-specs/schema-workflow.md"
        )
    fi
    if [[ -d "modules/${MODULE_NAME}/frontend" ]]; then
        SHARED_FRAMEWORK_SPECS+=(
            "frontend/SPECS/ideable-framework-specs/base_specs.md"
            "frontend/SPECS/ideable-framework-specs/shared-ui-specs.md"
            "frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md"
            "frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md"
            "frontend/SPECS/ideable-framework-specs/framework-css-classes-reference.md"
            "frontend/SPECS/ideable-framework-specs/look-and-feel-branding.md"
        )
    fi

    for shared_spec in "${SHARED_FRAMEWORK_SPECS[@]}"; do
        echo ""
        echo "Syncing shared framework spec: ${shared_spec}"
        if force_sync_regular_file_from_template "modules/module_template/${shared_spec}" "modules/${MODULE_NAME}/${shared_spec}"; then
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

    # Propagate the runtime Look & Feel override hooks into the module's frontend.
    # Idempotent: injects the hook only when absent (never overwrites customizations),
    # so modules generated before the hook existed get runtime theming without a rebuild.
    if [[ -d "modules/${MODULE_NAME}/frontend/SOURCES" ]]; then
        echo ""
        echo "Syncing runtime Look & Feel override hooks (index.html, nginx.conf, config/theme-override.css)..."
        ensure_theme_override_in_index_html "$MODULE_NAME" && SYNCED=$((SYNCED + 1)) || FAILED=$((FAILED + 1))
        ensure_theme_override_in_nginx "$MODULE_NAME" && SYNCED=$((SYNCED + 1)) || FAILED=$((FAILED + 1))
        ensure_theme_override_config "$MODULE_NAME" && SYNCED=$((SYNCED + 1)) || FAILED=$((FAILED + 1))
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

        MODULE_SLUG_VALUE=$(get_module_slug)
        MODULE_DB_PREFIX=$(get_module_db_prefix)
        sync_managed_compose_sections "$MODULE_COMPOSE" "$MODULE_SLUG_VALUE" "$MODULE_DB_PREFIX" || true

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

    # A run that could not read part of the template exits non-zero. The report already says so in
    # words, but words are what a caller cannot read: the report and the exit code have to agree,
    # or a wrapper that checks `$?` learns nothing. Exit 4 is reserved for this and only this —
    # "the sync ran, and could not check everything it is responsible for".
    if [[ "$(sync_report_unavailable_count)" -gt 0 ]]; then
        exit 4
    fi
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
