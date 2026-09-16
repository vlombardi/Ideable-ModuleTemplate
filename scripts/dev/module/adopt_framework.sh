#!/usr/bin/env bash
# Adopt a framework release in this project: install its identity, then bring its files in.
#
#     scripts/dev/module/adopt_framework.sh 1.6.3     # pin this project to that release
#     scripts/dev/module/adopt_framework.sh latest    # follow the channel
#
# THE MIRROR OF `publish_framework.sh`. The maintainer names a release once, to the publish; a
# project names the same release once, to this. The publish WRITES the two files that name a
# release — `framework.env` and `framework.lock.json` — and this INSTALLS the same two, from the
# release itself. Neither side asks anyone to edit a version into a file and remember to act on it.
#
# THE LOCK IS INSTALLED HERE, NOT DISCOVERED DURING THE SYNC. `framework.lock.json` is not ordinary
# content that can arrive with the rest of the files: it is the file every other resolution reads.
# Delivering it as one more force-synced file means it turns up DURING the step that already needed
# it, and a project whose lock is missing or corrupt then cannot sync — while the resolver's own
# error tells the reader to run the sync. That deadlock was real: a project predating the lock hit
# it, and so would any project whose lock was truncated by an interrupted sync or filled with
# conflict markers by a merge.
#
# So the order is: read the release's lock straight out of the template at its tag, write it and
# `framework.env`, and only then sync. The sync force-syncs the same lock from the same ref, so the
# two agree by construction rather than by luck.
#
# NOTHING IS TOUCHED UNTIL THE RELEASE IS PROVEN TO EXIST. The fetch comes first, so naming a
# version the framework never published fails against an untouched project.
#
# ON FAILURE THE PROJECT IS PUT BACK. If the sync fails, both files are restored to what they were.
# A project naming a release whose files it does not have is exactly the half-state this removes.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck source=scripts/dev/module/template_remote.sh
source "${SCRIPT_DIR}/template_remote.sh"

ENV_FILE="$PROJECT_ROOT/framework.env"
LOCK_FILE="$PROJECT_ROOT/framework.lock.json"
RESOLVER="$PROJECT_ROOT/scripts/runtime/framework_version.py"
SYNC="$SCRIPT_DIR/sync-template-updates.sh"

VERSION=""
BACKUP=""
RESTORE_ON_EXIT=0
SYNC_ARGS=()

say() { echo "[adopt-framework] $*"; }

restore() {
  [[ "$RESTORE_ON_EXIT" == "1" ]] || return 0
  [[ -f "$BACKUP/framework.env" ]] && cp "$BACKUP/framework.env" "$ENV_FILE"
  if [[ -f "$BACKUP/framework.lock.json" ]]; then
    cp "$BACKUP/framework.lock.json" "$LOCK_FILE"
  else
    rm -f "$LOCK_FILE"   # there was none before; leaving ours would be a change nobody asked for
  fi
  say "framework.env and framework.lock.json restored — ${VERSION} was not adopted"
  RESTORE_ON_EXIT=0
}
die() { restore; echo "[adopt-framework] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: scripts/dev/module/adopt_framework.sh <version> [sync options]

Adopts a framework release in this project: reads that release's framework.lock.json
out of the template repository, writes it and IDEABLE_FRAMEWORK_VERSION into
framework.env, then runs sync-template-updates.sh to bring the release's files in.

<version>   REQUIRED. `latest` to follow the channel, or X.Y.Z to pin a published
            release. The release must exist: a pinned version the framework never
            published is an error, never a fall-back to the newest.

            There is no default, so no run of this can un-pin a project by accident.
            `latest` may be adopted repeatedly: the maintainer republishes the
            channel whenever something changes, and adopting it again brings the new
            digests. Re-syncing the version already named, without deciding anything,
            is sync-template-updates.sh.

Any further arguments are passed through to sync-template-updates.sh (`-a`,
`--selective`, `--file <path>`, `--list-changes`).

Nothing is written until the release is proven to exist, and if the sync fails both
files are restored to what they were.
EOF
}

# THE WHOLE BODY IS ONE FUNCTION, AND THAT IS NOT A STYLE CHOICE.
#
# This script runs the sync, and the sync overwrites THIS FILE — `adopt_framework.sh` is one of the
# framework-owned files a release delivers. bash reads a script incrementally, by byte offset, so a
# replaced file means it resumes at the same offset in different content: measured on a real
# adoption, it landed mid-heredoc of the new version and reported `se: command not found`,
# `EOF: command not found` and a syntax error on a stray `}` — after the sync had already succeeded.
#
# Defining everything up front makes bash parse the entire body BEFORE any of it runs, so the file
# on disk can change underneath a run that no longer needs to read it. The final line calls and
# exits in one command, read in one go, so nothing is read from the file after the sync has touched
# it.
main() {
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

  [[ -x "$SYNC" ]] || die "sync-template-updates.sh is missing; this project's framework files are incomplete"
  git -C "$PROJECT_ROOT" rev-parse --git-dir >/dev/null 2>&1 \
    || die "this is not a git checkout, so the template cannot be fetched"

  # WHICH REF, COMPUTED FROM THE VERSION ALONE. Deliberately not asked of the resolver: the resolver
  # reads the lock, and the whole point of this step is to work when the lock is missing or wrong.
  # `latest` is the channel's branch; a release is its tag, which is the version with nothing added.
  REF="main"
  [[ "$VERSION" != "latest" ]] && REF="refs/tags/${VERSION}"

  say "adopting ${VERSION} from ${IDEABLE_TEMPLATE_URL} (${REF})"

  # First, and before anything local changes: prove the release exists and read its lock.
  if ! git -C "$PROJECT_ROOT" fetch --depth 1 "$IDEABLE_TEMPLATE_URL" "$REF" >/dev/null 2>&1; then
    if [[ "$VERSION" == "latest" ]]; then
      die "could not fetch 'main' from ${IDEABLE_TEMPLATE_URL}"
    fi
    die "the framework never published ${VERSION}: ${IDEABLE_TEMPLATE_URL} has no ${REF}.
         Nothing has been changed. Name a published version, or \`latest\` for the channel."
  fi

  RELEASE_LOCK="$(git -C "$PROJECT_ROOT" show FETCH_HEAD:framework.lock.json 2>/dev/null)"
  [[ -n "$RELEASE_LOCK" ]] \
    || die "${REF} of the template carries no framework.lock.json, so it does not describe a release.
         Nothing has been changed."

  # The lock a release carries must be the lock published FOR it; anything else means the template was
  # pushed without its lock, and adopting it would pin this project to digests for another version.
  LOCK_VERSION="$(printf '%s' "$RELEASE_LOCK" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null)"
  [[ "$LOCK_VERSION" == "$VERSION" ]] \
    || die "${REF} carries a lock published for '${LOCK_VERSION:-<unreadable>}', not ${VERSION}.
         Nothing has been changed. Tell the framework maintainer: the template was pushed out of step
         with the publish."

  # Everything below can change the project, so from here a failure restores it.
  BACKUP="$(mktemp -d)"
  trap 'rm -rf "$BACKUP"' EXIT
  [[ -f "$ENV_FILE" ]] && cp "$ENV_FILE" "$BACKUP/framework.env"
  [[ -f "$LOCK_FILE" ]] && cp "$LOCK_FILE" "$BACKUP/framework.lock.json"
  RESTORE_ON_EXIT=1

  printf 'IDEABLE_FRAMEWORK_VERSION=%s\n' "$VERSION" > "$ENV_FILE"
  printf '%s\n' "$RELEASE_LOCK" > "$LOCK_FILE"
  say "installed framework.env and framework.lock.json for ${VERSION}"

  # The sync now resolves, and force-syncs the same lock from the same ref: identical bytes.
  "$SYNC" "${SYNC_ARGS[@]+"${SYNC_ARGS[@]}"}" \
    || die "the sync failed, so ${VERSION}'s files were not brought in"

  python3 "$RESOLVER" check \
    || die "the sync completed but framework.env and framework.lock.json still disagree"

  RESTORE_ON_EXIT=0
  say "adopted ${VERSION}. Commit framework.env, framework.lock.json and the synced files."
}

main "$@"; exit $?
