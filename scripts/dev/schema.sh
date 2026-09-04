#!/usr/bin/env bash
# Schema workflow: design → model → migration → verify.
#
# One rule underlies every command here: THE MODEL IS THE SCHEMA, AND ONLY ALEMBIC WRITES IT.
# A design tool draws, sqlacodegen transcribes, Alembic applies. Nothing else may create, alter
# or drop a table — not the bootstrap job, not `create_all()`, not a GUI connected to a live
# database. When two things own a schema they drift, silently, and the drift is only discovered
# when something breaks in production.
#
# Every command works on THROWAWAY databases, never on the deployed one:
#
#   <db>_design   what the schema should become — the design tool's canvas.
#   <db>_head     what the committed migrations say the schema is right now.
#   <db>_verify   a scratch database for the acceptance gates.
#
# The deployed database is read (for a data-fidelity check) but never written. That guardrail is
# not theoretical: a downgrade run against a live database during this task destroyed a table.
#
# Usage:
#   scripts/dev/schema.sh design    [module]   # materialise <db>_design; print the import recipe
#   scripts/dev/schema.sh model     [module]   # sqlacodegen <db>_design → candidate models.py
#   scripts/dev/schema.sh migration [module] -m "message"   # autogenerate against <db>_head
#   scripts/dev/schema.sh verify    [module]   # the acceptance gates (what CI runs)
#   scripts/dev/schema.sh schema-sql[module]   # regenerate the derived full-schema SQL
#   scripts/dev/schema.sh squash    [module]   # maintainer: collapse versions/ into a baseline
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# --- This runs inside the dev tools container ---------------------------------------------------
#
# Re-exec once, at the top, rather than wrapping each alembic / sqlacodegen / psql call below. The
# schema workflow is the sharpest case for a standard toolchain: `alembic` autogenerate compares a
# model tree against a live database and WRITES a migration from the difference, so a different
# alembic or SQLAlchemy version does not fail — it writes a different migration, which is then
# committed and applied everywhere.
#
# `IDEABLE_IN_TOOL_CONTAINER=1` is set by the image, so this is not recursive. `IDEABLE_NO_CONTAINER=1`
# runs on the host toolchain, for a broken Docker.
if [[ "${IDEABLE_IN_TOOL_CONTAINER:-0}" != "1" && "${IDEABLE_NO_CONTAINER:-0}" != "1" ]]; then
  if [[ ! -x "${REPO_ROOT}/scripts/dev/tool.sh" ]]; then
    echo "scripts/dev/tool.sh is missing — it is how this project obtains its toolchain." >&2
    exit 1
  fi
  exec "${REPO_ROOT}/scripts/dev/tool.sh" bash "${REPO_ROOT}/scripts/dev/schema.sh" "$@"
fi

MODULE="${2:-module_template}"
[[ "${MODULE}" == -* ]] && MODULE="module_template"
BACKEND="${REPO_ROOT}/modules/${MODULE}/backend/SOURCES"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
info() { echo "${BOLD}==>${NC} $*"; }
ok()   { echo "${GREEN}✔${NC} $*"; }
warn() { echo "${YELLOW}!${NC} $*"; }
die()  { echo "${RED}✗${NC} $*" >&2; exit 1; }

[[ -d "${BACKEND}/alembic" ]] || die "no alembic/ in ${BACKEND} — module '${MODULE}' has no migrations yet"

# --- locating the running stack ---------------------------------------------------------------
# The module's own Postgres container hosts the scratch databases: no extra service to run, and
# they are dropped when the command finishes.
#
# The module slug is the directory name without the `module_` prefix and without underscores:
# module_template → template, host_app → hostapp.
SLUG="$(echo "${MODULE#module_}" | tr -d '_')"

# Non-replicable services keep the fixed name ${APP_SLUG}.${MODULE_SLUG}.<service>, so the database
# is still found by name.
DB_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E "\.${SLUG}\.database$" | head -1 || true)"
[[ -n "${DB_CONTAINER}" ]] || die "no running database container for '${MODULE}' (looked for *.${SLUG}.database) — start the stack first"

# The BACKEND is found by IMAGE, not by container name. The horizontal-scale work removed `container_name` from the
# replicable services — a container name is unique, so a second replica collided on it — and Compose
# now names them `<project>-<service>-<n>` (e.g. `ideable-backend-1`). Matching on the old fixed name
# therefore never succeeded again, which broke every schema.sh command for both modules.
#
# The image name is the stable identifier: `{MODULE_SLUG}.<submodule>` is a documented
# convention (rules/general-guidelines.md § "Docker image naming convention"), and it survives both
# the rename and any number of replicas. The registry prefix is tolerated for remote-built modules.
BACKEND_CONTAINER="$(docker ps --format '{{.Names}}\t{{.Image}}' \
  | awk -F'\t' -v slug="${SLUG}" '$2 ~ ("(^|/)" slug "\\.backend(:|$)") {print $1; exit}')"
if [[ -z "${BACKEND_CONTAINER}" ]]; then
  # Legacy fallback: a deployment still pinning the fixed container name.
  BACKEND_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E "\.${SLUG}\.backend$" | head -1 || true)"
fi
[[ -n "${BACKEND_CONTAINER}" ]] || die "no running backend container for '${MODULE}' (looked for image *${SLUG}.backend) — its image is needed to run alembic"

DB_USER="$(docker exec "${DB_CONTAINER}" printenv POSTGRES_USER)"
DB_NAME="$(docker exec "${DB_CONTAINER}" printenv POSTGRES_DB)"
DB_PASS="$(docker exec "${DB_CONTAINER}" printenv POSTGRES_PASSWORD)"
DB_HOST="$(docker inspect "${DB_CONTAINER}" --format '{{index .Config.Labels "com.docker.compose.service"}}')"
# A container can be on several networks; alembic needs exactly one to attach to, and any
# network that reaches the database will do.
NETWORK="$(docker inspect "${DB_CONTAINER}" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | head -1)"
IMAGE="$(docker inspect "${BACKEND_CONTAINER}" --format '{{.Config.Image}}')"

psql_() { docker exec -e PGPASSWORD="${DB_PASS}" "${DB_CONTAINER}" psql -qtA -U "${DB_USER}" "$@"; }

url_for() { echo "postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:5432/$1"; }

# Run a command inside the backend image with the WORKING TREE mounted, so the sources on disk
# are what runs — not whatever was baked into the last image build.
#
# The environment is inherited from the RUNNING backend container: importing the models pulls in
# the application settings, and a backend whose config requires (say) AUTHENTIK_JWKS_URL will
# refuse to import without it. Only DATABASE_URL is overridden — that is the whole point.
ENV_FILE="$(mktemp)"
trap 'rm -f "${ENV_FILE}"' EXIT
docker inspect "${BACKEND_CONTAINER}" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -v "^DATABASE_URL=" | grep -v "^$" > "${ENV_FILE}"

in_backend() {
  local db="$1"; shift
  # `--entrypoint python` and `-m` for the first argument: the backend image is distroless and has
  # no console-script directory on PATH, so a bare `alembic` is `executable file not found`. Every
  # call site here passes `alembic …`, and this is the one place that has to know how to reach it.
  #
  # This broke in the non-root image work, when the runtime moved to distroless, and stayed broken because nothing
  # runs schema.sh in the suite — it was found while proving the typed-model migration's migration was schema-neutral.
  local prog="$1"; shift
  docker run --rm --network "${NETWORK}" \
    --env-file "${ENV_FILE}" -e DATABASE_URL="$(url_for "${db}")" \
    -v "${BACKEND}/alembic.ini:/app/alembic.ini" \
    -v "${BACKEND}/alembic:/app/alembic" \
    -v "${BACKEND}/app:/app/app" \
    -w /app --entrypoint python "${IMAGE}" -m "${prog}" "$@"
}

recreate_db() {
  psql_ -d postgres -c "DROP DATABASE IF EXISTS $1;" >/dev/null
  psql_ -d postgres -c "CREATE DATABASE $1;" >/dev/null
}

drop_db() { psql_ -d postgres -c "DROP DATABASE IF EXISTS $1;" >/dev/null 2>&1 || true; }

# ================================================================================================
case "${1:-}" in

design)
  # PHASE 1. Materialise the current schema in a database the design tool may freely modify.
  # It is built from the migrations rather than copied from production on purpose: production may
  # carry drift no migration describes, and importing that drift into a design would launder it
  # into the next migration.
  recreate_db "${DB_NAME}_design"
  in_backend "${DB_NAME}_design" alembic upgrade head >/dev/null
  ok "${DB_NAME}_design is at head and ready to edit"
  cat <<EOF

  ${BOLD}Design it${NC}
    ChartDB (self-hosted)  — import by pasting the output of its schema query, run against:
        docker exec -e PGPASSWORD=… ${DB_CONTAINER} psql -U ${DB_USER} -d ${DB_NAME}_design
    Azimutt                — connect to ${DB_HOST}:5432/${DB_NAME}_design on network ${NETWORK}

  ${BOLD}Then apply your exported DDL to the design database${NC}, and continue with:
        scripts/dev/schema.sh model ${MODULE}

  Design ONLY the entity tables. The audit tables (*_version, transaction, transaction_meta) are
  generated by SQLAlchemy-Continuum from \`__versioned__\`; drawing them by hand would create a
  second, conflicting definition.
EOF
  ;;

model)
  # PHASE 2. Transcribe the designed database into SQLAlchemy models.
  command -v docker >/dev/null || die "docker is required"
  psql_ -d postgres -lqt | cut -d'|' -f1 | grep -qw "${DB_NAME}_design" \
    || die "${DB_NAME}_design does not exist — run 'schema.sh design ${MODULE}' first"

  # Exclude everything the developer does not own: Continuum's shadow tables (generated from the
  # model, so transcribing them would produce classes that collide with the generated ones),
  # Alembic's bookkeeping, and the framework tables that live in framework_models.py.
  TABLES="$(psql_ -d "${DB_NAME}_design" -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT LIKE '%_version' AND tablename NOT IN ('transaction','transaction_meta','alembic_version','module_bootstrap_execution','module_runtime_meta') ORDER BY 1;" | paste -sd, -)"
  [[ -n "${TABLES}" ]] || die "no entity tables found in ${DB_NAME}_design"
  info "transcribing: ${TABLES}"

  OUT="${BACKEND}/app/models.generated.py"
  docker run --rm --network "${NETWORK}" "${IMAGE}" sh -c \
    "pip install -q sqlacodegen >/dev/null 2>&1 && sqlacodegen '$(url_for "${DB_NAME}_design")' --tables ${TABLES}" > "${OUT}"

  ok "wrote ${OUT#"${REPO_ROOT}/"}"
  cat <<EOF

  ${BOLD}This is a candidate, not a replacement.${NC} Merge it into app/models.py by hand and keep:
    • \`__versioned__ = {}\` on audited entities   (sqlacodegen cannot know about Continuum)
    • singular class names                        (it pluralises: TemplateItems → TemplateItem)
    • the explanatory comments                    (it drops all of them)

  Diff:  diff -u modules/${MODULE}/backend/SOURCES/app/models.py ${OUT#"${REPO_ROOT}/"}
  Then:  scripts/dev/schema.sh migration ${MODULE} -m "your message"
EOF
  ;;

migration)
  # PHASE 3. The delta. This needs TWO states at once — the model (desired) and <db>_head
  # (current) — which is why it cannot run against the design database: a model transcribed from
  # <db>_design and diffed against <db>_design agrees with itself and yields an empty migration.
  MSG=""
  while [[ $# -gt 0 ]]; do case "$1" in -m) MSG="$2"; shift 2;; *) shift;; esac; done
  [[ -n "${MSG}" ]] || die 'a message is required:  schema.sh migration '"${MODULE}"' -m "add item status"'

  recreate_db "${DB_NAME}_head"
  in_backend "${DB_NAME}_head" alembic upgrade head >/dev/null
  info "${DB_NAME}_head built from committed migrations"

  BEFORE="$(find "${BACKEND}/alembic/versions" -name '*.py' | wc -l | tr -d ' ')"
  in_backend "${DB_NAME}_head" alembic revision --autogenerate -m "${MSG}"
  AFTER="$(find "${BACKEND}/alembic/versions" -name '*.py' | wc -l | tr -d ' ')"
  drop_db "${DB_NAME}_head"

  if [[ "${AFTER}" == "${BEFORE}" ]]; then
    warn "no migration written — the model already matches the committed migrations"
    exit 0
  fi
  NEW="$(find "${BACKEND}/alembic/versions" -name '*.py' -exec ls -t {} + | head -1)"
  ok "wrote ${NEW#"${REPO_ROOT}/"}"
  cat <<EOF

  ${BOLD}Review it before committing.${NC} Autogenerate detects structure, never intent:
    • it cannot know a column needs backfilling — add \`op.execute(...)\` for the data
    • it renders a rename as drop+add, which loses the data. Rewrite those by hand.
    • the migration MUST be unconditional. Only the baseline may branch on what exists.

  Read the SQL it will run:  alembic upgrade <previous-revision>:head --sql
  Then:                      scripts/dev/schema.sh verify ${MODULE}
EOF
  ;;

verify)
  # PHASE 4. The gates. Cheap enough (~1s) to run on every push.
  FAILED=0

  info "gate 1 — a fresh database reaches the schema the model describes"
  recreate_db "${DB_NAME}_verify"
  if in_backend "${DB_NAME}_verify" alembic upgrade head >/dev/null 2>&1; then
    if in_backend "${DB_NAME}_verify" alembic check 2>&1 | grep -q "No new upgrade operations"; then
      ok "fresh install: upgrade head + alembic check clean"
    else
      echo "${RED}✗${NC} fresh install: model and migrations disagree —"
      in_backend "${DB_NAME}_verify" alembic check 2>&1 | grep -i "detected\|error" | sed 's/^/    /' || true
      FAILED=1
    fi
  else
    echo "${RED}✗${NC} fresh install: 'alembic upgrade head' failed"
    in_backend "${DB_NAME}_verify" alembic upgrade head 2>&1 | tail -5 | sed 's/^/    /'
    FAILED=1
  fi

  # Every table the model declares must exist. Gate 1 alone would not have caught the real bug
  # this workflow was written after: a baseline that silently skipped the audit tables still
  # passed `alembic check`, because check compares what it can see.
  MISSING="$(psql_ -d "${DB_NAME}_verify" -c "SELECT count(*) FROM (VALUES ('transaction'),('transaction_meta')) AS t(n) WHERE n NOT IN (SELECT tablename FROM pg_tables WHERE schemaname='public');" 2>/dev/null || echo 1)"
  if [[ "${MISSING}" == "0" ]]; then ok "audit trail tables present"; else
    echo "${RED}✗${NC} audit trail tables missing from a fresh install"; FAILED=1; fi
  drop_db "${DB_NAME}_verify"

  info "gate 2 — real data survives the migration"
  # Row counts for every table, so this gate is not tied to one module's entity. alembic_version
  # is excluded: the migration is supposed to change it.
  ROWCOUNTS_SQL="SELECT coalesce(string_agg(t||':'||c, ', ' ORDER BY t),'(no tables)') FROM (
      SELECT table_name AS t,
             (xpath('/row/cnt/text()', query_to_xml(format('SELECT count(*) AS cnt FROM %I.%I','public',table_name), false, true, '')))[1]::text::bigint AS c
        FROM information_schema.tables
       WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name <> 'alembic_version') s;"

  BEFORE_ROWS="$(psql_ -d "${DB_NAME}" -c "${ROWCOUNTS_SQL}" 2>/dev/null || echo skip)"
  if [[ "${BEFORE_ROWS}" == "skip" ]]; then
    warn "deployed database not readable — data-fidelity gate skipped"
  else
    recreate_db "${DB_NAME}_verify"
    docker exec -e PGPASSWORD="${DB_PASS}" "${DB_CONTAINER}" \
      sh -c "pg_dump -U ${DB_USER} -d ${DB_NAME} | psql -q -U ${DB_USER} -d ${DB_NAME}_verify" >/dev/null 2>&1
    if in_backend "${DB_NAME}_verify" alembic upgrade head >/dev/null 2>&1; then
      AFTER_ROWS="$(psql_ -d "${DB_NAME}_verify" -c "${ROWCOUNTS_SQL}")"
      # Compare PER TABLE, over the tables that existed before.
      #
      # This used to compare the two listings as one string, so any migration that ADDED a table
      # failed the gate — the most common kind of migration, and one that cannot lose data by
      # existing. The spec's requirement is "row counts unchanged per table"; a new table is not a
      # changed count. New tables are reported instead, with their counts, because a new table
      # arriving with rows is a backfill: intended, but something the reviewer should see.
      FIDELITY="$(BEFORE="${BEFORE_ROWS}" AFTER="${AFTER_ROWS}" python3 - <<'PYFIDELITY'
import os, sys


def parse(text):
    text = text.strip()
    if not text or text == "(no tables)":
        return {}
    counts = {}
    for part in text.split(","):
        part = part.strip()
        if ":" in part:
            name, _, count = part.rpartition(":")
            counts[name.strip()] = count.strip()
    return counts


before = parse(os.environ["BEFORE"])
after = parse(os.environ["AFTER"])

changed = []
for table in sorted(before):
    was, now = before[table], after.get(table, "MISSING")
    if was != now:
        changed.append(table + ": " + was + " -> " + now)

added = [t + ":" + after[t] for t in sorted(set(after) - set(before))]

if changed:
    print("CHANGED " + "; ".join(changed))
    sys.exit(1)

summary = str(len(before)) + " pre-existing tables unchanged"
if added:
    summary += "; new: " + ", ".join(added)
print("OK " + summary)
PYFIDELITY
)"
      if [[ "${FIDELITY}" == OK* ]]; then
        ok "data fidelity: ${FIDELITY#OK }"
      else
        echo "${RED}✗${NC} DATA CHANGED by the migration"
        echo "    ${FIDELITY#CHANGED }"
        FAILED=1
      fi
      # A deployed database that adopts the migrations must end up matching the model too,
      # otherwise the next autogenerate silently folds today's drift into tomorrow's migration.
      if in_backend "${DB_NAME}_verify" alembic check 2>&1 | grep -q "No new upgrade operations"; then
        ok "deployed schema matches the model after upgrade"
      else
        echo "${RED}✗${NC} deployed database still differs from the model after upgrade:"
        in_backend "${DB_NAME}_verify" alembic check 2>&1 | grep -i "detected" | sed 's/^/    /' || true
        FAILED=1
      fi
    else
      echo "${RED}✗${NC} migrations do not apply to a copy of the deployed database"
      in_backend "${DB_NAME}_verify" alembic upgrade head 2>&1 | tail -5 | sed 's/^/    /'
      FAILED=1
    fi
    drop_db "${DB_NAME}_verify"
  fi

  [[ "${FAILED}" == "0" ]] || die "schema verification failed"
  ok "schema verified"
  ;;

schema-sql)
  # The readable whole-schema SQL for a fresh installation — derived from the migrations, never
  # the other way round. This is what datamodel.sql used to be, minus the second-owner problem.
  #
  # Produced by applying the migrations to an empty database and dumping the result, NOT by
  # `alembic upgrade head --sql`: offline mode cannot inspect a database, so it silently skips
  # the conditional branches in the baseline and emits an almost-empty script.
  # SPECS, because this is a specification rather than a source: SOURCES/ holds build inputs
  # (and is gitignored + rebuilt for some sub-modules), DIST/ holds deploy artifacts. Nothing
  # applies this file, so it is never copied to DIST/ or deployment_root either.
  OUT="${REPO_ROOT}/modules/${MODULE}/database/SPECS/schema.sql"
  recreate_db "${DB_NAME}_schemagen"
  in_backend "${DB_NAME}_schemagen" alembic upgrade head >/dev/null
  {
    echo "-- GENERATED — DO NOT EDIT, AND NOTHING APPLIES THIS FILE."
    echo "--"
    echo "-- The schema of a fresh installation: the Alembic migrations applied to an empty"
    echo "-- database and dumped, for reading and review. Alembic applies the schema (see the"
    echo "-- module's migrations job); this file is a derived artifact. Editing it changes"
    echo "-- nothing, and re-adding DDL that Alembic does not know about is how deployed"
    echo "-- databases drifted from the repository before."
    echo "--"
    echo "-- Regenerate:  scripts/dev/schema.sh schema-sql ${MODULE}"
    echo ""
    docker exec -e PGPASSWORD="${DB_PASS}" "${DB_CONTAINER}" \
      pg_dump --schema-only --no-owner --no-privileges -U "${DB_USER}" -d "${DB_NAME}_schemagen" \
      | grep -v "^--$" | grep -v "^-- Dumped\|^-- PostgreSQL database dump"
  } > "${OUT}"
  drop_db "${DB_NAME}_schemagen"
  ok "wrote ${OUT#"${REPO_ROOT}/"}"
  ;;

squash)
  # Maintainer operation: replace an accumulated history with a single baseline describing the
  # same end state. Deployed databases must be stamped at the new baseline afterwards — they
  # already have the schema, so re-running it would fail.
  cat <<EOF
  ${BOLD}Squashing ${MODULE}'s migrations${NC}

  1. Build the end state:      scripts/dev/schema.sh design ${MODULE}
  2. Render it:                cd ${BACKEND#"${REPO_ROOT}/"} && alembic upgrade head --sql > /tmp/schema.sql
  3. Remove alembic/versions/*.py and write ONE baseline with down_revision = None, creating
     each table conditionally (copy the shape of the current baseline).
  4. Prove it:                 scripts/dev/schema.sh verify ${MODULE}
  5. For every deployed database, stamp it so it is not re-applied:
         alembic stamp <new-revision-id>
     ${YELLOW}Step 5 is not optional${NC} — an unstamped database will try to create tables it has.
EOF
  ;;

*)
  sed -n '3,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
  ;;
esac
