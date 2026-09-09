#!/bin/bash
# Pull the host_app images this project consumes — by digest, from the framework lock.
#
# Usage:
#   ./scripts/pull-hostapp-images.sh [-h|--help] [--dry-run]     # at a deployed site
#
# THIS IS A DEPLOYED SCRIPT, and it runs from the deployment root — the copy the deploy placed in
# `<deployment root>/scripts/`, beside the resolver and above the lock it reads. In a project
# checkout run that copy (`deployment_root/scripts/pull-hostapp-images.sh`), not this source file:
# the source cannot reach a resolver, by design, because a script that a site runs must not name a
# path that exists only in a checkout.
#
# IT TAKES NO TAG, and that is the point. `framework.lock.json` records the digest the framework
# published for the release, and `framework_version.py` is its single reader. The deployed compose
# is generated from the same lock, so the puller and the deploy cannot name different images —
# which they once did, the puller fetching `latest` while compose asked for the consuming project's
# own commit. One image, two names, and a remote project could satisfy neither.
#
# THE SITE INHERITS THE RELEASE; IT DOES NOT CHOOSE IT. `framework.env` — the one line a module
# maintainer edits — stays in the checkout and is never deployed, because a deployment has no
# business re-deciding what was decided at coding time. So the release is read from the deployed
# lock's own `version`. This script used to search upward for `framework.env`: at a real site there
# is none, the search left the deployment root, and it reported the release of whatever checkout
# happened to sit above it — passing in the maintainer's tree, which is the one place the defect
# cannot occur, and failing everywhere that matters.
#
# PULLED BY DIGEST, TAGGED LOCALLY. `docker pull <registry>/<name>@sha256:…` fetches exactly the
# bytes the lock names — a moving tag cannot substitute a different build underneath it — and the
# image is then tagged `<registry>/<name>:<version>` so compose finds it locally and never reaches
# for the registry at start-up.
set -euo pipefail

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      echo "ERROR: unknown argument '$1'." >&2
      echo "       This script takes no tag: the release is the one the deployed" >&2
      echo "       framework.lock.json names. To move a project to another release, edit" >&2
      echo "       IDEABLE_FRAMEWORK_VERSION in framework.env in the project checkout, run" >&2
      echo "       sync-template-updates.sh, and redeploy — a site does not re-choose it." >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# THE SITE ROOT IS THE DIRECTORY HOLDING THE LOCK, AND THE SEARCH STOPS THERE.
#
# It anchors on `framework.lock.json` — the FACTS, and the file the deploy copies — rather than on
# `framework.env`, the CHOICE, which a site deliberately does not carry. That single change is what
# confines the search: the deployed copy finds the lock one level up, in the deployment root, and
# stops. The old search looked for a file that is never deployed, so it could only ever succeed by
# leaving the site and finding a checkout above it.
#
# One level up, and no further: the site root is `<script dir>/..` by construction, so a walk is not
# needed and a walk is precisely what went wrong.
DEPLOYMENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "$DEPLOYMENT_ROOT/framework.lock.json" ]]; then
  echo "ERROR: framework.lock.json not found at $DEPLOYMENT_ROOT." >&2
  echo "       It records the digests of the release this site runs, and the deploy copies it" >&2
  echo "       there. Two ways to be here:" >&2
  echo "         - you ran the source copy in a checkout (scripts/runtime/): run the" >&2
  echo "           deployed one instead — deployment_root/scripts/pull-hostapp-images.sh;" >&2
  echo "         - this site was deployed by a framework version that did not copy the lock:" >&2
  echo "           redeploy it from the project checkout." >&2
  exit 1
fi

# The resolver travels with the lock, the way compose_merge.py already travels with the merge
# script — beside this file, never in a checkout folder that does not exist at a site.
RESOLVER="$SCRIPT_DIR/framework_version.py"
if [[ ! -f "$RESOLVER" ]]; then
  echo "ERROR: framework_version.py not found beside $SCRIPT_DIR." >&2
  echo "       It is the one reader of framework.lock.json, and the deploy copies it next to this" >&2
  echo "       script. Redeploy this site from the project checkout." >&2
  exit 1
fi

# One line per image: "<ref><TAB><digest>".
if ! REFS="$(python3 - "$DEPLOYMENT_ROOT" "$SCRIPT_DIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import framework_version  # noqa: E402

try:
    # `deployed_*`: this tree may hold no choice to compare the lock with, and at a site it must
    # not — the release is whatever was deployed here.
    refs = framework_version.deployed_hostapp_image_refs(root)
except framework_version.FrameworkVersionError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)

for ref in sorted(refs.values(), key=lambda r: r.name):
    print(f"{ref.ref}\t{ref.digest}")
PY
)"; then
  echo "" >&2
  echo "ERROR: the host_app release could not be resolved (see above)." >&2
  exit 1
fi

if [[ -z "$REFS" ]]; then
  echo "ERROR: framework.lock.json names no host_app images." >&2
  exit 1
fi

PULLED=0
UP_TO_DATE=0
FAILED=0
TOTAL=0

echo "Pulling host_app images by digest, from framework.lock.json"
echo ""

while IFS=$'\t' read -r ref digest; do
  [[ -z "$ref" ]] && continue
  TOTAL=$((TOTAL + 1))
  repo="${ref%:*}"
  by_digest="${repo}@${digest}"

  # What is already here, if anything: the id the local tag points at, and the id of the digest.
  local_id="$(docker image inspect --format '{{.Id}}' "$ref" 2>/dev/null || true)"
  digest_id="$(docker image inspect --format '{{.Id}}' "$by_digest" 2>/dev/null || true)"

  if [[ -n "$local_id" && "$local_id" == "$digest_id" ]]; then
    echo "  [up-to-date] $ref"
    echo "               ${digest:0:19}…"
    UP_TO_DATE=$((UP_TO_DATE + 1))
    continue
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "  [would pull] $by_digest"
    echo "               and tag it $ref"
    PULLED=$((PULLED + 1))
    continue
  fi

  echo "  [pulling]    $by_digest"
  if ! docker pull "$by_digest" >/dev/null 2>&1; then
    echo "  [failed]     $ref — the registry does not hold ${digest:0:19}…"
    echo "               The lock names a digest this registry cannot serve: either the release was"
    echo "               never published, or the lock is not the one for this project's version."
    FAILED=$((FAILED + 1))
    continue
  fi
  # Tag it under the readable name the deployed compose uses, so compose resolves it locally.
  docker tag "$by_digest" "$ref"
  echo "  [pulled]     $ref"
  PULLED=$((PULLED + 1))
done <<< "$REFS"

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "  Up to date: $UP_TO_DATE"
echo "  Pulled:     $PULLED"
echo "  Failed:     $FAILED"
echo "  Total:      $TOTAL"

if [[ "$FAILED" -gt 0 ]]; then
  echo ""
  echo "ERROR: $FAILED image(s) could not be pulled. The stack cannot start without them." >&2
  exit 1
fi
