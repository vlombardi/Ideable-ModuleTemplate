#!/bin/bash
# Seed a module's authorization contract into Authentik on demand.
#
# The bootstrap seeds a module automatically the first time it sees that module's authorization
# contract, and never again — a restart re-seeds nothing. This script is the ONLY other way to make it
# run, for the cases where an operator has to ask for it explicitly:
#
#   - a module's contract was changed in place without a version/deployable change
#   - a devops wants to see what a seed would do before letting it happen (--dry-run)
#   - the seed state was lost or a module must be re-applied deliberately (--force)
#
# Seeding is NON-DESTRUCTIVE by construction. It adds associations a module requires and has never
# seeded before; it never removes associations added by hand, and it never restores one that was
# removed after a previous seed — that removal was a human decision, and it is reported in
# Admin -> System messages instead of being undone.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'USAGE'
Usage: ./scripts/seed-module.sh [<slug> ...] [--all] [--force] [--dry-run]

Arguments:
  <slug>       Module slug to seed (repeatable), e.g. template. Default: every enabled module.

Options:
  --all        Consider every enabled module (the default; accept it for explicitness in scripts).
  --force      Re-seed even when the module's authorization contract is unchanged.
  --dry-run    Report what would change and change nothing.
  -h, --help   Show this message.

Examples:
  ./scripts/seed-module.sh --dry-run              # what would a seed of everything do?
  ./scripts/seed-module.sh template               # seed just module_template
  ./scripts/seed-module.sh template --force       # re-apply its contract even if unchanged

Notes:
  - Requires the identity plane to be running (authentik-server healthy).
  - Results, and any association a module expects but that was removed after a previous seed, appear
    in Admin -> System messages.
USAGE
}

SLUGS=()
PASSTHROUGH=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --all)     PASSTHROUGH+=("--all") ;;
    --force)   PASSTHROUGH+=("--force") ;;
    --dry-run) PASSTHROUGH+=("--dry-run") ;;
    -*)        echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)         SLUGS+=("$1") ;;
  esac
  shift
done

for slug in "${SLUGS[@]:-}"; do
  [[ -n "$slug" ]] && PASSTHROUGH+=("--module" "$slug")
done

COMPOSE_FILE="${DEPLOYMENT_ROOT}/docker-compose.yml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: no deployed stack found at ${COMPOSE_FILE}" >&2
  exit 1
fi

# Load the merged env and derive the project name exactly as start.sh does. Without both, compose
# interpolates every ${VAR} to an empty string and derives an unprefixed project name, so it tries to
# create volumes like "_authentik_pgdata" instead of finding the running stack's.
if [[ -f "${DEPLOYMENT_ROOT}/.env.secrets" ]]; then
  set -a; source "${DEPLOYMENT_ROOT}/.env.secrets"; set +a
fi
if [[ -f "${DEPLOYMENT_ROOT}/.env.config" ]]; then
  set -a; source "${DEPLOYMENT_ROOT}/.env.config"; set +a
fi
PROJECT_NAME="${APP_SLUG:-$(basename "$DEPLOYMENT_ROOT")}"

# `run --rm` starts a NEW one-shot container from the bootstrap image with the same mounts, env and
# networks as the composed service. `up` is deliberately not used: it would recreate the long-lived
# services alongside it, which is exactly the restart-reseeds-everything behaviour this replaces.
echo "[seed-module.sh] running bootstrap with: ${PASSTHROUGH[*]:-<no flags>}"
cd "$DEPLOYMENT_ROOT"
docker compose \
  --project-directory "$DEPLOYMENT_ROOT" \
  --project-name "$PROJECT_NAME" \
  run --rm --no-deps --entrypoint python3 \
  authentik-bootstrap /bootstrap/scripts/bootstrap_authentik.py "${PASSTHROUGH[@]:-}"

echo ""
echo "[seed-module.sh] done. Check Admin -> System messages for what was applied, and for any"
echo "                 association a module expects that was removed after a previous seed."
