#!/usr/bin/env bash
# adopt_module.sh — take a published module release at a deployed site.
#
# The counterpart of publish_module.sh (a module maintainer's release) and of adopt_framework.sh, for a
# MODULE instead of the framework. Run from the deployment root:
#
#   ./scripts/runtime/adopt_module.sh <slug> <X.Y.Z> -g <git remote of the module>
#   ./scripts/runtime/adopt_module.sh <slug> <X.Y.Z> --dry-run
#
# A release is a git tag, the module's images in the registry, and the lock naming their digests. This
# fetches the lock from the tag, verifies it, installs it as modules/<slug>/module.lock.json, pulls every
# image BY DIGEST (the bytes the lock names, not whatever a tag points at today), tags each
# `<registry>/<name>:<X.Y.Z>` and points the module's deployed docker-compose.yml at those names.
#
# THE SITE IS UNTOUCHED UNLESS THE WHOLE RELEASE IS AVAILABLE: the lock must exist at the tag, read
# cleanly and be published for this version and slug, and every image must pull, before the lock or the
# compose file is written. Nothing is restarted: it says what to run next.
set -uo pipefail

export PYTHONDONTWRITEBYTECODE=1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVER="${HERE}/module_version.py"
ROOT="$(pwd)"

say() { echo "[adopt-module] $*"; }
die() { echo "[adopt-module] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: adopt_module.sh <slug> <X.Y.Z> [-g <git remote>] [--dry-run]

<slug>      The deployed module (modules/<slug>/ must exist at the deployment root).
<X.Y.Z>     The release to take. A module has no `latest`.
-g, --git-remote   The module's git remote (else PUBLISHING_GIT_REMOTE). It is never guessed.
--dry-run   Verify the release and say what would be pulled; change nothing.
USAGE
}

SLUG="" VERSION="" REMOTE="${PUBLISHING_GIT_REMOTE:-}" DRY=0 POS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--git-remote) [[ $# -ge 2 ]] || die "$1 needs a value"; REMOTE="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; die "unknown option: $1" ;;
    *) POS=$((POS + 1)); if [[ $POS -eq 1 ]]; then SLUG="$1"; elif [[ $POS -eq 2 ]]; then VERSION="$1"; else die "unexpected argument: $1"; fi; shift ;;
  esac
done

[[ -n "$SLUG" && -n "$VERSION" ]] || { usage >&2; die "a slug and a release are required"; }
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'${VERSION}' is not a release: a module is released as X.Y.Z (it has no 'latest')"
[[ -n "$REMOTE" ]] || die "no git remote: pass -g <remote> or set PUBLISHING_GIT_REMOTE"
[[ -f "$RESOLVER" ]] || die "module_version.py is missing beside this script"
MODULE_DIR="${ROOT}/modules/${SLUG}"
[[ -d "$MODULE_DIR" ]] || die "modules/${SLUG}/ is not deployed here — run from the deployment root, and deploy the module first"
command -v git >/dev/null || die "git is required"

say "module  : ${SLUG}"
say "release : ${VERSION}"
say "remote  : ${REMOTE}"

# ── 1. the lock, from the tag ──────────────────────────────────────────────────────────────────
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git clone --quiet --depth 1 --branch "$VERSION" "$REMOTE" "${WORK}/repo" 2>"${WORK}/clone.err" \
  || die "could not fetch tag ${VERSION} from ${REMOTE} ($(tr '\n' ' ' <"${WORK}/clone.err")) — nothing changed"
[[ -f "${WORK}/repo/module.lock.json" ]] || die "tag ${VERSION} carries no module.lock.json — it is not a published release; nothing changed"
mkdir "${WORK}/lock" && cp "${WORK}/repo/module.lock.json" "${WORK}/lock/"

python3 "$RESOLVER" check "${WORK}/lock" || die "the lock at ${VERSION} is not valid; nothing changed"
python3 - "${WORK}/lock/module.lock.json" "$VERSION" "$SLUG" <<'PY' || die "the lock is for another release; nothing changed"
import json, sys
lock = json.load(open(sys.argv[1]))
if lock["version"] != sys.argv[2]:
    sys.exit(f"the lock names version {lock['version']}, not {sys.argv[2]}")
if lock["module"]["slug"] != sys.argv[3]:
    sys.exit(f"the lock is for module '{lock['module']['slug']}', not '{sys.argv[3]}'")
PY

REFS="$(python3 "$RESOLVER" refs "${WORK}/lock")" || die "could not read the images from the lock; nothing changed"
say "images  :"
while read -r name pull local; do say "  ${name}  ${pull}"; done <<<"$REFS"

if [[ $DRY -eq 1 ]]; then
  say "dry run — nothing pulled, nothing written"
  exit 0
fi

# ── 2. every image, by digest, before anything is written ──────────────────────────────────────
command -v docker >/dev/null || die "docker is required to pull the images"
while read -r name pull local; do
  docker pull "$pull" >/dev/null || die "could not pull ${pull} — the site is untouched"
  docker tag "$pull" "$local" || die "could not tag ${local} — the site is untouched"
done <<<"$REFS"

# ── 3. the lock and the compose file ───────────────────────────────────────────────────────────
cp "${WORK}/lock/module.lock.json" "${MODULE_DIR}/module.lock.json"
COMPOSE="${MODULE_DIR}/docker-compose.yml"
if [[ -f "$COMPOSE" ]]; then
  python3 "$RESOLVER" bake "$MODULE_DIR" "$COMPOSE" || die "the images are pulled but ${COMPOSE} could not be updated"
else
  say "no docker-compose.yml in modules/${SLUG}/ — images are pulled and tagged, nothing to bake"
fi

say "module ${SLUG} ${VERSION} adopted. Nothing was restarted; to run it:"
say "  ./scripts/runtime/start.sh   (or ./scripts/runtime/rolling-deploy.sh)"
