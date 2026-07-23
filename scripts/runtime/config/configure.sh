#!/bin/bash
#
# configure.sh
#
# Interactive configuration script for a deployed Ideable project.
# Scans the exposed ports declared in the project env file, checks which are
# already in use on the host, reports conflicts, and interactively reassigns
# them. Also sets PROJECT_ROOT to the current working directory by default.
# Updates the target env file in place and also updates the corresponding
# fallback port values in module-side .env.config files. Prints a final recap.
#
# Usage:
#   ./scripts/runtime/config/configure.sh [-h|--help]
#   ./scripts/configure.sh [-h|--help]         (deployed bundle)
#

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Scans exposed ports declared in the project env file, checks for conflicts on the host,"
    echo "interactively reassigns conflicting ports, and updates the env file in place."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Detect context: source repo (script in scripts/runtime/config/) vs deployed (script in scripts/)
# In source repo: script is 3 levels deep → project.env.config is at ../../..
# In deployed: script is 1 level deep → no project.env.config, use .env.config in parent
if [[ -f "$SCRIPT_DIR/../../../project.env.config" ]]; then
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
    PROJECT_ENV="${PROJECT_ROOT}/project.env.config"
    PROJECT_SECRETS="${PROJECT_ROOT}/project.env.secrets"
    MODULES_DIR="${PROJECT_ROOT}/modules"
    ENABLED_MD="${MODULES_DIR}/enabled.md"
else
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    PROJECT_ENV="${PROJECT_ROOT}/.env.config"
    PROJECT_SECRETS="${PROJECT_ROOT}/.env.secrets"
    MODULES_DIR="${PROJECT_ROOT}/modules"
    ENABLED_MD=""
fi

# Source env files so variables are exported into the shell environment.
# Source secrets before config because config files may reference secret variables.
if [[ -f "$PROJECT_SECRETS" ]]; then
    # shellcheck disable=SC1090
    set +u
    set -a
    source "$PROJECT_SECRETS"
    set +a
    set -u
fi
if [[ -f "$PROJECT_ENV" ]]; then
    # shellcheck disable=SC1090
    set +u
    set -a
    source "$PROJECT_ENV"
    set +a
    set -u
fi

# Temporary files for bash 3.2 compatibility (no associative arrays)
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

F_COMPOSE_VAR="${TMPDIR}/compose_var.txt"
F_MODULE_VAR="${TMPDIR}/module_var.txt"
F_PROJECT_VAR="${TMPDIR}/project_var.txt"
F_SERVICES="${TMPDIR}/services.txt"
F_MODULES="${TMPDIR}/modules.txt"
F_DEFAULTS="${TMPDIR}/defaults.txt"
F_COMPOSE_VAR_FILE="${TMPDIR}/compose_var_file.txt"
F_USED_PORTS="${TMPDIR}/used_ports.txt"

for f in "$F_COMPOSE_VAR" "$F_MODULE_VAR" "$F_PROJECT_VAR" "$F_SERVICES" "$F_MODULES" "$F_DEFAULTS" "$F_COMPOSE_VAR_FILE" "$F_USED_PORTS"; do
    touch "$f"
done

# ---------------------------------------------------------------------------
# KV helpers
# ---------------------------------------------------------------------------
kv_get() {
    local file="$1" key="$2"
    grep "^${key}=" "$file" 2>/dev/null | sed "s/^${key}=//" | tail -1 || true
}

# Replace the line that starts with key= in a file. Uses Python so values may
# contain any characters (slashes, equals, spaces, etc.) without breaking the
# replacement.
replace_line_with_key() {
    local key="$1" value="$2" file="$3"
    python3 -c "
import sys
key, value, path = sys.argv[1:4]
with open(path, 'r') as f:
    lines = f.readlines()
with open(path, 'w') as f:
    for line in lines:
        if line.startswith(key + '='):
            f.write(key + '=' + value + '\n')
        else:
            f.write(line)
" "$key" "$value" "$file"
}

kv_set() {
    local file="$1" key="$2" value="$3"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        replace_line_with_key "$key" "$value" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

# ---------------------------------------------------------------------------
# Port conflict helpers
# ---------------------------------------------------------------------------
port_is_in_use() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"${port}" -sTCP:LISTEN -t >/dev/null 2>&1 && return 0
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -tln 2>/dev/null | awk -v p="${port}" '$0 ~ ":"p" " {exit 0} {exit 1}' && return 0
    fi
    if command -v netstat >/dev/null 2>&1; then
        netstat -tln 2>/dev/null | awk -v p="${port}" '$0 ~ ":"p" " {exit 0} {exit 1}' && return 0
    fi
    if command -v nc >/dev/null 2>&1; then
        nc -z localhost "${port}" 2>/dev/null && return 0
    fi
    return 1
}

port_owner() {
    local port="$1"
    local owner=""

    # Try lsof (Linux / macOS)
    if command -v lsof >/dev/null 2>&1; then
        owner=$(lsof -iTCP:"${port}" -sTCP:LISTEN -Fc 2>/dev/null | sed -n 's/^c//p' | head -1)
        [[ -n "$owner" ]] && { echo "$owner"; return; }

        # Some lsof versions don't support -sTCP:LISTEN
        owner=$(lsof -iTCP:"${port}" -Fc 2>/dev/null | sed -n 's/^c//p' | head -1)
        [[ -n "$owner" ]] && { echo "$owner"; return; }
    fi

    # Try ss with process info (Linux)
    if command -v ss >/dev/null 2>&1; then
        owner=$(ss -tlnp 2>/dev/null | awk -v p="${port}" '
            $0 ~ ":"p" " {
                match($0, /users:\(\("([^"]+)"/, m)
                if (m[1]) { print m[1]; exit }
                match($0, /pid=([0-9]+)/, m)
                if (m[1]) {
                    cmd = "ps -p " m[1] " -o comm= 2>/dev/null"
                    cmd | getline proc
                    close(cmd)
                    print proc
                    exit
                }
            }
        ')
        [[ -n "$owner" ]] && { echo "$owner"; return; }
    fi

    # Try netstat (older systems)
    if command -v netstat >/dev/null 2>&1; then
        owner=$(netstat -tlnp 2>/dev/null | awk -v p="${port}" '
            $0 ~ ":"p" " {
                last = $NF
                split(last, parts, "/")
                if (parts[2]) { print parts[2]; exit }
            }
        ')
        [[ -n "$owner" ]] && { echo "$owner"; return; }
    fi

    # Try fuser + ps
    if command -v fuser >/dev/null 2>&1; then
        local pids
        pids=$(fuser "${port}/tcp" 2>/dev/null | tr -s ' ' '\n' | grep -v '^$')
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                owner=$(ps -p "$pid" -o comm= 2>/dev/null | head -1)
                [[ -n "$owner" ]] && { echo "$owner"; return; }
            done
        fi
    fi

    # Try docker (container might be using the port)
    if command -v docker >/dev/null 2>&1; then
        owner=$(docker ps --format "{{.Names}}" --filter "publish=${port}" 2>/dev/null | head -1)
        [[ -n "$owner" ]] && { echo "docker:$owner"; return; }
    fi

    echo "(unknown)"
}

# Check whether a port is already bound by a container that belongs to this
# compose project.  Returns 0 and prints the service name when it does.
port_belongs_to_project() {
    local port="$1"
    [[ -n "$APP_SLUG" ]] || return 1
    if ! command -v docker >/dev/null 2>&1; then
        return 1
    fi

    local cid_tmp port_tmp label_tmp
    cid_tmp="${TMPDIR}/docker_cids.txt"
    port_tmp="${TMPDIR}/docker_port.txt"
    label_tmp="${TMPDIR}/docker_label.txt"

    docker ps -q > "$cid_tmp" 2>/dev/null || return 1

    while IFS= read -r cid; do
        [[ -n "$cid" ]] || continue

        if ! docker port "$cid" > "$port_tmp" 2>/dev/null; then
            continue
        fi

        local port_match=0
        port_match=$(awk -v p="$port" '
            {
                # Last field is host mapping like 0.0.0.0:8002 or [::]:8002
                n = split($NF, parts, ":")
                host_port = parts[n]
                # Strip any trailing /tcp, /udp etc.
                sub(/\/[a-z]+$/, "", host_port)
                if (host_port == p) { found = 1; exit }
            }
            END { print (found ? 1 : 0) }
        ' "$port_tmp")

        if [[ "$port_match" != "1" ]]; then
            continue
        fi

        if ! docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}' "$cid" > "$label_tmp" 2>/dev/null; then
            continue
        fi

        local proj svc
        proj="$(cut -d'|' -f1 "$label_tmp")"
        svc="$(cut -d'|' -f2 "$label_tmp")"

        if [[ "$proj" == "$APP_SLUG" ]]; then
            echo "${svc:-$cid}"
            return 0
        fi
    done < "$cid_tmp"

    return 1
}

get_env_value() {
    local key="$1" file="$2"
    if [[ -f "$file" ]]; then
        grep -E "^${key}=" "$file" 2>/dev/null | tail -1 | sed "s/^${key}=//" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true
    fi
}

# Resolve a var value across PROJECT_ENV and all module .env.config/.env.secrets files.
# Returns the first match found.
resolve_env_value() {
    local key="$1"
    local val
    # Check PROJECT_ENV first
    val="$(get_env_value "$key" "$PROJECT_ENV")"
    if [[ -n "$val" ]]; then
        echo "$val"
        return 0
    fi
    # Check module env files
    for module_name in "${ENABLED_MODULES[@]}"; do
        for module_env in "${MODULES_DIR}/${module_name}/.env.config" "${MODULES_DIR}/${module_name}/.env.secrets"; do
            val="$(get_env_value "$key" "$module_env")"
            if [[ -n "$val" ]]; then
                echo "$val"
                return 0
            fi
        done
    done
    return 1
}

# Find which env file contains the given var (for updating).
# Checks PROJECT_ENV first, then module env files.
resolve_env_file() {
    local key="$1"
    if grep -qE "^${key}=" "$PROJECT_ENV" 2>/dev/null; then
        echo "$PROJECT_ENV"
        return 0
    fi
    for module_name in "${ENABLED_MODULES[@]}"; do
        for module_env in "${MODULES_DIR}/${module_name}/.env.config" "${MODULES_DIR}/${module_name}/.env.secrets"; do
            if grep -qE "^${key}=" "$module_env" 2>/dev/null; then
                echo "$module_env"
                return 0
            fi
        done
    done
    return 1
}

set_env_value() {
    local key="$1" value="$2" file="$3"
    if grep -qE "^${key}=" "$file" 2>/dev/null; then
        replace_line_with_key "$key" "$value" "$file"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$file"
    fi
}

# Ensure a project-level env var in a module file is written as a reference
# (e.g. APP_SLUG=${APP_SLUG}) so it inherits the root value at runtime.
ensure_env_reference() {
    local key="$1" file="$2"
    if [[ ! -f "$file" ]]; then
        return
    fi
    if ! grep -qE "^${key}=" "$file" 2>/dev/null; then
        return
    fi
    if grep -qE "^${key}=\\\$\\\{${key}\\\}$" "$file" 2>/dev/null; then
        # Already a reference; nothing to do.
        return
    fi
    replace_line_with_key "$key" "\${${key}}" "$file"
    echo "  Converted ${key} to reference in ${file##*/}"
}

# Update the default value in a module-side .env.config for the corresponding compose var.
# Handles both direct values (e.g. TEMPLATE_POSTGRES_PORT=5434) and project var references
# (e.g. SRA_POSTGRES_PORT=${IDEABLE_MODULE_POSTGRES_PORT:-5434}).
update_module_env_port() {
    local cvar="$1" new_port="$2" module_env="$3"
    if [[ -z "$module_env" || ! -f "$module_env" ]]; then
        return
    fi
    if grep -qE "^${cvar}=" "$module_env" 2>/dev/null; then
        sed -i.bak "s/^\\(${cvar}=[^0-9]*\\)[0-9]\\+/\\1${new_port}/" "$module_env"
        rm -f "${module_env}.bak"
        echo "    Updated ${cvar} fallback/default to ${new_port} in ${module_env##*/}"
    fi
}

# Compose project name (always APP_SLUG) for distinguishing our own running containers
APP_SLUG="${APP_SLUG:-$(get_env_value "APP_SLUG" "$PROJECT_ENV")}"

# ---------------------------------------------------------------------------
# Parse enabled modules
# ---------------------------------------------------------------------------
ENABLED_MODULES=()
if [[ -n "$ENABLED_MD" && -f "$ENABLED_MD" ]]; then
    while IFS= read -r line; do
        line="${line%%#*}"
        line="$(echo "$line" | sed 's/[[:space:]]*$//')"
        [[ -z "$line" ]] && continue
        if [[ "$line" =~ ^([A-Za-z0-9_-]+):[[:space:]]*(local|remote) ]]; then
            ENABLED_MODULES+=("${BASH_REMATCH[1]}")
        fi
    done < "$ENABLED_MD"
elif [[ -d "$MODULES_DIR" ]]; then
    for entry in "$MODULES_DIR"/*/; do
        [[ -d "$entry" ]] || continue
        ENABLED_MODULES+=("$(basename "$entry")")
    done
fi

if [[ ${#ENABLED_MODULES[@]} -eq 0 ]]; then
    echo "ERROR: no enabled modules found"
    exit 1
fi

echo "========================================"
echo "  Configure"
echo "========================================"
echo ""
echo "Enabled modules: ${ENABLED_MODULES[*]}"
echo ""

# ---------------------------------------------------------------------------
# 1. Scan compose files: build map compose_var -> module|service|container_port
# ---------------------------------------------------------------------------
for module_name in "${ENABLED_MODULES[@]}"; do
    compose_file="${MODULES_DIR}/${module_name}/docker-compose.yml"
    [[ -f "$compose_file" ]] || continue

    awk -v mod="$module_name" '
    /^services:/ { in_svc = 1; next }
    in_svc && /^  [A-Za-z0-9_-]+:$/ {
        svc = $0
        gsub(/^  /, "", svc)
        gsub(/:$/, "", svc)
        current_service = svc
        in_ports = 0
        next
    }
    in_svc && /^    ports:/ { in_ports = 1; next }
    in_svc && in_ports && /^    [A-Za-z0-9_-]+:/ {
        in_ports = 0
        next
    }
    in_svc && in_ports {
        line = $0
        gsub(/^ *- *"?/, "", line)
        gsub(/"?$/, "", line)
        if (match(line, /\$\{([A-Za-z0-9_]+)(:-[0-9]+)?\}:[0-9]+(\/[a-z]+)?/)) {
            full = substr(line, RSTART, RLENGTH)
            if (match(full, /\$\{([A-Za-z0-9_]+)/)) {
                var = substr(full, RSTART + 2, RLENGTH - 2)
                defval = ""
                if (match(full, /:-([0-9]+)/)) {
                    defval = substr(full, RSTART + 2, RLENGTH - 2)
                }
                # Extract container port: everything after the last colon
                # full looks like ${VAR:-default}:80 or ${VAR}:80/tcp
                rest = full
                gsub(/^[^:]*:/, "", rest)
                gsub(/\/[a-z]+$/, "", rest)
                cp = rest
                print var "|" mod "|" current_service "|" cp "|" defval
            }
        }
    }
    ' "$compose_file" | while IFS='|' read -r cvar mod service cport default; do
        existing="$(kv_get "$F_COMPOSE_VAR" "$cvar")"
        if [[ -z "$existing" ]]; then
            kv_set "$F_COMPOSE_VAR" "$cvar" "${mod}|${service}|${cport}|${default}"
        else
            old_mod="$(echo "$existing" | cut -d'|' -f1)"
            old_svc="$(echo "$existing" | cut -d'|' -f2)"
            old_cp="$(echo "$existing" | cut -d'|' -f3)"
            old_def="$(echo "$existing" | cut -d'|' -f4)"
            kv_set "$F_COMPOSE_VAR" "$cvar" "${old_mod}|${old_svc},${service}|${old_cp}|${old_def}"
        fi
    done
done

# ---------------------------------------------------------------------------
# 2. Scan module .env files: build map module_var -> compose_var
#    and project_var -> module_var
# ---------------------------------------------------------------------------
for module_name in "${ENABLED_MODULES[@]}"; do
    # Read both .env.config and .env.secrets for each module
    for module_env in "${MODULES_DIR}/${module_name}/.env.config" "${MODULES_DIR}/${module_name}/.env.secrets"; do
        [[ -f "$module_env" ]] || continue

        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            cvar="${line%%=*}"
            [[ -z "$cvar" ]] && continue
            meta="$(kv_get "$F_COMPOSE_VAR" "$cvar")"
            [[ -z "$meta" ]] && continue

            env_line="$(grep -E "^${cvar}=" "$module_env" 2>/dev/null | tail -1 || true)"
            [[ -z "$env_line" ]] && continue

            # Remember which module env file owns this compose var
            kv_set "$F_COMPOSE_VAR_FILE" "$cvar" "$module_env"

            # Extract a project-level var reference like ${HOSTAPP_POSTGRES_PORT:-5433}
            if [[ "$env_line" =~ \$\{([A-Za-z0-9_]+) ]]; then
                pvar="${BASH_REMATCH[1]}"
                if grep -qE "^${pvar}=" "$PROJECT_ENV" 2>/dev/null; then
                    kv_set "$F_MODULE_VAR" "$cvar" "$pvar"
                    kv_set "$F_PROJECT_VAR" "$pvar" "$cvar"

                    meta_mod="$(echo "$meta" | cut -d'|' -f1)"
                    meta_svc="$(echo "$meta" | cut -d'|' -f2)"
                    meta_def="$(echo "$meta" | cut -d'|' -f4)"

                    existing_svc="$(kv_get "$F_SERVICES" "$pvar")"
                    if [[ -z "$existing_svc" ]]; then
                        kv_set "$F_SERVICES" "$pvar" "$meta_svc"
                        kv_set "$F_MODULES" "$pvar" "$meta_mod"
                        kv_set "$F_DEFAULTS" "$pvar" "$meta_def"
                    else
                        kv_set "$F_SERVICES" "$pvar" "${existing_svc},${meta_svc}"
                    fi
                fi
            else
                # Direct value (no ${...} reference): treat the compose var
                # itself as the project-level var so it gets checked for conflicts.
                pvar="$cvar"
                # Only register if not already mapped via indirection
                existing_pv="$(kv_get "$F_PROJECT_VAR" "$pvar")"
                if [[ -z "$existing_pv" ]]; then
                    kv_set "$F_MODULE_VAR" "$cvar" "$pvar"
                    kv_set "$F_PROJECT_VAR" "$pvar" "$cvar"

                    meta_mod="$(echo "$meta" | cut -d'|' -f1)"
                    meta_svc="$(echo "$meta" | cut -d'|' -f2)"
                    meta_def="$(echo "$meta" | cut -d'|' -f4)"

                    kv_set "$F_SERVICES" "$pvar" "$meta_svc"
                    kv_set "$F_MODULES" "$pvar" "$meta_mod"
                    kv_set "$F_DEFAULTS" "$pvar" "$meta_def"
                else
                    # Already registered; just append service if new
                    meta_svc="$(echo "$meta" | cut -d'|' -f2)"
                    meta_mod="$(echo "$meta" | cut -d'|' -f1)"
                    meta_def="$(echo "$meta" | cut -d'|' -f4)"
                    existing_svc="$(kv_get "$F_SERVICES" "$pvar")"
                    if [[ -n "$existing_svc" && "$existing_svc" != *"$meta_svc"* ]]; then
                        kv_set "$F_SERVICES" "$pvar" "${existing_svc},${meta_svc}"
                    fi
                fi
            fi
        done < "$F_COMPOSE_VAR"
    done
done

# Build a sorted list of project-level port vars
PROJECT_VARS=()
while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    var="${line%%=*}"
    [[ -n "$var" ]] && PROJECT_VARS+=("$var")
done < "$F_PROJECT_VAR"

IFS=$'\n' PROJECT_VARS=($(sort <<<"${PROJECT_VARS[*]}")); unset IFS

if [[ ${#PROJECT_VARS[@]} -eq 0 ]]; then
    echo "No project-level exposed ports found."
    exit 0
fi

# ---------------------------------------------------------------------------
# 3. Check each port for conflicts on the host
# ---------------------------------------------------------------------------
echo "Scanning exposed ports ..."
echo ""

CONFLICT_VARS=()
CONFLICT_VALS=()
CONFLICT_MODS=()
CONFLICT_SVCS=()

for var in "${PROJECT_VARS[@]}"; do
    current_value="$(resolve_env_value "$var" || true)"
    if [[ -z "$current_value" ]]; then
        current_value="$(kv_get "$F_DEFAULTS" "$var")"
    fi
    # Skip if still empty (var not found anywhere and no default)
    [[ -z "$current_value" ]] && continue

    module_name="$(kv_get "$F_MODULES" "$var")"
    service_name="$(kv_get "$F_SERVICES" "$var")"

    # Detect multiple services/variables assigned to the same port. This catches
    # cross-module collisions (e.g. host_app database and a remote module
    # database both defaulting to 5434) that a simple host-listen check misses
    # when no container is running yet.
    previous_assignee="$(kv_get "$F_USED_PORTS" "$current_value" || true)"
    if [[ -n "$previous_assignee" ]]; then
        printf "  CONFLICT: %-40s %-6s  (%s / %s)\n" "${var}=${current_value}" "" "$module_name" "$service_name"
        printf "            same port already assigned to: %s\n" "$previous_assignee"
        CONFLICT_VARS+=("$var")
        CONFLICT_VALS+=("$current_value")
        CONFLICT_MODS+=("$module_name")
        CONFLICT_SVCS+=("$service_name")
        continue
    fi
    kv_set "$F_USED_PORTS" "$current_value" "${var} (${module_name} / ${service_name})"

    if port_is_in_use "$current_value"; then
        project_container="$(port_belongs_to_project "$current_value" || true)"
        if [[ -n "$project_container" ]]; then
            printf "  OK:       %-40s %-6s  (%s / %s)\n" "${var}=${current_value}" "" "$module_name" "$service_name"
            printf "            (already bound by this project: %s)\n" "$project_container"
        else
            owner="$(port_owner "$current_value")"
            printf "  CONFLICT: %-40s %-6s  (%s / %s)\n" "${var}=${current_value}" "" "$module_name" "$service_name"
            printf "            already in use by: %s\n" "$owner"
            CONFLICT_VARS+=("$var")
            CONFLICT_VALS+=("$current_value")
            CONFLICT_MODS+=("$module_name")
            CONFLICT_SVCS+=("$service_name")
        fi
    else
        printf "  OK:       %-40s %-6s  (%s / %s)\n" "${var}=${current_value}" "" "$module_name" "$service_name"
    fi
done

echo ""

# ---------------------------------------------------------------------------
# 4. Interactive reassignment for conflicts
# ---------------------------------------------------------------------------
if [[ ${#CONFLICT_VARS[@]} -eq 0 ]]; then
    echo "No port conflicts detected."
else
    echo "-------------------------------------------------"
    echo " Found ${#CONFLICT_VARS[@]} conflict(s)."
    echo " Enter an alternative port number for each, or"
    echo " press Enter to keep the current value."
    echo "-------------------------------------------------"
    echo ""

    i=0
    while [[ $i -lt ${#CONFLICT_VARS[@]} ]]; do
        var="${CONFLICT_VARS[$i]}"
        current_val="${CONFLICT_VALS[$i]}"
        module_name="${CONFLICT_MODS[$i]}"
        service_name="${CONFLICT_SVCS[$i]}"

        while true; do
            read -rp "  ${var} (currently ${current_val}, module ${module_name}, service ${service_name}) → new port: " new_port
            if [[ -z "$new_port" ]]; then
                echo "    (keeping ${current_val})"
                break
            fi
            if [[ ! "$new_port" =~ ^[0-9]+$ ]]; then
                echo "    ERROR: '${new_port}' is not a valid port number."
                continue
            fi
            if [[ "$new_port" -lt 1 || "$new_port" -gt 65535 ]]; then
                echo "    ERROR: port must be between 1 and 65535."
                continue
            fi
            if port_is_in_use "$new_port"; then
                owner="$(port_owner "$new_port")"
                echo "    WARNING: port ${new_port} is also in use by ${owner}."
                read -rp "    Use it anyway? (y/N): " confirm
                if [[ "$confirm" =~ ^[Yy]$ ]]; then
                    target_file="$(resolve_env_file "$var" || echo "$PROJECT_ENV")"
                    set_env_value "$var" "$new_port" "$target_file"
                    echo "    Updated ${var}=${new_port} in ${target_file##*/}"
                    cvar="$(kv_get "$F_PROJECT_VAR" "$var" || true)"
                    if [[ -n "$cvar" ]]; then
                        module_env="$(kv_get "$F_COMPOSE_VAR_FILE" "$cvar" || true)"
                        if [[ -n "$module_env" && -f "$module_env" && "$module_env" != "$target_file" ]]; then
                            update_module_env_port "$cvar" "$new_port" "$module_env"
                        fi
                    fi
                    break
                fi
            else
                target_file="$(resolve_env_file "$var" || echo "$PROJECT_ENV")"
                set_env_value "$var" "$new_port" "$target_file"
                echo "    Updated ${var}=${new_port} in ${target_file##*/}"
                cvar="$(kv_get "$F_PROJECT_VAR" "$var" || true)"
                if [[ -n "$cvar" ]]; then
                    module_env="$(kv_get "$F_COMPOSE_VAR_FILE" "$cvar" || true)"
                    if [[ -n "$module_env" && -f "$module_env" && "$module_env" != "$target_file" ]]; then
                        update_module_env_port "$cvar" "$new_port" "$module_env"
                    fi
                fi
                break
            fi
        done
        i=$((i + 1))
    done
fi

echo ""

# ---------------------------------------------------------------------------
# 5. Recap: print all exposed ports
# ---------------------------------------------------------------------------
echo "========================================"
echo "  Exposed Ports Recap"
echo "========================================"
printf "  %-38s %-8s %-24s %-20s\n" "ENV_VAR" "PORT" "SERVICE" "MODULE"
printf "  %-38s %-8s %-24s %-20s\n" "--------------------------------------" "--------" "------------------------" "--------------------"

for var in "${PROJECT_VARS[@]}"; do
    current_value="$(resolve_env_value "$var" || true)"
    if [[ -z "$current_value" ]]; then
        current_value="$(kv_get "$F_DEFAULTS" "$var")"
    fi
    [[ -z "$current_value" ]] && continue
    service_name="$(kv_get "$F_SERVICES" "$var")"
    module_name="$(kv_get "$F_MODULES" "$var")"
    printf "  %-38s %-8s %-24s %-20s\n" "$var" "$current_value" "$service_name" "$module_name"
done

echo ""

# ---------------------------------------------------------------------------
# Optional: update EXTERNAL_BASE_HOST
# ---------------------------------------------------------------------------
current_external_host="$(resolve_env_value "EXTERNAL_BASE_HOST" || true)"
if [[ -z "$current_external_host" ]]; then
    current_external_host="$(get_env_value "EXTERNAL_BASE_HOST" "$PROJECT_ENV")"
fi
read -rp "EXTERNAL_BASE_HOST (currently ${current_external_host:-not set}) → new value: " new_host
if [[ -z "$new_host" ]]; then
    echo "  (keeping ${current_external_host:-not set})"
else
    host_target_file="$(resolve_env_file "EXTERNAL_BASE_HOST" || echo "$PROJECT_ENV")"
    set_env_value "EXTERNAL_BASE_HOST" "$new_host" "$host_target_file"
    echo "Updated EXTERNAL_BASE_HOST=${new_host} in ${host_target_file##*/}"
fi

echo ""

# ---------------------------------------------------------------------------
# Optional: update APP_NAME
# ---------------------------------------------------------------------------
current_app_name="$(resolve_env_value "APP_NAME" || true)"
if [[ -z "$current_app_name" ]]; then
    current_app_name="$(get_env_value "APP_NAME" "$PROJECT_ENV")"
fi
read -rp "APP_NAME (currently ${current_app_name:-not set}) → new value: " new_app_name
if [[ -z "$new_app_name" ]]; then
    echo "  (keeping ${current_app_name:-not set})"
else
    app_name_target_file="$(resolve_env_file "APP_NAME" || echo "$PROJECT_ENV")"
    set_env_value "APP_NAME" "$new_app_name" "$app_name_target_file"
    echo "Updated APP_NAME=${new_app_name} in ${app_name_target_file##*/}"
    for module_name in "${ENABLED_MODULES[@]}"; do
        module_env="${MODULES_DIR}/${module_name}/.env.config"
        ensure_env_reference "APP_NAME" "$module_env"
    done
fi

echo ""

# ---------------------------------------------------------------------------
# Optional: update APP_SLUG
# ---------------------------------------------------------------------------
current_app_slug="$(resolve_env_value "APP_SLUG" || true)"
if [[ -z "$current_app_slug" ]]; then
    current_app_slug="$(get_env_value "APP_SLUG" "$PROJECT_ENV")"
fi
echo "WARNING: changing APP_SLUG changes the Docker Compose project name."
echo "         Existing containers from the old project name will keep running unless stopped first."
read -rp "APP_SLUG (currently ${current_app_slug:-not set}) → new value: " new_app_slug
if [[ -z "$new_app_slug" ]]; then
    echo "  (keeping ${current_app_slug:-not set})"
else
    # Normalize: lowercase, no spaces/special chars
    normalized_slug="$(echo "$new_app_slug" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
    if [[ "$normalized_slug" != "$new_app_slug" ]]; then
        echo "  Normalized to: ${normalized_slug}"
        new_app_slug="$normalized_slug"
    fi
    app_slug_target_file="$(resolve_env_file "APP_SLUG" || echo "$PROJECT_ENV")"
    set_env_value "APP_SLUG" "$new_app_slug" "$app_slug_target_file"
    echo "Updated APP_SLUG=${new_app_slug} in ${app_slug_target_file##*/}"
    for module_name in "${ENABLED_MODULES[@]}"; do
        module_env="${MODULES_DIR}/${module_name}/.env.config"
        ensure_env_reference "APP_SLUG" "$module_env"
    done
fi

echo ""

# ---------------------------------------------------------------------------
# Optional: update PROJECT_ROOT
# ---------------------------------------------------------------------------
current_project_root="$(resolve_env_value "PROJECT_ROOT" || true)"
if [[ -z "$current_project_root" ]]; then
    current_project_root="$(get_env_value "PROJECT_ROOT" "$PROJECT_ENV")"
fi
# Propose the current directory (absolute) as the default, not the old env value.
default_project_root="$(pwd)"
read -rp "PROJECT_ROOT (currently ${default_project_root}) → new value: " new_project_root
if [[ -z "$new_project_root" ]]; then
    new_project_root="$default_project_root"
fi
if [[ "$new_project_root" != "$current_project_root" ]]; then
    root_target_file="$(resolve_env_file "PROJECT_ROOT" || echo "$PROJECT_ENV")"
    set_env_value "PROJECT_ROOT" "$new_project_root" "$root_target_file"
    echo "Updated PROJECT_ROOT=${new_project_root} in ${root_target_file##*/}"
else
    echo "  (keeping ${current_project_root})"
fi

echo ""
if [[ -n "${ENABLED_MD}" ]]; then
    echo "Run './redeploy.sh' to apply the changes."
else
    echo "Run './start.sh' to apply the changes."
fi
