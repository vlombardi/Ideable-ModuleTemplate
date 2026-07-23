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
  echo "  -h, --help          Show this help message"
  echo "  -a, --all           Process every enabled module declared as 'local'"
  echo "  -l, --list          List available modules from modules/enabled.md"
  echo "  -t, --tag TAG       Optional tag to append to every pushed image"
  echo "  --no-no-cache       Allow Docker cache during build (default: no-cache on)"
  echo "  --single-arch       Push existing local image instead of multi-arch build"
  echo "  --platform LIST     Comma-separated platforms (default: linux/amd64,linux/arm64)"
  echo "  --registry PREFIX   Fallback registry prefix (e.g. ghcr.io/OWNER)"
  echo ""
  echo "Run with --help (Python) for full argument details."
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec python3 "${PROJECT_ROOT}/scripts/common/push_module_images_to_registry.py" "$@"
