#!/usr/bin/env bash
# Run a dev-cycle tool inside the dev tools container instead of on this machine.
#
#     scripts/dev/tool.sh ruff check modules scripts
#     scripts/dev/tool.sh mypy modules/host_app/backend/SOURCES/app
#     scripts/dev/tool.sh pytest -q scripts/TESTS
#     scripts/dev/tool.sh --doctor          # assert the image is complete
#     scripts/dev/tool.sh --shell           # interactive
#     scripts/dev/tool.sh --stop            # remove the container
#
# WHY THIS EXISTS. Four defects in two days came from this machine drifting from what the tooling
# assumed, each behind a reassuring signal: `pydantic` absent so mypy checked nothing;
# `sqlalchemy-continuum` absent so six tests skipped at import for weeks; `PyYAML` absent in CI; and
# `.venv/bin/pip` carrying a shebang pointing at another project's interpreter. One digest-pinned
# image replaces parity-by-convention with parity-by-construction.
#
# WHICH IMAGE. Resolved from `framework.env` by `devtools_version.sh` — the dev tools version, or
# the framework version when that is empty (the supported way to say they coincide). The shell wins
# over the file, and `IDEABLE_DEVTOOLS_IMAGE` overrides the whole reference.
#
# HOW IT IS OBTAINED. Pulled from the registry, not built. Only the main repository builds a dev
# tools image; a project that could build its own would have a second toolbox, free to differ from
# the published one, which is the opposite of what this container is for.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVTOOLS_SOURCE="$REPO/modules/host_app/devtools/SOURCES"

die() { echo "[tool] $*" >&2; exit 1; }

# --- Environment carried into the container ----------------------------------------------------
# A command that runs inside must see the variables that decide what it DOES, or the container
# silently changes the run. The test runner is the sharp case: `conftest.py` and every
# `playwright.config.ts` refuse to run without `IDEABLE_TEST_RUNNER=1`, so a runner routed through
# here without it would fail at the guard — and the stack-E2E variables decide whether the
# authenticated specs run at all or skip, which is a green suite that tested less.
#
# Every `IDEABLE_*` variable is forwarded automatically; the rest are named because they have no
# common prefix. Forwarding the whole environment instead would carry the developer's shell into a
# container that is supposed to be identical for everyone.
FORWARDED_ENV=(
  RUN_STACK_E2E E2E_TEST_PASSWORD
  HOSTAPP_FRONTEND_URL TEMPLATE_FRONTEND_URL
  MODULE_SLUG MODULE_NAME
  TEST_AUTH_TOKEN
  CI GITHUB_ACTIONS
  # The verifiers' knobs. `KEEP_REMOTE_SHAPE_DIR` decides where a staged project is built AND
  # whether it survives; unforwarded, the script inside saw it unset, so it staged somewhere else
  # and then deleted the tree the caller had asked to keep.
  KEEP_REMOTE_SHAPE_DIR KEEP_WORKDIR REMOTE_SHAPE_MODULE PY
)

forwarded_env_args() {
  local out=() name
  while IFS='=' read -r name _; do
    [[ "$name" == IDEABLE_* ]] && out+=(-e "$name")
  done < <(env)
  for name in "${FORWARDED_ENV[@]}"; do
    [[ -n "${!name:-}" ]] && out+=(-e "$name")
  done
  # `${out[@]}` on an empty array is an unbound-variable error under `set -u`, and this function is
  # legitimately empty when nothing needs forwarding.
  [[ ${#out[@]} -gt 0 ]] && printf '%s\n' "${out[@]}"
  return 0
}

# shellcheck source=scripts/dev/devtools_version.sh
source "$REPO/scripts/dev/devtools_version.sh"
IMAGE="$(devtools_image_ref)" || die "could not determine the dev tools image repository from the
'origin' remote. Set IDEABLE_DEVTOOLS_IMAGE_REPO, or IDEABLE_DEVTOOLS_IMAGE for a full reference."
# One container per project, named for it — see `devtools_container_name` for why the image and the
# container have to be resolved from the same repository.
NAME="$(devtools_container_name)"

# Everything the dev cycle invokes. The doctor asserts each one, because an image missing a tool
# weakens the checks exactly as a missing host package did -- measured: running the suite in plain
# `python:3.13-slim` SILENTLY SKIPPED two tests for want of `git`.
REQUIRED_TOOLS=(python3 pip ruff mypy pytest node npm npx git gh jq docker alembic rsync)
# `alembic` is here as a LIBRARY as well as a binary: `schema-workflow.md` mandates
# `scripts/dev/schema.sh` for all four of its phases, and that script drives alembic. It was absent
# from both lists for as long as they have existed — the doctor certified a toolbox that could not
# run the schema workflow it is required for.
REQUIRED_PYLIBS=(pydantic sqlalchemy sqlalchemy_continuum yaml psycopg2 requests dotenv alembic)

# --- Recursion guard --------------------------------------------------------------------------
# The image sets IDEABLE_IN_TOOL_CONTAINER=1. Without this check a script that runs inside the
# container and calls tool.sh would try to exec into a container from within it -- which either
# recurses or fails with something that looks unrelated to the cause.
if [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" == "1" ]]; then
  [[ $# -gt 0 ]] || die "already inside the tool container, and no command given"
  exec "$@"
fi

command -v docker >/dev/null 2>&1 || die "docker is not installed. It is the ONE prerequisite this container removes the others for."
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable. Start Docker and try again."

# --- Image -----------------------------------------------------------------------------------
# Pull, do not build. The local build is the MAINTAINER path only, reached when the pull fails and
# the devtools source is present — which it is only in the main repository. A remote module project
# has no `modules/host_app/devtools/`, deliberately (verify_remote_shape.sh asserts its absence), so
# a remote either pulls the published image or stops with an actionable message.
#
# NOTE ON `latest`: an image already present is used as-is. That is correct for a pinned version and
# a trap for `latest`, which moves in the registry while the local copy does not. Refreshing it is
# what `scripts/dev/pull_devtools_image.sh` is for.
ensure_image() {
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    devtools_warn_on_digest_mismatch "$IMAGE"
    return 0
  fi

  echo "[tool] $IMAGE is not present locally."
  echo "[tool] pulling it (first run downloads ~2.7 GB, including the browsers; once only)"
  if docker pull "$IMAGE"; then
    echo "[tool] pulled $IMAGE"
    return 0
  fi

  if [[ -f "$DEVTOOLS_SOURCE/Dockerfile" ]]; then
    echo "[tool] pull failed; building from $DEVTOOLS_SOURCE (maintainer path)" >&2
    # `repo_root` gives the Dockerfile the repo-root requirements-dev.txt — the one CI installs.
    # Without it the build fails outright, which is the intended failure: the alternative was a
    # second copy inside the context, and it silently drifted.
    docker build --build-context "repo_root=$REPO" -t "$IMAGE" "$DEVTOOLS_SOURCE" \
      || die "could not build $IMAGE"
    return 0
  fi

  die "could not obtain $IMAGE.
The dev tools image is pulled from the registry; this project does not build one.
  - if the package is private or you are not logged in:  docker login ghcr.io
  - if the tag does not exist, check IDEABLE_FRAMEWORK_VERSION / IDEABLE_DEVTOOLS_VERSION
    in framework.env (currently resolving to '$IMAGE')"
}

# --- Container -------------------------------------------------------------------------------
# Mounted at the repo's OWN ABSOLUTE PATH, and that is load-bearing rather than tidy. The container
# drives the HOST daemon through the socket, so any `-v` it passes to `docker run` is resolved by the
# host -- 15 files here call `docker compose`, 8 call `docker exec`, 5 call `docker build`. If the
# repo lived at a different path inside, every one of those bind mounts would point at somewhere that
# does not exist on the host, and the errors would look like anything but a path problem.
#
# Which is also why the mount is what identifies a container as this project's. The name says it
# should be — it carries the project slug — but the two can disagree: an explicit
# `IDEABLE_DEVTOOLS_CONTAINER` naming another project's container, or two checkouts sharing an
# `APP_SLUG`. The name is the convention; this is the fact.
container_mounts_repo() {
  docker inspect "$NAME" --format '{{range .Mounts}}{{println .Destination}}{{end}}' 2>/dev/null \
    | grep -qxF "$REPO"
}

# Which checkout the running container was created for — its working directory IS that path, set
# from `-w "$REPO"` below. Used only to say so in the message when it is not this one.
container_workdir() {
  docker inspect "$NAME" --format '{{.Config.WorkingDir}}' 2>/dev/null
}

ensure_container() {
  if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    # Reuse only what belongs to this checkout. Reusing a foreign container failed later, inside
    # `docker exec`, as `OCI runtime exec failed: … chdir to cwd "<repo>" … no such file or
    # directory` — a message that names neither the container nor the cause.
    if container_mounts_repo; then return 0; fi

    # It carries this project's name but another checkout's mount — the primary checkout and a
    # worktree, which share `APP_SLUG` and therefore share this name. Recreate it here rather than
    # refusing: only one checkout of a project may be active at a time (the deployment is a
    # host-level singleton — see `rules/version-control.md`), so the other one is idle by
    # definition and its toolbox is not in use. Refusing instead would mean a manual `docker rm`
    # on every switch between checkouts, which is a step people automate away or resent.
    #
    # Safe only because the name is per project: a DIFFERENT project can no longer reach this
    # branch at all, so nothing here can take a container out from under another project's run.
    echo "[tool] $NAME was created for $(container_workdir), not this checkout — recreating it."
  fi
  # A stopped container with the same name still owns the name.
  docker rm -f "$NAME" >/dev/null 2>&1 || true

  # --- Run as the HOST user, not root --------------------------------------------------------
  #
  # Root inside the container makes the suite ask different questions than it does on the host, and
  # the divergence is silent. Measured 2026-08-31 on a file whose mode is `-rw-r--r--` in both
  # places: `os.access(f, os.X_OK)` is False as the host user and **True** as root, because
  # privilege wins. One framework test uses "is it executable?" as its proxy for "does this file
  # carry behaviour we ship?", so as root every markdown file looked executable and it demanded
  # coverage for 56 more files.
  #
  # Those 56 failures were the harmless half. The dangerous half is the inverse: root can read,
  # write and traverse anything, so a test asserting "this is not writable" or "this fails without
  # permission" would PASS for the wrong reason and stop testing anything. That is precisely the
  # silently-weakened check this container exists to eliminate.
  #
  # `--group-add 0` is the one concession: the docker socket is root:root mode 660 (measured), and
  # the dev cycle drives the host daemon through it. Group root grants the socket, and read on
  # root-owned world-readable files — far short of being root, and it leaves the execute-bit
  # semantics above intact, which is the property that matters here.
  local args=(
    -d --name "$NAME"
    -u "$(id -u):$(id -g)"
    --group-add 0
    -v "$REPO":"$REPO"
    -w "$REPO"
    -v /var/run/docker.sock:/var/run/docker.sock
    -e "IDEABLE_IN_TOOL_CONTAINER=1"
    # A non-root user has no home in this image. A tmpfs gives npm, pytest and playwright somewhere
    # writable without baking a user into the Dockerfile or writing into the mounted repo.
    --tmpfs /home/ideable:rw,mode=0777
    -e "HOME=/home/ideable"
    # Chromium's renderer shares memory through /dev/shm, which Docker caps at 64 MB by default.
    # A real page then dies mid-navigation with "Page crashed" — which reads like an application
    # bug, not a container limit. Measured: one entity page crashed on `waitUntil: networkidle`
    # while every lighter spec passed. `--ipc=host` is Playwright's own documented remedy.
    --ipc=host
  )
  # Each Playwright harness gets its OWN node_modules, in a named volume.
  #
  # Those trees contain COMPILED binaries — `@rspack/binding` is compiled Rust — built for the
  # platform that installed them. The repo is bind-mounted, so without this the container sees the
  # host's darwin-arm64 build and `npm ci`'s shortcut (`[ -d node_modules ] || npm ci`) accepts it;
  # the binding then fails to load and the whole UI suite runs zero tests.
  #
  # Installing into the bind-mounted directory instead would fix the container by breaking the host:
  # one directory, two incompatible platforms, each overwriting the other on alternate runs. Mounting
  # something else OVER that path gives the container its own copy at the same location, leaves the
  # host's untouched underneath, and persists — so the install happens once, not every run.
  #
  # A host directory, not a named volume: Docker creates named volumes owned by root, and this
  # container runs as the host user, so `npm ci` into one fails with EACCES (measured). A directory
  # the host user already owns sidesteps ownership entirely. It lives under the user's cache rather
  # than in the repo so it needs no .gitignore entry and can never be committed.
  # Two trees per module, not one: the Playwright harness has its own dependencies, and
  # `playwright.config.ts` starts the dev server with `npm run dev` in `frontend/SOURCES`, which uses
  # that tree's. The first was fixed alone and the failure simply moved to the second.
  local nm_dir nm_cache
  for nm_dir in modules/*/frontend/TESTS/playwright modules/*/frontend/SOURCES; do
    [[ -f "$REPO/$nm_dir/package.json" ]] || continue
    nm_cache="${HOME}/.cache/ideable-devtools/node_modules/$(printf '%s' "$nm_dir" | tr '/' '-')"
    mkdir -p "$nm_cache"
    args+=(-v "$nm_cache":"$REPO/$nm_dir/node_modules")
  done

  # The deployment's PUBLIC hostname must resolve here the way it does on the host.
  #
  # The edge suites ask for `https://<EXTERNAL_BASE_HOST>/…` on purpose: that is the address a user
  # types, and it is what exercises Traefik's Host-based routing rules and its certificate. On the
  # host that works because /etc/hosts maps the name to 127.0.0.1, so the request reaches the
  # published Traefik ports. Inside the container the name resolved to the real public IP instead,
  # which does not hairpin back — 11 edge tests failed, and the naive fix (point them at
  # `http://traefik`) would have sent `Host: traefik`, matched no router rule, and quietly turned an
  # edge test into a service test that happens to pass.
  #
  # `host-gateway` keeps the meaning intact: same URL, same Host header, same certificate, same
  # published port — only the resolution differs, which is the one thing that has to.
  local ext_host
  ext_host="$(grep -h '^EXTERNAL_BASE_HOST=' "$REPO/project.env.config" 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"'"'"' ' || true)"
  if [[ -n "$ext_host" && "$ext_host" != "localhost" && "$ext_host" != "127.0.0.1" ]]; then
    args+=(--add-host "${ext_host}:host-gateway")
  fi

  # A GIT WORKTREE keeps its repository somewhere else, and that somewhere else has to be mounted.
  #
  # In a worktree `$REPO/.git` is a FILE reading `gitdir: <primary>/.git/worktrees/<name>`, not a
  # directory. Mounting the worktree alone therefore carries a pointer to a path the container does
  # not have, and every git command inside fails with `fatal: not a git repository` — which the
  # push gate reported as `the checks that read those files FAIL against HEAD`, sending the
  # developer to inspect their own bookkeeping. The same three checks passed on the host for the
  # very tree the hook refused.
  #
  # A worktree is the normal way to work on a branch while another session keeps the primary
  # checkout, so this is the ordinary case, not an exotic one. `--git-common-dir` names the
  # directory the object store and the worktree metadata live in; mounting it at its own absolute
  # path keeps the `gitdir:` pointer valid, exactly as the repository mount above does.
  local git_common
  git_common="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$git_common" && -d "$git_common" && "$git_common" != "$REPO/.git" ]]; then
    args+=(-v "$git_common":"$git_common")
  fi

  # git and gh should behave as they do on the host: same identity, same auth. Read-only, because a
  # tool has no business rewriting your global config. Pointed at by env rather than placed under
  # HOME, because HOME is now a tmpfs the mounts would fight with.
  [[ -f "$HOME/.gitconfig" ]] && args+=(
    -v "$HOME/.gitconfig":/etc/ideable/gitconfig:ro -e "GIT_CONFIG_GLOBAL=/etc/ideable/gitconfig")
  [[ -d "$HOME/.config/gh" ]] && args+=(
    -v "$HOME/.config/gh":/etc/ideable/gh:ro -e "GH_CONFIG_DIR=/etc/ideable/gh")

  docker run "${args[@]}" "$IMAGE" sleep infinity >/dev/null \
    || die "could not start $NAME"
  echo "[tool] started $NAME from $IMAGE"
}

# The stack's network, so services resolve BY NAME -- `backend:8001`, `frontend:8080`. Verified
# reachable that way (200 from both). `host.docker.internal` also works but only on Docker Desktop,
# so it is not used: the same command has to work on plain Linux Docker.
#
# The stack may legitimately be down, and a lint run does not need it, so absence is not an error.
ensure_network() {
  # THIS project's stack, not whichever one is up. The filter used to name only the `backend`
  # service, which every Ideable-derived project has, and `head -1` then took one arbitrarily.
  # Measured with two projects open: the container joined the other project's network — and because
  # `container_stack_env.sh` addresses services BY NAME (`http://backend:8001`), resolved by Docker
  # DNS on the joined network, the suite would have asked its questions of the wrong stack and
  # reported the answers as if they were about this one. Two projects built from this framework have
  # the same service names by construction, which is exactly when the substitution is invisible.
  #
  # `com.docker.compose.project` is the discriminator: `deployment_root/start.sh` sets the compose
  # project name from `APP_SLUG`, so every container of this project's stack carries it.
  local slug net
  slug="$(devtools_project_slug)"
  # No identifiable project, no network. A stack this cannot name is one it must not adopt: the
  # suite then fails to resolve `backend` and says so, which is loud and correct, where joining an
  # arbitrary stack is quiet and wrong.
  [[ -n "$slug" ]] || return 0
  net="$(docker inspect "$(docker ps --filter "label=com.docker.compose.project=$slug" \
                                     --filter 'label=com.docker.compose.service=backend' \
                                     --format '{{.Names}}' | head -1)" \
        --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null | awk '{print $1}')"
  [[ -z "$net" ]] && return 0
  docker network inspect "$net" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null | grep -q "$NAME" && return 0
  docker network connect "$net" "$NAME" >/dev/null 2>&1 \
    && echo "[tool] joined $net (services resolve by name)"
  return 0
}

doctor() {
  ensure_image; ensure_container; ensure_network
  local missing=0
  echo "[doctor] image: $IMAGE"
  for t in "${REQUIRED_TOOLS[@]}"; do
    local v
    v="$(docker exec "$NAME" bash -lc "command -v $t >/dev/null 2>&1 && ($t --version 2>&1 | head -1)" 2>/dev/null)"
    if [[ -z "$v" ]]; then
      printf '[doctor] %-10s MISSING\n' "$t" >&2; missing=$((missing+1))
    else
      printf '[doctor] %-10s %s\n' "$t" "$(echo "$v" | cut -c1-52)"
    fi
  done
  # The probe passes the module names as ARGV and imports `importlib.util` properly.
  #
  # Both details are scars. It used to run `import importlib` and then call `importlib.util`, which
  # raises AttributeError -- `import importlib` does not bind the submodule. With stderr discarded
  # the output was empty, an empty result meant "nothing missing", and the doctor printed "python
  # libs all importable" UNCONDITIONALLY. Measured 2026-08-31 against the real image: it reported
  # all libs importable while `alembic` was absent. The one assertion whose whole job was to catch a
  # silently weakened check was itself the silent one.
  #
  # So the probe's own failure is now a failure, never a pass: a check that cannot run has not run.
  local py rc
  py="$(docker exec "$NAME" python3 -c '
import importlib.util, sys
bad = []
for m in sys.argv[1:]:
    try:
        if importlib.util.find_spec(m) is None:
            bad.append(m)
    except (ImportError, ValueError):
        bad.append(m)
print(" ".join(bad))
' "${REQUIRED_PYLIBS[@]}" 2>&1)"
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    echo "[doctor] python libs CHECK COULD NOT RUN (exit $rc): $py" >&2
    echo "[doctor]   Treating as a failure: a check that did not run proves nothing." >&2
    missing=$((missing+1))
  elif [[ -n "$py" ]]; then
    echo "[doctor] python libs MISSING: $py" >&2; missing=$((missing+1))
  else
    echo "[doctor] python libs all importable"
  fi
  # docker compose is a plugin, not a binary on PATH.
  if ! docker exec "$NAME" docker compose version >/dev/null 2>&1; then
    echo "[doctor] compose    MISSING (docker-compose-plugin)" >&2; missing=$((missing+1))
  else
    printf '[doctor] %-10s %s\n' "compose" "$(docker exec "$NAME" docker compose version 2>/dev/null | head -1)"
  fi

  if [[ "$missing" -gt 0 ]]; then
    echo "[doctor] $missing item(s) missing. FAIL -- and failing is the point:" >&2
    echo "[doctor]   a tool absent from the image weakens every check that needs it, silently. That" >&2
    echo "[doctor]   is how four defects hid for weeks. Add it to the Dockerfile rather than" >&2
    echo "[doctor]   letting the suite skip." >&2
    return 1
  fi
  echo "[doctor] OK — every required tool is present."
  return 0
}

case "${1:-}" in
  --doctor) shift; doctor ;;
  --stop)   docker rm -f "$NAME" >/dev/null 2>&1 && echo "[tool] removed $NAME"; exit 0 ;;
  --shell)  ensure_image; ensure_container; ensure_network; exec docker exec -it "$NAME" bash ;;
  -h|--help)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0 ;;
  "")       die "no command given. Try --doctor, --shell, or a tool such as: ruff check modules scripts" ;;
  *)
    ensure_image; ensure_container; ensure_network
    env_args=()
    while IFS= read -r line; do [[ -n "$line" ]] && env_args+=("$line"); done < <(forwarded_env_args)
    # -t only when attached to a terminal, so output stays clean when a script captures it.
    # `${env_args[@]+...}` guards the empty case under `set -u`.
    if [[ -t 1 ]]; then
      exec docker exec -it ${env_args[@]+"${env_args[@]}"} -w "$REPO" "$NAME" "$@"
    else
      exec docker exec ${env_args[@]+"${env_args[@]}"} -w "$REPO" "$NAME" "$@"
    fi ;;
esac
