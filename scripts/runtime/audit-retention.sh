#!/usr/bin/env bash
# Apply the audit compression and retention policies from environment settings.
#
# The policies live here, not in a migration, so changing how long audit history stays online is a
# configuration change a deployer makes — not a code change requiring a new migration and a
# release. The schema (hypertables) is Alembic's; the policy is the deployment's.
#
# Idempotent: each policy is removed and re-added, so running it on every deploy converges to
# whatever the environment currently says.
#
#   AUDIT_COMPRESS_AFTER   compress chunks older than this        (default: 90 days; "" disables)
#   AUDIT_RETAIN_FOR       drop chunks older than this            (default: "" — nothing dropped)
#   AUDIT_ARCHIVE_DIR      export expiring chunks here first      (default: "" — no archive)
#
# RETENTION DELETES DATA. It stays off unless AUDIT_RETAIN_FOR is set, and refuses to run at all
# unless an archive directory is configured or the operator explicitly opts out with
# AUDIT_ARCHIVE_OPTOUT=1 — "we keep everything" is a safer default than silent deletion, and a
# retention policy that runs before archival is verified is data loss with a schedule.
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

COMPRESS_AFTER="${AUDIT_COMPRESS_AFTER-90 days}"
RETAIN_FOR="${AUDIT_RETAIN_FOR-}"
ARCHIVE_DIR="${AUDIT_ARCHIVE_DIR-}"
HYPERTABLES=(transaction template_items_version)

psql_() { docker exec -e PGPASSWORD="${DB_PASSWORD}" "${DB_CONTAINER}" psql -qtA -U "${DB_USER}" -d "${DB_NAME}" "$@"; }

DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E "\.template\.database$" | head -1 || true)"
[[ -n "${DB_CONTAINER}" ]] || { echo "ERROR: template database container not running" >&2; exit 1; }
DB_USER="$(docker exec "${DB_CONTAINER}" printenv POSTGRES_USER)"
DB_NAME="$(docker exec "${DB_CONTAINER}" printenv POSTGRES_DB)"
DB_PASSWORD="$(docker exec "${DB_CONTAINER}" printenv POSTGRES_PASSWORD)"

for table in "${HYPERTABLES[@]}"; do
    if [[ "$(psql_ -c "SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='${table}';")" != "1" ]]; then
        echo "  skip ${table}: not a hypertable (has the partitioning migration run?)"
        continue
    fi

    # --- compression -------------------------------------------------------------------------
    psql_ -c "SELECT remove_compression_policy('${table}', if_exists => true);" >/dev/null
    if [[ -n "${COMPRESS_AFTER}" ]]; then
        # segmentby the entity id: history is always read per record, so grouping by it keeps a
        # single record's chunk reads together after compression.
        segment=$([[ "${table}" == *_version ]] && echo "id" || echo "")
        psql_ -c "ALTER TABLE ${table} SET (timescaledb.compress${segment:+, timescaledb.compress_segmentby = '$segment'});" >/dev/null
        psql_ -c "SELECT add_compression_policy('${table}', INTERVAL '${COMPRESS_AFTER}');" >/dev/null
        echo "  ${table}: compress after ${COMPRESS_AFTER}"
    else
        echo "  ${table}: compression disabled"
    fi

    # --- retention ---------------------------------------------------------------------------
    psql_ -c "SELECT remove_retention_policy('${table}', if_exists => true);" >/dev/null
    if [[ -z "${RETAIN_FOR}" ]]; then
        echo "  ${table}: retention disabled — nothing is dropped"
        continue
    fi
    if [[ -z "${ARCHIVE_DIR}" && "${AUDIT_ARCHIVE_OPTOUT:-0}" != "1" ]]; then
        echo "ERROR: AUDIT_RETAIN_FOR is set but AUDIT_ARCHIVE_DIR is not." >&2
        echo "       Dropping audit chunks without archiving them is data loss. Set an archive" >&2
        echo "       directory, or set AUDIT_ARCHIVE_OPTOUT=1 if deletion without a copy is" >&2
        echo "       genuinely intended." >&2
        exit 1
    fi
    if [[ -n "${ARCHIVE_DIR}" ]]; then
        mkdir -p "${ARCHIVE_DIR}"
        # Export what is about to expire BEFORE the policy can drop it, and checksum it, so
        # "archived" is a verifiable claim rather than an assumption.
        stamp="$(date +%Y-%m-%d-%H-%M-%S)"
        out="${ARCHIVE_DIR}/${table}-${stamp}.csv"
        psql_ -c "\\copy (SELECT * FROM ${table} WHERE issued_at < now() - INTERVAL '${RETAIN_FOR}') TO STDOUT WITH CSV HEADER" > "${out}"
        if [[ -s "${out}" ]]; then
            shasum -a 256 "${out}" > "${out}.sha256"
            echo "  ${table}: archived $(( $(wc -l < "${out}") - 1 )) expiring rows -> ${out}"
        else
            rm -f "${out}"
            echo "  ${table}: nothing past retention to archive"
        fi
    fi
    psql_ -c "SELECT add_retention_policy('${table}', INTERVAL '${RETAIN_FOR}');" >/dev/null
    echo "  ${table}: retain ${RETAIN_FOR}"
done

echo "Audit retention configuration applied."
