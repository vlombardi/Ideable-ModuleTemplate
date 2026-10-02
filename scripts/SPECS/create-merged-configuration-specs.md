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

## Reading per-module files: deployed tree, not source tree (mandatory)

- **Every per-module input this script reads — each module's `docker-compose.yml`, `.env.config`
  and `.env.secrets` — must come from that module's DEPLOYED directory,
  `deployment_root/modules/<module>/`, whenever that directory already holds a copy. The project's
  own `modules/<module>/` tree (one level above `deployment_root/`) is read for a module ONLY when
  no deployed copy exists there yet** — a module enabled for the first time, before any deploy has
  produced one. This is a per-module directory choice, decided independently for each module by
  whether `deployment_root/modules/<module>/docker-compose.yml` is present — never a single
  whole-run "source vs deployed context" switch.
  - **This is unconditional, and independent of the source-vs-deployed distinction used elsewhere in
    this contract** (the one that decides where the merged *root* `.env.config`/`.env.secrets` and
    `project.env.config` values come from, by whether `project.env.config` exists one directory
    above `DEPLOYMENT_ROOT`). That distinction answers a different question — is this run inside a
    full project checkout, or a bare deployable bundle shipped without one — and both answers still
    have a *project* `modules/` directory sitting next to `deployment_root/` in every checkout,
    framework or remote. Testing for that directory's existence cannot tell "a module was never
    deployed" apart from "a deploy already produced the file this call must not re-derive from" —
    the two conditions look identical from a checkout's root, since `modules/` always exists
    there.
  - **Why the deployed copy is the only correct input once it exists.** `build_and_deploy.py`
    already resolved that module's compose before writing it to
    `deployment_root/modules/<module>/docker-compose.yml`: `${MODULE_SLUG}`/`${APP_SLUG}`
    substituted, bind-mount paths rewritten deployment-root-relative, and — for a module enabled
    `remote` in `modules/enabled.md` — its **consumed image tag already baked** onto its own image
    references (from `module.json`'s `consumedImageTag`, or, for `host_app`, from the registry and
    version `framework.lock.json` resolves). The project's own `modules/<module>/docker-compose.yml`
    is pre-processing input: `scripts/runtime/compose_merge.py` (this script's own merge engine,
    shared with `build_and_deploy.py`) resolves `${MODULE_SLUG}` and
    `${MODULE_DOCKER_REGISTRY_PREFIX}` on whatever path it is handed, but it does **not** bake a
    consumed tag onto a `remote` module's own images — that substitution exists only in
    `build_and_deploy.py`, applied once, at the point the deployed copy is written. Reading the
    un-deployed source once a deployed copy exists therefore leaves a consumed module's merged
    image reference at its dev-time `:latest` placeholder, silently reverting whatever release the
    project's last build actually consumed.

## Consumed image tags are verified, not just baked (mandatory)

- **After assembling the merged `docker-compose.yml`, and as an unconditional part of this script's
  own run — never dependent on a separate verification step being invoked afterwards — verify, for
  every module enabled `remote` in `modules/enabled.md`, that every `image:` reference belonging to
  that module in the merged file equals exactly the tag its consumed release resolves to**: the
  registry and version `framework.lock.json` names for `host_app`, or the module's own
  `module.json`'s `consumedImageTag` for another consumed module. `:latest`, or any other tag, is a
  mismatch.
  - It runs unconditionally inside this script rather than being left to whatever else happens to
    call `verify_build_identity.py` afterwards, because this script's own merge is what a manual run
    invokes on its own (§ *Purpose*, and see `redeploy.sh`, which runs this merge regardless of
    whether a rebuild happened) — a check reachable only through a caller this script does not
    control would leave exactly the manual/no-rebuild paths unchecked that most need it.
  - On a mismatch, fail the merge (non-zero exit) naming the service, the tag the merged file
    carries and the tag the consumed release resolves to — so a regression in the rule above is
    caught here, at generation time, with a diagnosis that names the actual defect, rather than
    surfacing later as a `manifest unknown` pull failure once the stack tries to start.
