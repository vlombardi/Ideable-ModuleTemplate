"""
Tests for module_template observability.

The formatter is exercised for real — a live handler, real records, parsed back with json.loads —
because "every line is valid JSON" is the acceptance criterion and a source grep cannot establish
it. Endpoint behaviour (`X-Request-ID` echo, `/metrics` content) is checked against the deployed
backend; the internal-only property of `/metrics` is a routing contract, checked in compose.
"""
import io
import json
import logging
from pathlib import Path

import pytest
import requests

_APP_DIR = Path(__file__).resolve().parents[1] / "SOURCES" / "app"
_MODULE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def probe_base_url(api_base_url):
    return api_base_url.rsplit('/api', 1)[0]


@pytest.fixture
def json_logs(monkeypatch):
    """Configure the real formatter against a buffer and return a reader for what it emitted."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('lc_under_test', _APP_DIR / 'logging_config.py')
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)

    buffer = io.StringIO()
    root = logging.getLogger()
    saved = root.handlers[:]
    root.handlers.clear()
    root.addHandler(logging.StreamHandler(buffer))
    lc.configure_logging()
    for handler in root.handlers:
        handler.stream = buffer
    yield lc, lambda: [json.loads(l) for l in buffer.getvalue().splitlines() if l.strip()]
    root.handlers.clear()
    root.handlers.extend(saved)


class TestJsonLogging:

    def test_every_line_is_valid_json(self, json_logs):
        lc, read = json_logs
        logging.getLogger('app').info('hello')
        logging.getLogger('sqlalchemy.engine').warning('library line')
        lines = read()
        assert len(lines) == 2, 'library logs must go through the same formatter'
        assert {l['logger'] for l in lines} == {'app', 'sqlalchemy.engine'}

    def test_required_fields_are_present(self, json_logs):
        lc, read = json_logs
        logging.getLogger('app').info('hello')
        entry = read()[0]
        for field in ('timestamp', 'level', 'logger', 'message', 'module_slug'):
            assert field in entry, f'missing {field}'

    def test_request_scope_is_bound_and_absent_outside_a_request(self, json_logs):
        lc, read = json_logs
        logging.getLogger('app').info('outside')
        lc.request_id_var.set('req-1'); lc.actor_var.set('alice')
        lc.path_var.set('/api/items'); lc.method_var.set('GET')
        logging.getLogger('app').info('inside')
        outside, inside = read()
        assert 'request_id' not in outside, 'startup lines must not fake a request scope'
        assert inside['request_id'] == 'req-1' and inside['actor'] == 'alice'
        assert inside['path'] == '/api/items' and inside['method'] == 'GET'

    def test_extra_fields_survive_and_exceptions_are_structured(self, json_logs):
        lc, read = json_logs
        logging.getLogger('app').info('done', extra={'status_code': 200, 'duration_ms': 3.5})
        try:
            raise ValueError('boom')
        except ValueError:
            logging.getLogger('app').error('failed', exc_info=True)
        access, error = read()
        assert access['status_code'] == 200 and access['duration_ms'] == 3.5
        assert error['exception']['type'] == 'ValueError'
        assert 'boom' in error['exception']['message']
        assert 'Traceback' in error['exception']['traceback']


class TestCorrelation:

    def test_supplied_request_id_is_echoed(self, probe_base_url):
        r = requests.get(f"{probe_base_url}/ready", headers={'X-Request-ID': 'test-123'}, timeout=10)
        assert r.headers.get('X-Request-ID') == 'test-123'

    def test_missing_request_id_is_generated(self, probe_base_url):
        r = requests.get(f"{probe_base_url}/ready", timeout=10)
        generated = r.headers.get('X-Request-ID')
        assert generated, 'a request without the header must still get an id'
        assert len(generated) >= 8

    def test_middleware_reuses_then_generates(self):
        source = (_APP_DIR / 'middleware.py').read_text(encoding='utf-8')
        assert "request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())" in source
        assert "response.headers[REQUEST_ID_HEADER] = request_id" in source

    def test_access_line_carries_status_and_duration(self):
        source = (_APP_DIR / 'middleware.py').read_text(encoding='utf-8')
        assert "'status_code': status_code" in source and "'duration_ms': duration_ms" in source
        assert 'QUIET_PATHS' in source, 'probes must not drown real traffic'


class TestMetrics:

    def test_metrics_endpoint_serves_prometheus_text(self, probe_base_url):
        r = requests.get(f"{probe_base_url}/metrics", timeout=10)
        assert r.status_code == 200
        assert 'http_request_duration' in r.text, 'no latency histogram'

    def test_module_specific_collectors_are_exposed(self, probe_base_url):
        body = requests.get(f"{probe_base_url}/metrics", timeout=10).text
        for metric in ('db_pool_connections_in_use', 'db_pool_capacity',
                       'jwks_cache_age_seconds', 'audit_trail_errors_total'):
            assert metric in body, f'{metric} missing from /metrics'

    def test_metrics_is_not_routed_through_traefik(self):
        """Publishing /metrics would hand out endpoint inventory and error rates.

        Read from the FILE PROVIDER, not from compose labels. This test used to inspect
        `traefik.http.routers.*` labels — which Traefik never reads, because only the file provider is
        configured. It was therefore asserting about dead configuration: the labels could have said
        anything and /metrics would have been exposed or not regardless. The horizontal-scale work removed the labels,
        which is what surfaced it.
        """
        dynamic = (_REPO_ROOT / 'modules' / 'host_app' / 'traefik' / 'SOURCES'
                   / 'dynamic.yml.template').read_text(encoding='utf-8')
        rules = [l for l in dynamic.splitlines() if 'rule:' in l]
        assert rules, 'expected Traefik router rules to inspect'
        assert not [l for l in rules if 'metrics' in l.lower()], '/metrics must stay internal'

    def test_scrape_never_breaks_the_app(self):
        source = (_APP_DIR / 'metrics.py').read_text(encoding='utf-8')
        observer = source.split('def _observe_runtime_state(', 1)[1].split('\ndef ', 1)[0]
        assert observer.count('except Exception') >= 2, 'collectors must degrade, not raise'
