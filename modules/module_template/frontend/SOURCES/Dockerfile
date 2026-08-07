FROM node:20-alpine AS build

WORKDIR /app

# The build context is staged by SPECS/build.sh: it contains the frontend SOURCES
# plus the shared @ideable/ui package at ./.ideable-ui (a sibling folder is
# otherwise outside this SOURCES-rooted context), with package.json's `@ideable/ui`
# file: dependency repointed at ./.ideable-ui. Neither carries node_modules.
COPY . .

# Pull the shared @ideable/ui package from the `ideable_ui` named build context —
# passed via `--build-context ideable_ui=<repo>/reusable.ui` by SPECS/build.sh
# (local build) and the registry-push buildx call. A repo-root sibling is otherwise
# outside this SOURCES-rooted context; reusable.ui/.dockerignore keeps node_modules
# and generated files out of what is copied.
COPY --from=ideable_ui . ./.ideable-ui

# Repoint the file: dependency at the in-context copy, drop the stale lockfile, then
# install with --install-links (copies @ideable/ui + installs ITS deps fresh;
# native-safe, no symlink → avoids npm's file: "Cannot read properties of undefined
# (extraneous)" crash).
RUN sed -i 's#"@ideable/ui": *"file:[^"]*"#"@ideable/ui": "file:./.ideable-ui"#' package.json \
 && rm -f package-lock.json \
 && npm install --install-links --legacy-peer-deps

ARG VITE_APP_TITLE
ARG VITE_TEMPLATE_API_URL
# WIDGET_EXAMPLES=false excludes the dev-only Widget Examples gallery (+ Recharts)
# from the published bundle; local builds default to true.
ARG WIDGET_EXAMPLES=true

ENV VITE_APP_TITLE=$VITE_APP_TITLE
ENV VITE_TEMPLATE_API_URL=$VITE_TEMPLATE_API_URL
ENV WIDGET_EXAMPLES=$WIDGET_EXAMPLES

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
