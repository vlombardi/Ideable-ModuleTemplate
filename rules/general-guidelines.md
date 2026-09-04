---
trigger: mandatory
---

> **CRITICAL**: These guidelines are **MANDATORY** and must be followed at all times by both human developers and coding agents. These rules cannot be ignored or bypassed under any circumstances. If there is any uncertainty about how to apply these guidelines, **always ask for clarification** rather than making assumptions.

# Repository Model

The Ideable Framework spans two repositories:

- **Main Ideable repository** — the maintainer codebase containing the full source of `host_app` (MF 2.0 host) and `module_template` (MF 2.0 remote reference implementation). Used exclusively by Ideable maintainers.
- **Ideable-ModuleTemplate** — a GitHub template repository derived from the main repo, used as the starting point for external module developers. In this repo, `modules/host_app/` contains only `module.json` and `config/` (no SPECS, sub-modules, or TESTS). See `README.md` for the full description of both repositories, the push/sync scripts, and the external developer workflow.

## host_app / Remote Boundary (mandatory)

- host_app is the MF 2.0 shell and must remain module-agnostic.
- host_app must not hardcode, infer, or special-case any remote module slug, route prefix, manifest URL, remoteEntry URL, proxy path, or service name.
- Any route, manifest path, remoteEntry path, or reverse-proxy behavior required by a remote module must be provided by that remote module itself.
- Remote modules are responsible for exposing their own MF assets and any path contract they require for host_app consumption.
- Remote-module development projects may only adjust remote-owned source, specs, and config for their own module; they must not patch host_app internals or framework deployment logic locally.

### UI, Look & Feel, and the shared widget library (mandatory)

- **`reusable.ui` (`@ideable/ui`) is the single source of truth** for UI, Look & Feel (all CSS and design tokens), and widget definitions across the framework. There is one implementation of every shared widget/primitive and one canonical palette — not a copy per module. The canonical design-token values live once in `reusable.ui/styles/base-tokens.css` (`:root` + `.dark`); the `ideable:` Tailwind layer and token cascade live in `reusable.ui/styles/`.
- **host_app consumes the shared definitions; it must never carry redundant local ones.** host_app UI uses `@ideable/ui` widgets/primitives and inherits the canonical tokens via `@import "@ideable/ui/styles"`; it must not redefine widgets, primitives, or the palette values locally. The same rule applies to module_template and every remote module.
- **Look & Feel must be changeable without accessing or modifying the host_app repo.** Two supported paths, neither of which touches host_app sources:
  - **Build-time, per module:** override token *values* (never class names) via `--ideable-module-*` / `--<slug>-module-*` and render under `data-lf="module"` (see `reusable.ui/styles/tokens.css`).
  - **Runtime, no rebuild:** edit `config/theme-override.css` in the deployed folder (`deployment_root/modules/<module>/config/`); it is served with `no-store` and loaded after the compiled bundle, so it recolors chrome and all `@ideable/ui` widgets live. Logos, favicon, and login/home assets are likewise swapped by replacing files in the deployed `config/` folder. (Bundled icon glyphs are the one exception — they require a rebuild.)

### Framework-owned files — never modify in remote module projects (mandatory)

The following files are **framework-owned** and must **never** be directly modified by AI coding agents or human developers in remote-module development projects (i.e. projects derived from `Ideable-ModuleTemplate`):

- `redeploy.sh`
- `scripts/common/build_and_deploy.py` and any other file under `scripts/common/`
- Any file under `scripts/` (including `scripts/module_only/`, `scripts/runtime/`, and — in the maintainer repository only — `scripts/master_only/`, which is never synced)
- Root-level helper scripts: `start.sh`, `stop.sh`, `status.sh`, `update_backend.sh`, `update_frontend.sh`
- `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `rules/`, `.agents/`, `.kiro/`, `.claude/`, `.devin/`
- `IDEABLE-README.md`
- `modules/host_app/` in its entirety (in remote module projects it contains only the deployable version)
- `reusable.ui/` in its entirety (the shared `@ideable/ui` widget library, styles, and canonical design tokens — consumed read-only; changes are made in the main Ideable repo and propagate via sync)
- `modules/<MODULE>/SPECS/ideable-framework-specs/` (shared framework specs — the module_template directory in the maintainer repository; your own module's directory in a module project)
- `.gitignore`, `project.env.config.example`, `project.env.secrets.example`

### Agent behavior when a framework-owned file needs changing (mandatory)

When an AI coding agent determines that a change to a framework-owned file is necessary, the agent **must not** modify the file. Instead, the agent **must**:

1. **Stop** — do not edit the file.
2. **Inform the user** with a concise message containing:
   - **Reason**: why the change is needed (what problem it solves or what feature it enables).
   - **Change**: a concise description of the specific modification required.
3. **Direct the user** to ask the Ideable maintainer to make the change in the main Ideable repository and then follow the push/sync steps to propagate it to the remote module project.

Example message format:

> ⚠️ This change requires modifying a framework-owned file (`<file_path>`), which cannot be edited in a remote module project.
>
> - **Reason**: <concise reason>
> - **Change**: <concise description>
>
> Please ask the Ideable maintainer to apply this change in the main Ideable repository and then run the push/sync flow to propagate it here.

**MANDATORY sync ownership rule**:
- Framework-owned files must be edited only in the **main Ideable repository**.
- Remote module repositories must **never** be edited directly for framework-owned files.
- The only allowed propagation path for framework-owned changes is:
  1. update the main Ideable repository,
  2. push the curated changes to `module_template`,
  3. sync those changes into remote module repositories from `module_template`.
- This rule applies to host_app framework files, framework SPECS files, shared scripts, and any other files managed by the maintainer export/sync pipeline.
- If a remote module needs a framework-owned update, do **not** patch the remote repo by hand; use the push/sync flow instead.

# Project Structure
The Project is realized as a composition of modules, each module being a self-contained unit that can be built, deployed and run independently, but that can depend on other modules.
Each module is composed by one or more sub-modules, each sub-module being a self-contained unit that can be built, deployed and run independently, but that can depend on other sub-modules.

Each sub-module that depends on other sub-modules must be able to reach them using the local docker network or the host system or the external network.
The docker-compose.yml file of each module must define the dependencies between the sub-modules.

The project's structure is as follows:
- `modules/` folder: contains everything needed to build, deploy and run a module. In particular:
   - `<module_folder>`: there is a `<module_folder>` for each module, containing:
      - `.env.config`: the configuration env vars (ports, paths, params) for the module
      - `.env.secrets`: the secret env vars (passwords, tokens, secret keys) for the module
      - `docker-compose.yml`: the compose file for the module. During deployment, `scripts/common/build_and_deploy.py` copies it to `deployment_root/modules/<MODULE>/docker-compose.yml` and then merges all enabled modules' compose files into a single `deployment_root/docker-compose.yml`.
      - `README.md`: (optional) the documentation for the module
      - `config/`: contains all configuration and customization files for the module that are mounted as read-only volumes into containers at deployment time (e.g. `favicon.png`, `login_bg.png`, `modules_menu_mapping.json`, `menu_definition.json`). These files are copied to `deployment_root/modules/<MODULE>/config/` during deployment and referenced via volume mounts in `docker-compose.yml`.
      - `<sub_module_folder>`: there is a `<sub_module_folder>` for each sub-module, containing:
         - `SPECS/`: (optional) contains the specification files for the sub-module
         - `SOURCES/`: (optional) contains the source files for the sub-module
         - `TESTS/`: (optional) contains the test files for the sub-module
         - `Dockerfile`: (optional) the Dockerfile for the sub-module (to build Docker container)
         - `DIST/`: (optional) contains the deployment files for the sub-module
      - `SPECS/`: contains the specification files for the module, including:
         - `dependencies.md`: **mandatory** — the human-readable single source of truth for this module's **component versions**: a per-sub-module version table for every third-party library, framework, and Docker image used, plus a narrative of inter-module dependencies. The **machine-readable** inter-module dependency declaration (used by tooling to resolve build/startup order) lives in `module.json` (`provides` / `dependsOn`), not here — see § *module.json format* and § *Dependencies and Versions*.
      - `TESTS/`: (optional) contains the test files for the module
- `rules/`: contains the rules for the project. These rules are mandatory and must be followed at all times by both human developers and coding agents. These rules cannot be ignored or bypassed under any circumstances. If there is any uncertainty about how to apply these rules, always ask for clarification rather than making assumptions. It contains at least `general-guidelines.md` file representing the general guidelines for the project and the starting point for any other related and referred rule files.
- `deployment_root/`: contains the deployment files for the modules and sub-modules. The contents of this folder are used to deploy the system via Docker containers. In a production environment, this folder represents the deployed system.
- `scripts/`: contains the utility scripts for the project. These scripts are used to perform common tasks, such as starting and stopping the containers, or resetting the system. It contains, for example, the scripts to start and stop the containers, or to reset the system.
- `README.md`: contains the project's documentation.
- `.gitignore`: contains the list of files and folders to ignore when committing to the repository.

## module.json format (mandatory)

Each module must include `modules/<MODULE>/module.json` defining the canonical metadata used by tooling and integration.

Required fields:
- `name`: module name (e.g. `host_app`, `module_template`)
- `slug`: unique lowercase slug (e.g. `hostapp`, `template`)
- `displayName`: UI-friendly name
- `role`: `host`, `remote`, or `side`
- `cssPrefix`: Tailwind prefix for that module (must end with `-`)

Optional fields:
- `frontendPort`: module frontend runtime port (omit if the module has no frontend)
- `backendPort`: module backend runtime port (omit if the module has no backend)
- `routes[]`: exception edge routes for sub-remotes or external origins not covered by the standard `/remotes/<slug>` and `/module/<slug>` auto-derivation (see §Module Edge Routing below)
- `provides`: what this module offers to others — `css` (defaults to true when `frontendPort` is set), `api` (defaults to true when `backendPort` is set), `widgets` (array of Module-Federation-exposed widget names, default `[]`), and `gates` (array of `{ service, condition }` readiness barriers used to order container startup).
- `dependsOn[]`: the machine-readable inter-module dependency graph. Each edge is `{ module, kinds, optional, reason }`, where `kinds` ⊆ `{ runtime, api, data, css, widgets }`. Capability kinds (`api`, `css`, `widgets`) require the target to actually `provide` that capability; startup-gating kinds (`runtime`, `api`, `data`) affect container start order. Every non-host module implicitly depends on `host_app` (kind `runtime`) when host_app is enabled; `host_app` declares `"dependsOn": []`. A missing required target is a hard error; `optional: true` degrades to a warning.

The dependency graph is resolved **providers-first** by `scripts/common/module_deps.py` (build/startup order), validated together with the `module.json` schema by `scripts/common/validate_modules.sh` (which also emits the `provides`-vs-reality and drift lints), and can be inspected at a deployed site with `scripts/runtime/status.sh --deps`. The canonical contract is `modules/<MODULE>/SPECS/ideable-framework-specs/module-integration-specs.md` §5.1.

Role semantics:
- `host` — the Module Federation 2.0 host application.
- `remote` — a standard Ideable remote module that follows the full framework contract (framework specs, sub-modules, etc.).
- `side` — an auxiliary module that does not participate in the Ideable framework specs system and may omit sub-module structure.

`module.json` is the source of truth for:
- module registry generation,
- compose naming/packaging,
- host vs remote behavior,
- edge route derivation (standard routes + exception routes),
- inter-module dependency resolution (`provides` / `dependsOn` → build & startup order).

## Module Edge Routing (mandatory)

Edge routing is the set of Traefik (today) or Kubernetes Gateway/Ingress (future) routes that direct external HTTP traffic to the correct module frontend or backend service. The framework generates these routes at deploy time from `module.json` metadata — host_app never hardcodes per-module routes.

### Standard routes (auto-derived)

For every enabled remote module (`role: "remote"`), the framework auto-generates two edge routes:

1. **Frontend route**: `PathPrefix(/remotes/<slug>)` → `<slug>-frontend:80` (priority 130, stripPrefix `/remotes/<slug>`)
2. **Backend route**: `PathPrefix(/module/<slug>)` → `<slug>-backend:<backendPort>` (priority 110, stripPrefix `/module/<slug>`)

A self-contained MF 2.0 remote module needs nothing extra in `module.json` beyond the standard fields.

### Exception routes (`module.json` `routes[]`)

When a module requires edge routes that the standard derivation cannot cover — chiefly sub-remotes served by an external origin — it declares them via the optional `routes[]` array in `module.json`:

```jsonc
{
  "routes": [
    {
      "prefix": "/subremote",
      "upstream": "${MODULE_A_SUBREMOTE_ORIGIN}",
      "apiUpstream": "${MODULE_A_SUBREMOTE_API_ORIGIN}",
      "stripPrefix": true,
      "options": { "sse": true }
    }
  ]
}
```

Each `routes[]` entry has the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `prefix` | string (starts with `/`) | yes | Edge route path prefix. Must not collide with reserved namespaces or other module prefixes. |
| `upstream` | string (env var ref or URL) | yes\* | External origin URL for the UI/static remote. Env vars are resolved from the merged `.env.config` at deploy time. |
| `apiUpstream` | string (env var ref or URL) | no | Optional separate origin for backend API calls. When present, the env var placeholder is emitted into the merged `.env.config` so downstream modules can discover the API origin. |
| `service` | string | yes\* | Internal service name. Alternative to `upstream`. |
| `port` | integer | no | Port for `service` targets. Default: 80. |
| `stripPrefix` | boolean | no | Strip prefix before forwarding. Default: `false`. |
| `priority` | integer | no | Route priority. Must be > 10 (above catch-all). Default: 120. |
| `options` | object | no | Adapter-interpreted hints (see below). |

\* Exactly one of `upstream` or `service` must be specified per entry. `apiUpstream` is optional and can be used alongside `upstream` to expose a separate API origin for inter-module backend proxying.

### `options` — adapter-interpreted hints

`options` is a curated allowlist expressing **intent**, not mechanism. Each adapter (Traefik today, K8s Gateway tomorrow) implements the intent idiomatically for its backend. An adapter may ignore an option it doesn't support (with a deploy-time warning). Supported options:

- `sse`: disable response buffering; long read timeout
- `websocket`: upgrade support
- `forwardHeaders`: pass specific headers through

### Reserved namespaces

The following path prefixes are reserved for host_app and Authentik. No module `routes[]` entry may claim them:

- `/` (catch-all)
- `/api` (host_app backend)
- `/auth/callback` (OIDC callback)
- `/health` (host_app health)
- Authentik paths: `/if`, `/flows`, `/application`, `/static`, `/media`, `/api/v3`, `/ws`, `/outpost.goauthentik.io`

### Fail-closed validation

The deploy pipeline (`validate_modules.sh`) aborts if any `routes[]` entry:
1. has a prefix that collides with another module's prefix or a reserved namespace,
2. is malformed (prefix doesn't start with `/`, both `upstream` and `service` specified or neither, priority ≤ 10).

### Sub-remote MF runtime registration

A bridge remote that composes sub-remotes must declare them in its own `mf-manifest.json` `remotes[]` field. MF 2.0's runtime resolves sub-remotes from the parent manifest automatically — no host_app change is needed beyond the edge route that `routes[]` provides.

### Contract/renderer split

The routing architecture separates the portable contract (`module.json` + `module-registry.json` → RouteTable) from the adapter that renders it (Traefik file provider today, Kubernetes Gateway API tomorrow). This makes Compose→K8s a renderer swap, not a contract change.

# Development process

The user can ask a coding agent to execute a specific step, and the coding agent can suggest what is the step that is sound to execute in that moment.

The project development process is defined by the following steps:
1. **specifications**: during this step, one or more specification files inside one or more `SPECS` folder are defined or modified by the human developer or by a coding agent. The specifications files evaluation must follow the dependencies, starting from non depending modules and sub-modules, and then moving to depending modules and sub-modules. 
2. **coding**: during this step, one or more source files, and when needed `Dockerfile` files, are defined or modified inside `SOURCES` folders by the human developer or by a coding agent 
3. **build**: during this step all the files that need to be compiled and/or built are processed. The build step produces two kinds of outputs:
   - **Docker images**: sub-modules that have a `Dockerfile` in their `SOURCES/` folder are built into named Docker images using `docker build` (e.g. `docker build --no-cache -t <image-name> <sub-module>/SOURCES/`). The resulting image is stored in the local Docker registry. **Image names follow a strict convention** tied to the module's own `APP_SLUG` (see *Docker image naming convention* below), ensuring the same image name is produced regardless of which project performs the build.
   - **File artifacts**: sub-modules that produce non-image artifacts (e.g. SQL scripts, config files, bootstrap scripts) copy those files from `SOURCES/` into their `DIST/` folder. Sub-modules that produce only a Docker image do not need a `DIST/` folder.
   - **Compiled code**: sub-modules that produce compiled code (e.g. Python, Java, Go, etc.) create executable files or packages in their `DIST/` folder. 
4. **deployment**: during this step the contents of each sub-module's `DIST/` folder are copied to the expected position inside the `deployment_root` directory. Sub-modules that produce only a Docker image (no `DIST/`) have nothing to copy. All enabled module's `docker-compose.yml`, `.env.config`, and `.env.secrets` files are copied to `deployment_root/modules/<MODULE>` folder. All enabled modules' `.env.config` files are merged in order (host first, then remotes) into `deployment_root/.env.config`, and their `.env.secrets` files likewise into `deployment_root/.env.secrets` — keys defined by earlier modules are not overwritten by later ones. All enabled modules' compose files are then merged into `deployment_root/docker-compose.yml`. Examples (paths from the maintainer repository, where host_app is built from source): `modules/host_app/database/DIST/initdb/seed.sql` → `deployment_root/modules/host_app/database/initdb/seed.sql`; `modules/host_app/docker-compose.yml` → `deployment_root/modules/host_app/docker-compose.yml`.

5. **configuration**: during this step one or more configuration files (e.g., `.env.config`, `.env.secrets`) are modified and/or verified to ensure that they are correct and complete
6. **execution**: during this step the modules' Docker containers are started using the module's `docker-compose.yml` file. The execution must follow the dependencies, starting from non depending modules and sub-modules, and then moving to depending modules and sub-modules. 
7. **test**: during this step the modules' sub-modules are tested applying the tests defined inside the module's `TESTS` folder and a test report is created under `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md` at the project root. The test execution must follow the dependencies, starting from non depending modules and sub-modules, and then moving to depending modules and sub-modules.
8. **documentation**: during this step the specs and docs governing whatever changed — framework, module, or both, depending on the purpose of the work — are brought into line with what is now true. This is **mandatory** and it runs **after the tests are green and before anything is committed**, so the documentation changes are committed alongside the code they describe. Three things must hold when it finishes:
   - **Every affected document describes the present.** No sentence describes a superseded state, and none narrates the document's own history ("used to", "formerly", "previously named"). The narrow exception is a *rationale* whose content is the incident itself; the test is whether a reader could mistake the sentence for a description of current behaviour.
   - **Nothing removed or renamed is still named as if it were live** — env vars, flags, scripts, functions, paths, endpoints, contracts.
   - **Anything the change introduced that a reader must know about is in the document that governs it**, not only in the implementation plan.

   It **reconciles, it does not legislate**: updating a spec to match approved, tested reality is the step's job, but if aligning would require deciding something the work never decided — or the code contradicts a contract the spec exists to impose — that is a conflict, and it goes to the human developer per § *Decision Making Authority*. In a remote module project, framework-owned files are reported and never edited.

   Driven by the `ideable-align-docs` skill and the `Documenting` node of the dev-cycle; the artifact is the plan's `Docs` column and the check is `scripts/TESTS/test_docs_describe_the_present.py`. See `rules/implementation-plan.md` § *Documenting*.

# Project Guidelines

## deployment_root folder
During the development process, the contents of root level files (e.g., script files inside the scripts folder) and modules folder contents are modified, since they represent the project definition. 

The role of the deployment_root folder is to contain the deployed system, i.e. the system as it is running in a production environment. So, it must contain the final version of all the files that are needed to run the system as the result of the deployment step.

The expected `deployment_root/` structure for multi-module deployments is:

```
deployment_root/
├── docker-compose.yml                 # merged compose for all enabled modules (generated)
├── .env.config                        # merged config env for all enabled modules (generated)
├── .env.secrets                       # merged secret env for all enabled modules (generated)
├── module-registry.json               # generated module registry
├── start.sh
├── stop.sh
└── modules/
    ├── host_app/
    │   ├── docker-compose.yml         # deployed host_app compose (env_file: ../../.env.config, ../../.env.secrets)
    │   ├── database/initdb/...
    │   ├── traefik/...
    │   └── authentik/...
    └── module_template/
        ├── docker-compose.yml         # deployed module_template compose (env_file: ../../.env.config, ../../.env.secrets)
        └── database/initdb/...
```

**CRITICAL constraints for `deployment_root/`**:
- It must **never** contain `SOURCES/` folders or any reference to them.
- It must **never** contain `Dockerfile` files. Docker images are built during the build step and stored in the local (or remote) Docker registry; they are referenced by name in `docker-compose.yml`.
- Volume mounts in `docker-compose.yml` must only reference paths that exist inside `deployment_root/` at runtime (i.e. paths produced by the deployment step), never paths inside `SOURCES/` or `DIST/` of the project.

## Deployment Architecture

### Two-Level Execution Model

The deployment supports two execution modes:

1. **Standalone Module Execution**: Each module can run independently
   - Every module folder (`deployment_root/modules/<MODULE>/`) contains:
     - `docker-compose.yml` — module-specific compose configuration using **relative paths** (e.g., `./database/`, `./frontend/`)
     - `.env.config` — the original `modules/<MODULE>/.env.config` copied for standalone execution
     - `.env.secrets` — the original `modules/<MODULE>/.env.secrets` copied for standalone execution
   - Used for module-specific development, testing, or isolated deployment
   - Run with: `docker compose -f modules/<MODULE>/docker-compose.yml up`

2. **Composed Ecosystem Execution**: All modules run as an integrated system (production/test default)
   - `deployment_root/docker-compose.yml` — merged compose from all enabled modules, referencing the overall `.env.config` and `.env.secrets`
   - `deployment_root/.env.config` — merged configuration from all modules (host module first, remotes appended)
   - `deployment_root/.env.secrets` — merged secrets from all modules
   - This is the standard execution mode for production and integration testing
   - Run with: `./deployment_root/start.sh` or `docker compose up`

### Path Resolution in Merged Compose

When Docker Compose merges multiple compose files with `-f`, it resolves **relative paths from the first compose file's directory** (host_app). To ensure correct resolution:

- **host_app** paths remain relative (e.g., `./database/initdb/` resolves to `deployment_root/modules/host_app/database/initdb/`)
- **Remote modules** (non-host_app) have paths transformed during deployment:
  - Source: `./database/initdb/file.sql`
  - Deployed: `./modules/module_template/database/initdb/file.sql`
  - This ensures paths resolve correctly from `deployment_root/` regardless of which compose file is first

### Environment Variable Strategy

- **Standalone execution**: Uses per-module `.env.config` + `.env.secrets` in `deployment_root/modules/<MODULE>/`
- **Composed execution**: Uses merged `.env.config` + `.env.secrets` in `deployment_root/`
- **Container env vars**: All containers must reference variables from `${VAR_NAME}` — never hardcoded values
- **Merged `.env.config` and `.env.secrets` precedence**: host_app variables take priority; remote module variables with same name are prefixed or skipped

## docker-compose.yml rules

Each module's compose file is named `docker-compose.yml` and lives in the module's root folder (`modules/<MODULE>/docker-compose.yml`). During deployment, `scripts/common/build_and_deploy.py` copies it to `deployment_root/modules/<MODULE>/docker-compose.yml` and merges all enabled modules into `deployment_root/docker-compose.yml`. All compose commands are always run from `deployment_root/` using explicit `-f modules/<MODULE>/docker-compose.yml` flags.

All compose files (both per-module and the merged one) must comply with the following rules:

- **No `build:` sections**: the compose file must never contain `build:` sections. Docker images are built during the build step (step 3), not at container startup. In a production environment the images are already present in the local or remote Docker registry.
- **Image references only**: every service must reference a pre-built image by name via the `image:` key (e.g. `image: ${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.backend:${IMAGE_TAG}`). Image names must follow the *Docker image naming convention* below.
- **Docker image naming convention**: all modules use the unified pattern `{MODULE_SLUG}.<submodule>:${IMAGE_TAG}` (e.g. `hostapp.backend:a1b2c3d`, `template.frontend:a1b2c3d`). The `MODULE_SLUG` is resolved from `module.json` and substituted into compose files and image tags at deploy time. For remote deployments, the module's `.env.config` declares `MODULE_DOCKER_REGISTRY_PREFIX` (e.g. `ghcr.io/OWNER`, no trailing slash) and compose services reference it via `${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.<submodule>:${IMAGE_TAG}`. When empty, the prefix and slash resolve to nothing and local image names are used. It is the module maintainer's responsibility to ensure the prefix is correct in both `.env.config` and compose files. Build/deploy scripts must never derive module identity from a module `.env` file, and must never automatically prepend a registry prefix to image names.
- **`deployment_root/.env.config` has TWO generators, and the second one wins**: `build_and_deploy.py` writes it during a deploy, then `scripts/runtime/config/create-merged-configuration.sh` rewrites it — and that script also runs standalone at a deployed site where no build tooling exists. **Anything the second writer does not carry forward is silently lost.** This is not hypothetical: it is how `IMAGE_TAG` was written and immediately discarded, leaving every compose image reference as `name:`. The same trap was already known for compose (the cross-module `depends_on` injection exists precisely to survive both mergers) but nothing had generalised it to env keys. Any project-level key added to that file must be **preserved by the runtime merge**, not re-derived — at a deployed site there is no git checkout and no build, and an operator's hand edit (a rollback, for instance) must survive the next regeneration. A contract test asserts the writer/preserver counts match, so a new code path that rewrites the file cannot quietly drop a key.
- **Image tags are immutable — never `latest`**: `IMAGE_TAG` is the tag every image **this run builds** carries. It is the commit the build came from (short hash, `-dirty` when the working tree had uncommitted changes), or an explicit value stated for the run. There is no `latest` and no fallback to one: a tree that is neither a git checkout nor carrying an explicit tag aborts the build rather than producing an untraceable image. `build_and_deploy.py` records the tag in `deployment_root/.env.config`, which the runtime scripts source before calling compose — so `./start.sh` restarts *exactly* the deployed build rather than whatever a moving tag names now, and a rollback is one edited line followed by `./start.sh`. A `-dirty` tag must never be promoted to production: its contents are not reproducible from any commit. See `docs/RUNBOOK.md` § "Rolling back to a previous build" (maintainer repository; `docs/` is not synced to module projects).
- **State the tag with `--image-tag`, and the build must be the thing that runs**: `./redeploy.sh --image-tag <tag>` is how an operator or CI names a build; `IMAGE_TAG` in the environment is the same channel for CI. Precedence, in order: `--image-tag` → `IMAGE_TAG` in the environment → `IMAGE_TAG` in `project.env.config` → the commit → abort. The flag exists because the build runs under `env -i` and an environment variable alone could not reach it — **the `env -i` allow-list in `redeploy.sh` is the build's whole interface, so any variable documented as an operator control must appear in it.** Two facts are then recorded in `deployment_root/.env.config` and they are not the same fact: `IMAGE_TAG` is a runtime *selector* an operator may edit (that is how a rollback works), and `BUILT_IMAGE_TAG` is a *record* of the last build that is never edited and takes no override. After a build, `scripts/common/verify_build_identity.py` **fails the deploy when they differ** — one check that covers a dropped variable, a half-finished build and a stale merge alike. On a rollback they differ deliberately, which is why the check runs only after a build. `./status.sh` prints all three quantities — built, configured, and running per container — because the first two agreeing while the build was stale is exactly how a wrong deploy came to look completely healthy.
- **A tag for what you build is not a tag for what you consume**: a module enabled as `remote` in `modules/enabled.md` has its images built and published by another project, so its tag cannot be derived from this repository's commit — that names a build no registry holds, and compose reports `manifest unknown` after the build has already run. Such a module declares **`consumedImageTag`** in its `modules/<MODULE>/module.json`: which published release of that module this project runs. `build_and_deploy.py` resolves it into that module's deployed `docker-compose.yml` at generation time (like `${MODULE_SLUG}`, and for the same reason — the value is per module, and the merged env namespace is flat); `pull-hostapp-images.sh` reads the same field, so the puller and the deploy can never name the same images differently; and `validate_modules.sh` fails **before the build** when a remote module declares no tag or declares this repository's own commit. There is no fallback to `latest` anywhere, and a moving consumed tag (`latest`, `stable`, `main`) is reported as a warning: it resolves, so it cannot be a hard error without breaking projects that consume such a publish today, but two different builds answer to it and "which build is running?" then has no answer.
- **A partial publish is a failed publish**: `push_module_images_to_registry.py` records every ref a run owed before attempting it, then asks the registry — `docker manifest inspect` — whether each one actually resolves, and fails the run naming the ones that do not. Its last line states `Published: n/n — complete` or `Published: FAILED — n/m`. A non-zero exit code alone was not sufficient: it reports whether *this* run's pushes failed, while the failure that mattered was a run whose result was never checked, leaving three of five `hostapp.*` tags absent and a fresh machine unable to bring the stack up at all.
- **Docker container naming convention**: runtime container names must use the dotted prefix form `${APP_SLUG}.${MODULE_SLUG}.<service_name>` in source compose files (e.g. `${APP_SLUG}.${MODULE_SLUG}.backend`, `${APP_SLUG}.${MODULE_SLUG}.frontend`). During deployment, both `${APP_SLUG}` and `${MODULE_SLUG}` are substituted with their actual values so the final compose contains only concrete names. The `APP_SLUG` remains the only runtime identity variable; `MODULE_SLUG` is fully resolved at deploy time and never appears in deployed `.env.config` or `.env.secrets` files.
- **No `SOURCES/` path references**: volume mounts, bind mounts, and any other path references must never point to `SOURCES/` folders. All runtime files must come from the deployment step output inside `deployment_root/`.
- **No hardcoded values**: any value that has a corresponding env var defined in the module's `.env.config` or `.env.secrets` must reference that env var (e.g. `${AUTHENTIK_INTERNAL_URL}` not `http://authentik-server:9000`).

### Runtime hardening every service must declare (mandatory)

These were added by the compose-hygiene work and are load-bearing: each one corresponds to a way the
stack failed or could not scale. A contract test asserts them
(`modules/*/TESTS/test_horizontal_scale_contract.py`), so a service that omits one fails the suite
rather than being discovered in production.

- **`restart:` is explicit on every service.** Long-running services use `restart: unless-stopped`, so
  a crash or a host reboot brings them back. **One-shot jobs use `restart: "no"`** — a restarting
  one-shot can never satisfy `condition: service_completed_successfully`, so the whole dependency
  chain hangs.
- **`stop_grace_period:` on every traffic-serving service** (30s; 60s for the databases), so in-flight
  requests finish instead of being cut at Docker's 10-second default.
- **`deploy.resources.limits` (`cpus`, `memory`) and `deploy.resources.reservations.memory`**, each
  from a per-service env var (`${<SERVICE>_CPU_LIMIT}`, `${<SERVICE>_MEM_LIMIT}`,
  `${<SERVICE>_MEM_RESERVATION}`). Without a limit one container can starve the host. Compose honours
  these without Swarm.
- **`logging:` with `driver: json-file` and a `max-size`/`max-file` rotation**, or an unbounded log
  fills the disk — Traefik at `DEBUG` was the case that proved it. The log level itself is a variable
  (`${TRAEFIK_LOG_LEVEL:-INFO}`), never hardcoded to a debug level.
- **Database ports bind to loopback by default.** Publish as
  `"${<SLUG>_POSTGRES_BIND:-127.0.0.1}:${<SLUG>_POSTGRES_PORT}:5432"`. Binding a database to all
  interfaces is a deliberate act, and the variable makes it one.
- **Replicable services carry no `container_name:`** and take their replica count and published port
  spec from variables — see the horizontal-scale rules in
  `modules/<MODULE>/backend/SPECS/ideable-framework-specs/base-specs.md` and the same contract
  test. A `container_name` caps a service at one instance, because the second replica collides on it.

## .env rules

Each module has its own `modules/<MODULE>/.env.config` (ports, paths, params) and `modules/<MODULE>/.env.secrets` (passwords, tokens, secret keys) containing only the env vars needed by that module's services. Project-wide values live in repo-root `project.env.config` and `project.env.secrets` and are loaded before module env files. During deployment, all enabled modules' split env files are merged in order (host module first, then remotes) into `deployment_root/.env.config` and `deployment_root/.env.secrets`. Keys defined by earlier modules are never overwritten by later ones.

- **Source of truth**: `modules/<MODULE>/.env.config` and `.env.secrets` — edit here, never in `deployment_root/.env.config` or `.env.secrets` directly when in development. The general .env.config/.env.secrets file editing can be done to change the deployed project configuration.
- **`deployment_root/.env.config` and `.env.secrets` are auto-generated** by `scripts/common/build_and_deploy.py` — do not edit them manually.
- **Deployed compose files** must reference the merged env via `env_file: - ../../.env.config` and `- ../../.env.secrets` (relative path from `deployment_root/modules/<MODULE>/`).
- **Source compose files** (`modules/<MODULE>/docker-compose.yml`) use `env_file: - .env.config` and `- .env.secrets` for local development.
- **No slug-based env files** (e.g. `.env.template`) exist in `deployment_root/` — the merged `.env.config` and `.env.secrets` replace them all.
- **`MODULE_SLUG` is resolved at deploy time**: `MODULE_SLUG` exists in source `modules/<MODULE>/.env.config` for local development but is stripped from all deployed env files (both per-module and merged). Its value is baked into compose files during deployment.
- **Remote module env vars must be prefixed** with the module's slug in uppercase (e.g. `TEMPLATE_POSTGRES_DB`, `TEMPLATE_POSTGRES_USER`) to avoid collisions with host module vars in the merged env. Generic names like `POSTGRES_DB` are reserved for the host module.
- **`MODULE_DOCKER_REGISTRY_PREFIX`** (module-local, optional): each module may declare `MODULE_DOCKER_REGISTRY_PREFIX` in its `.env.config` (e.g. `ghcr.io/OWNER`). The push script reads this value to know which registry to push to. Compose services reference it via `${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.<submodule>:${IMAGE_TAG}`; when empty, local image names are used. The value should NOT include a trailing slash; compose files include the separator slash. It is the module maintainer's responsibility to keep `.env.config`, `.env.config.example`, and `docker-compose.yml` consistent. Build and deploy scripts must never automatically prepend a registry prefix.
- **`MODULE_DOCKER_REGISTRY_PREFIX` is resolved at compose generation time**: during deployment the script reads the prefix from each module's own `.env.config` and bakes it directly into the deployed `docker-compose.yml` image references. For locally built modules (`local` in `modules/enabled.md`) the prefix is replaced with an empty string so compose uses local images (e.g. `hostapp.backend:a1b2c3d`). For remote modules (`remote`) the full prefix is embedded so compose can pull pre-built images (e.g. `ghcr.io/OWNER/template.backend:a1b2c3d`). The variable itself is unconditionally stripped from all deployed env files (merged and per-module) to prevent cross-module leakage through the flat env namespace.
- **`<SLUG>_LOG_LEVEL` is derived automatically from module mode**: the deploy script injects a per-module `<SLUG>_LOG_LEVEL` environment variable for every enabled module. The variable name is derived from the module's `slug` (uppercased) + `_LOG_LEVEL`:
  - `local` (build from local source) → `<SLUG>_LOG_LEVEL=DEBUG`
  - `remote` (pre-built images) → `<SLUG>_LOG_LEVEL=INFO`
  For example: host_app (slug `hostapp`) gets `HOSTAPP_LOG_LEVEL`; module_template (slug `template`) gets `TEMPLATE_LOG_LEVEL`. This prefixed variable is injected into both the merged `deployment_root/.env.config` and each per-module `deployment_root/modules/<MODULE>/.env.config`.
  Each backend service's `docker-compose.yml` maps its own slugged variable to the standard `LOG_LEVEL` variable in the `environment:` block (e.g. `LOG_LEVEL=${TEMPLATE_LOG_LEVEL:-INFO}`). The backend code reads the generic `LOG_LEVEL` variable normally — no module-specific code is required. Docker Compose resolves the correct per-module value even when multiple modules run together.

## Dockerfiles

- `Dockerfile` files must be placed **only** inside a sub-module's `SOURCES/` folder.
- `Dockerfile` files must **never** appear in `DIST/` folders, sub-module root folders, or anywhere inside `deployment_root/`.
- A sub-module that has a `Dockerfile` in `SOURCES/` is built into a named Docker image during the build step. If it also produces runtime file artifacts (e.g. config templates), those are copied to `DIST/` separately (excluding the `Dockerfile` itself).

## Sub-Module Build Scripts

**CRITICAL — Modularity and Decoupling Principle**: All build logic that is specific to a sub-module MUST be defined inside that sub-module and MUST NOT be hardcoded in the global build script (`scripts/common/build_and_deploy.py`).

When a sub-module requires a **non-standard build process** (i.e. anything beyond the two generic types: `docker build` from a `Dockerfile`, or flat copy of `SOURCES/` to `DIST/`), the following rules apply:

1. **Create a `SPECS/build.sh` script** inside the sub-module's `SPECS/` folder. This script is the single source of truth for that sub-module's build process. It must be deterministic, idempotent, and self-contained.
2. **Reference `build.sh` in the sub-module's `base-specs.md`** — add it to the Specification Files Chain and describe what it does in the Build section.
3. **`scripts/common/build_and_deploy.py` detects `SPECS/build.sh` automatically**: if `SPECS/build.sh` exists for a sub-module, the script runs it instead of applying generic build logic. No changes to `build_and_deploy.py` are needed.

**Forbidden**: embedding sub-module-specific build logic directly in `build_and_deploy.py` (e.g. hardcoded function `build_database()`). The global script must remain generic and module-agnostic.

The same principle applies at module level: module-specific build or deployment considerations must be documented in the module's own `SPECS/` or `scripts/` folder, not in the project-level `scripts/` folder.

## Specifications
Inside the folder of each module or sub-module there is a folder named `SPECS` that contains its specification files. 

### Mandatory Reading Order

**CRITICAL**: The `base-specs.md` file in the module's `SPECS` folder is the **MANDATORY starting point** for ANY coding agent action on that module.

Before implementing, modifying, or troubleshooting ANY component of a module, you MUST:
1. **Read the entire `base-specs.md` file** of that module
2. **Follow ALL references** to other specification files mentioned in `base-specs.md`
3. **Read those referenced files completely** before taking any action
4. **Read the `base-specs.md`** of the specific sub-module you are working on, if present, and strictly follow its rules
5. **Read the `general_bug_avoider.md`** of the sub-module you are working on and strictly follow its rules specifying how to avoid known bugs and how to implement their fixes
6. **Read the `datamodel_related_bug_avoider.md`** of the sub-module you are working on, if present

**Every module's `base-specs.md` MUST contain**:
- An explicit "IMPORTANT: Read This First" section at the top
- A "Specification Files Chain" section listing ALL other specification files that must be read
- Clear indication of which specification files are MANDATORY vs optional
- Warnings about critical requirements that if ignored will cause failures

### Specification File Structure

When implementing or modifying a module or sub-module you must update the related specification file describing that specification aspect in detail, considering that:
- `base-specs.md` can directly define a specification aspect, but can also refer to a more specific specification file, if present (e.g., if a security specification section is present, it directly can contain security specifications and/or refer to a security.md file).
- the module's specification files can be specialized and/or overridden by sub-module specification files if present.

- `base-specs.md` file can contain the sections:
  - Build: describes the build process of the module. For instance, it can describe how to create the content of the DIST folder of a sub-module 
  - Deployment: describes the deployment process of the module. For instance, it can specify that the contents of the DIST folder must be directly copied to the sub-modules folder of the `deployment_root` directory (e.g., in the maintainer repository the `modules/host_app/database/DIST/initdb/seed.sql` file must be copied to the `deployment_root/modules/host_app/database/initdb/` directory).
  - Configuration: describes the configuration process of the module.
  - Execution: describes the execution process of the module.
  - Test: describes the test process of the module.
  - Security: describes the security process of the module.

### Specification Files automatic bug avoider
When some bugs are found during testing or execution, the specification files must be updated to reflect the changes made to the code, so that the next time the specifications are translated to code, the specifications are up-to-date and sufficient to generate SOURCES that are free of bugs.

Put this specification additional information in the specification file:
- `modules/<MODULE>/<SUB_MODULE>/SPECS/general_bug_avoider.md` if the bug is not related to a specific datamodel and can be generalized not referring to specific tables or views
- `modules/<MODULE>/<SUB_MODULE>/SPECS/datamodel_related_bug_avoider.md` if the bug is related to a specific datamodel, i.e., related to a specific table or a specific view

Before applying the changes to the specification files, you should always check if the changes are correct and if they are consistent with the code, then ask the user for confirmation.

### Strict Specification Implementation

> **CRITICAL**: When implementing code from specifications (step 2: coding), ALL specifications must be implemented EXACTLY as written, with ZERO deviations, shortcuts, or design decisions that are not explicitly specified.

**Mandatory rules for specification implementation:**

1. **Complete Implementation**: Every feature, component, page, and requirement mentioned in the specification files must be implemented. Nothing can be skipped, simplified, or deferred.

2. **No Design Decisions**: Do not make design choices that deviate from the specifications. If the specs say "sidebar navigation", implement a sidebar - not a header. If the specs say "collapsible", make it collapsible.

3. **No Shortcuts**: Do not create "minimal" or "simplified" versions. Implement the full feature set as specified.

4. **Explicit Requirements Only**: Only implement what is explicitly stated in the specifications. Do not add features that are not specified, but also do not omit features that are specified.

5. **Ask for Clarification**: If a specification is ambiguous, incomplete, or unclear, STOP and ask the user for clarification rather than making assumptions.

6. **Verification**: Before considering an implementation complete, verify that EVERY requirement from the specification files has been implemented exactly as written.

**When a user says "implement specs" or invokes the `ideable-implement-specs` skill, this means:**
- Read ALL specification files for the module/sub-module
- Implement EVERY requirement without exception
- Follow the exact structure, components, and features as specified
- Do not substitute, simplify, or redesign any specified feature

**Failure to follow these rules is considered a critical error** and requires immediate correction by re-implementing the code to match the specifications exactly.

## Enabled Modules
The project file `modules/enabled.md` describes which modules participate in the build and deployment process. Each entry follows the format:

```
<ModuleName>: <local|remote>
```

- A module that is neither `local` nor `remote` is considered disabled and should be commented out or removed from `modules/enabled.md`.
- **`local`** — the module's full source tree is present under `modules/<MODULE>/` and is built and deployed from source.
- **`remote`** — the module participates in the deployment but is not built locally. Its Docker images are expected to be available in a Docker registry. The `image:` references in the module's `docker-compose.yml` must already include the registry prefix when images are hosted remotely (e.g. `ghcr.io/owner/app.module.backend:a1b2c3d`). If no registry prefix is present, images are assumed to be available in the local Docker daemon (e.g., already pulled or restored from `docker save`). In this case `modules/<MODULE>/` contains only `module.json`, `config/`, and `.env` — no SPECS or sub-module source folders.

Example:

```markdown
host_app: remote
MyModule: local
# LegacyModule: remote
```

This means host_app is included via Docker images only, MyModule is fully built from source, and LegacyModule is excluded entirely.

## Dependencies and Versions

Dependencies are declared in **two complementary places**, each with a distinct role — keep both in sync:

1. **`modules/<MODULE>/module.json` (`provides` / `dependsOn`)** — the **machine-readable inter-module contract** and the authoritative source for the dependency graph. Tooling reads it to resolve providers-first build/startup order (`scripts/common/module_deps.py`), validate + drift-lint it (`scripts/common/validate_modules.sh`), and inspect it (`scripts/runtime/status.sh --deps`). See § *module.json format*.
2. **`modules/<MODULE>/SPECS/dependencies.md`** — the **human-readable single source of truth for component versions**. It must contain:
   - a narrative of this module's inter-module dependencies (mirroring the `dependsOn` edges, with the *why*);
   - **per-sub-module version tables** — for every sub-module, each third-party library, framework, and Docker image with its pinned version and purpose.

The project-level file `modules/dependencies.md` describes the overall inter-module dependency graph (Mermaid diagram). It exists in the maintainer repository; a module project has only its own `modules/<MODULE>/SPECS/dependencies.md`. It must be kept in sync with each module's `module.json` and `SPECS/dependencies.md`.

* **Mandatory Update Rule**: update the declarations immediately whenever:
    - A new third-party library or framework is added → `SPECS/dependencies.md`
    - A dependency version is upgraded or downgraded → `SPECS/dependencies.md`
    - A dependency is removed from the project → `SPECS/dependencies.md`
    - A new inter-module dependency is introduced or removed → the `dependsOn` edge in `module.json` **and** the narrative in `SPECS/dependencies.md`

## Ports
Exposed ports are not maintained in static files. Use `scripts/runtime/config/list-exposed-ports.sh` to list all host-exposed ports from `deployment_root/docker-compose.yml` at any time. This is the authoritative source for firewall configuration and conflict detection.

## CSS Prefix Convention

To enforce CSS isolation across host and remote modules (Tailwind v4 `prefix()` — colon syntax):

- Every module authors its own components with a Tailwind prefix equal to its module slug:
  - host_app: `hostapp:` (e.g. `hostapp:bg-accent`, `hover:hostapp:bg-accent`)
  - module_template / remote modules: `template:` / `${APP_SLUG}:` (e.g. `md:template:grid-cols-2`)
- **Shared `@ideable/ui` widgets use the neutral `ideable:` prefix** — you never write `ideable:` in your own module markup; it appears only inside the shared library, shipped as static CSS in `reusable.ui/styles/compiled.css` (Tailwind v4 allows only one prefix per build).
- All three prefixes resolve to the **same canonical design tokens** (`reusable.ui/styles/base-tokens.css`, the single source of truth); rebrand by overriding token *values*, never class names — see § "UI, Look & Feel, and the shared widget library".

Never use unprefixed Tailwind utility classes in module frontend source files.

## Code Quality
* **Exception Handling**: All potential exceptions and errors must be gracefully handled throughout the codebase to ensure application stability.

## Testing

> Full testing rules are in `rules/testing-guidelines.md` — read that file for the test step (step 7).

Key constraints applicable on every task:
- Test reports location: `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md` at project root (never inside `TESTS/`).
- Test locations: `modules/<MODULE>/TESTS/` (module-level) and `modules/<MODULE>/<SUB_MODULE>/TESTS/` (sub-module-level).

---

## Decision Making Authority

**CRITICAL RULE**: Decision-making authority always belongs to the **human developer**.

* **Agent Responsibility**: When a coding agent encounters any uncertainty, ambiguity, or situation requiring a decision, the agent **MUST**:
  1. **Stop** and clearly state the issue or question
  2. **Present** all relevant options with pros/cons
  3. **Ask** the human developer for clarification and decision
  4. **Wait** for human input before proceeding

* **Prohibited**: Agents must **NEVER**:
  - Make assumptions when requirements are unclear
  - Proceed with a "best guess" on important decisions
  - Choose between conflicting requirements without human input
  - Implement features that weren't explicitly requested

* **Examples of When to Ask**:
  - Unclear or conflicting requirements
  - Choice between multiple valid implementation approaches
  - Breaking changes that affect other modules
  - Security or architectural decisions
  - Trade-offs between performance, maintainability, or features

---

## Version Control

> Full git workflow rules are in `rules/version-control.md` — read that file for commit, branch, or PR tasks.

Key constraint applicable on every task: commit message format is `<type>(<module>): <short description>` (e.g. `feat(hostapp-backend): add endpoint`).

---

## Module-Specific Guidelines

* **Context-Aware Rules**: When working on specific modules or sub-modules, always consult the module-specific specification files following the mandatory reading order defined in the **Mandatory Reading Order** section above.

* **Precedence**: Module-specific rules take precedence over general guidelines when there is a conflict, but such conflicts should be minimized and documented.

---

# Agent Skill Priority Enforcement

When a specialized local agent skill exists for the domain of the task, it MUST be considered before specification files and eventually described in other specification files.

Whenever a local agent skill is found to be conflicting with a specification file, it must be explicitly mentioned in the report with great emphasis.

Generic solutions are only allowed if no relevant local skill applies.

---

# ⚠️ SUPER RULE — Project Rules Override All Skills

**This rule has the highest priority of any instruction in this project.**

`rules/general-guidelines.md` (this file) and any other file under `rules/` define **hard constraints** that CANNOT be overridden by agent skills, workflow files, or any other instruction source.

When ANY agent skill (e.g. `docker-expert`, `authentik-traefik-guard`, `fastapi-pro`) produces output that conflicts with a rule defined here, the rule WINS. The agent MUST:

1. Apply the rule, not the skill's suggestion.
2. Silently adapt the skill's output to comply (e.g. remove `build:` sections, move Dockerfiles to `SOURCES/`).
3. If the adaptation is non-trivial, flag the conflict explicitly to the user before proceeding.

**Concrete examples of mandatory overrides:**

| Skill output | Rule override |
|---|---|
| `build: ./backend` in docker-compose | FORBIDDEN — remove it; use `image:` only |
| `Dockerfile` at project root or in `backend/` | FORBIDDEN — move to `modules/<MODULE>/<SUB_MODULE>/SOURCES/Dockerfile` |
| `build:` section in any compose file | FORBIDDEN — all images must be pre-built |
| Test report saved inside `TESTS/reports/` | FORBIDDEN — save to `TEST_REPORTS/<timestamp>-<MODULE>/test-report.md` |
| Slug-named compose file (e.g. `docker-compose.hostapp.yml`) | FORBIDDEN — use `modules/<MODULE>/docker-compose.yml` inside `deployment_root/` |
| Slug-named env file (e.g. `.env.template`) in `deployment_root/` | FORBIDDEN — use the merged `deployment_root/.env.config` and `deployment_root/.env.secrets` |
| Hardcoded URL/value in compose when an env var exists for it | FORBIDDEN — always use `${ENV_VAR}` |
| `env_file: - .env` in a deployed compose file | FORBIDDEN — deployed compose must use `env_file: - ../../.env.config` and `- ../../.env.secrets` |

Skills are **advisory**. Rules are **mandatory**.

## Attribute what you cause

A command you run can start other processes that change the repository. `scripts/dev-cycle.sh run`
is the standing example: at an LLM node it spawns a headless agent, and that agent edits files.

**Diffs produced by a process your command started are yours.** Report them as the result of the
command you ran, never as an outside event, a coincidence, or someone else's work. "Another agent did
this" is almost always the wrong explanation and always the wrong one to reach for first — check what
you ran.

When unexplained changes appear in `git status`:

1. **Ask what you ran.** Re-read your own recent commands before looking for an external cause.
2. **Check for a child session.** `ls -lt ~/.claude/projects/<project>/*.jsonl` — a transcript newer
   than your own session's start is a process something started, most likely you.
3. **Review the changes before building on them.** They have not been reviewed just because they look
   like your style. On the occasion that produced this rule, one file was created and left unwired
   behind a comment asserting it was finished.
