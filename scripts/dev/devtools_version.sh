#!/usr/bin/env bash
# Resolve WHICH dev tools image this project runs. Sourced, never executed.
#
#     source scripts/dev/devtools_version.sh
#     devtools_image_ref            # ghcr.io/<owner>/ideable-devtools:<tag>
#
# ONE definition, three callers: `tool.sh` (runs the image), `pull_devtools_image.sh` (refreshes
# it) and `master_only/push_devtools_image_to_registry.sh` (publishes it). Each of them needs the
# same repository and the same tag rules, and three copies of that arithmetic is how the repository
# name in one of them quietly stops matching the others.
#
# PRECEDENCE, highest first:
#   1. the shell environment  — a one-off, no file edited
#   2. framework.env          — the project's tracked version, force-synced by the framework
#   3. the defaults below     — `latest`
set -uo pipefail

_DEVTOOLS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Read framework.env WITHOUT sourcing it: it is a data file, and sourcing would execute whatever a
# bad merge left in it. Only the two keys we own are taken, and only when the shell has not already
# set them.
_devtools_read_framework_env() {
  local file="${_DEVTOOLS_REPO_ROOT}/framework.env" line key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"; value="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    value="$(printf '%s' "$value" | sed -E 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"(.*)"$/\1/')"
    case "$key" in
      IDEABLE_FRAMEWORK_VERSION) [[ -n "${IDEABLE_FRAMEWORK_VERSION:-}" ]] || IDEABLE_FRAMEWORK_VERSION="$value" ;;
      IDEABLE_DEVTOOLS_VERSION)  [[ -n "${IDEABLE_DEVTOOLS_VERSION:-}"  ]] || IDEABLE_DEVTOOLS_VERSION="$value" ;;
      IDEABLE_DEVTOOLS_DIGEST)   [[ -n "${IDEABLE_DEVTOOLS_DIGEST:-}"   ]] || IDEABLE_DEVTOOLS_DIGEST="$value" ;;
    esac
  done < "$file"
}

# The image repository, derived from the `origin` remote so a fork publishes to and pulls from its
# own namespace rather than silently reaching for someone else's.
devtools_image_repo() {
  if [[ -n "${IDEABLE_DEVTOOLS_IMAGE_REPO:-}" ]]; then
    printf '%s' "$IDEABLE_DEVTOOLS_IMAGE_REPO"; return 0
  fi
  local url owner
  url="$(git -C "$_DEVTOOLS_REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  owner="$(printf '%s' "$url" | sed -E 's#^(https://github\.com/|git@github\.com:)([^/]+)/.*#\2#')"
  if [[ -z "$owner" || "$owner" == "$url" ]]; then
    return 1
  fi
  printf 'ghcr.io/%s/ideable-devtools' "$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')"
}

# The tag to run: the dev tools version when set, otherwise the framework version.
devtools_resolve_tag() {
  _devtools_read_framework_env
  local framework="${IDEABLE_FRAMEWORK_VERSION:-latest}"
  local devtools="${IDEABLE_DEVTOOLS_VERSION:-}"

  if [[ -z "$devtools" ]]; then
    printf '%s' "$framework"; return 0
  fi
  if [[ "$devtools" != "$framework" ]]; then
    # Said out loud every time, because the whole promise of the container is that everyone runs
    # the toolbox their framework version was tested against. Discouraged, not forbidden: bisecting
    # a toolchain problem is a real need.
    echo "[tool] NOTE: dev tools version '$devtools' does not match framework version '$framework'." >&2
    echo "[tool]       This is supported but discouraged — you are running a toolbox this framework" >&2
    echo "[tool]       version was never tested against. Clear IDEABLE_DEVTOOLS_VERSION to realign." >&2
  fi
  printf '%s' "$devtools"
}

# The manifest digest the framework published for this version, or empty when unknown.
#
# It lives in framework.env because that file is force-synced and host_app's dependencies.md is not:
# a remote project has no `modules/host_app/SPECS/` at all, so a digest recorded only there would be
# unreadable exactly where the check matters most. Both are written by the publish script, so
# neither is hand-maintained.
devtools_expected_digest() {
  _devtools_read_framework_env
  printf '%s' "${IDEABLE_DEVTOOLS_DIGEST:-}"
}

# Compare the local image against the published digest. Advisory: it warns, never fails.
#
# Skipped for `latest`, where a difference is expected rather than suspicious — the tag moves and
# the local copy does not. For a pinned version a difference means one of two things, and both are
# worth saying out loud: a tag was re-pushed, or the image was built by hand instead of pulled.
devtools_warn_on_digest_mismatch() {
  local image="$1" expected actual
  expected="$(devtools_expected_digest)"
  [[ -n "$expected" ]] || return 0
  [[ "$(devtools_resolve_tag)" != "latest" ]] || return 0

  actual="$(docker image inspect "$image" --format '{{join .RepoDigests " "}}' 2>/dev/null \
            | tr ' ' '\n' | sed -n 's/.*@//p' | head -1)"
  # No RepoDigests means the image was never pulled from a registry — a local build. Say so.
  if [[ -z "$actual" ]]; then
    echo "[tool] NOTE: $image carries no registry digest, so it was built locally rather than" >&2
    echo "[tool]       pulled. It may differ from the published image for this version." >&2
    return 0
  fi
  if [[ "$actual" != "$expected" ]]; then
    echo "[tool] NOTE: $image does not match the digest the framework published for this version." >&2
    echo "[tool]         expected $expected" >&2
    echo "[tool]         actual   $actual" >&2
    echo "[tool]       Refresh it with: scripts/dev/pull_devtools_image.sh --restart" >&2
  fi
  return 0
}

# The full reference the other scripts use.
devtools_image_ref() {
  # A complete override wins outright: it is how you run an image that is not in the registry at
  # all (a local build, a mirror), and second-guessing it would defeat the purpose.
  if [[ -n "${IDEABLE_DEVTOOLS_IMAGE:-}" ]]; then
    printf '%s' "$IDEABLE_DEVTOOLS_IMAGE"; return 0
  fi
  local repo tag
  repo="$(devtools_image_repo)" || return 1
  tag="$(devtools_resolve_tag)"
  printf '%s:%s' "$repo" "$tag"
}

# What this project calls itself: `APP_SLUG` from `project.env.config`, or empty when there is none.
#
# ONE READ, TWO CONSUMERS, and they need it for the same reason. The container name is built from it
# (below), and so is the name of the project's compose stack: `deployment_root/start.sh` runs
# `docker compose --project-name "${APP_SLUG:-…}"`, so `APP_SLUG` is the value carried by every one
# of that stack's containers as `com.docker.compose.project`. `tool.sh` matches on that label to
# join the right stack, so the two must derive it identically or the toolbox joins a stack that is
# not this project's.
#
# Returned RAW — trimmed of quotes and spaces, nothing else. The container name folds it into
# something Docker accepts; the label filter needs the value compose actually used. Folding here
# would make the filter match nothing for any slug that needed folding, which is a silent miss.
# Empty is a real answer and callers handle it: the container name falls back to the directory,
# and the stack filter joins nothing rather than guessing.
devtools_project_slug() {
  grep -h '^APP_SLUG=' "$_DEVTOOLS_REPO_ROOT/project.env.config" 2>/dev/null \
    | head -1 | cut -d= -f2- | tr -d "\"' " || true
}

# The container this project runs its toolchain in — one per project, named for the project.
#
# WHY PER PROJECT, and not one container shared by all of them. Everything that makes the container
# usable is derived from the repository it was created for: the identity mount `-v $REPO:$REPO`, the
# working directory, the per-repo `node_modules` caches, the `--add-host` read from that project's
# `project.env.config` — and, through `devtools_image_ref` above, WHICH IMAGE it runs. A single
# shared name made the first project to start the container own it, and every other project then hit
# one of two failures, measured with two projects open on 2026-09-02:
#
#   1. `OCI runtime exec failed: … chdir to cwd "<repo>" … no such file or directory` — the loud one,
#      naming neither the container nor the reason.
#   2. Silently running the FIRST project's image. The reference above is resolved per project, so a
#      project pinned to `v0.1.0` got whatever the other project's container had been started from.
#      That is the parity-by-construction promise inverted: the toolbox differed and nothing said so.
#
# Naming the container for the project makes the binding visible in `docker ps` and lets two projects
# work at the same time. `tool.sh` still verifies the mount before reusing one, because a name is a
# convention and the mount is the fact.
#
# The slug is `APP_SLUG` from `project.env.config` — the name the project already calls itself —
# falling back to the repository directory name when that file is absent or the key unset.
devtools_container_name() {
  # An explicit name wins outright: it is how you run a second container for one project, and how
  # two checkouts that share an APP_SLUG tell themselves apart.
  if [[ -n "${IDEABLE_DEVTOOLS_CONTAINER:-}" ]]; then
    printf '%s' "$IDEABLE_DEVTOOLS_CONTAINER"; return 0
  fi
  local slug
  slug="$(devtools_project_slug)"
  [[ -n "$slug" ]] || slug="$(basename "$_DEVTOOLS_REPO_ROOT")"
  # Docker accepts [a-zA-Z0-9][a-zA-Z0-9_.-]* — a slug carrying anything else would make the name
  # unusable, so it is folded rather than rejected.
  slug="$(printf '%s' "$slug" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_.-]+/-/g')"
  [[ -n "$slug" ]] || slug="project"
  printf 'ideable.devtools.%s' "$slug"
}
