#!/bin/bash
#
# List all host-exposed ports from deployment_root/docker-compose.yml.
# Useful for configuring production firewall rules and detecting port conflicts
# with other containers running on the same host.
#
# Usage:
#   ./scripts/runtime/list-exposed-ports.sh [--compose <path>]
#
# Options:
#   --compose <path>   Path to docker-compose.yml (default: deployment_root/docker-compose.yml)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/deployment_root/docker-compose.yml"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --compose)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--compose <path>]"
            exit 1
            ;;
    esac
done

if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: compose file not found: $COMPOSE_FILE"
    echo "Run build_and_deploy.py first to generate deployment_root/docker-compose.yml"
    exit 1
fi

echo "=============================================="
echo " Exposed ports from: $COMPOSE_FILE"
echo "=============================================="
echo ""

# Parse the compose file with awk:
# Collect service name, then inside a ports: block extract published port,
# target port, and protocol. Works with both long-form (mode/target/published)
# and short-form (- "host:container") entries.
awk '
BEGIN {
    service = ""
    in_services = 0
    in_ports = 0
    target = ""
    published = ""
    proto = "tcp"
    found_any = 0
}

/^services:/ { in_services = 1; next }

in_services && /^  [A-Za-z0-9_-]+:$/ {
    in_ports = 0; target = ""; published = ""; proto = "tcp"
    svc = $0; gsub(/^  /, "", svc); gsub(/:$/, "", svc)
    service = svc
    next
}

in_services && /^    ports:/ { in_ports = 1; next }

function flush_entry(    ) {
    if (target != "" && published != "") {
        printf "  %-35s  %-6s ->  %s/%s\n", service, published, target, proto
        found_any = 1
    }
    target = ""; published = ""; proto = "tcp"
}

in_services && in_ports && /^    [A-Za-z0-9_-]+:/ {
    flush_entry(); in_ports = 0; next
}

# Long-form list entry starts with "      - mode:" (6 spaces + dash)
in_ports && /^      - mode:/ { flush_entry(); next }

# Long-form fields (6+ spaces, no dash)
in_ports && /^        target:/ {
    val = $0; gsub(/.*target: *"?/, "", val); gsub(/".*/, "", val); gsub(/ .*/, "", val)
    target = val; next
}
in_ports && /^        published:/ {
    val = $0; gsub(/.*published: *"?/, "", val); gsub(/".*/, "", val); gsub(/ .*/, "", val)
    published = val; next
}
in_ports && /^        protocol:/ {
    val = $0; gsub(/.*protocol: */, "", val); gsub(/ .*/, "", val)
    proto = val; next
}

# Short-form: "      - HOST:CONTAINER" or "      - HOST:CONTAINER/proto"
in_ports && /^      - / {
    flush_entry()
    line = $0; gsub(/^      - *"?/, "", line); gsub(/".*/, "", line); gsub(/ .*/, "", line)
    n = split(line, parts, ":")
    if (n == 2) {
        h = parts[1]; rest = parts[2]
        p = "tcp"; if (split(rest, rp, "/") == 2) { rest = rp[1]; p = rp[2] }
        if (h ~ /^[0-9]+$/) { printf "  %-35s  %-6s ->  %s/%s\n", service, h, rest, p; found_any = 1 }
    } else if (n == 3) {
        h = parts[2]; rest = parts[3]
        p = "tcp"; if (split(rest, rp, "/") == 2) { rest = rp[1]; p = rp[2] }
        if (h ~ /^[0-9]+$/) { printf "  %-35s  %-6s ->  %s/%s\n", service, h, rest, p; found_any = 1 }
    }
}

END {
    flush_entry()
    if (!found_any) print "  (no host-exposed ports found)"
    print ""
    print "Legend:  SERVICE                              HOST   ->  CONTAINER/PROTO"
}
' "$COMPOSE_FILE"

echo "To check which of these ports are currently in use on this host, run:"
echo "  sudo lsof -iTCP -sTCP:LISTEN -n -P | grep -E ':(80|443|[0-9]{4,5}) '"
