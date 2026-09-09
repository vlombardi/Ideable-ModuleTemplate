FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS build

WORKDIR /app

# The build context is the frontend SOURCES. It carries package.json AND the committed
# package-lock.json, and no node_modules. It does NOT carry `.ideable-ui`: that is a tracked
# symlink for local development, excluded by .dockerignore because a symlink pointing four
# levels above a SOURCES-rooted context is dangling here. The real directory is created by
# the COPY below.
COPY . .

# Pull the shared @ideable/ui package from the `ideable_ui` named build context —
# passed via `--build-context ideable_ui=<repo>/reusable.ui` by SPECS/build.sh
# (local build) and the registry-push buildx call. A repo-root sibling is otherwise
# outside this SOURCES-rooted context; reusable.ui/.dockerignore keeps node_modules
# and generated files out of what is copied.
COPY --from=ideable_ui . ./.ideable-ui

# Install EXACTLY what the committed lockfile pins. `npm ci` never consults a version range, so
# rebuilding this commit rebuilds these versions -- which is what makes the image tag an
# identity rather than a label. It also fails loudly if package.json and the lock disagree, instead
# of silently re-resolving.
#
# There is no `sed` and no `rm -f package-lock.json` here any more, and their absence is the point:
#
#   package.json declares `file:./.ideable-ui`, the same path in this image and in a developer's
#   clone (where `.ideable-ui` is a tracked symlink to the repo-root reusable.ui). npm NORMALISES
#   `file:` paths when it writes the lock, so the old `file:../../../../reusable.ui` produced
#   `file:../reusable.ui` here and `file:../../../../reusable.ui` on the host -- two locks that
#   could never match. `./.ideable-ui` has no depth to normalise away; both sides record
#   `file:.ideable-ui` and the lockfiles are byte-identical (measured).
#
#   The old rewrite is exactly why the lockfile had to be deleted: it desynchronised package.json
#   from the lock on every build, and `npm install` with a stale lock plus a `file:` dep crashes
#   with "Cannot read properties of undefined (reading 'extraneous')" (reproduced).
#
# --install-links stays: it COPIES @ideable/ui instead of symlinking it, which is native-safe.
RUN npm ci --install-links --legacy-peer-deps

# Only genuinely compile-time flags remain build args. Environment VALUES (API URLs, titles,
# OIDC endpoints) are supplied at container start by docker-entrypoint.sh, so the same image runs
# in every environment — baking them in produced one image per environment and meant the artefact
# validated in staging was never the one that reached production.
# WIDGET_EXAMPLES=false excludes the dev-only Widget Examples gallery (+ Recharts) from the
# published bundle; it drives tree-shaking, so it must stay compile-time.
ARG WIDGET_EXAMPLES=true

ENV WIDGET_EXAMPLES=$WIDGET_EXAMPLES

RUN npm run build

# Production stage
# nginx-unprivileged: runs as uid 101, listens on an unprivileged port, and keeps its pid and temp
# paths under /tmp -- which is what makes `read_only: true` possible without patching nginx.conf's
# every *_temp_path.
FROM nginxinc/nginx-unprivileged:alpine@sha256:901e944d1f4fc2bd077e8f5568b98c1f6f8cdacf6b97a87747c43134a339b9a7

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
# `--chmod` rather than a `RUN chmod`: the image runs as a non-root user that cannot chmod files
# owned by root, and a separate RUN adds a layer for nothing.
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

EXPOSE 8080

# Writes /env-config.js from the container environment, then execs nginx.
CMD ["/docker-entrypoint.sh"]
