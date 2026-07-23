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


@pytest.fixture(scope="session")
def auth_token():
    """Get auth token from environment for authenticated tests"""
    token = os.getenv('TEST_AUTH_TOKEN')
    if not token:
        pytest.skip("TEST_AUTH_TOKEN not set - skipping authenticated tests")
    return token


@pytest.fixture
def auth_headers(auth_token):
    """Get auth headers with bearer token"""
    return {"Authorization": f"Bearer {auth_token}"}


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

    @pytest.fixture
    def auth_headers(self):
        """Get valid authentication headers from environment or skip"""
        token = os.getenv('TEST_AUTH_TOKEN')
        if not token:
            pytest.skip("TEST_AUTH_TOKEN not set - skipping authenticated tests")
        return {"Authorization": f"Bearer {token}"}

    def test_list_items_with_auth(self, api_base_url, auth_headers):
        """Should list items with valid auth token"""
        response = requests.get(f"{api_base_url}/items", headers=auth_headers)
        # May be 200 (success) or 403 (no permission) depending on user
        assert response.status_code in [200, 403]
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "size" in data
            assert "pages" in data
            assert isinstance(data["items"], list)

    def test_create_item_with_auth(self, api_base_url, auth_headers):
        """Should create item with valid auth and permissions"""
        response = requests.post(
            f"{api_base_url}/items",
            json={"name": "Integration Test Item", "description": "Created by test"},
            headers=auth_headers
        )
        # May be 201 (created) or 403 (no permission)
        assert response.status_code in [201, 403]


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
