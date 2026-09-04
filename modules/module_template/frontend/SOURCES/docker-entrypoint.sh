#!/bin/sh
# Generate the runtime env config consumed by getEnv() (src/config/oidc.ts reads window.__ENV__
# before falling back to build-time values).
#
# This is what makes ONE image promotable across environments: the values come from the
# container's environment at start, so changing an API URL is an .env.config edit plus a restart,
# not a rebuild. Baking VITE_* in at build time produced one image per environment and meant the
# artefact validated in staging was never the artefact that ran in production.
#
# Every VITE_* variable present in the environment is emitted, so a module that adds one needs no
# change here. Values are escaped for JS string context.
set -e

# /tmp, not the html root: the root filesystem is read-only. nginx serves this
# path through a `location = /env-config.js` alias, so the URL is unchanged.
OUT=/tmp/env-config.js
echo "window.__ENV__ = {" > "$OUT"
env | grep '^VITE_' | sort | while IFS='=' read -r key value; do
  escaped=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')
  echo "  \"$key\": \"$escaped\"," >> "$OUT"
done
echo "};" >> "$OUT"

exec nginx -g "daemon off;"
