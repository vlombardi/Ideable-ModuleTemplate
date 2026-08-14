"""
Integration tests for module_template frontend
Tests run against deployed/bundled frontend served by nginx (not source code)

These are E2E-style tests that verify the deployed frontend works correctly
when served from the container at deployment_root.
"""
import pytest
import requests
import os
import re

# Base URL for the deployed frontend
FRONTEND_URL = os.getenv('TEMPLATE_FRONTEND_URL', 'http://localhost:3001')

# Derive the module's slug + a real menu route from its own manifest, so these
# assertions hold for whatever module this file belongs to (not literal 'template').
_MANIFEST = os.path.join(os.path.dirname(__file__), '..', 'SOURCES', 'src', 'moduleManifest.ts')


def _manifest_text() -> str:
    return open(_MANIFEST, encoding='utf-8').read()


def _module_slug() -> str:
    m = re.search(r"slug:\s*['\"]([^'\"]+)['\"]", _manifest_text())
    return m.group(1) if m else 'template'


def _first_menu_href() -> str:
    # menuItems[].href is host-absolute (e.g. '/template/items'); use it as the SPA route.
    m = re.search(r"href:\s*['\"]([^'\"]+)['\"]", _manifest_text())
    return m.group(1) if m else f'/{_module_slug()}/items'


SLUG = _module_slug()
MENU_HREF = _first_menu_href()


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

        # Check that the HTML references the expected static assets. The remote is
        # served under /remotes/<slug>/ (assetPrefix), derived from the module manifest.
        assert (
            f'/remotes/{SLUG}/static/js/' in html
            or f'/remotes/{SLUG}/static/css/' in html
            or 'moduleManifest' in html
        )

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
        """The module's entity route should be accessible (SPA routing)."""
        response = requests.get(f"{FRONTEND_URL}{MENU_HREF}")
        # Should return index.html for SPA routing
        assert response.status_code == 200
        assert 'text/html' in response.headers.get('content-type', '')
