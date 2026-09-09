#!/usr/bin/env bash
# Show status of all Docker Compose containers for this project.
# Usage: ./status.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help] [--deps]"
    echo ""
    echo "Shows the status of all Docker Compose containers for this project (ps)."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    echo "  --deps      Show the resolved inter-module dependency graph (module.json dependsOn),"
    echo "              providers-first, instead of container status."
    exit 0
fi

_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# THE DEPLOYMENT ROOT, AND WHY IT IS NOT JUST "BESIDE THIS FILE".
# `scripts/runtime/` IS the deployed scripts folder, copied whole — so this file lands at a site
# twice: at the deployment root (the copy a devops runs) and inside `scripts/` beside its siblings.
# Both copies must work, so the root is the directory holding `docker-compose.yml`, looked for
# beside this file and then one level above it. Neither means this is not a deployed tree, which is
# reported rather than guessed at: the source copy under `scripts/runtime/` is not meant to run,
# the project root's wrapper of the same name is.
if [[ -f "$_SELF_DIR/docker-compose.yml" ]]; then
  DEPLOY_ROOT="$_SELF_DIR"
elif [[ -f "$_SELF_DIR/../docker-compose.yml" ]]; then
  DEPLOY_ROOT="$(cd "$_SELF_DIR/.." && pwd)"
else
  echo "ERROR: no docker-compose.yml beside $_SELF_DIR or in its parent, so this is not a deployed" >&2
  echo "       tree. Run the deployment root's copy (deployment_root/$(basename "${BASH_SOURCE[0]}"))," >&2
  echo "       or the project root's wrapper of the same name." >&2
  exit 1
fi

# --deps: print the resolved inter-module dependency graph (from each module.json's
# dependsOn + the implicit host_app edge), providers-first. Self-contained so it works at a
# deployed site (module.json is deployed under modules/<M>/); no build tooling required.
if [[ "${1:-}" == "--deps" ]]; then
    MODULES_DIR="${DEPLOY_ROOT}/modules"
    [[ -d "$MODULES_DIR" ]] || MODULES_DIR="${DEPLOY_ROOT}/../modules"
    python3 - "$MODULES_DIR" <<'PY'
import json, os, sys
mods_dir = sys.argv[1]
HOST = "host_app"
if not os.path.isdir(mods_dir):
    print(f"No modules directory found at {mods_dir}"); sys.exit(0)
names = [d for d in sorted(os.listdir(mods_dir))
         if os.path.isfile(os.path.join(mods_dir, d, "module.json"))]
metas = {}
for n in names:
    try:
        metas[n] = json.load(open(os.path.join(mods_dir, n, "module.json"), encoding="utf-8"))
    except Exception:
        metas[n] = {"name": n}
edge_kinds = {n: {} for n in names}
for n in names:
    for e in metas[n].get("dependsOn", []) or []:
        t, kinds = e.get("module"), (e.get("kinds") or [])
        if t in names:
            edge_kinds[n].setdefault(t, set()).update(kinds)
    if n != HOST and HOST in names:
        edge_kinds[n].setdefault(HOST, set()).add("runtime (implicit)")
# stable providers-first topological sort
emitted, seen = [], set()
progress = True
while progress and len(emitted) < len(names):
    progress = False
    for n in names:
        if n in seen: continue
        if all(dep in seen for dep in edge_kinds[n]):
            emitted.append(n); seen.add(n); progress = True
cycle = [n for n in names if n not in seen]
print("Resolved module order (providers first):")
print("  " + (" -> ".join(emitted) if emitted else "(none)"))
if cycle:
    print("  !! dependency cycle among: " + ", ".join(sorted(cycle)))
print("")
print("Declared dependencies (module -> provider [kinds]):")
for n in emitted + cycle:
    deps = edge_kinds[n]
    if not deps:
        print(f"  {n}: (none)")
    else:
        for t in sorted(deps):
            print(f"  {n} -> {t} [{', '.join(sorted(deps[t]))}]")
PY
    exit 0
fi

# Source split env files for compose interpolation and project identity.
# Source .env.secrets before .env.config because config files may reference secret variables.
if [[ -f "$DEPLOY_ROOT/.env.secrets" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$DEPLOY_ROOT/.env.secrets"
  set +a
  set -u
fi
if [[ -f "$DEPLOY_ROOT/.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$DEPLOY_ROOT/.env.config"
  set +a
  set -u
fi

PROJECT_NAME="${APP_SLUG:-$(basename "$DEPLOY_ROOT")}"

# ── Build identity ────────────────────────────────────────────────────────────
# "Which build is running?" has to have an answer, per container, before anything else here is
# useful. Every locally built image is `latest`, so its NAME cannot answer; its LABELS can — the
# deploy stamps the commit (`org.opencontainers.image.revision`) and whether the tree was dirty on
# every image it builds. A consumed image (host_app in a remote project) is pulled by the digest the
# framework lock names, so its digest is the answer there. Third-party images have neither.
#
# And which framework this project runs: the one line in framework.env, and what the lock says it
# resolved to. At a deployed site there is no framework.env beside the deployment, and this says so.
label_of() { docker inspect --format "{{index .Config.Labels \"$2\"}}" "$1" 2>/dev/null || true; }

FRAMEWORK_ENV=""
for candidate in "$DEPLOY_ROOT/../framework.env" "$DEPLOY_ROOT/framework.env"; do
  [[ -f "$candidate" ]] && { FRAMEWORK_ENV="$candidate"; break; }
done
echo "Framework version"
if [[ -n "$FRAMEWORK_ENV" ]]; then
  fw_version="$(grep -E '^IDEABLE_FRAMEWORK_VERSION=' "$FRAMEWORK_ENV" | head -1 | cut -d= -f2- | tr -d "\"' ")"
  lock_file="$(dirname "$FRAMEWORK_ENV")/framework.lock.json"
  if [[ -f "$lock_file" ]]; then
    lock_summary="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(f"{d.get(\"version\",\"?\")}, published {d.get(\"published_at\",\"?\")}")' "$lock_file" 2>/dev/null || echo "unreadable")"
  else
    lock_summary="no framework.lock.json beside it"
  fi
  echo "  framework.env  IDEABLE_FRAMEWORK_VERSION=${fw_version:-<unset>}   (lock: ${lock_summary})"
else
  echo "  not available here: no framework.env beside this deployment"
fi

echo "Build identity (per container: image · revision, or the pulled digest)"
while IFS=$'\t' read -r cname cimage cid; do
  [[ -z "$cname" ]] && continue
  revision="$(label_of "$cid" org.opencontainers.image.revision)"
  dirty="$(label_of "$cid" tech.ideable.dirty)"
  if [[ -n "$revision" ]]; then
    identity="revision ${revision}$([[ "$dirty" == "true" ]] && echo ' (dirty tree)')"
  else
    digest="$(docker image inspect --format '{{join .RepoDigests " "}}' "$cimage" 2>/dev/null | awk '{print $1}' | sed 's/.*@//')"
    identity="${digest:+digest ${digest:0:19}…}"
    identity="${identity:-(no revision label, no registry digest)}"
  fi
  printf '  %-40s %-34s %s\n' "$cname" "$cimage" "$identity"
done < <(docker ps \
  --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
  --format '{{.Names}}\t{{.Image}}\t{{.ID}}' | sort)

# The comparison is per SERVICE, not global. Third-party images legitimately differ from one
# another, so "more than one image is running" is normal and warning on it would be noise that
# teaches operators to ignore the warning. What is never normal is two replicas of the SAME service
# on different builds — a scale-up across a redeploy — and since every replica now carries the same
# NAME (`…:latest`), the comparison has to be on the image ID, which is the build.
DISAGREEING=""
while IFS=$'\t' read -r csvc; do
  [[ -z "$csvc" ]] && continue
  case " $DISAGREEING " in *" $csvc "*) continue ;; esac
  n=$(docker ps -q \
    --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
    --filter "label=com.docker.compose.service=${csvc}" \
    | xargs -r docker inspect --format '{{.Image}}' 2>/dev/null | sort -u | wc -l | tr -d ' ')
  [[ "$n" -gt 1 ]] && DISAGREEING="$DISAGREEING $csvc"
done < <(docker ps \
  --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
  --format '{{.Label "com.docker.compose.service"}}' | sort -u)

if [[ -n "$DISAGREEING" ]]; then
  echo ""
  echo "  ⚠ replicas of the same service are running DIFFERENT builds:$DISAGREEING"
  echo "    Requests to that service are being served by more than one version of the code."
  echo "    Run ./start.sh to recreate every replica from the current image."
fi
echo ""

exec docker compose \
  --project-directory "$DEPLOY_ROOT" \
  --project-name "$PROJECT_NAME" \
  ps
