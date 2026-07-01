# ModuleTemplate Backend Tests

## MF 2.0 UI Composition (General Concepts)

ModuleTemplate backend is part of a remote module composed into HostApp at runtime via MF 2.0.

- HostApp owns shell UI and shared auth context.
- ModuleTemplate provides module-specific pages and API behavior.
- Backend integration must preserve JWT validation and Authentik claim-based permission checks.

These tests verify the remote backend remains compatible in a composed HostApp + remotes runtime.

## Compatible Module Creation (from `ModuleTemplate`)

For new modules cloned from `ModuleTemplate`, backend onboarding should include:

1. Copy template module folder and rename module identity (slug, env vars, permissions).
2. Update specs (`SPECS`) before backend implementation changes.
3. Keep permission namespace `<slug>.<resource>:<action>`.
4. Keep JWKS validation and HostApp permission-context integration.
4. Keep JWKS validation and Authentik claim-based authorization integration.
5. Run full build/deploy/start flow and execute integration tests against containers.

Reference workflow docs:
- `IDEABLE-README.md` (repo root)
- `modules/HostApp/README.md`
- `modules/ModuleTemplate/MODULE-README.md`

This directory contains integration tests for the ModuleTemplate backend API.

**IMPORTANT**: Tests run against the deployed API endpoints (running in Docker containers),
not against source code directly.

## Test Philosophy

Per the project development process (step 7), tests execute against the deployed system:
1. Build step produces Docker images
2. Deployment step copies to `deployment_root/`
3. Execution step starts containers (including `template-backend` and `template-database`)
4. **Test step runs tests against running containers**

## Test Structure

- `conftest.py` - Pytest fixtures for API base URL and authentication
- `test_items.py` - Integration tests for template_items API endpoints

## Running Tests

**Prerequisites**: The ModuleTemplate containers must be running in `deployment_root/`

```bash
# Set environment variables
export TEMPLATE_API_URL=http://localhost:8002/module/template/api
export TEST_AUTH_TOKEN=<valid_jwt_token>  # Optional, for authenticated tests

# Run tests
cd modules/ModuleTemplate/backend
pytest TESTS/ -v
```

## Test Types

These are **integration tests** that:
- Call the actual HTTP API endpoints
- Test authentication and authorization requirements
- Verify API contract compliance
- Run against the deployed container, not source code

## No Source Imports

Tests in this directory **must not** contain:
- `from app.main import app` or similar source imports
- `from app.database import ...` direct database access
- Unit tests that bypass the API layer

Instead, tests use `requests` library to call the deployed API.

## Authentication

For tests requiring authentication:
1. Obtain a valid JWT token from the running Authentik instance
2. Set `TEST_AUTH_TOKEN` environment variable
3. Tests will skip authenticated scenarios if token is not provided

## Test Coverage

The tests cover:
- Health check endpoint
- CRUD operations for template_items
- Authentication requirements (JWT validation)
- Permission-based access control
- Error handling

## Permissions

The tests verify that endpoints require specific permissions:
- `items:view` - for listing/reading items
- `items:edit` - for creating, updating, and deleting items
