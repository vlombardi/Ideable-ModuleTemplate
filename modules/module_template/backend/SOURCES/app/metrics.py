"""Prometheus metrics.

`prometheus-fastapi-instrumentator` supplies the per-endpoint latency histogram and status
counters; everything below it are the signals this stack actually gets paged on and that no
generic instrumentation knows about: connection-pool saturation (the pool-sizing work's ceiling), JWKS cache age
(the JWT hot-path work's self-healing rotation), and audit-path failures (the audit-correctness work's loud errors).

`/metrics` is deliberately **not** routed through Traefik — no router rule matches it, so it is
reachable only on the internal Docker network. Exposing it publicly would hand out endpoint
inventory, traffic volumes and error rates to anyone who asks.
"""
import logging
import time

from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator import metrics as default_metrics

logger = logging.getLogger(__name__)

# Incremented by the audit path when it refuses to serve a partial history. A rising
# rate here means the audit trail is unreadable — the condition that used to be a silent 200.
AUDIT_ERRORS = Counter(
    'audit_trail_errors_total',
    'Audit-trail reads that failed and returned 503 instead of a partial history',
    ['reason'],
)

POOL_IN_USE = Gauge(
    'db_pool_connections_in_use',
    'Connections currently checked out of the SQLAlchemy pool',
)
POOL_OVERFLOW = Gauge(
    'db_pool_connections_overflow',
    'Connections currently checked out beyond pool_size (into max_overflow)',
)
POOL_CAPACITY_GAUGE = Gauge(
    'db_pool_capacity',
    'pool_size + max_overflow — the ceiling in-use is measured against',
)
JWKS_CACHE_AGE = Gauge(
    'jwks_cache_age_seconds',
    'Seconds since the JWKS was last fetched; grows unbounded if refresh is failing',
)

# ---------------------------------------------------------------------------------------------
# Audit retention, which otherwise runs and reports nothing.
#
# Retention is a TimescaleDB policy added by `scripts/runtime/config/audit-retention.sh`, and it is
# OFF unless `AUDIT_RETAIN_FOR` is set. So there are two silent states, not one: never enabled, and
# enabled but no longer dropping anything. Both look identical from outside — the audit tables simply
# grow — and the first symptom is a disk alert that points nowhere near retention.
#
# `rows pruned` is deliberately NOT a counter here. The pruning is done by a background policy in the
# database, not by this process, so the application never sees the event and a counter it increments
# would be structurally incapable of observing it. The oldest chunk's age is the same information
# read from the state instead of the event: if retention is working, it stays near the retention
# window; if retention stopped, it grows without bound. A gauge that CAN be wrong is worth more than
# a counter that can only ever be zero.
AUDIT_TABLE_BYTES = Gauge(
    'audit_table_bytes',
    'On-disk size of an audit table including indexes and TimescaleDB chunks',
    ['table'],
)
AUDIT_CHUNKS = Gauge(
    'audit_table_chunks',
    'Number of TimescaleDB chunks in an audit table; unbounded growth means retention is not running',
    ['table'],
)
AUDIT_OLDEST_DATA_AGE = Gauge(
    'audit_oldest_data_age_seconds',
    'Age of the oldest row in an audit table. Compare against AUDIT_RETAIN_FOR: exceeding it means '
    'retention is enabled but no longer dropping, or was never enabled at all',
    ['table'],
)


def _observe_runtime_state() -> None:
    """Refresh the gauges that describe live state, on scrape.

    Read lazily and defensively: a metrics scrape must never be the thing that breaks the app.
    """
    try:
        from .database import MAX_OVERFLOW, POOL_SIZE, engine

        pool = engine.pool
        POOL_CAPACITY_GAUGE.set(POOL_SIZE + MAX_OVERFLOW)
        # `checkedout()` / `overflow()` live on QueuePool, not on the Pool base class that
        # `engine.pool` is typed as, so mypy cannot prove they exist. They do at runtime — the
        # engine is built with the default QueuePool — and the whole block is already inside a
        # `try` because a metrics scrape must never fail a request.
        POOL_IN_USE.set(pool.checkedout())          # type: ignore[attr-defined]
        POOL_OVERFLOW.set(max(0, pool.overflow()))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — a scrape must not fail the request
        logger.debug('pool metrics unavailable', exc_info=True)

    try:
        from .auth import _jwks_cache

        fetched_at = _jwks_cache.get('fetched_at')
        JWKS_CACHE_AGE.set(time.time() - fetched_at if fetched_at else -1)
    except Exception:  # noqa: BLE001 — a metrics scrape must never fail a request
        logger.debug("metrics: JWKS cache age unavailable", exc_info=True)

    try:
        _observe_audit_state()
    except Exception:  # noqa: BLE001 — a metrics scrape must never fail a request
        logger.debug('metrics: audit table state unavailable', exc_info=True)


def _observe_audit_state() -> None:
    """Read the audit tables' size, chunk count and oldest row, on scrape.

    One query, not one per table: retention covers every `*_version` table plus `transaction`, and a
    module with nine entities has ten of them — a per-table round trip on every scrape would make the
    metrics endpoint the most expensive thing in the process.

    Discovered from the catalog rather than listed. A hardcoded table list would silently stop
    covering a newly added entity, which is exactly the blind spot this metric exists to remove.
    """
    from sqlalchemy import text

    from .database import engine

    with engine.connect() as conn:
        rows = conn.execute(text(r"""
            SELECT c.relname AS table_name,
                   pg_total_relation_size(c.oid) AS bytes,
                   (SELECT count(*) FROM timescaledb_information.chunks ch
                     WHERE ch.hypertable_name = c.relname) AS chunks
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relkind = 'r'
               AND (c.relname LIKE '%\_version' OR c.relname = 'transaction')
        """)).fetchall()

    for name, size_bytes, chunks in rows:
        AUDIT_TABLE_BYTES.labels(table=name).set(size_bytes or 0)
        AUDIT_CHUNKS.labels(table=name).set(chunks or 0)

    # The oldest row per table, which is what says whether retention is still dropping. Queried
    # separately and defensively: `issued_at` is present on every audit table by construction
    # (audit_partitioning.py adds it), but a table mid-migration may not have it yet, and a metrics
    # scrape must not be the thing that breaks during a deploy.
    for name, _size, _chunks in rows:
        try:
            with engine.connect() as conn:
                oldest = conn.execute(
                    text(f'SELECT EXTRACT(EPOCH FROM (now() - min(issued_at))) FROM "{name}"')
                ).scalar()
            AUDIT_OLDEST_DATA_AGE.labels(table=name).set(float(oldest) if oldest is not None else 0.0)
        except Exception:  # noqa: BLE001, PERF203 — one unreadable table must not hide the others
            logger.debug("metrics: oldest-row age unavailable for %s", name, exc_info=True)


def instrument(app) -> None:
    """Attach the instrumentator and expose /metrics on the internal network only."""
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        # Probes and the scrape itself would dominate the histogram and tell nobody anything.
        excluded_handlers=['/metrics', '/health', '/ready', '/startup'],
    )
    # The library adds its default instrumentation only when none was registered, so adding our
    # own collector silently replaces the latency histogram and status counters. Add the default
    # back explicitly — without it `/metrics` returns 200 carrying only process gauges, which
    # looks healthy and answers none of the questions metrics exist for.
    instrumentator.add(default_metrics.default())
    instrumentator.add(lambda _info: _observe_runtime_state())
    instrumentator.instrument(app).expose(app, endpoint='/metrics', include_in_schema=False)
