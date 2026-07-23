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
# Detect context: deployed (script in scripts/) vs source repo (script in scripts/runtime/config/)
if [[ -f "$SCRIPT_DIR/../docker-compose.yml" ]]; then
  COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.yml"
else
  PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
  COMPOSE_FILE="${PROJECT_ROOT}/deployment_root/docker-compose.yml"
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --compose)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--compose <path>]"
            echo ""
            echo "Options:"
            echo "  --compose <path>  Path to docker-compose.yml (default: deployment_root/docker-compose.yml)"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--compose <path>]"
            echo "  Run '$0 --help' for details."
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
# HOST can be a number, ${VAR}, or ${VAR:-default} — all contain colons that
# break naive split on ":".  Extract container port as text after the last colon.
in_ports && /^      - / {
    flush_entry()
    line = $0; gsub(/^      - *"?/, "", line); gsub(/".*/, "", line); gsub(/ .*/, "", line)
    # Strip protocol suffix if present (e.g. ":80/tcp" → ":80")
    proto = "tcp"
    if (match(line, /\/[a-z]+$/)) {
        proto = substr(line, RSTART + 1, RLENGTH - 1)
        line = substr(line, 1, RSTART - 1)
    }
    # Find the last colon — everything after it is the container port
    colon_pos = 0
    for (i = length(line); i > 0; i--) {
        if (substr(line, i, 1) == ":") {
            colon_pos = i
            break
        }
    }
    if (colon_pos > 0) {
        h = substr(line, 1, colon_pos - 1)
        rest = substr(line, colon_pos + 1)
        # Resolve ${VAR:-default} to the default value for display
        if (match(h, /\$\{[A-Za-z0-9_]+:-[0-9]+\}/)) {
            gsub(/\$\{[A-Za-z0-9_]+:-/, "", h)
            gsub(/\}/, "", h)
        } else if (match(h, /\$\{[A-Za-z0-9_]+\}/)) {
            gsub(/[\$\{\}]/, "", h)
            h = "{" h "}"
        }
        printf "  %-35s  %-6s ->  %s/%s\n", service, h, rest, proto
        found_any = 1
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
