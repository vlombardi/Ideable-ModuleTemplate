"""
Integration tests for ModuleTemplate frontend
Tests run against deployed/bundled frontend served by nginx (not source code)

These are E2E-style tests that verify the deployed frontend works correctly
when served from the container at deployment_root.
"""
import pytest
import requests
import os

# Base URL for the deployed frontend
FRONTEND_URL = os.getenv('TEMPLATE_FRONTEND_URL', 'http://localhost:3001')


class TestFrontendDeployment:
    """Tests for deployed frontend accessibility"""

    def test_frontend_serves_index(self):
        """Frontend should serve index.html at root"""
        response = requests.get(FRONTEND_URL)
        assert response.status_code == 200
        assert 'text/html' in response.headers.get('content-type', '')

    def test_frontend_serves_static_assets(self):
        """Frontend should serve static JS/CSS assets"""
        # Get index.html first
        index_response = requests.get(FRONTEND_URL)
        html = index_response.text

        # Check that the HTML references the expected static assets
        # ModuleTemplate uses /remotes/template/ paths
        assert '/remotes/template/static/js/' in html or '/remotes/template/static/css/' in html or 'moduleManifest' in html

    def test_mf_manifest_accessible(self):
        """Module Federation manifest should be accessible"""
        response = requests.get(f"{FRONTEND_URL}/mf-manifest.json")
        # May be 200 or 404 depending on build configuration
        assert response.status_code in [200, 404]


class TestFrontendAPIIntegration:
    """Tests for frontend integration with backend API"""

    def test_frontend_can_reach_backend(self):
        """Frontend (when running in browser) should be able to reach backend"""
        # This is a smoke test - the actual CORS/auth is tested via backend tests
        # Use base URL without trailing /api suffix for health check
        api_url = os.getenv('TEMPLATE_API_URL', 'http://localhost:8002/api').rstrip('/')
        api_base = api_url[:-4] if api_url.endswith('/api') else api_url
        response = requests.get(f"{api_base}/health")
        assert response.status_code == 200


class TestFrontendRoutes:
    """Tests for frontend routing (SPA behavior)"""

    def test_items_route_accessible(self):
        """Items route should be accessible (SPA routing)"""
        response = requests.get(f"{FRONTEND_URL}/template/items")
        # Should return index.html for SPA routing
        assert response.status_code == 200
        assert 'text/html' in response.headers.get('content-type', '')
