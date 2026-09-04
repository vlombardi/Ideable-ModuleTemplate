"""Structured JSON logging.

Every log line — this application's, uvicorn's, SQLAlchemy's — is emitted as one JSON object, so
logs from several containers can be queried as data rather than grepped as prose. The formatter is
installed on the **root** handler for exactly that reason: a formatter attached only to the app's
own logger would leave uvicorn's access lines as plain text, and a stream that is 90% JSON is not
machine-readable at all.

Request-scoped fields (`request_id`, `actor`, `path`, `method`) are read from ContextVars set by
the correlation middleware, so a call site never has to thread them through.

Deliberately dependency-free. If per-call key-value logging or structured tracebacks become
worth a third-party dependency, this is the one file `structlog` would replace — see the backend
framework spec § "Observability".
"""
import json
import logging
import os
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Set by the correlation middleware for the duration of a request.
request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)
actor_var: ContextVar[str | None] = ContextVar('actor', default=None)
path_var: ContextVar[str | None] = ContextVar('path', default=None)
method_var: ContextVar[str | None] = ContextVar('method', default=None)

MODULE_SLUG = os.getenv('MODULE_SLUG', 'template')

# Attributes LogRecord always carries; anything else a caller passed via `extra` is merged into
# the JSON object rather than dropped.
_STANDARD_ATTRS = frozenset(logging.LogRecord('', 0, '', 0, '', (), None).__dict__) | {
    'message', 'asctime', 'taskName',
}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module_slug': MODULE_SLUG,
        }
        # Request scope — omitted rather than null when there is no request (startup, CLI, jobs).
        for key, var in (('request_id', request_id_var), ('actor', actor_var),
                         ('path', path_var), ('method', method_var)):
            value = var.get()
            if value is not None:
                payload[key] = value

        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith('_'):
                payload[key] = value

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload['exception'] = {
                'type': getattr(exc_type, '__name__', str(exc_type)),
                'message': str(exc_value),
                'traceback': ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            }

        # default=str so a stray datetime/UUID in `extra` degrades to a string instead of raising
        # inside the logging call and losing the line entirely.
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Install the JSON formatter on the root handler and align uvicorn's loggers with it.

    Safe to call more than once (each uvicorn worker calls it at startup).
    """
    level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setLevel(level)
        handler.setFormatter(JsonFormatter())

    # uvicorn installs its own handlers; leaving them attached would emit those lines twice —
    # once as text through uvicorn's formatter and once as JSON through root.
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
