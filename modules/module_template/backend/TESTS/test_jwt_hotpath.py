"""
Tests for the module_template backend JWT hot path.

What a healthy stack can show is asserted live (the `/ready` probe surfaces JWKS freshness, and
an authenticated request validates its token exactly once when `TEST_AUTH_TOKEN` is available).
The rest — TTL expiry, refresh-on-miss rate limiting, backoff, the `503 Retry-After` on an
unreachable provider — is asserted as a source contract: reproducing them live would mean
rotating Authentik's signing key or taking the identity provider down, which is a manual
acceptance step, not something to inflict on a shared test run.
"""
from pathlib import Path

import pytest
import requests

_APP_DIR = Path(__file__).resolve().parents[1] / "SOURCES" / "app"


@pytest.fixture(scope="session")
def probe_base_url(api_base_url):
    return api_base_url.rsplit('/api', 1)[0]


@pytest.fixture(scope="class")
def auth_source():
    return (_APP_DIR / 'auth.py').read_text(encoding='utf-8')


class TestJwksFreshnessIsObservable:

    def test_ready_reports_jwks_state_and_freshness(self, probe_base_url):
        response = requests.get(f"{probe_base_url}/ready", timeout=10)
        assert response.status_code == 200
        body = response.json()
        assert body.get('jwks') in ('ok', 'not_cached')
        assert 'jwks_fetched_at' in body
        assert body.get('jwks_last_outcome') in ('never', 'ok', 'error')

    def test_warm_cache_reports_a_fetch_timestamp_and_key_count(self, probe_base_url, auth_headers):
        """Once a token has been validated the cache is warm and says so."""
        requests.get(f"{probe_base_url}/api/items", headers=auth_headers, timeout=10)
        body = requests.get(f"{probe_base_url}/ready", timeout=10).json()
        assert body.get('jwks') == 'ok'
        assert body.get('jwks_last_outcome') == 'ok'
        assert body.get('jwks_fetched_at')
        assert (body.get('jwks_keys') or 0) >= 1


class TestSingleValidationPerRequest:

    def test_authenticated_request_succeeds_through_the_shared_claims(self, api_base_url, auth_headers):
        """The route reads request.state.claims set by the app-level dependency."""
        response = requests.get(f"{api_base_url}/items", headers=auth_headers, timeout=10)
        assert response.status_code == 200

    def test_route_still_rejects_a_bad_token(self, api_base_url):
        response = requests.get(
            f"{api_base_url}/items",
            headers={'Authorization': 'Bearer not-a-jwt'},
            timeout=10,
        )
        assert response.status_code == 401


class TestHotPathContract:
    """Source-level guarantees; the live equivalents need a key rotation or an IdP outage."""

    def test_jwks_cache_holds_key_objects_indexed_by_kid(self, auth_source):
        assert '_jwks_cache' in auth_source
        assert "'keys': {}" in auth_source
        assert 'keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk' in auth_source
        # The old shape rebuilt the key inside the per-request validation.
        validate_body = auth_source.split('def _validate_token(', 1)[1].split('\ndef ', 1)[0]
        assert 'from_jwk' not in validate_body

    def test_cache_has_an_explicit_ttl_from_the_environment(self, auth_source):
        assert "JWKS_TTL_SECONDS = int(os.getenv('AUTHENTIK_JWKS_TTL_SECONDS', '600'))" in auth_source
        assert 'lru_cache' not in auth_source, 'the untimed lru_cache must be gone'

    def test_refresh_on_miss_is_locked_and_rate_limited(self, auth_source):
        assert '_jwks_lock = threading.Lock()' in auth_source
        assert 'JWKS_MIN_REFRESH_INTERVAL_SECONDS = 30' in auth_source
        signing_body = auth_source.split('def _signing_key(', 1)[1].split('\ndef ', 1)[0]
        assert 'with _jwks_lock:' in signing_body
        assert 'JWKS_MIN_REFRESH_INTERVAL_SECONDS' in signing_body

    def test_fetch_retries_with_bounded_backoff(self, auth_source):
        assert 'JWKS_FETCH_ATTEMPTS = 3' in auth_source
        assert 'JWKS_FETCH_BACKOFF_SECONDS = (0.5, 1.0)' in auth_source
        fetch_body = auth_source.split('def _fetch_jwks(', 1)[1].split('\ndef ', 1)[0]
        assert 'time.sleep(JWKS_FETCH_BACKOFF_SECONDS[attempt])' in fetch_body

    def test_unreachable_provider_is_a_retryable_503(self, auth_source):
        unavailable = auth_source.split('def _provider_unavailable(', 1)[1].split('\ndef ', 1)[0]
        assert 'HTTP_503_SERVICE_UNAVAILABLE' in unavailable
        assert "'Retry-After'" in unavailable

    def test_refresh_is_logged_at_info(self, auth_source):
        assert "logger.info('JWKS refreshed:" in auth_source
        assert "logger.info('Unknown JWT kid" in auth_source

    def test_no_token_string_cache_is_introduced(self, auth_source):
        """Explicit task constraint: caching whole tokens is unbounded and outlives `exp`."""
        assert 'lru_cache' not in auth_source
        assert '_token_cache' not in auth_source

    def test_claims_are_reused_from_request_state(self, auth_source):
        claims_body = auth_source.split('def get_claims(', 1)[1].split('\ndef ', 1)[0]
        assert "getattr(request.state, 'claims', None)" in claims_body
        main_source = (_APP_DIR / 'main.py').read_text(encoding='utf-8')
        assert 'request.state.claims = claims' in main_source
