#!/bin/bash
# Build script for the ModuleTemplate database sub-module.
# Materializes SPECS SQL into SOURCES/initdb/ and copies SOURCES/initdb/ into DIST/initdb/.
# Referenced from: modules/ModuleTemplate/database/SPECS/base-specs.md (Build section)
# Called by: scripts/common/build_and_deploy.py via sub-module SPECS convention

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUBMODULE_DIR="$(dirname "$SCRIPT_DIR")"
SPECS_DIR="$SUBMODULE_DIR/SPECS"
SOURCES_INITDB_DIR="$SUBMODULE_DIR/SOURCES/initdb"
DIST_INITDB_DIR="$SUBMODULE_DIR/DIST/initdb"

echo "  [ModuleTemplate/database] Building: $SPECS_DIR -> $SOURCES_INITDB_DIR -> $DIST_INITDB_DIR"

rm -rf "$SUBMODULE_DIR/DIST" "$SUBMODULE_DIR/SOURCES"
mkdir -p "$SOURCES_INITDB_DIR" "$DIST_INITDB_DIR"

cp "$SPECS_DIR/datamodel.sql" "$SOURCES_INITDB_DIR/datamodel.sql"
cp "$SPECS_DIR/seed.sql" "$SOURCES_INITDB_DIR/seed.sql"

for item in "$SOURCES_INITDB_DIR"/*; do
    [ -e "$item" ] || continue
    cp -r "$item" "$DIST_INITDB_DIR/"
done

find "$DIST_INITDB_DIR" -name "*.sh" -exec chmod +x {} \;

echo "  [ModuleTemplate/database] Done. Files in $DIST_INITDB_DIR:"
ls "$DIST_INITDB_DIR"
