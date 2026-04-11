#!/bin/bash
# Build script for the ModuleTemplate database sub-module.
# Copies SOURCES/initdb/ into DIST/initdb/ and sets execute permissions on shell scripts.
# Referenced from: modules/ModuleTemplate/database/SPECS/base-specs.md (Build section)
# Called by: scripts/build_and_deploy.py via sub-module SPECS convention

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUBMODULE_DIR="$(dirname "$SCRIPT_DIR")"
SOURCES_INITDB_DIR="$SUBMODULE_DIR/SOURCES/initdb"
DIST_INITDB_DIR="$SUBMODULE_DIR/DIST/initdb"

echo "  [ModuleTemplate/database] Building: $SOURCES_INITDB_DIR -> $DIST_INITDB_DIR"

rm -rf "$SUBMODULE_DIR/DIST"
mkdir -p "$DIST_INITDB_DIR"

for item in "$SOURCES_INITDB_DIR"/*; do
    [ -e "$item" ] || continue
    cp -r "$item" "$DIST_INITDB_DIR/"
done

find "$DIST_INITDB_DIR" -name "*.sh" -exec chmod +x {} \;

echo "  [ModuleTemplate/database] Done. Files in $DIST_INITDB_DIR:"
ls "$DIST_INITDB_DIR"
