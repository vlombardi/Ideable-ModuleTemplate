#!/usr/bin/env bash
# Make the local dev tools image be exactly the one framework.lock.json names, and optionally
# recreate the container from it.
#
#     scripts/dev/common/pull_devtools_image.sh            # pull the locked digest, even if an image is present
#     scripts/dev/common/pull_devtools_image.sh --restart  # …and recreate the container from it
#
# WHY THIS EXISTS, and why it is not just `docker pull`.
#
# The image is pulled BY DIGEST — the one the lock records for this project's framework version —
# and then tagged with the name the project runs. `tool.sh` does the same on its own when the image
# is absent, or when the project tracks `latest` and the lock has moved on. What it will NOT do is
# replace an image on a PINNED version that differs from the lock: that is a hard failure, because a
# pinned version must run exactly the published toolbox and a difference means a re-pushed tag or a
# hand-built image. This script is the deliberate act that replaces it.
#
# Pulling is only half of it. A running container was created FROM the old image and keeps running
# it; a fresh image changes nothing until the container is recreated, which is what `--restart`
# does. Leaving that to the developer to remember is how "I pulled it and it still misbehaves"
# happens.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RESTART=0

die() { echo "[pull] $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=1; shift ;;
    -h|--help)
      sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

# shellcheck source=scripts/dev/common/devtools_version.sh
source "$REPO/scripts/dev/common/devtools_version.sh"
# The same derivation `tool.sh` uses, from the same files: this script refreshes the image THIS
# project references, so it must act on the container THIS project runs and no other.
NAME="$(devtools_container_name)"

command -v docker >/dev/null 2>&1 || die "docker is not installed."
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable. Start Docker and try again."

IMAGE="$(devtools_image_ref)" || die "could not resolve the dev tools image — see the message above."
DIGEST="$(devtools_locked_digest)" || die "could not read the dev tools digest from framework.lock.json."

BEFORE="$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)"

echo "[pull] $IMAGE"
echo "[pull] digest ${DIGEST} (framework.lock.json)"
devtools_pull_locked_image "$IMAGE" "$DIGEST" || die "could not pull ${IMAGE%:*}@${DIGEST}.
  - if the package is private or you are not logged in:  docker login ghcr.io
  - the digest is the one framework.lock.json records for the version in framework.env; if that
    version is wrong, edit the one line and run scripts/dev/module/sync-template-updates.sh"

AFTER="$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)"

if [[ -n "$BEFORE" && "$BEFORE" == "$AFTER" ]]; then
  echo "[pull] already up to date"
else
  [[ -n "$BEFORE" ]] && echo "[pull] updated: ${BEFORE:7:12} -> ${AFTER:7:12}" || echo "[pull] fetched ${AFTER:7:12}"
  if [[ "$RESTART" == 0 ]] && docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "[pull] NOTE: '$NAME' is running from the PREVIOUS image and will keep doing so." >&2
    echo "[pull]       Re-run with --restart, or: scripts/dev/common/tool.sh --stop" >&2
  fi
fi

if [[ "$RESTART" == 1 ]]; then
  docker rm -f "$NAME" >/dev/null 2>&1 && echo "[pull] removed $NAME (it will be recreated from the new image)"
fi
