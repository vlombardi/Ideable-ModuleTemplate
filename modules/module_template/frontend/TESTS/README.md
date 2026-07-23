# module_template Frontend Tests

## MF 2.0 UI Composition (General Concepts)

module_template frontend is a remote module that host_app composes at runtime via MF 2.0.

- host_app shell owns header/sidebar/layout and route guards.
- module_template contributes remote pages through `./moduleManifest`.
- Runtime loading uses module registry + remote manifest endpoints.
- Default L&F should match host_app; module-specific styling is allowed only in module scope.

## Compatible Module Creation (from `module_template`)

When this template is cloned to create a new module, frontend compatibility requires:

1. Rename slug/prefix in `module.json`, `.env`, MF config, and `moduleManifest`.
2. Keep route/menu conventions compatible with host_app integration rules.
3. Update specs first (`SPECS`), then frontend source implementation (`SOURCES`).
4. Run build/deploy/start and validate remote composition in host_app runtime.

Reference workflow docs:
- `IDEABLE-README.md` (repo root)
- `modules/host_app/README.md`
- `modules/module_template/MODULE-README.md`

This directory contains integration tests for the module_template frontend.

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
- `test_lf_parity_contract.py` - source-level L&F parity contract checks against host_app references
- `playwright/` - visual snapshot parity tests (host_app Users vs module_template Items)

## Running Tests

**Prerequisites**: The module_template containers must be running in `deployment_root/`

```bash
# Set environment variables for deployed service URLs
export TEMPLATE_FRONTEND_URL=http://localhost:3001
export TEMPLATE_API_URL=http://localhost:8002/module/template/api
export TEST_AUTH_TOKEN=<valid_jwt_token>  # Optional, for authenticated tests

# Run tests from module directory
cd modules/module_template/frontend
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
cd modules/module_template/frontend/TESTS/playwright
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
