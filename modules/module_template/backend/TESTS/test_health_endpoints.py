"""
Integration + contract tests for the module_template backend diagnostic probes.

Liveness (`/health`), readiness (`/ready`) and startup (`/startup`) are unauthenticated and
served at the application root (never under `/api`). The live assertions run against the
deployed backend; the degraded-path assertions are contract checks on the source, because
taking the database down mid-suite would break every other test in the run (the DB-down
behaviour is verified manually per the readiness-probe work acceptance list).
"""
from pathlib import Path

import pytest
import requests

_MAIN_PY = Path(__file__).resolve().parents[1] / "SOURCES" / "app" / "main.py"


@pytest.fixture(scope="session")
def probe_base_url(api_base_url):
    """Probes live at the application root, not under the `/api` prefix."""
    return api_base_url.rsplit('/api', 1)[0]


class TestLivenessProbe:

    def test_health_returns_200_without_auth(self, probe_base_url):
        response = requests.get(f"{probe_base_url}/health", timeout=10)
        assert response.status_code == 200
        assert response.json().get('status') == 'ok'


class TestReadinessProbe:

    def test_ready_returns_200_on_a_healthy_stack(self, probe_base_url):
        response = requests.get(f"{probe_base_url}/ready", timeout=10)
        assert response.status_code == 200
        body = response.json()
        assert body.get('database') == 'ok'
        # The JWKS is fetched lazily, so a cold cache is reported but is not a fault.
        assert body.get('jwks') in ('ok', 'not_cached')
        assert 'degraded' not in body

    def test_ready_needs_no_authentication(self, probe_base_url):
        response = requests.get(f"{probe_base_url}/ready", timeout=10)
        assert response.status_code != 401


class TestStartupProbe:

    def test_startup_reports_started_once_booted(self, probe_base_url):
        response = requests.get(f"{probe_base_url}/startup", timeout=10)
        assert response.status_code == 200
        assert response.json().get('status') == 'started'


class TestProbeContract:
    """Source-level guarantees that cannot be observed on a healthy running stack."""

    @pytest.fixture(scope="class")
    def main_source(self):
        return _MAIN_PY.read_text(encoding='utf-8')

    def test_probes_are_hidden_from_the_openapi_schema(self, main_source):
        for path in ('/health', '/ready', '/startup'):
            assert f"@app.get('{path}', include_in_schema=False)" in main_source

    def test_probes_skip_the_audit_actor_dependency(self, main_source):
        assert "PROBE_PATHS = frozenset({'/health', '/ready', '/startup'})" in main_source
        assert 'if request.url.path in PROBE_PATHS:' in main_source

    def test_ready_answers_503_and_names_the_degraded_component(self, main_source):
        assert 'return JSONResponse(status_code=503, content=body)' in main_source
        assert "body['degraded'] = [" in main_source

    def test_readiness_db_check_uses_a_dedicated_bounded_connection(self):
        database_source = (_MAIN_PY.parent / 'database.py').read_text(encoding='utf-8')
        assert 'poolclass=NullPool' in database_source
        assert "'connect_timeout': PROBE_TIMEOUT_SECONDS" in database_source
        assert 'PROBE_TIMEOUT_SECONDS = 2' in database_source

    def test_jwks_check_reads_the_cache_instead_of_fetching(self):
        auth_source = (_MAIN_PY.parent / 'auth.py').read_text(encoding='utf-8')
        assert 'def jwks_cache_state()' in auth_source
        # The probe inspects the cached keys; a refresh call would trigger a remote fetch.
        state_body = auth_source.split('def jwks_cache_state()', 1)[1].split('\ndef ', 1)[0]
        assert "'ok' if _jwks_cache['keys'] else 'not_cached'" in state_body
        assert '_refresh_jwks(' not in state_body
        assert 'requests.get' not in state_body

    def test_ready_reports_jwks_freshness(self, main_source):
        for field in ('jwks_fetched_at', 'jwks_last_outcome'):
            assert field in main_source
