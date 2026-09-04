#!/usr/bin/env bash
# Run the CI-selected tests against a PRISTINE CHECKOUT — exactly the condition CI has.
#
# The selector in stack_free_tests.py is a heuristic over imports and conftest chains, and a
# heuristic is wrong until something checks it. Twice it was: tests that read `deployment_root/`
# and a generated `modules_menu_mapping.json` import nothing live, so they looked stack-free and
# failed in CI; and a directory whose CONFTEST opens a database errored at fixture setup while every
# test file in it looked clean.
#
# A git worktree at HEAD gives a checkout with no build artefacts — no deployment_root, no generated
# config — in about a second. Discovering this class locally beats discovering it in CI.
#
#     scripts/common/verify_stack_free.sh
set -uo pipefail

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

# --- This runs inside the dev tools container ---------------------------------------------------
#
# It runs pytest, so it runs on the standard toolchain like every other test path. Routing it also
# closes a gap that would otherwise be perverse: this script exists to prove the CI-selected tests
# pass on a pristine checkout, and proving it with a different pytest than CI uses proves less.
if [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" != "1" && "${IDEABLE_NO_CONTAINER:-0}" != "1" ]]; then
  if [[ ! -x "$REPO/scripts/dev/tool.sh" ]]; then
    echo "[verify] scripts/dev/tool.sh is missing — it is how this project obtains its toolchain." >&2
    exit 1
  fi
  exec "$REPO/scripts/dev/tool.sh" bash "$REPO/scripts/common/verify_stack_free.sh" "$@"
fi

# The worktree goes INSIDE the repo, not in $TMPDIR.
#
# Only the repository is mounted into the dev tools container, so a worktree under /tmp (or macOS's
# per-user /var/folders/... TMPDIR) simply does not exist in there — the pytest run would find
# nothing and the check would pass vacuously. `.ideable-work/` is git-ignored, and `git worktree`
# is content with a path inside the repo as long as it is not tracked.
WORK="$REPO/.ideable-work/pristine-$$"
mkdir -p "$REPO/.ideable-work"

cleanup() { git worktree remove --force "$WORK" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "[verify] creating a pristine worktree at HEAD (no build artefacts)"
git worktree add -q --detach "$WORK" HEAD || { echo "[verify] could not create a worktree" >&2; exit 1; }
[ -d "$WORK/deployment_root" ] && { echo "[verify] deployment_root exists in the worktree — not pristine" >&2; exit 1; }

PY="${PY:-}"
# Inside the dev tools container there is no `.venv` — python3 IS the standard interpreter,
# and preferring a host venv path there resolved to nothing and reported every suite as
# "unrecognised pytest output". Prefer the venv only when it actually exists.
[ -n "$PY" ] || { [ -x "$REPO/.venv/bin/python" ] && PY="$REPO/.venv/bin/python" || PY="$(command -v python3)"; }
[ -x "$PY" ] || PY="$(command -v python3)"

"$REPO/scripts/common/stack_free_tests.py" --by-suite > "$WORK/.suites" || exit 1
[ -s "$WORK/.suites" ] || { echo "[verify] the selector produced nothing — it is broken, not the repo" >&2; exit 1; }

rc=0
while IFS= read -r group; do
  [ -z "$group" ] && continue
  label="$(echo "$group" | awk '{print $1}' | xargs dirname)"
  out=$( cd "$WORK" && IDEABLE_UNRECORDED_RUN=1 "$PY" -m pytest -q $group -p no:cacheprovider </dev/null 2>&1 | tail -1 )
  case "$out" in
    *failed*|*error*|*"no tests ran"*)
      rc=1; printf '[verify] FAIL %-44s %s\n' "$label" "$out" ;;
    *) printf '[verify] ok   %-44s %s\n' "$label" "$out" ;;
  esac
done < "$WORK/.suites"

if [ "$rc" -ne 0 ]; then
  echo "[verify] Some selected tests need more than a checkout. Either they belong in the local-only"
  echo "[verify] half — teach scripts/common/stack_free_tests.py what they depend on — or they read a"
  echo "[verify] build artefact they should not."
else
  echo "[verify] OK — every selected test passes on a pristine checkout, which is CI's condition."
fi
exit $rc
