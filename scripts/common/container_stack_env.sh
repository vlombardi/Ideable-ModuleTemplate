#!/usr/bin/env bash
# Where the running stack is, seen from inside the dev tools container. Sourced, never executed.
#
#     source scripts/common/container_stack_env.sh
#     container_stack_addresses                     # the fixed service addresses
#     container_module_addresses host_app module_template   # the per-module, slug-derived ones
#
# ONE definition, every caller. `run_enabled_tests.sh` and `module_only/run_tests.sh` both run tests
# from inside the container and both need these; a second copy of the mapping is how one of them
# quietly stops matching the stack. This repository has paid for that pattern four times in a month
# (`.devin/skills`, `.devin/workflows`, the pull-side spec allowlist, and a duplicated database
# guard), so the arithmetic lives here once.
#
# WHY IT IS NEEDED AT ALL. Suites that talk to a running stack read a URL from the environment and
# default to `http://localhost:<published port>`. That is right on the host and wrong in here, where
# `localhost` is this container: 58 tests failed with ConnectionRefused the first time the runner was
# routed through it, and 95 more SKIPPED — reporting "no running stack" while the run said PASSED.
#
# Everything below uses `:=`, so an address the caller set explicitly always wins.

# Fixed service addresses. The ports are the services' OWN, not the host's published ones — the
# frontend is published 3000→8080 and traefik 8088→8080, so reusing the host numbers fails just as
# surely as using localhost. Verified from inside: backend/health 200, frontend 200,
# authentik-server 302, traefik 301, template-backend/health 200.
container_stack_addresses() {
  [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" == "1" ]] || return 0

  : "${HOSTAPP_BASE_URL:=http://backend:8001}"
  : "${BACKEND_URL:=http://backend:8001}"
  : "${HOSTAPP_API_URL_HOST:=http://backend:8001/api}"
  : "${FRONTEND_URL:=http://frontend:8080}"
  : "${AUTHENTIK_URL:=http://authentik-server:9000}"
  : "${TRAEFIK_DASHBOARD_URL:=http://traefik:8080}"
  # The databases publish on 127.0.0.1 only, so no host route reaches them from here; the service
  # name on its own 5432 is the only way in, not the host's 5433.
  : "${POSTGRES_HOST:=database}"
  : "${POSTGRES_PORT:=5432}"

  export HOSTAPP_BASE_URL BACKEND_URL HOSTAPP_API_URL_HOST FRONTEND_URL AUTHENTIK_URL \
         TRAEFIK_DASHBOARD_URL POSTGRES_HOST POSTGRES_PORT

  # The EDGE is deliberately NOT remapped — neither EXTERNAL_BASE_HOST nor EXTERNAL_BASE_URL.
  #
  # Those suites ask for `https://<public hostname>/…` because that is the address a user types, and
  # it is what exercises Traefik's Host-based routing rules and its certificate. Pointing them at
  # `http://traefik` was tried and is wrong in a way that hides itself: the request carries
  # `Host: traefik`, matches no router rule, and an edge test silently becomes a service test.
  # `tool.sh` instead makes the public hostname RESOLVE in here (`--add-host <host>:host-gateway`),
  # so the same URL reaches the same Traefik through the same published port.
}

# One value from an env file, total: absent file, absent key and empty value all give "".
_stack_env_file_value() {  # <file> <key>
  [ -f "$1" ] || return 0
  grep -h "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

# A module's backend port, with one level of variable reference resolved.
#
# WHY THIS IS NOT A `grep -oE "^<UP>_BACKEND_PORT=[0-9]+"`. It was, and the pattern cannot match the
# shape the template's own `.env.config.example` ships:
#
#     TEMPLATE_BACKEND_PORT=${IDEABLE_MODULE_BACKEND_PORT:-8002}
#
# A module generated from that example and left as it stands — which is the encouraged shape, and
# what a real remote module (slug `sra`) had — produced no match, so no `<SLUG>_API_URL` was
# exported, so the module's `conftest.py` fell back to its `http://localhost:<port>` default. Inside
# the dev tools container `localhost` is the container, and the measured result was **85 backend
# tests SKIPPING while the run reported `0 failed`**. A skip caused by the harness looked exactly
# like a skip caused by the code under test.
#
# Resolution order, most-specific first: the process environment (the runner may have exported it),
# the module's own `.env.config`, the merged deployed config, then the project-level config, then
# the reference's own `:-default`. Those files keep references UNRESOLVED — `deployment_root/.env.config`
# really does contain `BACKEND_PORT=${HOSTAPP_BACKEND_PORT:-8001}` — so the lookup has to be a
# lookup, not a read.
#
# Prints the port and returns 0, or prints nothing and returns 1. It never guesses: an underivable
# port is announced by the caller, because the alternative is the silence above.
_module_backend_port() {  # <module .env.config> <UPPERCASED SLUG>
  local cfg="$1" up="$2" raw key name default live

  # The module's own prefixed key first; the bare one is host_app's spelling.
  for key in "${up}_BACKEND_PORT" "BACKEND_PORT"; do
    raw=$(_stack_env_file_value "$cfg" "$key")
    [ -n "$raw" ] && break
  done
  [ -n "$raw" ] || return 1

  # An inline comment, surrounding quotes and trailing space are all legal in these files.
  raw="${raw%%#*}"
  raw="$(printf '%s' "$raw" | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")"

  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    printf '%s' "$raw"
    return 0
  fi

  if [[ "$raw" =~ ^\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}$ ]]; then
    name="${BASH_REMATCH[1]}"
    default="${BASH_REMATCH[3]:-}"

    live=$(eval "printf '%s' \"\${${name}:-}\"" || true)
    if [[ ! "$live" =~ ^[0-9]+$ ]]; then
      for f in "$cfg" deployment_root/.env.config project.env.config; do
        live=$(_stack_env_file_value "$f" "$name")
        live="${live%%#*}"
        live="$(printf '%s' "$live" | sed -e 's/[[:space:]]*$//')"
        [[ "$live" =~ ^[0-9]+$ ]] && break
      done
    fi
    if [[ "$live" =~ ^[0-9]+$ ]]; then
      printf '%s' "$live"
      return 0
    fi
    if [[ "$default" =~ ^[0-9]+$ ]]; then
      printf '%s' "$default"
      return 0
    fi
  fi
  return 1
}

# Per-module addresses, derived rather than listed.
#
# A module's own suite reads a RUNTIME-NAMED variable — `conftest.py` does
# `os.getenv(f"{SLUG.upper()}_API_URL", …)` — so no fixed list of names can cover it, and grepping
# for env defaults does not find it either. The slug comes from the module's manifest, the port from
# its own `.env.config`, and the compose service from the convention `docker ps` shows: `backend`
# for host_app, `<slug>-backend` for every other module.
container_module_addresses() {
  [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" == "1" ]] || return 0

  local m mf slug up cfg port svc var fsvc fvar
  for m in "$@"; do
    mf="modules/$m/frontend/SOURCES/src/moduleManifest.ts"
    slug=""
    if [ -f "$mf" ]; then
      slug=$(grep -oE "slug:[[:space:]]*['\"][^'\"]+['\"]" "$mf" 2>/dev/null | head -1 \
             | sed -E "s/.*['\"]([^'\"]+)['\"].*/\1/" || true)
    fi
    [ -n "$slug" ] || slug=$(printf '%s' "$m" | tr -d '_')
    up=$(printf '%s' "$slug" | tr '[:lower:]' '[:upper:]')
    cfg="modules/$m/.env.config"

    port=$(_module_backend_port "$cfg" "$up" || true)
    var="${up}_API_URL"
    if [ -n "$port" ]; then
      if [ "$m" = "host_app" ]; then svc="backend"; else svc="${slug}-backend"; fi
      if [ -z "$(eval "printf '%s' \"\${${var}:-}\"" || true)" ]; then
        export "${var}=http://${svc}:${port}/api"
        echo "  · ${var}=http://${svc}:${port}/api (container view of $m)"
      fi
    elif [ -z "$(eval "printf '%s' \"\${${var}:-}\"" || true)" ]; then
      # SAY IT. Falling through quietly is what cost 85 backend tests: with no `${var}` the
      # module's `conftest.py` uses its `http://localhost:<port>` default, which in here is this
      # container, and every API test SKIPS with "no running stack" while the run reports 0 failed.
      # A harness that cannot find the stack must not be mistaken for code under test that is fine.
      echo "  ⚠ ${var} could NOT be derived for $m: no usable backend port in ${cfg}."
      echo "    Expected ${up}_BACKEND_PORT (or BACKEND_PORT) as a number, or as \${VAR:-<number>}"
      echo "    with VAR resolvable from the environment, ${cfg},"
      echo "    deployment_root/.env.config or project.env.config."
      echo "    Until it is, $m's API tests will target localhost — i.e. this container — and SKIP."
      echo "    Set ${var} explicitly to override."
    fi

    # The frontend SERVICE — deliberately a different variable from `<SLUG>_FRONTEND_URL`, which is
    # the SHELL: the address a browser opens, which Playwright's login needs to be the public
    # hostname because Authentik's redirects and cookies are bound to it. Overriding the shell to
    # reach a service zeroed the entire UI suite while the run still reported 0 failed. 8080 is the
    # frontend IMAGE's port, shared by every module.
    if [ "$m" = "host_app" ]; then fsvc="frontend"; else fsvc="${slug}-frontend"; fi
    fvar="${up}_FRONTEND_SERVICE_URL"
    if [ -z "$(eval "printf '%s' \"\${${fvar}:-}\"" || true)" ]; then
      export "${fvar}=http://${fsvc}:8080"
      echo "  · ${fvar}=http://${fsvc}:8080 (container view of $m)"
    fi
  done
}
