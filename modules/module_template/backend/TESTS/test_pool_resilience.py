"""
Tests for the module_template backend connection pool and concurrency settings.

The live half checks what a healthy deployed stack can show: the backend still serves traffic and
its probes stay green. The pool's real failure modes — exhaustion under load, a database restart,
a query hitting `statement_timeout` — need a load generator or a `docker restart`, so they are
asserted here as source contracts and verified by hand per the pool-sizing work acceptance list.
"""
from pathlib import Path

import pytest
import requests

_APP_DIR = Path(__file__).resolve().parents[1] / "SOURCES" / "app"
_SOURCES = _APP_DIR.parent


@pytest.fixture(scope="session")
def probe_base_url(api_base_url):
    return api_base_url.rsplit('/api', 1)[0]


@pytest.fixture(scope="class")
def database_source():
    return (_APP_DIR / 'database.py').read_text(encoding='utf-8')


@pytest.fixture(scope="class")
def main_source():
    return (_APP_DIR / 'main.py').read_text(encoding='utf-8')


class TestBackendStillServes:

    def test_ready_probe_is_green(self, probe_base_url):
        """A mis-sized pool or a botched engine config shows up here first."""
        response = requests.get(f"{probe_base_url}/ready", timeout=10)
        assert response.status_code == 200
        assert response.json().get('database') == 'ok'

    def test_repeated_requests_do_not_exhaust_the_pool(self, probe_base_url):
        """Connections must be returned to the pool; a leak turns this into 503s."""
        for _ in range(25):
            assert requests.get(f"{probe_base_url}/ready", timeout=10).status_code == 200


class TestPoolConfiguration:

    def test_engine_is_explicitly_parameterised(self, database_source):
        for setting in ('pool_size=POOL_SIZE', 'max_overflow=MAX_OVERFLOW',
                        'pool_timeout=POOL_TIMEOUT_SECONDS', 'pool_recycle=POOL_RECYCLE_SECONDS'):
            assert setting in database_source
        assert 'create_engine(DATABASE_URL)' not in database_source, 'the unparameterised engine is back'

    def test_stale_connections_are_detected(self, database_source):
        """Without pre-ping, a database restart costs one failed request per pooled connection."""
        assert 'pool_pre_ping=True' in database_source

    def test_connections_are_identifiable_and_bounded(self, database_source):
        assert "'application_name': f'{MODULE_SLUG}-backend'" in database_source
        assert "'connect_timeout': CONNECT_TIMEOUT_SECONDS" in database_source
        assert "-c statement_timeout={STATEMENT_TIMEOUT_MS}" in database_source

    def test_pool_settings_come_from_the_environment(self, database_source):
        for var in ('DB_POOL_SIZE', 'DB_MAX_OVERFLOW', 'DB_POOL_TIMEOUT',
                    'DB_POOL_RECYCLE', 'DB_CONNECT_TIMEOUT', 'DB_STATEMENT_TIMEOUT_MS'):
            assert f"os.getenv('{var}'" in database_source

    def test_probe_engine_stays_isolated_from_the_application_pool(self, database_source):
        """The readiness-probe work's guarantee must survive the pool-sizing work: the probe never queues behind traffic."""
        assert 'poolclass=NullPool' in database_source


class TestConcurrencyContract:

    def test_container_runs_multiple_workers(self):
        """Multiple workers, with the count configurable at runtime — the property, not a mechanism.

        This used to assert `--workers ${BACKEND_WORKERS:-2}` in the Dockerfile and, explicitly,
        that the CMD was *not* exec form — "exec form cannot expand BACKEND_WORKERS". That premise
        was wrong, and expensive: the shell form it mandated left `/bin/sh` as PID 1, so `SIGTERM`
        never reached uvicorn and `docker stop` took 30,236 ms before `SIGKILL`, severing in-flight
        requests on every deploy. `app/__main__.py` reads the value from the environment instead, so
        the count is still runtime-configurable and the application is PID 1.
        """
        dockerfile = (_SOURCES / 'Dockerfile').read_text(encoding='utf-8')
        assert 'CMD ["python", "-m", "app"]' in dockerfile, (
            'shell form makes /bin/sh PID 1 and SIGTERM never arrives'
        )
        entrypoint = (_SOURCES / 'app' / '__main__.py').read_text(encoding='utf-8')
        assert '"BACKEND_WORKERS"' in entrypoint and 'workers=workers' in entrypoint

    def test_no_import_time_ddl_at_all(self, database_source, main_source):
        """The advisory lock was a stopgap for DDL at import; the DDL is gone, so the lock is too.

        This test used to assert that `create_all()` ran inside `schema_lock()`. Serialising
        import-time DDL was the best available answer while the schema was created by the
        traffic-serving process — but it only made the race orderly, and `create_all` could still
        never alter an existing table, so no deployed schema could evolve. A one-shot migrations
        job owns the schema now (see docker-compose.yml), which is strictly better than a lock:
        the DDL happens once, before any worker starts, and is observable as a deploy step.
        """
        assert 'Base.metadata.create_all' not in main_source, (
            'create_all() is back in main.py — the schema belongs to the migrations job'
        )
        assert 'def schema_lock()' not in database_source, (
            'schema_lock() is dead code once no import-time DDL remains'
        )
        # And the replacement must actually be wired: readiness depends on the schema matching.
        assert 'schema_revision_matches_head()' in main_source

    def test_threadpool_is_sized_to_the_pool(self, main_source):
        assert 'POOL_CAPACITY = POOL_SIZE + MAX_OVERFLOW' in main_source
        assert 'limiter.total_tokens = POOL_CAPACITY' in main_source

    def test_pool_exhaustion_is_a_retryable_503(self, main_source):
        assert '@app.exception_handler(SQLAlchemyPoolTimeout)' in main_source
        handler = main_source.split('async def _pool_exhausted(', 1)[1].split('\n@', 1)[0]
        assert 'status_code=503' in handler
        assert "'Retry-After': str(POOL_TIMEOUT_SECONDS)" in handler


class TestWriteRateLimiting:

    def test_limiter_covers_write_methods_only(self, main_source):
        assert "_WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})" in main_source
        assert 'request.method not in _WRITE_METHODS' in main_source

    def test_limiter_is_switchable_off(self, main_source):
        assert "RATE_LIMIT_WRITES_PER_MINUTE = int(os.getenv('RATE_LIMIT_WRITES_PER_MINUTE', '120'))" in main_source
        assert 'if RATE_LIMIT_WRITES_PER_MINUTE <= 0' in main_source

    def test_limiter_buckets_by_authenticated_identity(self, main_source):
        """Middleware would run before the audit dependency and only ever see the peer address."""
        assert 'Depends(_audit_actor_dependency), Depends(_rate_limit_dependency)' in main_source
        assert "@app.middleware('http')" not in main_source
        identity = main_source.split('def _rate_limit_identity(', 1)[1].split('\ndef ', 1)[0]
        assert "getattr(request.state, 'claims', None)" in identity

    def test_limit_breach_is_a_429_with_retry_after(self, main_source):
        body = main_source.split('async def _rate_limit_dependency(', 1)[1].split('\nregister_audit_listener', 1)[0]
        assert 'status_code=429' in body
        assert "'Retry-After': '60'" in body
