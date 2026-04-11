#!/usr/bin/env bash

# check_port_availability.sh
#
# Reads base_services/.env, finds all variables ending with _PORT,
# and for each unique port value checks:
#   - If it is used by any host process (via lsof)
#   - If it is mapped by any Docker container (via docker port)
#
# Usage:
#   ./scripts/check_port_availability.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../base_services" && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] base_services/.env not found at: $ENV_FILE" >&2
  exit 1
fi

# Load environment variables from base_services/.env
# shellcheck source=/dev/null
source "$ENV_FILE"

if ! command -v lsof >/dev/null 2>&1; then
  echo "[WARNING] 'lsof' not found. Host process checks will be skipped." >&2
  HAS_LSOF=false
else
  HAS_LSOF=true
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[WARNING] 'docker' not found. Docker container checks will be skipped." >&2
  HAS_DOCKER=false
else
  HAS_DOCKER=true
fi

# Collect all variable names ending with _PORT from the env file (Bash 3 compatible)
PORT_VARS=()
while IFS='=' read -r var_name _; do
  # Skip empty names just in case
  [[ -z "$var_name" ]] && continue
  PORT_VARS+=("$var_name")
done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*_PORT=' "$ENV_FILE" | sort -u)

if [[ ${#PORT_VARS[@]} -eq 0 ]]; then
  echo "No *_PORT variables found in $ENV_FILE"
  exit 0
fi

echo "🔍 Checking port availability based on $ENV_FILE"
echo
# Fixed-width table header
printf '%-6s %-30s %s\n' "PORT" "SERVICE (env vars)" "USED BY"
printf '%-6s %-30s %s\n' "------" "------------------------------" "----------------------------"

for var in "${PORT_VARS[@]}"; do
  # Indirect expansion to get the value of the env var we just sourced
  port="${!var-}"
  if [[ -z "$port" ]]; then
    continue
  fi
  # Only consider numeric ports
  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    continue
  fi

  # Determine who is using this port
  USED_BY_PARTS=()

  # Host processes using this port (format: full-command(pid))
  # Show only ONE representative process, preferring a 'node ' command if present
  host_procs=""
  if [[ "$HAS_LSOF" == true ]]; then
    # Collect unique PIDs listening on this port
    pids=$( (lsof -i ":$port" -P -n 2>/dev/null || true) | awk 'NR>1 {print $2}' | sort -u )
    for pid in $pids; do
      # Use ps to get the full command line; fallback to just pid if ps fails
      cmd=$(ps -p "$pid" -o command= 2>/dev/null | sed 's/^ *//')
      [[ -z "$cmd" ]] && cmd="pid:$pid"
      entry="${cmd}(${pid})"
      # Prefer a node-based process if present; otherwise keep the first one
      if [[ "$cmd" == node* ]]; then
        host_procs="$entry"
        break
      fi
      if [[ -z "$host_procs" ]]; then
        host_procs="$entry"
      fi
    done
  fi

  # Docker containers mapping this port (by container name)
  docker_names=""
  if [[ "$HAS_DOCKER" == true ]]; then
    while IFS=' ' read -r cid cname; do
      mappings="$(docker port "$cid" 2>/dev/null || true)"
      [[ -z "$mappings" ]] && continue
      if echo "$mappings" | grep -q ":$port\b"; then
        if [[ -z "$docker_names" ]]; then
          docker_names="$cname"
        else
          docker_names="$docker_names, $cname"
        fi
      fi
    done < <(docker ps --format '{{.ID}} {{.Names}}')
  fi

  if [[ -n "$docker_names" ]]; then
    # If a container is using the port, that's enough information
    USED_BY_PARTS+=("docker:$docker_names")
  elif [[ -n "$host_procs" ]]; then
    USED_BY_PARTS+=("proc:$host_procs")
  fi

  if [[ ${#USED_BY_PARTS[@]} -eq 0 ]]; then
    used_by="None"
  else
    # Join USED_BY_PARTS with '; '
    used_by="${USED_BY_PARTS[0]}"
    idx=1
    while [[ $idx -lt ${#USED_BY_PARTS[@]} ]]; do
      used_by="$used_by; ${USED_BY_PARTS[$idx]}"
      idx=$((idx+1))
    done
  fi

  # Fixed-width row: PORT(6), SERVICE(30), USED BY(rest)
  printf '%-6s %-30s %s\n' "$port" "$var" "$used_by"

done

echo
echo "✅ Port check completed."
