#!/bin/bash
# Build script for the module_template database sub-module.
# Materializes SPECS SQL into SOURCES/initdb/ and copies SOURCES/initdb/ into DIST/initdb/.
# Referenced from: modules/module_template/database/SPECS/ideable-framework-specs/base-specs.md (Build section)
# Called by: scripts/common/build_and_deploy.py via sub-module SPECS convention

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Guard: skip if running inside a database container (docker-entrypoint-initdb.d)
# This script is meant to run during the host build phase, not inside the container.
if [[ "$SCRIPT_DIR" == "/docker-entrypoint-initdb.d" ]] || [[ "$SCRIPT_DIR" == *"/docker-entrypoint-initdb.d" ]]; then
    echo "  [database] build.sh: skipping — running inside container init context"
    exit 0
fi

SUBMODULE_DIR="$(dirname "$SCRIPT_DIR")"
SPECS_DIR="$SUBMODULE_DIR/SPECS"
SOURCES_INITDB_DIR="$SUBMODULE_DIR/SOURCES/initdb"
DIST_INITDB_DIR="$SUBMODULE_DIR/DIST/initdb"

echo "  [module_template/database] Building: $SPECS_DIR -> $SOURCES_INITDB_DIR -> $DIST_INITDB_DIR"

rm -rf "$SUBMODULE_DIR/DIST" "$SUBMODULE_DIR/SOURCES"
mkdir -p "$SOURCES_INITDB_DIR" "$DIST_INITDB_DIR"

cp "$SPECS_DIR/datamodel.sql" "$SOURCES_INITDB_DIR/datamodel.sql"
cp "$SPECS_DIR/seed.sql" "$SOURCES_INITDB_DIR/seed.sql"

for item in "$SOURCES_INITDB_DIR"/*; do
    [ -e "$item" ] || continue
    cp -r "$item" "$DIST_INITDB_DIR/"
done

find "$DIST_INITDB_DIR" -name "*.sh" -exec chmod +x {} \;

echo "  [module_template/database] Done. Files in $DIST_INITDB_DIR:"
ls "$DIST_INITDB_DIR"
