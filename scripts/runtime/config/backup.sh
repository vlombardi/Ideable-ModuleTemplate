#!/usr/bin/env bash
# Back up every database in the deployment plus the artefacts needed to rebuild the stack.
# Usage: ./scripts/runtime/config/backup.sh [-h|--help] [--dir <path>]
#
# Targets (see the framework spec § "Backup and recovery"): RPO 24h, RTO 4h — a nightly logical
# dump. There is no WAL archiving, so anything written since the last successful run is lost in a
# host-loss scenario; tighten the schedule, or add PITR, if that is not acceptable.
#
# Exits non-zero if ANY database or artefact fails, and prunes old backups only after a fully
# successful run: a partial backup that reports success is worse than no backup, because it is
# trusted.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help] [--dir <path>]"
    echo ""
    echo "Backs up every database (host_app, Authentik, each enabled module) with pg_dump -Fc,"
    echo "plus .env.config, traefik/acme.json, authentik blueprints and module config/ folders."
    echo ""
    echo "Each run writes backups/<YYYY-MM-DD-HH-MM-SS>/ containing the dumps, the artefacts and"
    echo "a SHA-256 manifest. Restore with restore.sh; rehearse with verify-backup.sh."
    echo ""
    echo "Options:"
    echo "  --dir <path>  Backup root (default: \$BACKUP_DIR, else <deployment>/backups)"
    echo "  -h, --help    Show this help message"
    echo ""
    echo "Environment:"
    echo "  BACKUP_DIR             backup root"
    echo "  BACKUP_RETENTION_DAYS  prune runs older than this after a successful run (default 14)"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Detect context: deployed (script sits next to .env.config) vs source repo.
if [[ -f "$SCRIPT_DIR/../.env.config" ]]; then
  DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  DEPLOY_ROOT="$(cd "$SCRIPT_DIR/../../../deployment_root" && pwd)"
fi

set +u
set -a
# shellcheck disable=SC1090,SC1091
[[ -f "$DEPLOY_ROOT/.env.config" ]] && source "$DEPLOY_ROOT/.env.config"
# shellcheck disable=SC1090,SC1091
[[ -f "$DEPLOY_ROOT/.env.secrets" ]] && source "$DEPLOY_ROOT/.env.secrets"
set +a
set -u

BACKUP_ROOT="${BACKUP_DIR:-$DEPLOY_ROOT/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) BACKUP_ROOT="$2"; shift 2 ;;
    *) echo "Unknown option: $1 (use --help)" >&2; exit 2 ;;
  esac
done

STAMP="$(date '+%Y-%m-%d-%H-%M-%S')"
TARGET="$BACKUP_ROOT/$STAMP"
mkdir -p "$TARGET"
FAILURES=0

log()  { echo "[backup] $*"; }
fail() { echo "[backup] FAILED: $*" >&2; FAILURES=$((FAILURES + 1)); }

# --- Databases -------------------------------------------------------------------------------
# Discovered from the running containers rather than a hardcoded list, so a module added later is
# backed up without editing this script. Each entry: <container>|<db>|<user>|<label>.
declare -a DATABASES=()

if [[ -n "${APP_SLUG:-}" ]]; then
  hostapp_db="${POSTGRES_DB:-}"
  hostapp_user="${POSTGRES_USER:-}"
  if [[ -n "$hostapp_db" && -n "$hostapp_user" ]]; then
    DATABASES+=("${APP_SLUG}.hostapp.database|${hostapp_db}|${hostapp_user}|hostapp")
    # Authentik has its OWN database service since the identity-plane split -- `${APP_SLUG}.hostapp.authentik-database`,
    # a separate container with a separate volume, so the identity store can be backed up, restored
    # and sized independently of the application.
    #
    # This line used to say `${APP_SLUG}.hostapp.database`, with a comment claiming "Authentik shares
    # host_app's database service". That was true before the identity-plane split and false after it, and the stale
    # comment is why the line was never revisited: every backup since then failed this one dump with
    # `database "authentik" does not exist` -- pg_dump was connecting to the APPLICATION database and
    # correctly reporting that the identity database was not in it.
    #
    # backup.sh exits non-zero when any dump fails, so the failure was never silent. It was simply
    # never run, which is the same lesson in a different coat: an untested backup is a claim, and
    # docs/RUNBOOK.md documents an "Identity database restore" that had nothing to restore from.
    DATABASES+=("${APP_SLUG}.hostapp.authentik-database|${AUTHENTIK_POSTGRES_DB:-authentik}|${AUTHENTIK_POSTGRES_USER:-$hostapp_user}|authentik")
  fi
  # Module databases: every running <app>.<module>.database container that is not host_app's.
  while IFS= read -r container; do
    [[ -z "$container" || "$container" == "${APP_SLUG}.hostapp.database" ]] && continue
    slug="$(echo "$container" | awk -F. '{print $2}')"
    upper="$(echo "$slug" | tr '[:lower:]' '[:upper:]')"
    db_var="${upper}_ENTITIES_DB_NAME";   db="${!db_var:-}"
    user_var="${upper}_ENTITIES_DB_USER"; user="${!user_var:-}"
    if [[ -z "$db" || -z "$user" ]]; then
      fail "module '$slug': ${db_var}/${user_var} not set — cannot back it up"
      continue
    fi
    DATABASES+=("${container}|${db}|${user}|${slug}")
  done < <(docker ps --format '{{.Names}}' 2>/dev/null | grep -E "^${APP_SLUG}\..*\.database$" || true)
fi

if [[ ${#DATABASES[@]} -eq 0 ]]; then
  echo "[backup] No databases discovered — is the stack running and APP_SLUG set?" >&2
  exit 1
fi

# PROVENANCE.json records what PRODUCED this backup, not just what is in it.
#
# The dumps and MANIFEST.sha256 answer "are these bytes intact". They cannot answer the question an
# operator actually has at 3am: "is this backup compatible with the code I am about to run against
# it?" Different framework versions carry different datamodels, and a restore is destructive, so the
# answer has to be available BEFORE the restore, not discovered after it.
#
# Each database's Alembic revision is inside its own dump (the `alembic_version` table restores with
# everything else), but that is no help for a pre-flight check: reading it would mean restoring
# first. So it is recorded out here, alongside the build that produced it.
PROVENANCE="$TARGET/PROVENANCE.json"
prov_dbs=""

for entry in "${DATABASES[@]}"; do
  IFS='|' read -r container db user label <<< "$entry"
  out="$TARGET/${label}.dump"
  log "dumping ${label} (${db}) from ${container}"
  if docker exec "$container" pg_dump -Fc -U "$user" -d "$db" > "$out" 2>"$TARGET/${label}.pg_dump.log"; then
    rm -f "$TARGET/${label}.pg_dump.log"

    # Recorded per database, because they migrate independently: host_app and each module own their
    # own Alembic history, so "the backup's revision" is not one value.
    # Every probe ends in `|| true`, and that is not defensive noise. Under `set -euo pipefail` a
    # failing command inside `x="$(...)"` aborts the script, and one of these probes ALWAYS fails:
    # the Authentik database has no `alembic_version` table at all -- Django owns its schema, not
    # Alembic -- so querying it is an error, and losing the whole backup over a field that is
    # legitimately absent would be a spectacular own goal. Absent is recorded as such below.
    rev="$(docker exec "$container" psql -qtAX -U "$user" -d "$db" \
             -c "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null | tr -d '[:space:]' || true)"
    ts_ver="$(docker exec "$container" psql -qtAX -U "$user" -d "$db" \
             -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';" 2>/dev/null | tr -d '[:space:]' || true)"
    pg_ver="$(docker exec "$container" psql -qtAX -U "$user" -d "$db" \
             -c "SHOW server_version;" 2>/dev/null | tr -d '[:space:]' || true)"
    # Structural fingerprint, so the restore rehearsal can check that the SHAPE came back and not
    # merely that some tables appeared. This exists because a plain pg_restore of a Timescale
    # hypertable silently dropped both primary keys on the versioning tables while reporting
    # success: 7 tables restored, 0 primary keys, and the old rehearsal called that "clean".
    tbls="$(docker exec "$container" psql -qtAX -U "$user" -d "$db" \
             -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '[:space:]' || true)"
    pks="$(docker exec "$container" psql -qtAX -U "$user" -d "$db" \
             -c "SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE c.contype='p' AND n.nspname='public';" 2>/dev/null | tr -d '[:space:]' || true)"
    # NOT `[[ -n "$x" ]] && ...`: under `set -e` that compound returns 1 when the test is false,
    # which killed the script on the FIRST database every time. An `if` has no exit status to trip on.
    if [[ -n "$prov_dbs" ]]; then prov_dbs="$prov_dbs,"; fi
    prov_dbs="$prov_dbs
    {\"label\": \"$label\", \"database\": \"$db\", \"container\": \"$container\",
     \"alembic_revision\": \"${rev:-none}\", \"timescaledb\": \"${ts_ver:-none}\",
     \"postgres\": \"${pg_ver:-unknown}\",
     \"tables\": ${tbls:-0}, \"primary_keys\": ${pks:-0}}"
  else
    fail "pg_dump of ${label} (${db}) — see ${label}.pg_dump.log"
    rm -f "$out"
  fi
done

cat > "$PROVENANCE" <<PROV
{
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "app_slug": "${APP_SLUG:-unknown}",
  "image_tag": "${IMAGE_TAG:-unknown}",
  "databases": [${prov_dbs}
  ]
}
PROV
[[ -s "$PROVENANCE" ]] || fail "writing PROVENANCE.json"
log "provenance: image_tag=${IMAGE_TAG:-unknown}"

# --- Non-database artefacts ------------------------------------------------------------------
# A restored database is not a running system: without these, the stack cannot be rebuilt.
# NOTE: .env.secrets is deliberately NOT backed up — see docs/RUNBOOK.md § Secrets.
copy_artefact() {
  local src="$1" dest="$2"
  [[ -e "$src" ]] || { log "skipping $(basename "$src") (absent)"; return 0; }
  mkdir -p "$(dirname "$dest")"
  cp -R "$src" "$dest" || fail "copying $src"
}

copy_artefact "$DEPLOY_ROOT/.env.config"                       "$TARGET/artefacts/.env.config"
copy_artefact "$DEPLOY_ROOT/modules/host_app/traefik/acme.json" "$TARGET/artefacts/traefik/acme.json"
copy_artefact "$DEPLOY_ROOT/modules/host_app/authentik/blueprints" "$TARGET/artefacts/authentik/blueprints"
copy_artefact "$DEPLOY_ROOT/module-registry.json"              "$TARGET/artefacts/module-registry.json"
for config_dir in "$DEPLOY_ROOT"/modules/*/config; do
  [[ -d "$config_dir" ]] || continue
  module="$(basename "$(dirname "$config_dir")")"
  copy_artefact "$config_dir" "$TARGET/artefacts/modules/$module/config"
done

# --- Manifest --------------------------------------------------------------------------------
# Checksums are what let restore.sh refuse a corrupted backup instead of half-applying it.
( cd "$TARGET" && find . -type f ! -name 'MANIFEST.sha256' -print0 \
    | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256 ) || fail "writing manifest"

if [[ $FAILURES -gt 0 ]]; then
  echo "[backup] $FAILURES failure(s); backup at $TARGET is INCOMPLETE and was not pruned." >&2
  exit 1
fi

# --- Retention (only after a fully successful run) --------------------------------------------
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ && "$RETENTION_DAYS" -gt 0 ]]; then
  while IFS= read -r old; do
    log "pruning $(basename "$old") (older than ${RETENTION_DAYS}d)"
    rm -rf "$old"
  done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" 2>/dev/null || true)
fi

log "OK — $TARGET ($(du -sh "$TARGET" | cut -f1))"
