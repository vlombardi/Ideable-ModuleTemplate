#!/usr/bin/env bash
# Restore a backup produced by backup.sh.
# Usage: ./scripts/runtime/config/restore.sh --from <backup-dir> [--yes] [--only <label>]
#
# Destructive: it drops and recreates the contents of the target databases. Checksums are
# verified first — a backup that fails verification is refused outright rather than half-applied,
# which is the failure mode that turns a bad day into a lost database.
set -euo pipefail

usage() {
    echo "Usage: $0 --from <backup-dir> [--yes] [--only <label>] [--force-version]"
    echo ""
    echo "Restores databases from a backup directory created by backup.sh, in dependency order:"
    echo "database (healthy) -> bootstrap -> backends."
    echo ""
    echo "Options:"
    echo "  --from <dir>   Backup directory (e.g. backups/2026-08-16-02-00-00)"
    echo "  --only <label> Restore a single database (hostapp | authentik | <module slug>)"
    echo "  --yes          Skip the confirmation prompt (for automation; verify-backup.sh uses it)"
    echo "  --force-version  Restore even when the backup's schema is NEWER than this build's"
    echo "                   Alembic history. Deliberate override: Alembic does not downgrade, so"
    echo "                   the code would be serving a schema it does not know."
    echo "  -h, --help     Show this help message"
}

SOURCE_DIR=""; ASSUME_YES=0; ONLY=""; FORCE_VERSION=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) SOURCE_DIR="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --force-version) FORCE_VERSION=1; shift ;;
    --yes)  ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1 (use --help)" >&2; exit 2 ;;
  esac
done
[[ -n "$SOURCE_DIR" ]] || { usage; exit 2; }
[[ -d "$SOURCE_DIR" ]] || { echo "[restore] No such backup: $SOURCE_DIR" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

log() { echo "[restore] $*"; }

# --- Verify before touching anything ----------------------------------------------------------
if [[ -f "$SOURCE_DIR/MANIFEST.sha256" ]]; then
  log "verifying checksums"
  ( cd "$SOURCE_DIR" && shasum -a 256 -c MANIFEST.sha256 --quiet ) \
    || { echo "[restore] Checksum verification FAILED — refusing to restore." >&2; exit 1; }
else
  echo "[restore] No MANIFEST.sha256 in $SOURCE_DIR — refusing to restore an unverifiable backup." >&2
  exit 1
fi

mapfile -t DUMPS < <(find "$SOURCE_DIR" -maxdepth 1 -name '*.dump' | sort)
[[ ${#DUMPS[@]} -gt 0 ]] || { echo "[restore] No .dump files in $SOURCE_DIR" >&2; exit 1; }

# --- Version pre-flight -----------------------------------------------------------------------
# Checksums prove the bytes are intact. They say nothing about whether this backup FITS the code
# that is about to run against it, and different framework versions carry different datamodels.
#
# A restore is destructive, so this has to be answered before it, not discovered after. Two
# directions, and they are not symmetric:
#
#   backup OLDER than the live database  -> recoverable. The schema comes back behind the code;
#                                           Alembic migrates forward. Worth stating, not blocking.
#   backup NEWER than the live database  -> NOT recoverable by migration. Alembic does not
#                                           downgrade, so the schema would be ahead of the code that
#                                           has to serve it. Refused unless forced.
#
# A backup with no PROVENANCE.json predates this check. It is not refused -- refusing every older
# backup would be its own outage -- but the operator is told the check could not run, rather than
# being left to assume it did.
PROV="$SOURCE_DIR/PROVENANCE.json"
if [[ ! -f "$PROV" ]]; then
  log "WARNING: no PROVENANCE.json in this backup — the version compatibility check CANNOT run."
  log "         It was taken before backup.sh recorded provenance. Verify by hand which framework"
  log "         version produced it before trusting a restore into a different one."
else
  prov_get() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],''))" "$PROV" "$1" 2>/dev/null || true; }
  B_TAG="$(prov_get image_tag)"
  log "backup was produced by image_tag=${B_TAG:-unknown}; this deployment runs ${IMAGE_TAG:-unknown}"
  if [[ -n "$B_TAG" && -n "${IMAGE_TAG:-}" && "$B_TAG" != "$IMAGE_TAG" ]]; then
    log "NOTE: build differs. That alone is normal (a backup is usually older than the code);"
    log "      what matters is the per-database schema revision checked below."
  fi

  MISMATCH=0
  while IFS='|' read -r label b_rev; do
    [[ -z "$label" || "$b_rev" == "none" ]] && continue
    coords="$(coords_for_label "$label" 2>/dev/null)" || continue
    IFS='|' read -r c d u <<< "$coords"
    live_rev="$(docker exec "$c" psql -qtAX -U "$u" -d "$d" \
        -c "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null | tr -d '[:space:]' || true)"
    [[ -z "$live_rev" ]] && continue
    if [[ "$b_rev" == "$live_rev" ]]; then
      log "$label: schema revision matches ($b_rev)"
      continue
    fi
    # Is the backup's revision present in the live database's history? If the live head knows it,
    # the backup is an ancestor -> older -> migratable. If not, the backup is from a future the
    # running code has never heard of.
    if docker exec "$c" test -d /app/alembic/versions 2>/dev/null \
       && docker exec "$c" sh -c "grep -rlq '$b_rev' /app/alembic/versions" 2>/dev/null; then
      log "$label: backup schema $b_rev is OLDER than live $live_rev — Alembic can migrate forward."
      log "        Run the migrations job after this restore, or the code will serve an old schema."
    else
      echo "[restore] $label: backup schema '$b_rev' is NOT in this build's Alembic history" >&2
      echo "[restore]   (live revision is '$live_rev'). The backup is NEWER than the code that would" >&2
      echo "[restore]   serve it, and Alembic does not downgrade. Restore the matching build first." >&2
      MISMATCH=1
    fi
  done < <(python3 -c "
import json,sys
for db in json.load(open(sys.argv[1])).get('databases', []):
    print(f\"{db.get('label','')}|{db.get('alembic_revision','none')}\")" "$PROV" 2>/dev/null || true)

  if [[ "$MISMATCH" -eq 1 && "$FORCE_VERSION" -ne 1 ]]; then
    echo "[restore] Refusing to restore. Re-run with --force-version to override deliberately." >&2
    exit 1
  fi
  if [[ "$MISMATCH" -eq 1 ]]; then
    log "WARNING: --force-version given; restoring a schema this build cannot migrate."
  fi
fi

if [[ $ASSUME_YES -ne 1 ]]; then
  echo ""
  echo "About to OVERWRITE the current contents of these databases from $SOURCE_DIR:"
  for d in "${DUMPS[@]}"; do echo "  - $(basename "$d" .dump)"; done
  echo ""
  read -r -p "Type 'restore' to proceed: " answer
  [[ "$answer" == "restore" ]] || { log "aborted"; exit 1; }
fi

# Label -> "<container>|<db>|<user>". ONE definition, used by both the version pre-flight and the
# restore itself: two copies of this mapping is exactly how backup.sh and restore.sh both ended up
# pointing at the wrong container for Authentik and stayed wrong for weeks.
coords_for_label() {
  local label="$1" container db user upper db_var user_var
  case "$label" in
    hostapp)   container="${APP_SLUG}.hostapp.database"; db="${POSTGRES_DB:-}"; user="${POSTGRES_USER:-}" ;;
    # Authentik's own database service since the identity-plane split -- NOT hostapp.database.
    authentik) container="${APP_SLUG}.hostapp.authentik-database"; db="${AUTHENTIK_POSTGRES_DB:-authentik}"; user="${AUTHENTIK_POSTGRES_USER:-${POSTGRES_USER:-}}" ;;
    *)
      upper="$(echo "$label" | tr '[:lower:]' '[:upper:]')"
      container="${APP_SLUG}.${label}.database"
      db_var="${upper}_ENTITIES_DB_NAME"; user_var="${upper}_ENTITIES_DB_USER"
      db="${!db_var:-}"; user="${!user_var:-}"
      ;;
  esac
  if [[ -z "$db" || -z "$user" ]]; then
    echo "[restore] Unknown database config for '$label'" >&2
    return 1
  fi
  printf '%s|%s|%s' "$container" "$db" "$user"
}

# --- Dependency order: database up and healthy, then bootstrap, then backends ------------------
compose() { docker compose -f "$DEPLOY_ROOT/docker-compose.yml" "$@"; }

log "stopping backends so nothing writes during the restore"
compose stop backend template-backend 2>/dev/null || true

restore_one() {
  local label="$1" dump="$2" container db user
  local coords; coords="$(coords_for_label "$label")" || return 1
  IFS='|' read -r container db user <<< "$coords"

  log "waiting for $container to be accepting connections"
  local waited=0
  until docker exec "$container" pg_isready -U "$user" -d "$db" >/dev/null 2>&1; do
    sleep 2; waited=$((waited + 2))
    [[ $waited -ge 120 ]] && { echo "[restore] $container not ready after 120s" >&2; return 1; }
  done

  log "restoring $label into $db"

  # TimescaleDB needs its OWN restore procedure, and without it the restore silently loses
  # constraints. Measured on this stack: a plain pg_restore of the template database produced two
  # `ONLY option not supported on hypertable operations` errors and left the versioning tables with
  # ZERO primary keys -- a database that restores "successfully" and is not the one that was backed
  # up. Wrapped in pre/post_restore: zero errors, both primary keys present, hypertables intact.
  #
  # These are Timescale's own functions and the supported mechanism for 2.x. (The standalone
  # `timescaledb-backup` binary was archived upstream, so this is that decision's current form.)
  # pre_restore turns off the background workers and the extension's DDL hooks; post_restore turns
  # them back on and MUST run even if the restore fails, or the database is left with its
  # scheduler disabled.
  local has_ts
  has_ts="$(docker exec "$container" psql -qtAX -U "$user" -d "$db" \
      -c "SELECT 1 FROM pg_extension WHERE extname='timescaledb';" 2>/dev/null | tr -d '[:space:]' || true)"

  if [[ "$has_ts" == "1" ]]; then
    log "$label: timescaledb present — using timescaledb_pre_restore/post_restore"
    docker exec "$container" psql -qtAX -U "$user" -d "$db" -c "SELECT timescaledb_pre_restore();" >/dev/null
  fi

  local rc=0
  # --clean --if-exists drops the existing objects inside the dump's scope. NOT
  # --single-transaction when Timescale is involved: pre_restore's effect is per-session and
  # pg_restore runs its own, so the wrapping only works with the default multi-statement mode.
  if [[ "$has_ts" == "1" ]]; then
    docker exec -i "$container" pg_restore --clean --if-exists --no-owner \
        -U "$user" -d "$db" < "$dump" || rc=$?
    # `|| true` on purpose: a failed post_restore must not mask the restore's own status, but it
    # must still be attempted, because skipping it leaves the scheduler off.
    docker exec "$container" psql -qtAX -U "$user" -d "$db" -c "SELECT timescaledb_post_restore();" >/dev/null || true
  else
    # single-transaction where it is safe: a mid-way failure rolls back instead of leaving a
    # half-restored database.
    docker exec -i "$container" pg_restore --clean --if-exists --no-owner --single-transaction \
        -U "$user" -d "$db" < "$dump" || rc=$?
  fi
  return $rc
}

STATUS=0
for dump in "${DUMPS[@]}"; do
  label="$(basename "$dump" .dump)"
  [[ -n "$ONLY" && "$ONLY" != "$label" ]] && continue
  restore_one "$label" "$dump" || { echo "[restore] FAILED restoring $label" >&2; STATUS=1; }
done

log "starting bootstrap, then backends"
compose up -d 2>/dev/null || true

if [[ $STATUS -ne 0 ]]; then
  echo "[restore] Completed with errors — check the output above before trusting this system." >&2
  exit 1
fi
log "OK — restored from $SOURCE_DIR"
