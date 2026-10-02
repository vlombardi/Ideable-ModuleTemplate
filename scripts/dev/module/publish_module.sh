#!/usr/bin/env bash
# Publish a module release: its images, its lock, its changelog section, its git tag.
#
#     scripts/dev/module/publish_module.sh 1.2.0              # publish that release
#     scripts/dev/module/publish_module.sh 1.2.0 --dry-run    # show the plan, touch nothing
#
# THE MODULE MAINTAINER'S COUNTERPART OF `publish_framework.sh`, run inside the module project. A
# release is a git tag, the module's images in the registry, and `module.lock.json` naming their
# digests — the three published together, so a deployed site can take it BY DIGEST and never builds
# (`rules/version-control.md` § *A module release*; the site's half is `adopt_module.sh`).
#
# ONE VERSION, NAMED HERE, WRITTEN DOWN ONCE. The release is the argument, `X.Y.Z` — a module has no
# `latest`, so there is no channel to be ambiguous about — and this script writes it into
# `modules/<module>/module.json`'s `version` before anything reads it. That field stays the one place a
# module's version is stated.
#
# THE ORDER IS NOT ARBITRARY. The lock records the digests the registry actually resolved, so it can
# only be written after the images exist; the release commit carries the lock, so it follows it; the
# tags mark a publish that already succeeded.
#
#   1. images       → push_module_images_to_registry.py   (the release name alone, --no-latest)
#   2. module.json  → the version
#   3. the lock     → write_module_lock.py                 (asks the registry for the digests)
#   4. release commit, tag `worklog/<X.Y.Z>` on it, carrying kanban/, implementation-plans/ and
#      TEST_REPORTS/ in full
#   5. compaction   → compact_release_bookkeeping.py       (finished cards, merged plans, test reports)
#   6. tag `<X.Y.Z>` on the compacted commit, then push the branch and both tags
#
# A PARTIAL PUBLISH IS A FAILED PUBLISH. Every step is checked and the run stops at the first failure;
# `module.json` goes back to what it said, because the version it names was never published. A lock
# naming digests for images that were never pushed is worse than no lock.
#
# REFUSED BEFORE ANYTHING IS BUILT: a version that is not X.Y.Z, a dirty tree, a card in
# `kanban/doing/` (its plan has not landed), a `CHANGELOG.md` with no `## <X.Y.Z>` section (the
# `ideable-changelog` skill drafts it; this script only checks it exists), and a version that is
# already tagged.
set -uo pipefail

# The helpers this runs import each other; bytecode written beside them would make the tree dirty.
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "$REPO"

DRY_RUN=0
VERSION=""
MODULE=""
MODULE_JSON=""
PREVIOUS_VERSION=""
JSON_WRITTEN=0

say() { echo "[publish-module] $*"; }
step() { echo ""; echo "[publish-module] ── $* ─────────────────────────────────────────"; }

# A failed publish must not leave the module renamed.
restore_version() {
  [[ "$JSON_WRITTEN" == "1" ]] || return 0
  python3 - "$MODULE_JSON" "$PREVIOUS_VERSION" <<'PY'
import json, sys
path, version = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
data["version"] = version
open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2) + "\n")
PY
  say "module.json restored to ${PREVIOUS_VERSION} — ${VERSION} was not published"
  JSON_WRITTEN=0
}
die() { restore_version; echo "[publish-module] ERROR: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --module) MODULE="${2:-}"; [[ -n "$MODULE" ]] || die "--module needs a name"; shift 2 ;;
    --version|--tag) die "the release is named as a bare argument, not with a flag: publish_module.sh <X.Y.Z>" ;;
    -h|--help)
      cat <<'HELP'
Usage: scripts/dev/module/publish_module.sh <X.Y.Z> [--module <name>] [--dry-run]

Publishes a module release: pushes the module's images at <X.Y.Z>, writes module.lock.json from the
digests the registry resolved, commits it with the new module.json version, tags worklog/<X.Y.Z>,
compacts the finished bookkeeping, tags <X.Y.Z> and pushes.

<X.Y.Z>     REQUIRED. The release. A module has no `latest`. Written into module.json's `version`.
--module    The module's directory name under modules/ (default: the project's single local module
            other than host_app).
--dry-run   Print the plan and what a real publish would refuse; publish nothing.

Refused before anything is built: a dirty tree, a card in kanban/doing/, no `## <X.Y.Z>` section in
CHANGELOG.md, a version already tagged.
HELP
      exit 0 ;;
    -*) die "unknown argument '$1' (see --help)" ;;
    *)
      [[ -z "$VERSION" ]] || die "name one version, not two ('$VERSION' and '$1')"
      VERSION="$1"; shift ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  echo "[publish-module] name the release to publish:" >&2
  echo "    scripts/dev/module/publish_module.sh 1.2.0" >&2
  die "no version named"
fi
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "'$VERSION' is not X.Y.Z (a module has releases, no \`latest\`)"

WRITER="${SCRIPT_DIR}/write_module_lock.py"
COMPACT="${REPO}/scripts/dev/common/compact_release_bookkeeping.py"
PUSHER="${REPO}/scripts/dev/common/push_module_images_to_registry.py"
RESOLVER="${REPO}/scripts/runtime/module_version.py"

if [[ -z "$MODULE" ]]; then
  MODULE="$(python3 "$WRITER" --print-module --root "$REPO")" || die "could not tell which module this project releases (name it with --module)"
fi
MODULE_JSON="${REPO}/modules/${MODULE}/module.json"
[[ -f "$MODULE_JSON" ]] || die "modules/${MODULE}/module.json does not exist"
SLUG="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('slug',''))" "$MODULE_JSON")"
PREVIOUS_VERSION="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('version',''))" "$MODULE_JSON")"
[[ -n "$SLUG" ]] || die "modules/${MODULE}/module.json declares no slug"

say "module     : ${MODULE} (${SLUG})"
say "version    : ${VERSION}  (module.json says ${PREVIOUS_VERSION:-nothing})"
say "repository : ${REPO}"

# ── The refusals, before anything is built ─────────────────────────────────────────────────────
REFUSALS=()
if [[ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]]; then
  REFUSALS+=("a dirty working tree — the images would carry changes no commit describes, and the tag would name a tree that is not what was published. Commit or stash first")
fi
if git -C "$REPO" rev-parse -q --verify "refs/tags/${VERSION}" >/dev/null || git -C "$REPO" rev-parse -q --verify "refs/tags/worklog/${VERSION}" >/dev/null; then
  REFUSALS+=("${VERSION} is already tagged — a release is published once")
fi
if [[ ! -f "$REPO/CHANGELOG.md" ]] || ! grep -qE "^## +${VERSION//./\\.}([^0-9]|$)" "$REPO/CHANGELOG.md"; then
  REFUSALS+=("CHANGELOG.md has no '## ${VERSION}' section — draft it with the \`ideable-changelog\` skill and review it (rules/version-control.md § A release says what it contains)")
fi
if ! python3 "$COMPACT" --dry-run >/dev/null 2>&1; then
  REFUSALS+=("a plan is in flight: kanban/doing/ is not empty, so the release would archive a card describing unfinished work as if it were history")
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo ""
  say "--dry-run: would publish, in order:"
  say "  1. ${SLUG}'s images at :${VERSION} only (--no-latest)"
  say "  2. modules/${MODULE}/module.json -> version ${VERSION}"
  say "  3. module.lock.json for ${VERSION}, from the digests the registry resolves"
  say "  4. release commit, then tag worklog/${VERSION} (the full bookkeeping tree)"
  say "  5. compact the finished bookkeeping and commit it"
  say "  6. tag ${VERSION} on the compacted commit, push the branch and both tags"
  if ((${#REFUSALS[@]})); then
    echo ""
    for why in "${REFUSALS[@]}"; do say "A real publish would REFUSE: ${why}"; done
  else
    say "no refusal: a real publish would go ahead"
  fi
  exit 0
fi

if ((${#REFUSALS[@]})); then
  for why in "${REFUSALS[@]}"; do echo "[publish-module] refusing: ${why}" >&2; done
  die "refusing to publish ${VERSION} (see above); nothing was built or changed"
fi

# ── 1. images ──────────────────────────────────────────────────────────────────────────────────
step "1/6  images"
python3 "$PUSHER" "$MODULE" --tag "$VERSION" --no-latest \
  || die "the image publish failed — nothing further has been published"

# ── 2. the version, written down once ──────────────────────────────────────────────────────────
# AFTER the images, because the pusher refuses a dirty tree and this edit dirties it; BEFORE the lock
# and the commit, which read it.
step "2/6  module.json"
python3 - "$MODULE_JSON" "$VERSION" <<'PY' || die "could not write the version into module.json"
import json, sys
path, version = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
data["version"] = version
open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2) + "\n")
PY
JSON_WRITTEN=1
say "modules/${MODULE}/module.json now names ${VERSION} (was ${PREVIOUS_VERSION})"

# ── 3. the lock ────────────────────────────────────────────────────────────────────────────────
step "3/6  module.lock.json"
python3 "$WRITER" --root "$REPO" --module "$MODULE" --version "$VERSION" \
  || die "the images are published but the lock could not be written; re-run after fixing it"
python3 "$RESOLVER" check "$REPO" \
  || die "the freshly written lock does not satisfy the resolver; nothing is committed or tagged"

# ── 4. the release commit and the worklog tag ──────────────────────────────────────────────────
step "4/6  release commit and worklog/${VERSION}"
git -C "$REPO" add "modules/${MODULE}/module.json" module.lock.json \
  || die "the publish succeeded but the release files could not be staged"
git -C "$REPO" commit -q -m "chore(release): ${SLUG} ${VERSION}" \
  || die "the publish succeeded but the release commit failed"
JSON_WRITTEN=0   # committed: there is nothing left to restore
say "committed module.json + module.lock.json for ${VERSION}"
git -C "$REPO" tag -a "worklog/${VERSION}" -m "${SLUG} ${VERSION} — worklog" \
  || die "the publish succeeded but tagging the worklog failed"
say "tagged worklog/${VERSION} (the full bookkeeping tree)"

# ── 5. compaction ──────────────────────────────────────────────────────────────────────────────
step "5/6  compaction"
python3 "$COMPACT" \
  || die "the images are published and worklog/${VERSION} is tagged, but the compaction failed"
if [[ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]]; then
  git -C "$REPO" commit -q -m "chore(release): compact bookkeeping after ${SLUG} ${VERSION}" \
    || die "the compaction commit failed"
  say "committed the compaction — the tree is clean for the next cycle"
fi

# ── 6. the release tag and the push ────────────────────────────────────────────────────────────
step "6/6  tag ${VERSION} and push"
git -C "$REPO" tag -a "${VERSION}" -m "${SLUG} ${VERSION}" \
  || die "the publish succeeded but tagging ${VERSION} failed"
say "tagged ${VERSION} (the clean tree)"
# `--follow-tags`: the branch AND the annotated tags reachable from it, in one command — pushing the
# tag alone sends the commit's objects but leaves the branch where it was.
if git -C "$REPO" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
  git -C "$REPO" push --follow-tags \
    || die "published, committed and tagged, but the push failed. The release exists only here; run: git push --follow-tags"
  git -C "$REPO" push origin "refs/tags/worklog/${VERSION}" \
    || die "pushed ${VERSION}, but the worklog tag was not; run: git push origin refs/tags/worklog/${VERSION}"
  say "pushed the branch and the tags ${VERSION} and worklog/${VERSION}"
else
  BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
  say "'${BRANCH}' has no upstream, so nothing was pushed:"
  say "  git push -u origin ${BRANCH} --follow-tags && git push origin refs/tags/worklog/${VERSION}"
fi

echo ""
say "Published ${SLUG} ${VERSION} — images, lock and tag."
