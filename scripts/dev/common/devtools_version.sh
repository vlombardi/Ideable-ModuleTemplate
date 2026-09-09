#!/usr/bin/env bash
# The dev tools shell library: which image this project runs, which container, which project.
# Sourced, never executed.
#
#     source scripts/dev/common/devtools_version.sh
#     devtools_version                 # latest | X.Y.Z            — framework.env, through the resolver
#     devtools_image_ref               # ghcr.io/<owner>/ideable-devtools:<version>
#     devtools_locked_digest           # sha256:…                  — framework.lock.json
#     devtools_ensure_locked_image <image> <digest> <version>
#     devtools_pull_locked_image   <image> <digest>
#     devtools_container_name          # ideable.devtools.<APP_SLUG>
#     devtools_project_slug            # APP_SLUG, raw
#
# WHICH IMAGE is not decided here. `scripts/runtime/framework_version.py` is the ONE reader of
# `framework.env` (the version a person chose) and `framework.lock.json` (the digest the publish
# recorded for it); this library asks it and adds the docker arithmetic around the answer. There is
# no precedence chain, no shell override and no registry owner derived from a git remote: one file
# names the version, one generated lock names the bytes, and a second parser in shell is how two
# readers stop agreeing.
#
# ONE definition, two callers: `tool.sh` runs the image and `pull_devtools_image.sh` refreshes it.
# Both must pull the same bytes and act on the same container, so the arithmetic lives once.
set -uo pipefail

_DEVTOOLS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
_DEVTOOLS_RESOLVER="$_DEVTOOLS_REPO_ROOT/scripts/runtime/framework_version.py"

# The resolver prints its own diagnosis on stderr; callers only need to know it failed.
_devtools_resolve() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "[tool] python3 is required to read framework.env and framework.lock.json" >&2
    echo "[tool] (scripts/runtime/framework_version.py is the one reader of both)." >&2
    return 1
  fi
  python3 "$_DEVTOOLS_RESOLVER" "$@"
}

devtools_version()       { _devtools_resolve version; }
devtools_image_ref()     { _devtools_resolve devtools-image-ref; }
devtools_locked_digest() { _devtools_resolve devtools-digest; }

# The registry digest the local image was pulled under, for the image's own repository — empty when
# it was never pulled (a hand-built image has no RepoDigests).
devtools_local_digest() {  # <image:tag>
  local image="$1" repo="${1%:*}"
  docker image inspect "$image" --format '{{join .RepoDigests "\n"}}' 2>/dev/null \
    | sed -n "s#^${repo}@##p" | head -1
}

# Pull BY DIGEST and tag the result with the name the project runs. The tag is a local convenience;
# the digest is the fact, and pulling by it means a moving `latest` in the registry can never
# replace the toolbox the lock names.
devtools_pull_locked_image() {  # <image:tag> <digest>
  local image="$1" digest="$2" repo="${1%:*}" id
  docker pull "${repo}@${digest}" || return 1
  id="$(docker image inspect "${repo}@${digest}" --format '{{.Id}}')" || return 1
  docker tag "$id" "$image"
}

# Make the local image be the one the lock names. Absent: pull it. Present and matching: nothing.
# Present and different: on a PINNED version that is a hard failure — a pinned version must run
# exactly the published toolbox, so a difference means a re-pushed tag or a hand-built image and
# has to be looked at; on `latest` it is expected — the channel moved and the last sync pinned the
# new digest — so the image is pulled and retagged in place.
devtools_ensure_locked_image() {  # <image:tag> <digest> <version>
  local image="$1" digest="$2" version="$3" actual
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "[tool] $image is not present locally."
    echo "[tool] pulling ${image%:*}@${digest} (first run downloads ~2.7 GB, including the browsers; once only)"
    devtools_pull_locked_image "$image" "$digest" || return 1
    echo "[tool] pulled $image"
    return 0
  fi
  actual="$(devtools_local_digest "$image")"
  [[ "$actual" == "$digest" ]] && return 0
  if [[ "$version" != "latest" ]]; then
    echo "[tool] $image does not match the digest framework.lock.json records for framework $version." >&2
    echo "[tool]   locked  $digest" >&2
    echo "[tool]   local   ${actual:-<none: built locally, never pulled>}" >&2
    echo "[tool]   A pinned version runs exactly the published toolbox. Either a tag was re-pushed or the" >&2
    echo "[tool]   image was built by hand. Replace it with the published one:" >&2
    echo "[tool]     scripts/dev/common/pull_devtools_image.sh --restart" >&2
    return 1
  fi
  echo "[tool] $image is not the toolbox the lock names for latest; pulling $digest and retagging"
  devtools_pull_locked_image "$image" "$digest" || return 1
  echo "[tool] updated $image"
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
#      project pinned to one version got whatever the other project's container had been started
#      from. That is the parity-by-construction promise inverted: the toolbox differed and nothing
#      said so.
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
