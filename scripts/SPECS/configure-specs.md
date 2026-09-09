# configure.sh specification

## Purpose
Inspect exposed service ports and interactively resolve host and cross-module port conflicts.

## Contract
- Support source and deployed contexts and load secrets before config values.
- Discover enabled modules from `modules/enabled.md`, or all module directories when no enabled list exists.
- Derive exposed host ports from each module's `docker-compose.yml` and resolve their values through the project and module env files.
- Detect ports already used by the host, ports assigned to multiple services, and ports already owned by the current Compose project.
- Report the owning process/container when possible.
- For each conflict, accept a blank response to retain the current value; validate replacements as integers from 1 through 65535 and warn before accepting an occupied port.
- Update the authoritative project/module env file and synchronize module fallback/default values when a project-level port is changed.
- Provide optional interactive updates for `EXTERNAL_BASE_HOST`, `APP_NAME`, `APP_SLUG`, and `PROJECT_ROOT`; normalize `APP_SLUG` to lowercase safe characters and convert module identity values to root references.
- Print a final exposed-port recap and the command needed to apply changes.
- Preserve unrelated file content and never modify compose files, containers, or Git history directly; only the selected project/module environment file may be updated in place.
