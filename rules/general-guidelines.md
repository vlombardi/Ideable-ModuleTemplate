---
trigger: mandatory
---

> **CRITICAL**: These guidelines are **MANDATORY** and must be followed at all times by both human developers and coding agents. These rules cannot be ignored or bypassed under any circumstances. If there is any uncertainty about how to apply these guidelines, **always ask for clarification** rather than making assumptions.

# Repository Model

The Ideable Framework spans two repositories:

- **Main Ideable repository** — the maintainer codebase containing the full source of `HostApp` (MF 2.0 host) and `ModuleTemplate` (MF 2.0 remote reference implementation). Used exclusively by Ideable maintainers.
- **Ideable-ModuleTemplate** — a GitHub template repository derived from the main repo, used as the starting point for external module developers. In this repo, `modules/HostApp/` contains only `module.json` and `config/` (no SPECS, sub-modules, or TESTS). See `README.md` for the full description of both repositories, the push/sync scripts, and the external developer workflow.

# Project Structure
The Project is realized as a composition of modules, each module being a self-contained unit that can be built, deployed and run independently, but that can depend on other modules.
Each module is composed by one or more sub-modules, each sub-module being a self-contained unit that can be built, deployed and run independently, but that can depend on other sub-modules.

Each sub-module that depends on other sub-modules must be able to reach them using the local docker network or the host system or the external network.
The docker-compose.yml file of each module must define the dependencies between the sub-modules.

The project's structure is as follows:
- `modules/` folder: contains everything needed to build, deploy and run a module. In particular:
   - `<module_folder>`: there is a `<module_folder>` for each module, containing:
      - `.env`: the environment variables for the module
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
         - `dependencies.md`: **mandatory** — the single source of truth for all dependencies and component versions of this module. Contains inter-module dependencies, and a per-sub-module version table for every third-party library, framework, and Docker image used.
      - `TESTS/`: (optional) contains the test files for the module
- `rules/`: contains the rules for the project. These rules are mandatory and must be followed at all times by both human developers and coding agents. These rules cannot be ignored or bypassed under any circumstances. If there is any uncertainty about how to apply these rules, always ask for clarification rather than making assumptions. It contains at least `general-guidelines.md` file representing the general guidelines for the project and the starting point for any other related and referred rule files.
- `deployment_root/`: contains the deployment files for the modules and sub-modules. The contents of this folder are used to deploy the system via Docker containers. In a production environment, this folder represents the deployed system.
- `scripts/`: contains the utility scripts for the project. These scripts are used to perform common tasks, such as starting and stopping the containers, or resetting the system. It contains, for example, the scripts to start and stop the containers, or to reset the system.
- `README.md`: contains the project's documentation.
- `.gitignore`: contains the list of files and folders to ignore when committing to the repository.

## module.json format (mandatory)

Each module must include `modules/<MODULE>/module.json` defining the canonical metadata used by tooling and integration.

Required fields:
- `name`: module name (e.g. `HostApp`, `ModuleTemplate`)
- `slug`: unique lowercase slug (e.g. `hostapp`, `template`)
- `displayName`: UI-friendly name
- `role`: `host` or `remote`
- `cssPrefix`: Tailwind prefix for that module (must end with `-`)
- `frontendPort`: module frontend runtime port
- `backendPort`: module backend runtime port

`module.json` is the source of truth for:
- module registry generation,
- compose naming/packaging,
- host vs remote behavior.

# Development process

The user can ask a coding agent to execute a specific step, and the coding agent can suggest what is the step that is sound to execute in that moment.

The project development process is defined by the following steps:
1. **specifications**: during this step, one or more specification files inside one or more `SPECS` folder are defined or modified by the human developer or by a coding agent. The specifications files evaluation must follow the dependencies, starting from non depending modules and sub-modules, and then moving to depending modules and sub-modules. 
2. **coding**: during this step, one or more source files, and when needed `Dockerfile` files, are defined or modified inside `SOURCES` folders by the human developer or by a coding agent 
3. **build**: during this step all the files that need to be compiled and/or built are processed. The build step produces two kinds of outputs:
   - **Docker images**: sub-modules that have a `Dockerfile` in their `SOURCES/` folder are built into named Docker images using `docker build` (e.g. `docker build --no-cache -t <image-name> <sub-module>/SOURCES/`). The resulting image is stored in the local Docker registry. **Image names follow a strict convention** tied to the module's own `APP_SLUG` (see *Docker image naming convention* below), ensuring the same image name is produced regardless of which project performs the build.
   - **File artifacts**: sub-modules that produce non-image artifacts (e.g. SQL scripts, config files, bootstrap scripts) copy those files from `SOURCES/` into their `DIST/` folder. Sub-modules that produce only a Docker image do not need a `DIST/` folder.
   - **Compiled code**: sub-modules that produce compiled code (e.g. Python, Java, Go, etc.) create executable files or packages in their `DIST/` folder. 
4. **deployment**: during this step the contents of each sub-module's `DIST/` folder are copied to the expected position inside the `deployment_root` directory. Sub-modules that produce only a Docker image (no `DIST/`) have nothing to copy. All enabled module's `docker-compose.yml` and `.env` files are copied to `deployment_root/modules/<MODULE>` folder. All enabled modules' `.env` files are merged in order (host first, then remotes) into a single `deployment_root/.env` — keys defined by earlier modules are not overwritten by later ones. All enabled modules' compose files are then merged into `deployment_root/docker-compose.yml`. Examples: `modules/HostApp/database/DIST/initdb/datamodel.sql` → `deployment_root/modules/HostApp/database/initdb/datamodel.sql`; `modules/HostApp/docker-compose.yml` → `deployment_root/modules/HostApp/docker-compose.yml`.

5. **configuration**: during this step one or more configuration files (e.g., `.env`) are modified and/or verified to ensure that they are correct and complete
6. **execution**: during this step the modules' Docker containers are started using the module's `docker-compose.yml` file. The execution must follow the dependencies, starting from non depending modules and sub-modules, and then moving to depending modules and sub-modules. 
7. **test**: during this step the modules' sub-modules are tested applying the tests defined inside the module's `TESTS` folder and a test report is created under `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md` at the project root. The test execution must follow the dependencies, starting from non depending modules and sub-modules, and then moving to depending modules and sub-modules.

# Project Guidelines

## deployment_root folder
During the development process, the contents of root level files (e.g., script files inside the scripts folder) and modules folder contents are modified, since they represent the project definition. 

The role of the deployment_root folder is to contain the deployed system, i.e. the system as it is running in a production environment. So, it must contain the final version of all the files that are needed to run the system as the result of the deployment step.

The expected `deployment_root/` structure for multi-module deployments is:

```
deployment_root/
├── docker-compose.yml                 # merged compose for all enabled modules (generated)
├── .env                               # merged env for all enabled modules (generated)
├── module-registry.json               # generated module registry
├── start.sh
├── stop.sh
└── modules/
    ├── HostApp/
    │   ├── docker-compose.yml         # deployed HostApp compose (env_file: ../../.env)
    │   ├── database/initdb/...
    │   ├── traefik/...
    │   └── authentik/...
    └── ModuleTemplate/
        ├── docker-compose.yml         # deployed ModuleTemplate compose (env_file: ../../.env)
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
     - `.env` — the original `modules/<MODULE>/.env` copied as-is for standalone execution
   - Used for module-specific development, testing, or isolated deployment
   - Run with: `docker compose -f modules/<MODULE>/docker-compose.yml up`

2. **Composed Ecosystem Execution**: All modules run as an integrated system (production/test default)
   - `deployment_root/docker-compose.yml` — merged compose from all enabled modules, referencing the overall `.env`
   - `deployment_root/.env` — merged environment from all modules (host module first, remotes appended)
   - This is the standard execution mode for production and integration testing
   - Run with: `./deployment_root/start.sh` or `docker compose up`

### Path Resolution in Merged Compose

When Docker Compose merges multiple compose files with `-f`, it resolves **relative paths from the first compose file's directory** (HostApp). To ensure correct resolution:

- **HostApp** paths remain relative (e.g., `./database/initdb/` resolves to `deployment_root/modules/HostApp/database/initdb/`)
- **Remote modules** (non-HostApp) have paths transformed during deployment:
  - Source: `./database/initdb/file.sql`
  - Deployed: `./modules/ModuleTemplate/database/initdb/file.sql`
  - This ensures paths resolve correctly from `deployment_root/` regardless of which compose file is first

### Environment Variable Strategy

- **Standalone execution**: Uses per-module `.env` in `deployment_root/modules/<MODULE>/.env`
- **Composed execution**: Uses merged `.env` in `deployment_root/.env`
- **Container env vars**: All containers must reference variables from `${VAR_NAME}` — never hardcoded values
- **Merged `.env` precedence**: HostApp variables take priority; remote module variables with same name are prefixed or skipped

## docker-compose.yml rules

Each module's compose file is named `docker-compose.yml` and lives in the module's root folder (`modules/<MODULE>/docker-compose.yml`). During deployment, `scripts/common/build_and_deploy.py` copies it to `deployment_root/modules/<MODULE>/docker-compose.yml` and merges all enabled modules into `deployment_root/docker-compose.yml`. All compose commands are always run from `deployment_root/` using explicit `-f modules/<MODULE>/docker-compose.yml` flags.

All compose files (both per-module and the merged one) must comply with the following rules:

- **No `build:` sections**: the compose file must never contain `build:` sections. Docker images are built during the build step (step 3), not at container startup. In a production environment the images are already present in the local or remote Docker registry.
- **Image references only**: every service must reference a pre-built image by name via the `image:` key (e.g. `image: hostapp-backend:latest`). Image names must follow the *Docker image naming convention* below.
- **Docker image naming convention**: image names are derived from the module's canonical identity source, not from the project that happens to build it:
  - **HostApp**: `hostapp-<submodule>:latest` (e.g. `hostapp-frontend:latest`)
  - **All other modules**: `<module.json slug>/<submodule>:latest` (e.g. `template/frontend:latest`)
  - Build/deploy scripts must never derive module identity from a module `.env` file.
- **Docker container naming convention**: runtime container names must use the dotted prefix form `${APP_SLUG}.${MODULE_SLUG}.<container_name>` in source compose files (e.g. `${APP_SLUG}.hostapp.backend`, `${APP_SLUG}.template.template-frontend`). During deployment, the module slug is resolved per module before generating the merged compose file so each module keeps a unique dotted runtime name even when all `.env` files are merged together.
- **No `SOURCES/` path references**: volume mounts, bind mounts, and any other path references must never point to `SOURCES/` folders. All runtime files must come from the deployment step output inside `deployment_root/`.
- **No hardcoded values**: any value that has a corresponding env var defined in the module's `.env` must reference that env var (e.g. `${AUTHENTIK_INTERNAL_URL}` not `http://authentik-server:9000`).

## .env rules

Each module has its own `modules/<MODULE>/.env` containing only the env vars needed by that module's services. Project-wide values live in repo-root `project.env` and are loaded before module env files. During deployment, all enabled modules' `.env` files are merged in order (host module first, then remotes) into a single `deployment_root/.env`. Keys defined by earlier modules are never overwritten by later ones.

- **Source of truth**: `modules/<MODULE>/.env` — edit here, never in `deployment_root/.env` directly when in development. The general .env file editing can be done to change the deoployed project configuration.
- **`deployment_root/.env` is auto-generated** by `scripts/common/build_and_deploy.py` — do not edit it manually.
- **Deployed compose files** must reference the merged env via `env_file: - ../../.env` (relative path from `deployment_root/modules/<MODULE>/`).
- **Source compose files** (`modules/<MODULE>/docker-compose.yml`) use `env_file: - .env` for local development convenience.
- **No slug-based env files** (e.g. `.env.template`) exist in `deployment_root/` — the single merged `.env` replaces them all.
- **Remote module env vars must be prefixed** with the module's slug in uppercase (e.g. `TEMPLATE_POSTGRES_DB`, `TEMPLATE_POSTGRES_USER`) to avoid collisions with host module vars in the merged env. Generic names like `POSTGRES_DB` are reserved for the host module.

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
  - Deployment: describes the deployment process of the module. For instance, it can specify that the contents of the DIST folder must be directly copied to the sub-modules folder of the `deployment_root` directory (e.g., the `modules/HostApp/database/DIST/initdb/datamodel.sql` file most be copied to `deployment_root/modules/HostApp/database/initdb/datamodel.sql` directory).
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

**When a user says "implement specs" or uses the `/Specs2Sources` workflow, this means:**
- Read ALL specification files for the module/sub-module
- Implement EVERY requirement without exception
- Follow the exact structure, components, and features as specified
- Do not substitute, simplify, or redesign any specified feature

**Failure to follow these rules is considered a critical error** and requires immediate correction by re-implementing the code to match the specifications exactly.

## Enabled Modules
The project file `modules/enabled.md` describes which modules are enabled and how they are sourced. Each entry follows the format:

```
<ModuleName>: <enabled|disabled> [<local|remote>]
```

- A module that is **not enabled** will not be built, deployed, executed, tested, or configured.
- **`local`** (default when omitted) — the module's full source tree is present under `modules/<MODULE>/` and is built and deployed from source.
- **`remote`** — the module participates in the deployment but is not built locally. Its Docker images are expected to be available in a Docker registry. The registry is determined by the env var `HOSTAPP_DOCKER_REGISTRY`; if not set, images are assumed to be present in the local Docker daemon (e.g., already pulled or restored from `docker save`). In this case `modules/<MODULE>/` contains only `module.json`, `config/`, and `.env` — no SPECS or sub-module source folders.

Example:

```markdown
HostApp: enabled remote
MyModule: enabled local
LegacyModule: disabled
```

This means HostApp is included via Docker images only, MyModule is fully built from source, and LegacyModule is excluded entirely.

## Dependencies and Versions
Each module's `SPECS/dependencies.md` is the **single source of truth** for that module's dependencies and component versions. It must contain:

1. **Inter-module dependencies** — which other modules this module depends on, and why.
2. **Per-sub-module version tables** — for every sub-module, a table listing each third-party library, framework, and Docker image with its pinned version and purpose.

The project-level file `modules/dependencies.md` describes the overall inter-module dependency graph (Mermaid diagram). It must be kept in sync with each module's `SPECS/dependencies.md`.

* **Mandatory Update Rule**: `SPECS/dependencies.md` **MUST** be updated immediately whenever:
    - A new third-party library or framework is added
    - A dependency version is upgraded or downgraded
    - A dependency is removed from the project
    - A new inter-module dependency is introduced or removed

## Ports
Exposed ports are not maintained in static files. Use `scripts/runtime/list-exposed-ports.sh` to list all host-exposed ports from `deployment_root/docker-compose.yml` at any time. This is the authoritative source for firewall configuration and conflict detection.

## CSS Prefix Convention

To enforce CSS isolation across host and remote modules:

- Every module must use a Tailwind prefix equal to its module slug plus trailing `-`.
- Prefix examples:
  - HostApp: `hostapp-`
  - ModuleTemplate: `template-`
- Prefix placement must follow Tailwind modifier syntax:
  - `hover:hostapp-bg-accent`
  - `md:template-grid-cols-2`

Never use unprefixed Tailwind utility classes in module frontend source files.

## Code Quality
* **Exception Handling**: All potential exceptions and errors must be gracefully handled throughout the codebase to ensure application stability.

## Testing

### Test Organization

* **Test Locations**: Tests are organized in `TESTS/` directories at both module and sub-module levels:
  - **Module-level tests**: `modules/<MODULE>/TESTS/` - integration tests across sub-modules
  - **Sub-module-level tests**: `modules/<MODULE>/<SUB_MODULE>/TESTS/` - unit and component tests

### Test Types

Each test suite should include appropriate test types based on the sub-module:

* **Unit Tests**: Test individual functions, classes, and components in isolation
  - Must have high coverage of critical business logic
  - Should be fast and independent
  - Mock external dependencies

* **Integration Tests**: Test interactions between components within a sub-module
  - Database interactions
  - API endpoint functionality
  - Service-to-service communication

* **End-to-End Tests**: Test complete user workflows across sub-modules
  - Critical user journeys
  - Multi-sub-module interactions
  - Real-world scenarios

### Test Execution

* **Test Step**: Tests are executed during the **test** step of the development process (step 7)
* **Test Frameworks**: Use standard frameworks appropriate for each technology:
  - **Python**: `pytest`, `unittest`
  - **JavaScript/TypeScript**: `jest`, `vitest`, `cypress` (for E2E)

### Test Reports

* **Report Generation**: After running tests, generate a comprehensive report:
  - **Location**: `TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/test-report.md` at the project root
  - **Contents**: 
    - Test execution summary (passed/failed/skipped)
    - Code coverage metrics
    - Failed test details with error messages
    - Recommendations for improvements

### Test Best Practices

1. **Isolation**: Tests must be independent and not rely on execution order
2. **Clarity**: Test names should clearly describe what is being tested
3. **Maintainability**: Update tests whenever related code changes
4. **Documentation**: Document complex test scenarios and edge cases
5. **Coverage**: Aim for high coverage of critical paths, but prioritize meaningful tests over coverage percentages
6. **Speed**: Keep unit tests fast; reserve longer-running tests for integration suites

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

### Git Workflow

* **Branching Strategy**:
  - **`main`**: Production-ready code only
  - **`develop`**: Integration branch for ongoing development
  - **Feature branches**: `feature/<module>-<description>` (e.g., `feature/cam-user-auth`)
  - **Bugfix branches**: `bugfix/<module>-<description>` (e.g., `bugfix/esp-kafka-connection`)
  - **Hotfix branches**: `hotfix/<description>` (for urgent production fixes)

* **Branch Lifecycle**:
  1. Create feature branch from `develop`
  2. Implement feature with regular commits
  3. Create pull request (PR) to merge back into `develop`
  4. Code review and testing
  5. Merge to `develop` after approval
  6. Delete feature branch after merge

### Commit Guidelines

* **Commit Message Format**:
  ```
  <type>(<module>): <short description>
  
  <detailed description if needed>
  
  <references to issues/tickets if applicable>
  ```

* **Commit Types**:
  - `feat`: New feature
  - `fix`: Bug fix
  - `docs`: Documentation changes
  - `style`: Code style changes (formatting, no logic change)
  - `refactor`: Code refactoring
  - `test`: Adding or updating tests
  - `chore`: Maintenance tasks (dependencies, build, etc.)

* **Examples**:
  ```
  feat(cam-backend): add user authentication endpoint
  fix(esp-flink): resolve kafka connection timeout
  docs(general): update testing guidelines
  ```

### Pull Request Process

* **PR Requirements**:
  - Clear title and description
  - Reference to related issues/tickets
  - All tests passing
  - Code review approval from at least one team member
  - Updated documentation if appropriate
  - Updated `SPECS/dependencies.md` if applicable

* **Review Checklist**:
  - Code follows project guidelines
  - Tests are comprehensive
  - No security vulnerabilities introduced
  - Breaking changes are documented
  - Module dependencies are correctly declared

### Breaking Changes

* **Definition**: Changes that break backward compatibility or require modifications in dependent modules
* **Process**:
  1. Clearly document the breaking change in PR description
  2. Update module `SPECS/base-specs.md` with migration notes
  3. Coordinate with owners of dependent modules
  4. Plan migration strategy before merging
  5. Version appropriately (follow semantic versioning)

### .gitignore Best Practices

* **Always Ignore**:
  - Build artifacts (contents of `DIST/` folders)
  - Environment files with secrets (`.env`, not `.env.example`)
  - IDE-specific files (`.vscode/*`, `.idea/*`, except shared configs)
  - Dependency directories (`node_modules/`, `__pycache__/`, `target/`)
  - Test reports (unless specifically archived)
  - Docker volumes and data directories

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
| Slug-named env file (e.g. `.env.template`) in `deployment_root/` | FORBIDDEN — use the single merged `deployment_root/.env` |
| Hardcoded URL/value in compose when an env var exists for it | FORBIDDEN — always use `${ENV_VAR}` |
| `env_file: - .env` in a deployed compose file | FORBIDDEN — deployed compose must use `env_file: - ../../.env` |

Skills are **advisory**. Rules are **mandatory**.
