"""Request correlation.

A request crosses Traefik and one or more module backends; without a shared id, reconstructing it
from logs means guessing by timestamp across containers. This middleware takes `X-Request-ID` from
the inbound request (so the id is preserved across module-to-module calls), generates one when it
is absent, puts it on every log line for that request, and echoes it back so the caller can quote
it in a bug report.

It also emits the access log — one JSON line per request carrying `status_code` and
`duration_ms`, which is what the latency SLO is measured from.
"""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .logging_config import actor_var, method_var, path_var, request_id_var

logger = logging.getLogger('request')

REQUEST_ID_HEADER = 'X-Request-ID'
# Probes are high-frequency and uninteresting; logging them buries real traffic.
QUIET_PATHS = frozenset({'/health', '/ready', '/startup', '/metrics'})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind the request id (and friends) to the log context for the life of the request."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        tokens = [
            request_id_var.set(request_id),
            path_var.set(request.url.path),
            method_var.set(request.method),
        ]
        started = time.perf_counter()
        status_code = 500  # if the handler raises, the access line still reports a real status
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if request.url.path not in QUIET_PATHS:
                # The actor is set by the audit dependency, which has run by now.
                logger.info(
                    '%s %s %s', request.method, request.url.path, status_code,
                    extra={'status_code': status_code, 'duration_ms': duration_ms},
                )
            for token, var in zip(tokens, (request_id_var, path_var, method_var)):
                var.reset(token)
            actor_var.set(None)
