import os
import re
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.plugins import TransactionMetaPlugin
from .audit import ActorPlugin
from .config import settings

# From `Settings`, which declares it required with no default. It used to be an `os.getenv` with a
# fallback connection string carrying a literal username and password — credentials in the source,
# and a misconfigured container that started and then failed obscurely instead of refusing to start.
DATABASE_URL = settings.DATABASE_URL
MODULE_SLUG = os.getenv('MODULE_SLUG', 'template')

# Connection pool. Left to SQLAlchemy's defaults a backend caps out at 15 connections, queues for
# 30s and then raises an opaque error; every value here is explicit so the ceiling is a decision
# rather than an accident. See the framework spec § "Connection pool and concurrency" for the
# arithmetic against Postgres `max_connections`.
POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '10'))
MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '10'))
POOL_TIMEOUT_SECONDS = int(os.getenv('DB_POOL_TIMEOUT', '10'))
POOL_RECYCLE_SECONDS = int(os.getenv('DB_POOL_RECYCLE', '1800'))
CONNECT_TIMEOUT_SECONDS = int(os.getenv('DB_CONNECT_TIMEOUT', '5'))
STATEMENT_TIMEOUT_MS = int(os.getenv('DB_STATEMENT_TIMEOUT_MS', '15000'))

# Readiness probes must never consume the last connection of the application pool, and must
# never hang longer than the probe interval — so they run on their own pool-less engine with
# an explicit connect and statement timeout.
PROBE_TIMEOUT_SECONDS = 2

make_versioned(user_cls=None, plugins=[TransactionMetaPlugin(), ActorPlugin()])

engine = create_engine(
    DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT_SECONDS,
    # Recycle before a typical idle-connection reaper closes them, and check liveness on
    # checkout: after a database restart or failover a stale pooled connection is discarded and
    # replaced instead of failing the request.
    pool_recycle=POOL_RECYCLE_SECONDS,
    pool_pre_ping=True,
    connect_args={
        'connect_timeout': CONNECT_TIMEOUT_SECONDS,
        # `application_name` makes this backend's connections identifiable in pg_stat_activity;
        # `statement_timeout` stops one pathological query from holding a worker thread forever.
        'application_name': f'{MODULE_SLUG}-backend',
        'options': f'-c statement_timeout={STATEMENT_TIMEOUT_MS}',
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

probe_engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    connect_args={
        'connect_timeout': PROBE_TIMEOUT_SECONDS,
        'options': f'-c statement_timeout={PROBE_TIMEOUT_SECONDS * 1000}',
    },
)


def schema_revision_matches_head() -> tuple[bool, str]:
    """(at_head, detail) — is the database at the revision this image expects?

    Read from `alembic_version` and compared against the newest revision file shipped in the
    image. A container serving traffic against a schema its code does not expect is the failure
    mode rolling deploys exist to avoid, so `/startup` refuses until they agree.
    """
    versions_dir = Path(__file__).resolve().parents[1] / 'alembic' / 'versions'
    heads = set()
    if versions_dir.is_dir():
        for path in versions_dir.glob('*.py'):
            match = re.search(r"^revision: str = ['\"]([^'\"]+)['\"]", path.read_text(encoding='utf-8'), re.M)
            if match:
                heads.add(match.group(1))
    if not heads:
        return True, 'no migrations shipped'

    try:
        with probe_engine.connect() as connection:
            row = connection.execute(text('SELECT version_num FROM alembic_version')).first()
    except Exception as exc:  # noqa: BLE001 — an unreachable/unmigrated DB is "not at head"
        return False, f'alembic_version unreadable: {type(exc).__name__}'

    current = row[0] if row else None
    if current is None:
        return False, 'database has no alembic revision — migrations have not run'
    if current not in heads:
        return False, f'database at {current}, image ships {sorted(heads)}'
    return True, current


def check_database() -> tuple[bool, str]:
    """Readiness check: run `SELECT 1` on the dedicated probe connection.

    Returns (ok, detail) where detail is `'ok'` or the failure class name, so the probe
    response can name the degraded component without leaking connection details.
    """
    try:
        with probe_engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return True, 'ok'
    except Exception as exc:  # noqa: BLE001 - any driver error means "not ready"
        return False, f'error: {type(exc).__name__}'


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
