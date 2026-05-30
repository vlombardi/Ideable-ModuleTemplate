# ModuleTemplate Frontend Tests

## MF 2.0 UI Composition (General Concepts)

ModuleTemplate frontend is a remote module that HostApp composes at runtime via MF 2.0.

- HostApp shell owns header/sidebar/layout and route guards.
- ModuleTemplate contributes remote pages through `./moduleManifest`.
- Runtime loading uses module registry + remote manifest endpoints.
- Default L&F should match HostApp; module-specific styling is allowed only in module scope.

## Compatible Module Creation (from `ModuleTemplate`)

When this template is cloned to create a new module, frontend compatibility requires:

1. Rename slug/prefix in `module.json`, `.env`, MF config, and `moduleManifest`.
2. Keep route/menu conventions compatible with HostApp integration rules.
3. Update specs first (`SPECS`), then frontend source implementation (`SOURCES`).
4. Run build/deploy/start and validate remote composition in HostApp runtime.

Reference workflow docs:
- `README.md` (repo root)
- `modules/HostApp/README.md`
- `modules/ModuleTemplate/README.md`

This directory contains integration tests for the ModuleTemplate frontend.

**IMPORTANT**: Tests run against the deployed/bundled frontend in `deployment_root/`,
not against source files in `SOURCES/`.

## Test Philosophy

Per the project development process (step 7), tests execute against the deployed system:
1. Build step produces Docker images
2. Deployment step copies to `deployment_root/`
3. Execution step starts containers
4. **Test step runs tests against running containers**

## Test Structure

- `test_frontend_integration.py` - E2E-style tests against deployed frontend
- `test_template_items_table_contract.py` - source-level contract checks for table controls and query behavior
- `test_lf_parity_contract.py` - source-level L&F parity contract checks against HostApp references
- `playwright/` - visual snapshot parity tests (HostApp Users vs ModuleTemplate Items)

## Running Tests

**Prerequisites**: The ModuleTemplate containers must be running in `deployment_root/`

```bash
# Set environment variables for deployed service URLs
export TEMPLATE_FRONTEND_URL=http://localhost:3001
export TEMPLATE_API_URL=http://localhost:8002/module/template/api
export TEST_AUTH_TOKEN=<valid_jwt_token>  # Optional, for authenticated tests

# Run tests from module directory
cd modules/ModuleTemplate/frontend
python -m pytest TESTS/ -v
```

### Run L&F parity checks (automated + visual)

From repository root:

```bash
chmod +x scripts/check_moduletemplate_lf_parity.sh
./scripts/check_moduletemplate_lf_parity.sh
```

Environment overrides:

- `HOSTAPP_FRONTEND_URL` (default `http://localhost:3000`)
- `TEMPLATE_FRONTEND_URL` (default `http://localhost:3001`)
- `RUN_PLAYWRIGHT=0` to run only automated parity checks without snapshots

To refresh visual baselines:

```bash
cd modules/ModuleTemplate/frontend/TESTS/playwright
npm run test:update
```

## Test Types

The suite contains two categories:

- **Runtime integration tests** against deployed frontend/backend endpoints
- **Source contract tests** that assert parity contracts and integration conventions

Runtime integration tests are NOT unit tests that import from `SOURCES/`. Instead:

- **HTTP-level tests**: Verify frontend serves correctly via nginx
- **SPA routing tests**: Verify routes return index.html
- **Integration tests**: Verify frontend can reach backend API
- **MF manifest tests**: Verify Module Federation setup

## No Source Imports

Tests in this directory **must not** contain:
- `import from '../src/...'` or similar source imports
- Direct component rendering
- Unit tests requiring build-time transpilation

Instead, tests interact with the deployed frontend via HTTP requests.
