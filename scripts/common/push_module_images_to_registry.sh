#!/bin/bash
# Push module Docker images to a registry.
# Usage: ./scripts/common/push_module_images_to_registry.sh [-h|--help] [args...]
#
# Delegates to push_module_images_to_registry.py — all args are forwarded.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: $0 [-h|--help] [args...]"
  echo ""
  echo "Pushes module Docker images to a registry."
  echo "Delegates to push_module_images_to_registry.py — all args are forwarded."
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec python3 "${PROJECT_ROOT}/scripts/common/push_module_images_to_registry.py" "$@"
