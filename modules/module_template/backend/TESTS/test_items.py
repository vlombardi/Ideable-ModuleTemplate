"""
Integration tests for module_template backend API
Tests run against the deployed API endpoints (not source code)
"""
import pytest
import requests
import os


@pytest.fixture(scope="session")
def api_base_url():
    """Get API base URL from environment"""
    return os.getenv('TEMPLATE_API_URL', 'http://localhost:8002/api')


# `auth_token` / `auth_headers` deliberately live in conftest.py and are NOT redefined here.
# They used to be duplicated in this file and again inside TestCRUDWithAuth, all three reading
# TEST_AUTH_TOKEN and skipping when it was unset — which nothing ever set. A local fixture shadows
# the conftest one silently, so fixing the shared fixture would not have fixed these tests.


class TestHealthEndpoint:
    """Tests for health check endpoint"""

    def test_health_check(self, api_base_url):
        """Health endpoint should return status ok"""
        response = requests.get(f"{api_base_url.replace('/api', '')}/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'ok'


class TestAuthentication:
    """Tests for authentication requirements"""

    def test_list_items_requires_auth(self, api_base_url):
        """List items endpoint should require authentication"""
        response = requests.get(f"{api_base_url}/items")
        assert response.status_code in [401, 403]  # Unauthorized or Forbidden

    def test_create_item_requires_auth(self, api_base_url):
        """Create item endpoint should require authentication"""
        response = requests.post(
            f"{api_base_url}/items",
            json={"name": "Test Item", "description": "Test Description"}
        )
        assert response.status_code in [401, 403]

    def test_update_item_requires_auth(self, api_base_url):
        """Update item endpoint should require authentication"""
        response = requests.put(
            f"{api_base_url}/items/1",
            json={"name": "Updated Item"}
        )
        assert response.status_code in [401, 403]

    def test_delete_item_requires_auth(self, api_base_url):
        """Delete item endpoint should require authentication"""
        response = requests.delete(f"{api_base_url}/items/1")
        assert response.status_code in [401, 403]


class TestCRUDWithAuth:
    """CRUD tests with valid authentication (run against deployed system)"""

    # No local auth_headers fixture: the conftest one mints a token and asserts, before any test
    # runs, that the persona actually resolves `template.items:view`. That premise is what lets the
    # assertions below name a single expected status.

    def test_list_items_with_auth(self, api_base_url, auth_headers):
        """Should list items with valid auth token.

        This used to assert `status_code in [200, 403]` and only check the response shape when it
        happened to be 200 — so it passed whether authorization worked or not, and passed on an
        empty body. With a persona whose permissions are asserted up front, 403 is a failure.
        """
        response = requests.get(f"{api_base_url}/items", headers=auth_headers)
        assert response.status_code == 200, (
            f"the persona holds template.items:view (asserted by the auth_token fixture) but the "
            f"module refused: {response.status_code} {response.text[:300]}"
        )
        data = response.json()
        assert isinstance(data, dict)
        for key in ("items", "total", "page", "size", "pages"):
            assert key in data, f"paged response is missing {key!r}: {sorted(data)}"
        assert isinstance(data["items"], list)

    def test_create_item_with_auth(self, api_base_url, auth_headers):
        """Should create item with valid auth and permissions, and clean up after itself.

        Previously `status_code in [201, 403]`, which could not distinguish "creation works" from
        "creation is forbidden". It also left every created row behind on every run.
        """
        response = requests.post(
            f"{api_base_url}/items",
            json={"name": "Integration Test Item", "description": "Created by test"},
            headers=auth_headers
        )
        assert response.status_code == 201, (
            f"the persona holds template.items:edit but creation was refused: "
            f"{response.status_code} {response.text[:300]}"
        )
        created = response.json()
        assert created.get("name") == "Integration Test Item"

        # A test that creates must remove what it created: this suite runs repeatedly against a
        # live stack, and an accumulating table changes the counts other tests assert on.
        item_id = created.get("id")
        assert item_id, f"the created item carries no id: {created}"
        cleanup = requests.delete(f"{api_base_url}/items/{item_id}", headers=auth_headers)
        assert cleanup.status_code in (200, 204), (
            f"could not delete the item this test created (id={item_id}): "
            f"{cleanup.status_code} {cleanup.text[:200]}"
        )


class TestAPIContract:
    """Tests for API contract compliance"""

    def test_openapi_spec_available(self, api_base_url):
        """OpenAPI spec should be accessible"""
        response = requests.get(f"{api_base_url}/openapi.json")
        # May require auth, so check either 200 or 401/403
        assert response.status_code in [200, 401, 403]
        if response.status_code == 200:
            payload = response.json()
            security_schemes = payload.get('components', {}).get('securitySchemes', {})
            assert security_schemes, 'Expected OpenAPI securitySchemes to be present'
            assert any(
                scheme.get('type') == 'oauth2'
                for scheme in security_schemes.values()
                if isinstance(scheme, dict)
            ), 'Expected Swagger OAuth2 security scheme'
        
    def test_docs_endpoint(self, api_base_url):
        """Swagger docs endpoint should be accessible"""
        response = requests.get(f"{api_base_url}/docs")
        # Returns HTML, may require auth
        assert response.status_code in [200, 401, 403]

    def test_docs_oauth2_redirect_endpoint(self, api_base_url):
        """Swagger OAuth2 redirect endpoint should be reachable"""
        response = requests.get(f"{api_base_url}/docs/oauth2-redirect")
        assert response.status_code in [200, 401, 403]
