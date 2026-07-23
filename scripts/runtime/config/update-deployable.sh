#!/usr/bin/env bash
# Pull the latest deployable bundle, preserving local .env configuration.
# Every local .env.config and .env.secrets file is snapshotted before the reset,
# including files not changed by the remote commit. The remote template is then
# interactively merged with each local file:
#   - new variables are added
#   - variables present in both but with different values are resolved by
#     asking the user whether to keep the local value or take the remote one
#   - variables removed in the remote template are dropped and reported
# Non-env files are reset to the remote HEAD as usual.
#
# Usage:
#   ./scripts/runtime/config/update-deployable.sh [PATH] [--dry-run] [-h|--help]
#   ./scripts/update-deployable.sh [PATH] [--dry-run] [-h|--help]   (deployed bundle)
set -euo pipefail

TEMP_BACKUP_DIR=""
MERGE_SCRIPT=""
DECISIONS_FILE=""

cleanup() {
    [[ -n "$MERGE_SCRIPT" && -f "$MERGE_SCRIPT" ]] && rm -f "$MERGE_SCRIPT"
    [[ -n "$TEMP_BACKUP_DIR" && -d "$TEMP_BACKUP_DIR" ]] && rm -rf "$TEMP_BACKUP_DIR"
    [[ -n "$DECISIONS_FILE" && -f "$DECISIONS_FILE" ]] && rm -f "$DECISIONS_FILE"
    return 0
}

trap cleanup EXIT

DRY_RUN=0
KEEP_LOCAL=0
FORCE=0
REPO_PATH=""

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            echo "Usage: $0 [PATH] [--dry-run] [--keep-local] [--force] [-h|--help]"
            echo ""
            echo "Update the deployable git repo at PATH (default: current directory)"
            echo "to the latest remote commit while preserving local environment configuration."
            echo ""
            echo "This script performs the following operations:"
            echo "  1. Fetches the configured remote branch (REMOTE, default: origin)"
            echo "  2. Reports whether the local repository is behind, ahead, or diverged from remote"
            echo "  3. If local HEAD equals remote HEAD and --force is not passed, exits with 'Up to date'"
            echo "  4. Snapshots all existing .env.config and .env.secrets files (including unchanged files)"
            echo "  5. Resets non-environment files to the remote commit"
            echo "  6. Merges each env file with its remote template:"
            echo "     - New keys from remote template are added"
            echo "     - Conflicting keys are resolved interactively (or automatically with --keep-local)"
            echo "     - Keys removed by remote template are reported and dropped"
            echo "  7. Cross-file decision memory: user choices for conflicting keys are reused"
            echo "     across multiple .env files to avoid redundant prompts"
            echo ""
            echo "Options:"
            echo "  PATH          Path to the deployable repo (default: .)"
            echo "  --dry-run     Inspect changes but do not reset the working tree or write files"
            echo "  --keep-local  Automatically keep all local values for conflicting env vars"
            echo "                (skips interactive prompts; equivalent to answering 'old' to all)"
            echo "  --force       Reconsider env var changes even if local and remote commits are the same"
            echo "                (useful when local env edits are not yet committed)"
            echo "  -h, --help    Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  REMOTE        Git remote to fetch from (default: origin)"
            echo "  BRANCH        Branch to fetch and reset to (default: main)"
            exit 0
            ;;
        --dry-run)
            DRY_RUN=1
            ;;
        --keep-local)
            KEEP_LOCAL=1
            ;;
        --force)
            FORCE=1
            ;;
        -*)
            echo "Error: unknown option $arg" >&2
            exit 1
            ;;
        *)
            if [[ -z "$REPO_PATH" ]]; then
                REPO_PATH="$arg"
            else
                echo "Error: only one PATH argument is allowed" >&2
                exit 1
            fi
            ;;
    esac
done

REPO_PATH="${REPO_PATH:-.}"
if [[ ! -d "$REPO_PATH" ]]; then
    echo "Error: directory does not exist: $REPO_PATH" >&2
    exit 1
fi

cd "$REPO_PATH"

if [[ ! -d .git ]]; then
    echo "Error: $REPO_PATH is not a git repository" >&2
    exit 1
fi

# If --keep-local was not passed, ask the user interactively
if [[ "$KEEP_LOCAL" -eq 0 ]] && [[ -t 0 ]]; then
    echo ""
    echo "When merging environment files, conflicting values will need to be resolved."
    echo "You can choose to automatically keep all local values for conflicts, or resolve"
    echo "each conflict interactively."
    echo ""
    read -p "Keep all local values for conflicts? [y/N]: " -r
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        KEEP_LOCAL=1
        echo "Will keep all local values for conflicts (equivalent to --keep-local)"
    else
        echo "Will resolve conflicts interactively"
    fi
fi

REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
REMOTE_BRANCH="$REMOTE/$BRANCH"

echo "=== Deployable repo: $(pwd) ==="
echo "Remote: $(git remote get-url "$REMOTE" 2>/dev/null || echo "(none)")"
echo "Local branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "(unknown)")"
echo ""

echo "=== Fetching remote ==="
if ! git fetch "$REMOTE" "$BRANCH"; then
    echo "Error: failed to fetch $REMOTE/$BRANCH" >&2
    exit 1
fi
echo ""

LOCAL_HEAD=$(git rev-parse HEAD)
# Some git configurations (or shallow clones) do not create the remote tracking
# ref (origin/main) after a fetch; FETCH_HEAD is always updated.
REMOTE_HEAD=$(git rev-parse "$REMOTE_BRANCH" 2>/dev/null || git rev-parse FETCH_HEAD 2>/dev/null || true)
if [[ -z "$REMOTE_HEAD" ]]; then
    echo "Error: cannot determine remote HEAD for $REMOTE/$BRANCH" >&2
    exit 1
fi

if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
    echo "=== Up to date ==="
    echo "Local and remote are already at the same commit: ${LOCAL_HEAD:0:12}"
    if [[ "$FORCE" -eq 1 ]]; then
        echo "--force: proceeding with env-merge pass anyway"
    else
        exit 0
    fi
fi

if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
    LOCAL_BASE=$(git merge-base HEAD "$REMOTE_HEAD" 2>/dev/null || true)

    if [[ "$LOCAL_BASE" == "$REMOTE_HEAD" ]]; then
        echo "=== Status: local is ahead of remote ==="
        echo "Remote can be fast-forwarded. Local commits not on remote:"
        git log --oneline "$REMOTE_HEAD..HEAD"
    elif [[ "$LOCAL_BASE" == "$LOCAL_HEAD" ]]; then
        echo "=== Status: remote is ahead of local (fast-forward possible) ==="
        echo "Incoming commits:"
        git log --oneline "HEAD..$REMOTE_HEAD"
    else
        echo "=== Status: DIVERGED (force update detected) ==="
        echo "Common ancestor: ${LOCAL_BASE:-unknown}"
        echo ""
        echo "Incoming remote commits (will replace local state):"
        git log --oneline "HEAD..$REMOTE_HEAD"
        echo ""
        echo "Local commits that would be discarded:"
        git log --oneline "$REMOTE_HEAD..HEAD"
    fi

    echo ""
    echo "=== Files changed on remote ==="
    git diff --stat "$LOCAL_HEAD..$REMOTE_HEAD"
else
    LOCAL_BASE="$LOCAL_HEAD"
    echo ""
    echo "=== No remote changes; --force will re-merge local env values against committed templates ==="
fi

echo ""
echo "=== Checking for .env files to preserve ==="

# Snapshot every existing local .env.config and .env.secrets file, not only
# files changed by the remote commit. git reset --hard would otherwise discard
# local customizations in tracked env files that upstream did not touch.
CHANGED_ENV_FILES=()
while IFS= read -r -d '' file; do
    file="${file#./}"
    CHANGED_ENV_FILES+=("$file")
done < <(find . -path './.git' -prune -o -type f \( -name '.env.config' -o -name '.env.secrets' \) -print0)

# Also include env files introduced or renamed by the remote update.
while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    # git diff --name-status lines look like:
    #   M<TAB>path/to/file
    #   R100<TAB>old<TAB>new
    # The last field is the post-update path we care about.
    file="$(printf '%s' "$line" | awk -F'\t' '{print $NF}')"
    [[ -n "$file" ]] || continue
    case "$file" in
        *.env.config|*.env.secrets)
            already_listed=0
            for existing in "${CHANGED_ENV_FILES[@]}"; do
                if [[ "$existing" == "$file" ]]; then
                    already_listed=1
                    break
                fi
            done
            [[ "$already_listed" -eq 1 ]] || CHANGED_ENV_FILES+=("$file")
            ;;
    esac
done < <(git diff --name-status "$LOCAL_HEAD..$REMOTE_HEAD")

if [[ ${#CHANGED_ENV_FILES[@]} -eq 0 ]]; then
    echo "  No local or remote .env.config/.env.secrets files found."
else
    TEMP_BACKUP_DIR=$(mktemp -d)
    echo "  Snapshotting local .env files to: $TEMP_BACKUP_DIR"
    for file in "${CHANGED_ENV_FILES[@]}"; do
        if [[ -f "$file" ]]; then
            mkdir -p "$(dirname "$TEMP_BACKUP_DIR/$file")"
            cp "$file" "$TEMP_BACKUP_DIR/$file"
            echo "    snapshotted: $file"
        fi
    done

    MERGE_SCRIPT=$(mktemp)
    cat > "$MERGE_SCRIPT" <<'PYEOF'
#!/usr/bin/env python3
import os
import re
import sys


def parse_env(path):
    entries = []
    keys = {}
    if not os.path.exists(path):
        return entries, keys
    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                entries.append(("raw", line, None))
            else:
                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
                if m:
                    key, value = m.group(1), m.group(2)
                    entries.append(("kv", key, value))
                    keys[key] = value
                else:
                    entries.append(("raw", line, None))
    return entries, keys


def prompt_choice(key, old_val, new_val):
    print(f"  {key}:")
    print(f"    [o] old: {old_val}")
    print(f"    [n] new: {new_val}")
    print(f"    [d] show diff")
    while True:
        try:
            ans = input("  Choice [o/n/d]: ").strip().lower()
        except EOFError:
            print("  EOF detected; keeping old value.")
            return old_val
        if ans in ("o", "old"):
            return old_val
        elif ans in ("n", "new"):
            return new_val
        elif ans in ("d", "diff"):
            print(f"    - {key}={old_val}")
            print(f"    + {key}={new_val}")
        else:
            print("    Please enter o, n, or d.")


def load_decisions(path):
    decisions = {}
    if not path or not os.path.exists(path):
        return decisions
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                decisions[k.strip()] = v.strip()
    return decisions


def save_decisions(path, decisions):
    if not path:
        return
    with open(path, "w") as f:
        for k in sorted(decisions):
            f.write(f"{k}={decisions[k]}\n")


def main():
    if len(sys.argv) < 4:
        print("Usage: merge_env.py <old_env> <new_env> <out_env> [--dry-run] [--keep-local] [--decisions-file PATH]", file=sys.stderr)
        sys.exit(1)
    old_path = sys.argv[1]
    new_path = sys.argv[2]
    out_path = sys.argv[3]
    extra = sys.argv[4:]
    dry_run = "--dry-run" in extra
    keep_local = "--keep-local" in extra
    decisions_file = None
    if "--decisions-file" in extra:
        idx = extra.index("--decisions-file")
        if idx + 1 < len(extra):
            decisions_file = extra[idx + 1]
    prior_decisions = load_decisions(decisions_file)

    old_entries, old_keys = parse_env(old_path)
    new_entries, new_keys = parse_env(new_path)

    removed = [k for k in old_keys if k not in new_keys]
    added = [k for k in new_keys if k not in old_keys]
    changed = [k for k in new_keys if k in old_keys and old_keys[k] != new_keys[k]]

    if removed:
        print("  Removed variables (no longer in new template):")
        for k in removed:
            print(f"    - {k}={old_keys[k]}")
    if added:
        print("  New variables:")
        for k in added:
            print(f"    + {k}={new_keys[k]}")
    if changed:
        print("  Changed variables:")
        for k in changed:
            print(f"    ~ {k}:")
            print(f"        old: {old_keys[k]}")
            print(f"        new: {new_keys[k]}")

    if dry_run:
        save_decisions(decisions_file, dict(prior_decisions))
        return

    prefer = None
    if keep_local:
        prefer = "old"
    elif not sys.stdin.isatty():
        print("  Warning: stdin is not a TTY; keeping old values for conflicts.", file=sys.stderr)
        prefer = "old"

    decisions = dict(prior_decisions)
    result = []
    for entry in new_entries:
        if entry[0] == "raw":
            result.append(entry[1])
        else:
            key, new_val = entry[1], entry[2]
            if key in old_keys and old_keys[key] != new_val:
                if key in decisions:
                    chosen = decisions[key]
                    print(f"  {key}: reused prior decision ({chosen})")
                elif prefer == "old":
                    chosen = old_keys[key]
                    decisions[key] = chosen
                    print(f"  {key}: kept old value (non-interactive)")
                else:
                    chosen = prompt_choice(key, old_keys[key], new_val)
                    decisions[key] = chosen
                result.append(f"{key}={chosen}\n")
            else:
                result.append(f"{key}={new_val}\n")

    save_decisions(decisions_file, decisions)

    with open(out_path, "w") as f:
        f.writelines(result)


if __name__ == "__main__":
    main()
PYEOF
    chmod +x "$MERGE_SCRIPT"
    DECISIONS_FILE=$(mktemp)

    echo ""
    echo "=== Diff for .env files (local → remote) ==="
    for file in "${CHANGED_ENV_FILES[@]}"; do
        echo ""
        echo "--- $file ---"
        git diff "$LOCAL_HEAD..$REMOTE_HEAD" -- "$file" || true
    done
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "=== Dry-run merge preview for .env files ==="
    if [[ ${#CHANGED_ENV_FILES[@]} -gt 0 ]]; then
        for file in "${CHANGED_ENV_FILES[@]}"; do
            old_file="$TEMP_BACKUP_DIR/$file"
            remote_file=$(mktemp)
            if git show "$REMOTE_HEAD:$file" > "$remote_file" 2>/dev/null; then
                echo ""
                echo "--- $file ---"
                if [[ -f "$old_file" ]]; then
                    python3 "$MERGE_SCRIPT" "$old_file" "$remote_file" "/dev/null" --dry-run --decisions-file "$DECISIONS_FILE"$( [[ "$KEEP_LOCAL" -eq 1 ]] && echo " --keep-local" )
                else
                    echo "  New env file added by remote update."
                    python3 "$MERGE_SCRIPT" "/dev/null" "$remote_file" "/dev/null" --dry-run --decisions-file "$DECISIONS_FILE"$( [[ "$KEEP_LOCAL" -eq 1 ]] && echo " --keep-local" )
                fi
            else
                echo ""
                echo "--- $file ---"
                if [[ -f "$old_file" ]]; then
                    echo "  Env file removed in remote update; local variables would be dropped."
                    python3 "$MERGE_SCRIPT" "$old_file" "/dev/null" "/dev/null" --dry-run --decisions-file "$DECISIONS_FILE"$( [[ "$KEEP_LOCAL" -eq 1 ]] && echo " --keep-local" )
                else
                    echo "  Warning: neither local nor remote version found for $file" >&2
                fi
            fi
            rm -f "$remote_file"
        done
    fi
    echo ""
    echo "=== Dry run; working tree left unchanged ==="
    exit 0
fi

# Pre-check for files/directories that git reset --hard will not be able to write.
# These are typically root-owned because Docker containers wrote them, or locked
# because a container has them mounted. Catching this early prevents the messy
# half-reset state and gives the user actionable recovery steps.
echo ""
echo "=== Checking write permissions for files changed by remote ==="
UNWRITABLE_FILES=()
while IFS= read -r -d '' file; do
    [[ -n "$file" ]] || continue
    if [[ -e "$file" ]]; then
        if [[ ! -w "$file" ]]; then
            UNWRITABLE_FILES+=("$file")
        fi
    else
        # File will be created by reset; check parent directory writability
        parent=$(dirname "$file")
        if [[ ! -d "$parent" || ! -w "$parent" ]]; then
            UNWRITABLE_FILES+=("$file (parent directory not writable: $parent)")
        fi
    fi
done < <(git diff --name-only -z "$LOCAL_HEAD..$REMOTE_HEAD")

if [[ ${#UNWRITABLE_FILES[@]} -gt 0 ]]; then
    echo "ERROR: the following files or directories are not writable and would block the update:" >&2
    for f in "${UNWRITABLE_FILES[@]}"; do
        echo "  - $f" >&2
    done
    echo "" >&2
    echo "Common cause: a running container owns these files. To fix, run:" >&2
    echo "  ./stop.sh" >&2
    echo "" >&2
    echo "If the files are owned by root (common on Linux with Docker), also run:" >&2
    echo "  sudo chown -R \$(whoami):\$(whoami) ." >&2
    echo "" >&2
    echo "Then re-run ./scripts/update-deployable.sh" >&2
    exit 1
fi

echo ""
echo "=== Resetting local branch to $REMOTE/$BRANCH ($REMOTE_HEAD) ==="
git reset --hard "$REMOTE_HEAD"
echo "Local branch is now at: $(git rev-parse --short HEAD)"

if [[ ${#CHANGED_ENV_FILES[@]} -gt 0 ]]; then
    echo ""
    echo "=== Merging .env files (local values vs remote template) ==="
    for file in "${CHANGED_ENV_FILES[@]}"; do
        old_file="$TEMP_BACKUP_DIR/$file"
        new_file="$file"
        echo ""
        echo "--- $file ---"
        if [[ -f "$old_file" && -f "$new_file" ]]; then
            python3 "$MERGE_SCRIPT" "$old_file" "$new_file" "$new_file" --decisions-file "$DECISIONS_FILE"$( [[ "$KEEP_LOCAL" -eq 1 ]] && echo " --keep-local" )
        elif [[ -f "$old_file" && ! -f "$new_file" ]]; then
            echo "  Env file removed in remote update; dropped local variables."
            python3 "$MERGE_SCRIPT" "$old_file" "/dev/null" "/dev/null" --dry-run --decisions-file "$DECISIONS_FILE"$( [[ "$KEEP_LOCAL" -eq 1 ]] && echo " --keep-local" )
        elif [[ ! -f "$old_file" && -f "$new_file" ]]; then
            echo "  New env file added by remote update; kept as-is."
        else
            echo "  Warning: neither local nor remote version found for $file" >&2
        fi
    done
fi
