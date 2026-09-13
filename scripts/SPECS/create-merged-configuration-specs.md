# create-merged-configuration.sh specification

## Purpose
Generate the deployable merged configuration from project and per-module environment files and compose definitions. This script performs the following operations:
1. Auto-registers modules from module.json files (updates module-registry.json, generates Traefik routes, validates apiUpstream env vars)
2. Merges environment files (creates merged .env.config, .env.secrets, per-module split files, and .env.secrets.example)
3. Merges Docker Compose files (creates merged docker-compose.yml)
4. Merges menu mapping (creates merged modules_menu_mapping.json with confirmation prompt)
5. Invalidates cached Authentik blueprint (deletes authz-plan.generated.yaml to force regeneration)

## Contract
- Support source-repository and deployment-root contexts.
- Generate root `.env.config`, root `.env.secrets`, merged `docker-compose.yml`, and required generated runtime assets.
- Emit each environment variable at most once in each generated root file.
- Apply precedence in this order: project/root values, `host_app` values, then remote-module values. Earlier authoritative values must not be overwritten by later defaults.
- Keep `MODULE_SLUG`, `MODULE_NAME`, and `MODULE_DOCKER_REGISTRY_PREFIX` out of merged root env files.
- Preserve deployment customizations already present in root env files when regenerating from per-module files.
- Classify variables into ports/paths, parameters, and secrets. Resolve transitive secret references recursively and terminate circular/self references as parameters.
- Generate per-module split env files containing only module-specific variables. Exclude all keys defined in `project.env.config` and `project.env.secrets` (project-level variables) from per-module split files, not just `APP_SLUG` and `APP_NAME`. The merged `docker-compose.yml` uses `${VAR}` interpolation from root env files, so per-module split files do not need to duplicate project-level variables.
- Detect source vs deployed context by checking whether `project.env.config` exists one directory above `DEPLOYMENT_ROOT`, not by counting script directory depth levels.
- Scan non-host module `module.json` files before merge; register missing modules, sync structural fields (`entry`, `remoteEntry`, `basePath`) of existing registry entries to match expected values derived from the module slug, and generate missing standard Traefik routes.
- In addition to standard `/remotes/<slug>` and `/module/<slug>` routes, render optional `routes[]` entries declared in `module.json` into Traefik routers, middlewares, and services. Each entry produces a router named `{slug}-route-{normalized-prefix}`, an optional stripPrefix middleware (when `stripPrefix: true`), and a loadBalancer service pointing to `upstream` (env var ref or URL) or `http://<service>:<port>`. **`upstream` values containing `${VAR}` references must be resolved against the merged environment at template generation time** — they must not be left as `${VAR}` placeholders for `envsubst` in the Traefik container, because module-specific env vars are not guaranteed to be in the container's environment.
- Invalid or malformed `routes[]` entries must not abort the merge: log a warning and skip the offending entry. Priority ≤ 10 falls back to 120 with a warning.
- Route registration must be idempotent: repeated executions must not duplicate router, middleware, or service blocks, and must repair duplicate named blocks left by earlier executions before writing the template. Custom `routes[]` entries are deduplicated against existing names using the same pattern as standard routes.
- When `--regen-routes` flag is passed (or `TRAEFIK_FORCE_ROUTE_REGEN=1` env var is set), purge all module-owned route blocks (routers, middlewares, services whose names follow the `{slug}-remotes-{slug}`, `{slug}-module-{slug}`, `{slug}-route-{normalized_prefix}`, and `*-stripprefix` patterns) before the add-loop, forcing re-emission with current values. Host_app base routes (frontend, backend, authentik) are not module-owned and are left untouched. Without the flag, route generation remains add-only/idempotent so normal deploys are unaffected and manual template hotfixes aren't clobbered.
- Custom route `upstream` values containing `${VAR}` references must be resolved against a merged env map that overlays each module's on-disk `.env.config`/`.env.secrets` onto `os.environ`, ensuring the resolved URL reflects current per-module env values regardless of the `auto_register_modules()` → `merge_env_files()` ordering.
- Every `/remotes/<module>` router must declare a `stripPrefix` middleware and the corresponding middleware must be defined in the `middlewares` section.
- Backend-only modules (no `frontendPort` in `module.json` and no `frontend/` directory) must not receive `/remotes/<module>` routes, services, or middlewares, and must not be added to `module-registry.json` as Module Federation remotes. They still receive `/module/<module>` routes for backend access.
- Do not modify running containers or unrelated files; generated deployment configuration and the authoritative module registry/Traefik template may be updated as part of the merge.
- After completing all merge steps, delete the cached Authentik blueprint (`modules/host_app/authentik/blueprints/authz-plan.generated.yaml`) if it exists. If deletion fails due to permissions, attempt with `sudo`. This forces the `authentik-bootstrap` container to regenerate the authorization plan from the current set of module `authorization.yaml` contracts on its next start, ensuring newly added modules' permissions are included.
- Always merge `modules_menu_mapping.json` from all enabled modules' `config/modules_menu_mapping.json` files into `host_app/config/modules_menu_mapping.json`. If the destination file already exists, prompt the user to choose between recreating from modules (overwrite) or keeping the current file. If the user chooses to keep, skip the merge. If the file does not exist, generate it without prompting. When no interactive input is available (e.g. called from a non-interactive context such as `redeploy.sh`), default to keeping the existing file.
- Print a detailed log of operations performed, using the format "- Created merged <file> from modules: <module_list>" for each generated file. This provides clear visibility into what was merged and from which modules.
