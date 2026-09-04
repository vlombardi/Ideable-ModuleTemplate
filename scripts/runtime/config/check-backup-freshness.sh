#!/usr/bin/env bash
# Alarm when no recent backup exists.
# Usage: ./scripts/runtime/config/check-backup-freshness.sh [--max-age-hours N]
#
# A backup job that stops running fails silently: the last backup simply gets older, and nobody
# notices until a restore is needed. This is the check that turns that into a loud failure — run
# it from cron on a different schedule than backup.sh itself.
set -euo pipefail

MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"   # nightly RPO 24h + 2h of slack
while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-age-hours) MAX_AGE_HOURS="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--max-age-hours N]"
      echo ""
      echo "Exits non-zero if the newest backup is older than N hours (default 26, i.e. the 24h"
      echo "RPO plus slack), or if there is no backup at all."
      echo ""
      echo "Environment: BACKUP_DIR, BACKUP_MAX_AGE_HOURS"
      exit 0 ;;
    *) echo "Unknown option: $1 (use --help)" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/../.env.config" ]]; then
  DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  DEPLOY_ROOT="$(cd "$SCRIPT_DIR/../../../deployment_root" && pwd)"
fi
BACKUP_ROOT="${BACKUP_DIR:-$DEPLOY_ROOT/backups}"

latest="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1 || true)"
if [[ -z "$latest" ]]; then
  echo "[backup-freshness] CRITICAL: no backup found under $BACKUP_ROOT" >&2
  exit 1
fi

# A directory with no manifest is an interrupted run, not a backup.
if [[ ! -f "$latest/MANIFEST.sha256" ]]; then
  echo "[backup-freshness] CRITICAL: newest backup $(basename "$latest") has no manifest — the run did not finish" >&2
  exit 1
fi

now=$(date '+%s')
mtime=$(date -r "$latest/MANIFEST.sha256" '+%s' 2>/dev/null || stat -c %Y "$latest/MANIFEST.sha256")
age_hours=$(( (now - mtime) / 3600 ))

if [[ $age_hours -gt $MAX_AGE_HOURS ]]; then
  echo "[backup-freshness] CRITICAL: newest backup $(basename "$latest") is ${age_hours}h old (limit ${MAX_AGE_HOURS}h)" >&2
  exit 1
fi
echo "[backup-freshness] OK — newest backup $(basename "$latest") is ${age_hours}h old (limit ${MAX_AGE_HOURS}h)"
