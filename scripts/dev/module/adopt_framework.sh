#!/usr/bin/env bash
# Adopt a framework release in this project: name it, then bring its files in.
#
#     scripts/dev/module/adopt_framework.sh 1.6.3     # pin this project to that release
#     scripts/dev/module/adopt_framework.sh latest    # follow the channel instead
#
# THE MIRROR OF `publish_framework.sh`. The maintainer names a release once, to the publish; a
# project names the same release once, to this. Both write it into `IDEABLE_FRAMEWORK_VERSION` and
# then do the work, so on neither side is a version typed into a file by hand and remembered about
# separately.
#
# WHY THIS IS ONE COMMAND AND NOT TWO. Adopting used to be: edit `framework.env`, then run
# `sync-template-updates.sh`. Between those two moments the project states a version its lock does
# not describe — `tool.sh`, the deploy and every image reference refuse, and the resolver names the
# sync as the way out. The window is survivable (`template_ref` is deliberately ungated so the sync
# can still be told where to fetch from), but it is a window a person can stop halfway through, and
# what they are left with looks like a broken project rather than an unfinished adoption. Here the
# choice and the facts move together, or neither moves.
#
# ON FAILURE THE PROJECT IS PUT BACK. If the sync fails, `framework.env` is restored to the version
# that was actually adopted. A project naming a release whose files it does not have is exactly the
# half-state this command exists to remove.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE="$PROJECT_ROOT/framework.env"
RESOLVER="$PROJECT_ROOT/scripts/runtime/framework_version.py"
SYNC="$SCRIPT_DIR/sync-template-updates.sh"

VERSION=""
PREVIOUS=""
WRITTEN=0
SYNC_ARGS=()

say() { echo "[adopt-framework] $*"; }
restore() {
  [[ "$WRITTEN" == "1" ]] || return 0
  printf 'IDEABLE_FRAMEWORK_VERSION=%s\n' "$PREVIOUS" > "$ENV_FILE"
  say "framework.env restored to ${PREVIOUS} — ${VERSION} was not adopted"
  WRITTEN=0
}
die() { restore; echo "[adopt-framework] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: scripts/dev/module/adopt_framework.sh <version> [sync options]

Adopts a framework release in this project: writes <version> into
IDEABLE_FRAMEWORK_VERSION in framework.env, then runs sync-template-updates.sh,
which fetches the framework files at that release and force-syncs the lock.

<version>   `latest` to follow the channel, or X.Y.Z to pin a published release.
            The release must exist: a pinned version the framework never published
            is an error, never a fall-back to the newest.

Any further arguments are passed through to sync-template-updates.sh (`-a`,
`--selective`, `--file <path>`, `--list-changes`).

If the sync fails, framework.env is put back to the version it named before.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -*) SYNC_ARGS+=("$1"); shift ;;
    *)
      if [[ -z "$VERSION" ]]; then VERSION="$1"; else SYNC_ARGS+=("$1"); fi
      shift ;;
  esac
done

[[ -n "$VERSION" ]] || { usage >&2; echo "" >&2; die "name the release to adopt"; }
[[ "$VERSION" == "latest" || "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || die "'$VERSION' is neither \`latest\` nor X.Y.Z"

[[ -f "$ENV_FILE" ]] || die "no framework.env here — this runs in a project created from the template"
[[ -x "$SYNC" ]] || die "sync-template-updates.sh is missing; this project's framework files are incomplete"

PREVIOUS="$(python3 "$RESOLVER" version 2>/dev/null || true)"
[[ -n "$PREVIOUS" ]] || die "could not read IDEABLE_FRAMEWORK_VERSION from framework.env"

say "adopting ${VERSION} (this project names ${PREVIOUS})"
if [[ "$VERSION" != "$PREVIOUS" ]]; then
  printf 'IDEABLE_FRAMEWORK_VERSION=%s\n' "$VERSION" > "$ENV_FILE"
  WRITTEN=1
fi

# The sync reads the version through the resolver, so it now fetches at the release just named.
"$SYNC" "${SYNC_ARGS[@]+"${SYNC_ARGS[@]}"}" \
  || die "the sync failed, so ${VERSION}'s files were not brought in"

# The lock the sync brought must be the one published for this version; if it is not, the project
# would look adopted while resolving nothing.
python3 "$RESOLVER" check \
  || die "the sync completed but framework.env and framework.lock.json still disagree"

WRITTEN=0
say "adopted ${VERSION}. Commit framework.env and framework.lock.json with the synced files."
