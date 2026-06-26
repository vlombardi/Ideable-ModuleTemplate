#!/usr/bin/env sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT format('CREATE DATABASE %I', 'authentik')
WHERE NOT EXISTS (
  SELECT 1 FROM pg_database WHERE datname = 'authentik'
)\gexec
SQL
