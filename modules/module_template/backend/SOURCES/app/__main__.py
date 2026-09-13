"""Console entrypoint: `python -m app`.

This exists so the container's `CMD` can be **exec form**. It replaces
`CMD python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers ${BACKEND_WORKERS:-2}`,
which was shell form only because `${BACKEND_WORKERS}` had to be expanded somewhere.

The cost of that shell form was not stylistic. `/bin/sh` became PID 1 and did not `exec`, so uvicorn
ran as its child and never received `SIGTERM`: measured, `docker stop` took **30,236 ms** and ended
in `SIGKILL`, severing every in-flight request on every deploy, scale and restart. With replicas
 a rolling restart was not rolling.

`BACKEND_WORKERS` is still expanded at runtime — here, from the environment, rather than by the
shell — so the behaviour the spec asked for is unchanged. What changes is that the Python process is
PID 1 and FastAPI's shutdown handlers actually run.

The app is passed as an **import string**, not an object: uvicorn requires that to fork workers.
"""

import logging
import os

import uvicorn

logger = logging.getLogger(__name__)

#: `0.0.0.0` inside a container is correct and intentional — the port is published deliberately by
#: compose, and binding to the loopback would make the service unreachable from the network
#: namespace it is meant to serve.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8002


def _int_env(name: str, default: int) -> int:
    """An integer from the environment, or the default if it is unset or unreadable.

    Deliberately tolerant: a malformed `BACKEND_WORKERS` should not stop the service from starting.
    It is a tuning knob, not a required setting — unlike `DATABASE_URL`, which `app/config.py`
    validates and refuses to default.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer — using %d", name, raw, default)
        return default


def main() -> None:
    host = os.getenv("APP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    port = _int_env("APP_PORT", DEFAULT_PORT)
    workers = _int_env("BACKEND_WORKERS", 2)

    logger.info("starting on %s:%d with %d worker(s)", host, port, workers)
    uvicorn.run("app.main:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    main()
