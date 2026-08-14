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

exec docker compose \
  --project-directory "$SCRIPT_DIR" \
  --project-name "${APP_SLUG:-$(basename "$SCRIPT_DIR")}" \
  ps
