#!/bin/bash
# SPECS/build.sh — module_template frontend image build.
#
# build_and_deploy.py auto-detects and runs this INSTEAD of the generic docker
# build. The frontend consumes the shared @ideable/ui package (repo-root
# `reusable.ui/`), which is a sibling outside this SOURCES-rooted build context.
# It is provided to the Dockerfile as the `ideable_ui` named BuildKit build context
# (the Dockerfile COPYs it to ./.ideable-ui and installs it). The registry-push
# path (push_module_images_to_registry.py) passes the same `--build-context`, so
# both build paths stage @ideable/ui identically.
#
# WIDGET_EXAMPLES (env, default "true"): "false" excludes the dev-only Widget
# Examples gallery + its heavy deps (Recharts) from the image.
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # .../frontend
SOURCES="$FRONTEND_DIR/SOURCES"
MODULE_DIR="$(cd "$FRONTEND_DIR/.." && pwd)"                       # .../module_template
REPO_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"                       # repo root
REUSABLE_UI="$REPO_ROOT/reusable.ui"

[[ -d "$REUSABLE_UI" ]] || { echo "ERROR: shared UI package not found at $REUSABLE_UI" >&2; exit 1; }

SLUG=$(grep -o '"slug"[[:space:]]*:[[:space:]]*"[^"]*"' "$MODULE_DIR/module.json" | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)".*/\1/')
[[ -n "$SLUG" ]] || { echo "ERROR: could not read slug from $MODULE_DIR/module.json" >&2; exit 1; }
# The tag and the identity labels come from build_and_deploy.py (export_build_identity_env): every
# local build is `latest`, and what it was built from is stamped on the image. No defaults — an
# image without its revision label fails the deploy's identity check.
IMG="${SLUG}.frontend:${LOCAL_IMAGE_TAG:?LOCAL_IMAGE_TAG must be exported by build_and_deploy.py}"
LABEL_ARGS=(
  --label "org.opencontainers.image.revision=${IDEABLE_IMAGE_REVISION:?exported by build_and_deploy.py}"
  --label "org.opencontainers.image.created=${IDEABLE_IMAGE_CREATED:?exported by build_and_deploy.py}"
  --label "tech.ideable.dirty=${IDEABLE_IMAGE_DIRTY:?exported by build_and_deploy.py}"
)
WIDGET_EXAMPLES="${WIDGET_EXAMPLES:-true}"

# VITE_* build args (loaded from .env.config by build_and_deploy.py) + the gallery gate.
BUILD_ARGS=()
while IFS='=' read -r k v; do
  [[ "$k" == VITE_* && -n "$v" ]] && BUILD_ARGS+=(--build-arg "$k=$v")
done < <(env)
BUILD_ARGS+=(--build-arg "WIDGET_EXAMPLES=$WIDGET_EXAMPLES")

echo "  [frontend] Building $IMG (WIDGET_EXAMPLES=$WIDGET_EXAMPLES) with @ideable/ui build context"
DOCKER_BUILDKIT=1 docker build --no-cache -t "$IMG" "${LABEL_ARGS[@]}" \
  --build-context "ideable_ui=$REUSABLE_UI" \
  "${BUILD_ARGS[@]}" \
  "$SOURCES"
