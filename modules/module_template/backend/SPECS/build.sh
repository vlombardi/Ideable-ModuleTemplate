#!/bin/bash
# SPECS/build.sh — module_template backend image build.
#
# build_and_deploy.py auto-detects and runs this INSTEAD of the generic docker build. The reason it
# has to exist is one line below: `--build-context ideable_api=...`.
#
# The backend consumes the shared framework package `ideable_api` (repo-root `reusable.api/`),
# which is a sibling OUTSIDE this SOURCES-rooted build context. In a clone it is reached through the
# tracked relative symlink `SOURCES/.ideable-api`, and Docker does not follow a symlink out of its
# context — so without the named build context below the developer machine works and the image
# cannot import the framework. The Dockerfile COPYs it from that context and puts it on PYTHONPATH.
#
# This mirrors exactly what the frontend does with `reusable.ui` and the `ideable_ui` context.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # .../backend
SOURCES="$BACKEND_DIR/SOURCES"
MODULE_DIR="$(cd "$BACKEND_DIR/.." && pwd)"                        # .../module_template
REPO_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"                       # repo root
REUSABLE_API="$REPO_ROOT/reusable.api"

[[ -d "$REUSABLE_API" ]] || { echo "ERROR: shared backend package not found at $REUSABLE_API" >&2; exit 1; }

SLUG=$(grep -o '"slug"[[:space:]]*:[[:space:]]*"[^"]*"' "$MODULE_DIR/module.json" | head -1 | sed 's/.*:[[:space:]]*"\([^"]*\)".*/\1/')
[[ -n "$SLUG" ]] || { echo "ERROR: could not read slug from $MODULE_DIR/module.json" >&2; exit 1; }
# The tag and the identity labels come from build_and_deploy.py (export_build_identity_env): every
# local build is `latest`, and what it was built from is stamped on the image. No defaults — an
# image without its revision label fails the deploy's identity check.
IMG="${SLUG}.backend:${LOCAL_IMAGE_TAG:?LOCAL_IMAGE_TAG must be exported by build_and_deploy.py}"
LABEL_ARGS=(
  --label "org.opencontainers.image.revision=${IDEABLE_IMAGE_REVISION:?exported by build_and_deploy.py}"
  --label "org.opencontainers.image.created=${IDEABLE_IMAGE_CREATED:?exported by build_and_deploy.py}"
  --label "tech.ideable.dirty=${IDEABLE_IMAGE_DIRTY:?exported by build_and_deploy.py}"
)

echo "  [backend] Building $IMG with the ideable_api build context"
DOCKER_BUILDKIT=1 docker build -t "$IMG" "${LABEL_ARGS[@]}" \
  --build-context "ideable_api=$REUSABLE_API" \
  "$SOURCES"
