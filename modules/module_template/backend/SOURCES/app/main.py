import os
import threading
import time

import logging

import anyio
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as SQLAlchemyPoolTimeout
from sqlalchemy.orm import configure_mappers

from .audit import (
    AuditUnavailableError,
    clear_current_user,
    register_audit_listener,
    set_current_user,
    set_request_path,
)
from .auth import authenticate_optional, jwks_cache_state
from .logging_config import actor_var, configure_logging
from .metrics import AUDIT_ERRORS, instrument
from .middleware import RequestContextMiddleware
from .audit_partitioning import apply_audit_partitioning_metadata
from .database import (
    MAX_OVERFLOW,
    POOL_SIZE,
    POOL_TIMEOUT_SECONDS,
    Base,
    check_database,
    engine,
    schema_revision_matches_head,
)
from .routers.items import router as items_router

configure_logging()

logger = logging.getLogger(__name__)


# Liveness / readiness / startup probes: unauthenticated, high-frequency, and deliberately
# exempt from JWT validation (see _audit_actor_dependency).
PROBE_PATHS = frozenset({'/health', '/ready', '/startup'})

# Set once the startup handlers have completed; read by the /startup probe.
_startup_complete = False

# Sync endpoints run in AnyIO's threadpool; sizing it to the pool keeps the queue at the database.
POOL_CAPACITY = POOL_SIZE + MAX_OVERFLOW

# Per-identity write rate limit. 0 disables it entirely.
RATE_LIMIT_WRITES_PER_MINUTE = int(os.getenv('RATE_LIMIT_WRITES_PER_MINUTE', '120'))
_WRITE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_buckets: dict[str, tuple[float, float]] = {}  # identity -> (tokens, last refill timestamp)
_buckets_lock = threading.Lock()


def _rate_limit_identity(request: Request) -> str:
    """Who to charge for this write: the authenticated user, else the peer address."""
    claims = getattr(request.state, 'claims', None) or {}
    return (
        claims.get('preferred_username')
        or claims.get('sub')
        or (request.client.host if request.client else 'unknown')
    )


def _take_token(identity: str) -> bool:
    """Classic token bucket: `RATE_LIMIT_WRITES_PER_MINUTE` tokens, refilled continuously."""
    capacity = float(RATE_LIMIT_WRITES_PER_MINUTE)
    now = time.monotonic()
    with _buckets_lock:
        tokens, last = _buckets.get(identity, (capacity, now))
        tokens = min(capacity, tokens + (now - last) * capacity / 60.0)
        if tokens < 1.0:
            _buckets[identity] = (tokens, now)
            return False
        _buckets[identity] = (tokens - 1.0, now)
        return True


async def _audit_actor_dependency(request: Request):
    """Set the audit actor for every request that carries a valid JWT.

    Must be an async generator so FastAPI runs it in the same asyncio task
    as the route handler; otherwise the ContextVar is set in a thread-pool
    context and never propagates to the handler.

    The username is resolved here rather than via `Depends(...)` so probe requests can be
    skipped entirely: a sub-dependency would be resolved before this body runs, making every
    10-second health check pay for a JWT validation.
    """
    if request.url.path in PROBE_PATHS:
        yield
        return
    # Lets the audit guardrail tell an unattributed request commit from a bootstrap/shell one.
    set_request_path(request.url.path)
    # Single validation point of the request: the claims are stored on request.state and reused
    # by get_claims, so a protected route no longer re-verifies the same token.
    claims, username = authenticate_optional(request.headers.get('authorization'))
    request.state.claims = claims
    if username:
        set_current_user(username)
        actor_var.set(username)   # every log line in this request carries who made it
        logger.debug('Audit actor set: %s', username)
    yield
    clear_current_user()
    set_request_path(None)


async def _rate_limit_dependency(request: Request):
    """Per-identity token bucket on write methods; `RATE_LIMIT_WRITES_PER_MINUTE=0` disables it.

    A dependency rather than middleware, and registered *after* the audit-actor dependency, so
    the identity comes from `request.state.claims` — the token this request already validated.
    Middleware runs before dependencies, so it would only ever see the peer address, and reading
    the JWT there unverified would let a caller bucket themselves as anyone they like.

    Counters live in this process, so with N uvicorn workers the effective ceiling is N × the
    configured value — an exact limit needs a store shared between workers, which the stack does
    not have yet. Documented in the framework spec rather than left as a surprise.
    """
    if RATE_LIMIT_WRITES_PER_MINUTE <= 0 or request.method not in _WRITE_METHODS:
        return
    identity = _rate_limit_identity(request)
    if not _take_token(identity):
        logger.warning('Rate limit hit for %s on %s %s', identity, request.method, request.url.path)
        raise HTTPException(
            status_code=429,
            detail='Too many write requests — slow down.',
            headers={'Retry-After': '60'},
        )


register_audit_listener(engine)
configure_mappers()

# Audit tables are time-partitioned hypertables; see audit_partitioning for why the metadata has
# to say so in the app as well as in alembic/env.py.
apply_audit_partitioning_metadata(Base.metadata)
# Schema creation deliberately does NOT happen here. `create_all()` at import ran DDL inside every
# uvicorn worker of every deploy — a race the pool-sizing work advisory lock only stopgapped, and a schema
# that could never evolve (it creates what is missing and alters nothing). Alembic owns the schema
# now, applied by the one-shot `template-migrations` job before this service starts.

_module_slug = os.getenv('MODULE_SLUG', 'template')
_swagger_oauth2_redirect_url = os.getenv(
    'MODULE_SWAGGER_CALLBACK_URL',
    f'/module/{_module_slug}/api/docs/oauth2-redirect',
)

app = FastAPI(
    title='module_template Backend',
    version='1.0.0',
    docs_url=None,
    openapi_url='/api/openapi.json',
    redirect_slashes=False,
    # Order matters: the audit dependency validates the token and puts the claims on
    # request.state, which the rate limiter then reads to bucket per identity.
    dependencies=[Depends(_audit_actor_dependency), Depends(_rate_limit_dependency)],
)


app.add_middleware(RequestContextMiddleware)
instrument(app)


@app.exception_handler(AuditUnavailableError)
async def _audit_unavailable(request: Request, exc: AuditUnavailableError):
    """The audit trail could not be read — say so, loudly.

    Previously these paths returned 200 with an empty or partial history, which is
    indistinguishable from a record that never changed. For a compliance artefact that is silent
    integrity loss: a monitored 503 is the honest answer.
    """
    AUDIT_ERRORS.labels(reason=str(exc)[:60]).inc()
    logger.error('Audit trail unavailable on %s %s: %s', request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={'detail': f'Audit trail temporarily unavailable ({exc}).'},
        headers={'Retry-After': '30'},
    )


@app.exception_handler(SQLAlchemyPoolTimeout)
async def _pool_exhausted(request: Request, exc: SQLAlchemyPoolTimeout):
    """Pool exhaustion is a capacity signal, not a server fault.

    Waiting out `pool_timeout` and then raising surfaced as a 500 — indistinguishable from a bug
    to a client, a load balancer, or an on-call engineer. A 503 with `Retry-After` says what
    actually happened and what to do about it.
    """
    logger.warning('Connection pool exhausted (%s): %s %s', POOL_CAPACITY, request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={'detail': 'Database connection pool exhausted — retry shortly.'},
        headers={'Retry-After': str(POOL_TIMEOUT_SECONDS)},
    )


@app.on_event('startup')
async def _size_threadpool():
    """Match the sync-endpoint threadpool to the DB pool.

    Endpoints are sync `def`, so FastAPI runs them in AnyIO's threadpool (40 threads by default).
    More threads than connections just moves the queue out of the database — where it is
    measurable — into an invisible one.
    """
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = POOL_CAPACITY
    logger.info('AnyIO threadpool sized to %d (pool_size %d + max_overflow %d)',
                POOL_CAPACITY, POOL_SIZE, MAX_OVERFLOW)


@app.on_event('startup')
async def _configure_logging():
    """Re-apply JSON logging after uvicorn configures its own handlers in each worker."""
    configure_logging()


@app.on_event('startup')
async def _mark_startup_complete():
    """Last startup handler: from here on the app has finished booting."""
    global _startup_complete
    _startup_complete = True


@app.get('/health', include_in_schema=False)
def health_check():
    """Liveness: no I/O, asserts only that the process responds."""
    return {'status': 'ok'}


@app.get('/ready', include_in_schema=False)
def readiness_check():
    """Readiness: the process can actually serve traffic (DB reachable, JWKS usable)."""
    database_ok, database_detail = check_database()
    jwks_ok, jwks_detail = jwks_cache_state()
    body = {
        'database': database_detail,
        'jwks': jwks_detail['state'],
        # Freshness of the signing keys: when they were last fetched and how that fetch went.
        'jwks_keys': jwks_detail.get('keys'),
        'jwks_fetched_at': jwks_detail.get('fetched_at'),
        'jwks_last_outcome': jwks_detail.get('last_outcome'),
    }
    if jwks_detail.get('last_error'):
        body['jwks_last_error'] = jwks_detail['last_error']
    if database_ok and jwks_ok:
        return body
    body['degraded'] = [
        name for name, ok in (('database', database_ok), ('jwks', jwks_ok)) if not ok
    ]
    return JSONResponse(status_code=503, content=body)


@app.get('/startup', include_in_schema=False)
def startup_check():
    """Startup: 200 only once the process has booted **and** the database is at the image's head.

    Tying this to the real Alembic revision is what makes it a startup probe rather than a
    self-report: a container whose migrations have not been applied is not ready to serve, and
    saying so is what lets a rolling deploy hold traffic back.
    """
    if not _startup_complete:
        return JSONResponse(status_code=503, content={'status': 'starting'})
    at_head, detail = schema_revision_matches_head()
    if not at_head:
        return JSONResponse(status_code=503, content={'status': 'schema_not_at_head', 'detail': detail})
    return {'status': 'started', 'schema': detail}


@app.get('/api')
def api_root():
    return {'message': 'module_template API', 'version': '1.0.0'}


@app.get('/api/docs')
def swagger_docs():
    return get_swagger_ui_html(
        openapi_url='openapi.json',
        title='module_template Backend - Swagger UI',
        oauth2_redirect_url=_swagger_oauth2_redirect_url,
        init_oauth={
            'usePkceWithAuthorizationCodeGrant': True,
            'clientId': os.getenv('VITE_OIDC_CLIENT_ID', ''),
        },
        swagger_ui_parameters={
            'persistAuthorization': True,
        },
    )


@app.get('/api/docs/oauth2-redirect', include_in_schema=False)
def swagger_oauth2_redirect():
    return get_swagger_ui_oauth2_redirect_html()


app.include_router(items_router, prefix='/api')
