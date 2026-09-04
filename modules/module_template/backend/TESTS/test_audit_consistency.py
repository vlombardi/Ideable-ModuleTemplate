"""
Tests for module_template audit-trail correctness and robustness.

The live half proves the property that actually broke when the pool-sizing work added a second worker: the
synthetic creation timestamp for a record with no history must be identical across repeated
requests, whichever worker answers. The failure paths — an unreadable transaction table, a
missing actor table — need a DB fault to reproduce, so they are asserted as source contracts and
verified by hand per the audit-correctness work acceptance list.
"""
from pathlib import Path

import pytest
import requests

_APP_DIR = Path(__file__).resolve().parents[1] / "SOURCES" / "app"
_MODULE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="class")
def audit_source():
    return (_APP_DIR / 'audit.py').read_text(encoding='utf-8')


@pytest.fixture(scope="class")
def main_source():
    return (_APP_DIR / 'main.py').read_text(encoding='utf-8')


class TestEpochIsStableAcrossWorkers:
    """With BACKEND_WORKERS=2 consecutive requests land on different workers."""

    def test_history_timestamp_is_identical_across_requests(self, api_base_url, auth_headers):
        items = requests.get(f"{api_base_url}/items", headers=auth_headers, timeout=10)
        if items.status_code != 200 or not (items.json() or {}).get('items'):
            pytest.skip('no items available to inspect history for')
        item_id = items.json()['items'][0]['id']

        timestamps = set()
        for _ in range(20):
            r = requests.get(f"{api_base_url}/items/{item_id}/history",
                             headers=auth_headers, timeout=10)
            assert r.status_code == 200, r.text
            rows = r.json().get('items') or r.json().get('versions') or []
            if rows:
                timestamps.add(rows[-1]['timestamp'])
        assert len(timestamps) <= 1, f'creation timestamp varies between workers: {timestamps}'


class TestPersistedEpoch:

    def test_epoch_is_read_from_the_database_not_the_process(self, audit_source):
        assert "SYSTEM_EPOCH_KEY = 'system_epoch'" in audit_source
        assert 'FROM module_runtime_meta WHERE key = :key' in audit_source
        getter = audit_source.split('def get_system_startup_at(', 1)[1].split('\ndef ', 1)[0]
        assert '_read_system_epoch()' in getter
        assert '_system_startup_at: datetime = datetime.now(timezone.utc)' not in audit_source, \
            'the per-process global is back'

    def test_absent_epoch_is_announced_not_silently_substituted(self, audit_source):
        getter = audit_source.split('def get_system_startup_at(', 1)[1].split('\ndef ', 1)[0]
        assert 'logger.warning(' in getter
        assert 'datetime.now(timezone.utc)' in getter, 'a fallback must still exist'

    def test_epoch_table_is_declared_in_the_model_and_created_by_the_migrations(self):
        '''The epoch table is schema, so Alembic owns it — not idempotent bootstrap DDL.

        This test used to require `CREATE TABLE IF NOT EXISTS module_runtime_meta` in
        datamodel.sql and its SPECS copy. Two files declaring one table is exactly what let four
        `au_*` columns survive in deployed databases, and `IF NOT EXISTS` is what made it
        invisible: it creates but never alters, so the copies could diverge silently. The table
        is now declared once in framework_models.py and created by the baseline migration.
        '''
        framework_models = (_APP_DIR / 'framework_models.py').read_text(encoding='utf-8')
        assert "__tablename__ = 'module_runtime_meta'" in framework_models
        assert 'primary_key=True' in framework_models

        versions = _MODULE_ROOT / 'backend' / 'SOURCES' / 'alembic' / 'versions'
        migrations = ''.join(p.read_text(encoding='utf-8') for p in versions.glob('*.py'))
        assert 'module_runtime_meta' in migrations, (
            'no migration creates module_runtime_meta — a fresh install would have no audit epoch'
        )

        # And the bootstrap must no longer create it: rows only.
        compose = (_MODULE_ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        bootstrap = compose.split('SYNC-MANAGED-BEGIN: bootstrap-service', 1)[1] \
                           .split('SYNC-MANAGED-END: bootstrap-service', 1)[0]
        assert 'CREATE TABLE' not in bootstrap.upper()

    def test_bootstrap_writes_the_epoch_idempotently(self):
        '''The epoch is written on every deploy, and stays whatever it first was.

        This used to also require the `template_runtime_meta_v1` ledger key. The guard is gone:
        the write is `ON CONFLICT DO NOTHING`, so it is already safe to repeat, and guarding it
        cost an order-dependent trap — a recorded key once stopped a block from re-running, which
        is how this very table came to be missing at deploy time.
        '''
        compose = (_MODULE_ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
        assert "INSERT INTO module_runtime_meta (key, value) VALUES ('system_epoch', NOW()) " \
               "ON CONFLICT (key) DO NOTHING;" in compose
        # ON CONFLICT is what makes re-running harmless; without it, repetition would either fail
        # or move the epoch, and synthetic creation timestamps would shift under users.
        assert 'ON CONFLICT (key) DO NOTHING' in compose


class TestAuditFailuresAreLoud:

    def test_unreadable_transactions_raise_instead_of_returning_empty(self, audit_source):
        for fn in ('def build_transaction_map(', 'def build_transaction_actor_map('):
            body = audit_source.split(fn, 1)[1].split('\ndef ', 1)[0]
            assert 'raise AuditUnavailableError' in body, f'{fn} still degrades silently'
            assert 'logger.error(' in body and 'exc_info=True' in body
            assert 'db.rollback()' in body, 'the session must stay usable'

    def test_history_endpoint_does_not_degrade_to_empty_versions(self):
        items_source = (_APP_DIR / 'routers' / 'items.py').read_text(encoding='utf-8')
        # Code only — the comment explaining why this is gone mentions the old assignment.
        code = [ln.split('#', 1)[0] for ln in items_source.splitlines()]
        assert not [ln for ln in code if 'versions = []' in ln], \
            'a DB fault would look like "never changed"'
        assert 'raise AuditUnavailableError' in items_source

    def test_audit_failure_is_answered_as_503(self, main_source):
        assert '@app.exception_handler(AuditUnavailableError)' in main_source
        handler = main_source.split('async def _audit_unavailable(', 1)[1].split('\n@', 1)[0]
        assert 'status_code=503' in handler
        assert 'Retry-After' in handler
        assert 'logger.error(' in handler


class TestActorGuardrail:

    def test_unattributed_in_request_commits_warn(self, audit_source):
        assert 'def _warn_unattributed(' in audit_source
        warn = audit_source.split('def _warn_unattributed(', 1)[1].split('\nclass ', 1)[0]
        assert 'logger.warning(' in warn
        assert '_request_path.get()' in warn, 'must only fire inside a request'
        assert audit_source.count("_warn_unattributed('") == 2, 'both injection points must warn'

    def test_request_path_is_set_and_cleared_per_request(self, main_source):
        assert 'set_request_path(request.url.path)' in main_source
        assert 'set_request_path(None)' in main_source

    def test_listener_registration_is_a_single_call_site(self, main_source):
        """Each worker is its own process; within one, the listener registers once at import."""
        assert main_source.count('register_audit_listener(engine)') == 1
        assert main_source.count('configure_mappers()') == 1
