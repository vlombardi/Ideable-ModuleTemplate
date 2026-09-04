#!/usr/bin/env bash
# Prove a backup can actually be restored, without touching production.
# Usage: ./scripts/runtime/config/verify-backup.sh [--from <backup-dir>] [--keep]
#
# An untested backup is not a backup. This restores the latest (or given) backup into a THROWAWAY
# Postgres container — its own name, its own volume, no ports published, nothing shared with the
# running stack — runs sanity queries against it, and tears it down. Safe from cron.
set -euo pipefail

usage() {
    echo "Usage: $0 [--from <backup-dir>] [--keep] [-h|--help]"
    echo ""
    echo "Restores a backup into a disposable container and checks it holds real data."
    echo "Exits non-zero if the backup cannot be restored or looks empty."
    echo ""
    echo "Options:"
    echo "  --from <dir>  Backup directory (default: the most recent one)"
    echo "  --keep        Leave the throwaway container running for inspection"
    echo "  -h, --help    Show this help message"
}

SOURCE_DIR=""; KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) SOURCE_DIR="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1 (use --help)" >&2; exit 2 ;;
  esac
done

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
set +a
set -u

BACKUP_ROOT="${BACKUP_DIR:-$DEPLOY_ROOT/backups}"
if [[ -z "$SOURCE_DIR" ]]; then
  SOURCE_DIR="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d | sort | tail -1 || true)"
fi
[[ -n "$SOURCE_DIR" && -d "$SOURCE_DIR" ]] || { echo "[verify] No backup found under $BACKUP_ROOT" >&2; exit 1; }

log() { echo "[verify] $*"; }

log "verifying checksums of $(basename "$SOURCE_DIR")"
[[ -f "$SOURCE_DIR/MANIFEST.sha256" ]] || { echo "[verify] No MANIFEST.sha256 — backup is unverifiable." >&2; exit 1; }
( cd "$SOURCE_DIR" && shasum -a 256 -c MANIFEST.sha256 --quiet ) \
  || { echo "[verify] Checksum verification FAILED." >&2; exit 1; }

# Throwaway everything: distinct container name, no published port, ephemeral volume.
SCRATCH="verify-restore-$(date '+%s')"
IMAGE="timescale/timescaledb:${TIMESCALEDB_VERSION:-latest-pg16}"
SCRATCH_USER="verify"; SCRATCH_PASS="verify"; STATUS=0

cleanup() {
  if [[ $KEEP -eq 1 ]]; then
    log "leaving $SCRATCH running (--keep); remove it with: docker rm -f $SCRATCH"
  else
    docker rm -f "$SCRATCH" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

log "starting throwaway database ($SCRATCH)"
docker run -d --name "$SCRATCH" \
  -e POSTGRES_USER="$SCRATCH_USER" -e POSTGRES_PASSWORD="$SCRATCH_PASS" -e POSTGRES_DB=postgres \
  "$IMAGE" >/dev/null

waited=0
until docker exec "$SCRATCH" pg_isready -U "$SCRATCH_USER" -d postgres >/dev/null 2>&1; do
  sleep 2; waited=$((waited + 2))
  [[ $waited -ge 120 ]] && { echo "[verify] throwaway database never became ready" >&2; exit 1; }
done

for dump in "$SOURCE_DIR"/*.dump; do
  [[ -e "$dump" ]] || continue
  label="$(basename "$dump" .dump)"
  log "restoring $label"
  docker exec "$SCRATCH" psql -U "$SCRATCH_USER" -d postgres -c "CREATE DATABASE \"$label\";" >/dev/null 2>&1 || true

  # The rehearsal has to rehearse the REAL procedure, not a simpler one, or it proves the wrong
  # thing. restore.sh wraps Timescale-bearing databases in pre/post_restore; without the same
  # wrapping here the rehearsal would keep reporting the `ONLY option not supported` errors that
  # the real restore no longer produces -- failing on a defect that had been fixed, which erodes
  # trust in the check just as surely as passing on a real one.
  docker exec "$SCRATCH" psql -U "$SCRATCH_USER" -d "$label" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" >/dev/null 2>&1 || true
  has_ts="$(docker exec "$SCRATCH" psql -qtAX -U "$SCRATCH_USER" -d "$label" \
      -c "SELECT 1 FROM pg_extension WHERE extname='timescaledb';" 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ "$has_ts" == "1" ]]; then
    docker exec "$SCRATCH" psql -qtAX -U "$SCRATCH_USER" -d "$label" -c "SELECT timescaledb_pre_restore();" >/dev/null 2>&1 || true
  fi

  if ! docker exec -i "$SCRATCH" pg_restore --no-owner --dbname "$label" -U "$SCRATCH_USER" < "$dump" \
        >/dev/null 2>"/tmp/${SCRATCH}-${label}.log"; then
    # pg_restore's errors are CLASSIFIED, not waved through.
    #
    # This used to log "pg_restore reported issues" and carry on, with the only real check being
    # "did any table appear". That check passed on a restore that had failed to create primary keys
    # on the versioning hypertables and had lost a whole table's rows -- so the weekly rehearsal,
    # which docs/RUNBOOK.md calls "the only thing that proves the backup is usable", said
    # "OK - restores cleanly" about a backup that did not.
    #
    # The original reasoning was sound for WARNINGS and wrong for ERRORS: a bare throwaway instance
    # genuinely does lack the roles and extensions the source had, and complaining about that would
    # cry wolf every week until nobody read the output. So those two are named and tolerated, and
    # anything else -- a failed COPY (lost rows), a failed constraint or index (a restored database
    # that is not the one that was backed up) -- fails the rehearsal.
    errlog="/tmp/${SCRATCH}-${label}.log"
    # `grep -c` PRINTS 0 and EXITS 1 when it matches nothing, so `|| echo 0` appended a second zero
    # and the arithmetic below died on "0\n0". `|| true` keeps the printed count and swallows the
    # exit status.
    benign="$(grep -cE 'role "[^"]+" does not exist|extension "[^"]+" is not available|must be owner of' "$errlog" 2>/dev/null || true)"
    total="$(grep -cE '^pg_restore: error:' "$errlog" 2>/dev/null || true)"
    benign="${benign:-0}"; total="${total:-0}"
    serious=$((total - benign))
    if [[ "$serious" -gt 0 ]]; then
      echo "[verify] $label: $serious pg_restore error(s) that are NOT missing-role/extension noise." >&2
      grep -E '^pg_restore: error:' "$errlog" 2>/dev/null \
        | grep -vE 'role "[^"]+" does not exist|extension "[^"]+" is not available|must be owner of' \
        | head -5 | sed 's/^/[verify]   /' >&2
      echo "[verify]   full log: $errlog" >&2
      STATUS=1
    elif [[ "$total" -gt 0 ]]; then
      log "$label: $total pg_restore message(s), all missing-role/extension noise from the bare throwaway instance"
    fi
  fi

  if [[ "$has_ts" == "1" ]]; then
    docker exec "$SCRATCH" psql -qtAX -U "$SCRATCH_USER" -d "$label" -c "SELECT timescaledb_post_restore();" >/dev/null 2>&1 || true
  fi

  tables="$(docker exec "$SCRATCH" psql -tA -U "$SCRATCH_USER" -d "$label" \
      -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo 0)"
  if [[ "${tables:-0}" -lt 1 ]]; then
    echo "[verify] $label restored with NO tables — this backup would not bring the system back." >&2
    STATUS=1
  else
    log "$label: $tables table(s) restored"
  fi

  # Compare the restored SHAPE against what the backup recorded, not just "are there tables".
  #
  # "7 tables restored" was the old verdict on a restore that had silently dropped BOTH primary keys
  # from the versioning hypertables. Table count cannot see that; a constraint count can. The
  # expected numbers come from PROVENANCE.json, written by backup.sh at dump time against the live
  # database, so this compares the restore to its own source rather than to a hardcoded guess.
  if [[ -f "$SOURCE_DIR/PROVENANCE.json" ]]; then
    exp_pks="$(python3 -c "
import json,sys
for d in json.load(open(sys.argv[1])).get('databases', []):
    if d.get('label') == sys.argv[2]:
        print(d.get('primary_keys', ''))" "$SOURCE_DIR/PROVENANCE.json" "$label" 2>/dev/null || true)"
    if [[ -n "$exp_pks" && "$exp_pks" != "0" ]]; then
      got_pks="$(docker exec "$SCRATCH" psql -qtAX -U "$SCRATCH_USER" -d "$label" -c \
        "SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace n ON n.oid=r.relnamespace WHERE c.contype='p' AND n.nspname='public';" \
        2>/dev/null | tr -d '[:space:]' || true)"
      if [[ "${got_pks:-0}" -lt "$exp_pks" ]]; then
        echo "[verify] $label: $got_pks primary key(s) restored, but the backup was taken from a database with $exp_pks." >&2
        echo "[verify]   A restore that loses constraints is not a restore. This is what the" >&2
        echo "[verify]   TimescaleDB pre/post_restore wrapping exists to prevent." >&2
        STATUS=1
      else
        log "$label: $got_pks/$exp_pks primary key(s) present"
      fi
    fi
  fi
done

if [[ $STATUS -ne 0 ]]; then
  echo "[verify] FAILED — $(basename "$SOURCE_DIR") is not a usable backup." >&2
  exit 1
fi
log "OK — $(basename "$SOURCE_DIR") restores cleanly"
