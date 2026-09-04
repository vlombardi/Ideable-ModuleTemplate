#!/usr/bin/env bash
# Force a refresh of the dev tools image this project references.
#
#     scripts/dev/pull_devtools_image.sh            # pull the resolved tag, even if present
#     scripts/dev/pull_devtools_image.sh --restart  # …and recreate the container from it
#
# WHY THIS EXISTS, and why it is not just `docker pull`.
#
# `tool.sh` obtains the image once: present locally means use it. For a pinned `vX.Y.Z` that is
# exactly right — the tag is immutable, so the local copy can never be wrong. For `latest` it is a
# trap: the tag moves in the registry while the local copy does not, so a developer tracking
# `latest` keeps a stale toolbox indefinitely and nothing says so. `latest` is the setting the
# framework maintainer is most likely to be on.
#
# Pulling is only half of it. A running container was created FROM the old image and keeps running
# it; a fresh image changes nothing until the container is recreated, which is what `--restart`
# does. Leaving that to the developer to remember is how "I pulled it and it still misbehaves"
# happens.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESTART=0

die() { echo "[pull] $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=1; shift ;;
    -h|--help)
      sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

# shellcheck source=scripts/dev/devtools_version.sh
source "$REPO/scripts/dev/devtools_version.sh"
# The same derivation `tool.sh` uses, from the same file: this script refreshes the image THIS
# project references, so it must act on the container THIS project runs and no other.
NAME="$(devtools_container_name)"

command -v docker >/dev/null 2>&1 || die "docker is not installed."
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable. Start Docker and try again."

IMAGE="$(devtools_image_ref)" \
  || die "could not determine the dev tools image repository from the 'origin' remote.
Set IDEABLE_DEVTOOLS_IMAGE_REPO, or IDEABLE_DEVTOOLS_IMAGE for a full reference."

BEFORE="$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)"

echo "[pull] $IMAGE"
docker pull "$IMAGE" || die "could not pull $IMAGE.
  - if the package is private or you are not logged in:  docker login ghcr.io
  - if the tag does not exist, check IDEABLE_FRAMEWORK_VERSION / IDEABLE_DEVTOOLS_VERSION
    in framework.env"

AFTER="$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)"

if [[ -n "$BEFORE" && "$BEFORE" == "$AFTER" ]]; then
  echo "[pull] already up to date"
else
  [[ -n "$BEFORE" ]] && echo "[pull] updated: ${BEFORE:7:12} -> ${AFTER:7:12}" || echo "[pull] fetched ${AFTER:7:12}"
  if [[ "$RESTART" == 0 ]] && docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "[pull] NOTE: '$NAME' is running from the PREVIOUS image and will keep doing so." >&2
    echo "[pull]       Re-run with --restart, or: scripts/dev/tool.sh --stop" >&2
  fi
fi

if [[ "$RESTART" == 1 ]]; then
  docker rm -f "$NAME" >/dev/null 2>&1 && echo "[pull] removed $NAME (it will be recreated from the new image)"
fi
