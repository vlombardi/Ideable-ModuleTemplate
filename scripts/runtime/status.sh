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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --deps: print the resolved inter-module dependency graph (from each module.json's
# dependsOn + the implicit host_app edge), providers-first. Self-contained so it works at a
# deployed site (module.json is deployed under modules/<M>/); no build tooling required.
if [[ "${1:-}" == "--deps" ]]; then
    MODULES_DIR="${SCRIPT_DIR}/modules"
    [[ -d "$MODULES_DIR" ]] || MODULES_DIR="${SCRIPT_DIR}/../modules"
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
if [[ -f "$SCRIPT_DIR/.env.secrets" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$SCRIPT_DIR/.env.secrets"
  set +a
  set -u
fi
if [[ -f "$SCRIPT_DIR/.env.config" ]]; then
  # shellcheck disable=SC1090
  set +u
  set -a
  source "$SCRIPT_DIR/.env.config"
  set +a
  set -u
fi

PROJECT_NAME="${APP_SLUG:-$(basename "$SCRIPT_DIR")}"

# ── Build identity ────────────────────────────────────────────────────────────
# "Which build is running?" has to have an answer, per replica, before anything else here is
# useful. Images are tagged with the commit they were built from (never `latest`), so the tag a
# container was started with is a fact worth printing — and worth comparing.
#
# The comparison is the point, and it takes THREE quantities, not two. `BUILT_IMAGE_TAG` says what
# the last build *produced*; `IMAGE_TAG` says what ./start.sh *would* start; the per-container tags
# say what is *actually* serving. Each pair diverges in situations an operator needs to see:
#
#  - built ≠ configured — the last deploy built one tag and configured another, so the stack is
#    running an earlier build. This is the pair that was missing here, and its absence is why a
#    deploy that dropped IMAGE_TAG looked completely healthy: configured and running agreed
#    perfectly, both naming a build from twenty minutes earlier.
#  - configured ≠ running — a rollback edited the file but start.sh was never run; a container was
#    recreated by hand.
#  - running ≠ running, within one service — a scale-up across a config change, so replica 1 and
#    replica 2 serve different code.
#
# `docker compose ps` alone shows every one of these as "Up".
echo "Build identity"
echo "  built      (last deploy)  BUILT_IMAGE_TAG=${BUILT_IMAGE_TAG:-<unset>}"
echo "  configured (.env.config)  IMAGE_TAG=${IMAGE_TAG:-<unset>}"
if [[ -n "${BUILT_IMAGE_TAG:-}" && -n "${IMAGE_TAG:-}" && "${BUILT_IMAGE_TAG}" != "${IMAGE_TAG}" ]]; then
  echo "  ⚠ the configured tag is NOT the tag the last deploy built."
  echo "    Deliberate for a rollback; otherwise the stack is running an earlier build than the"
  echo "    one that was last produced here. Rebuild with ./redeploy.sh --image-tag ${BUILT_IMAGE_TAG}"
fi

# The comparison is per SERVICE, not global. Third-party images legitimately carry their own tags
# (postgres:16-alpine, the Authentik release), so "more than one tag is running" is normal and
# warning on it would be noise that teaches operators to ignore the warning. What is never normal
# is two replicas of the SAME service on different tags — that is a half-applied rollback or a
# scale-up across a config change, and it means requests are being served by two different builds.
DISAGREEING=""
while IFS=$'\t' read -r csvc cimage; do
  [[ -z "$csvc" ]] && continue
  case " $DISAGREEING " in *" $csvc "*) continue ;; esac
  n=$(docker ps \
    --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
    --filter "label=com.docker.compose.service=${csvc}" \
    --format '{{.Image}}' | sort -u | wc -l | tr -d ' ')
  [[ "$n" -gt 1 ]] && DISAGREEING="$DISAGREEING $csvc"
done < <(docker ps \
  --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
  --format '{{.Label "com.docker.compose.service"}}\t{{.Image}}')

while IFS=$'\t' read -r cname cimage; do
  [[ -z "$cname" ]] && continue
  printf '  %-40s %s\n' "$cname" "$cimage"
done < <(docker ps \
  --filter "label=com.docker.compose.project=${PROJECT_NAME}" \
  --format '{{.Names}}\t{{.Image}}' | sort)

if [[ -n "$DISAGREEING" ]]; then
  echo ""
  echo "  ⚠ replicas of the same service are running DIFFERENT builds:$DISAGREEING"
  echo "    Requests to that service are being served by more than one version of the code."
  echo "    Run ./start.sh to converge every replica on IMAGE_TAG=${IMAGE_TAG:-<unset>}."
fi
echo ""

exec docker compose \
  --project-directory "$SCRIPT_DIR" \
  --project-name "$PROJECT_NAME" \
  ps
