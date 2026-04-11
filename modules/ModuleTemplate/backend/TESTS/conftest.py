"""
Test configuration for ModuleTemplate backend integration tests
Tests run against deployed API, not source code
"""
import pytest
import os


@pytest.fixture(scope="session")
def api_base_url():
    """Get API base URL from environment"""
    return os.getenv('TEMPLATE_API_URL', 'http://localhost:8002/module/template/api')


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
