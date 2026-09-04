# ── builder ─────────────────────────────────────────────────────────────────────────────────────
# Stays on `slim`, not alpine: psycopg2-binary and cryptography ship `manylinux` wheels that need
# glibc. slim (bookworm) and distroless-debian12 are both glibc 2.36, so what is built here runs
# there unchanged. Alpine is musl and would force a source build of both.
FROM python:3.11-slim@sha256:be1575ed968de893bd54f4c56315ff7c4736ce522c1bca08fd521731aafc0d76 AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt .

# --target, not a normal install: the runtime has no pip, so the dependencies have to arrive as a
# directory that PYTHONPATH can point at.
# --no-compile: PYTHONDONTWRITEBYTECODE stops the RUNTIME writing bytecode, but pip
# byte-compiles what it installs regardless, and 1,034 .pyc were being baked into /deps.
# They are dead weight in a read-only image: nothing can invalidate or replace them, and
# the interpreter recompiles to memory on import anyway.
RUN pip install --no-cache-dir --no-compile --target=/deps -r requirements.txt

# ── runtime ─────────────────────────────────────────────────────────────────────────────────────
# Distroless: no shell, no package manager, no pip. An RCE lands in an image with nothing to run.
#
# Two consequences that are handled elsewhere and must stay handled:
#   * `docker exec <c> sh -c …` does not work. `docker exec <c> python …` does, which is what
#     scripts/runtime/authz.sh and run_enabled_tests.sh use. See docs/RUNBOOK.md.
#   * there is no console-script directory on PATH, so `alembic` is run as `python -m alembic`
#     (docker-compose.yml, migrations job).
#
# `:nonroot` ships uid 65532 and sets USER itself; it is repeated below because the guideline asks
# for the UID to be explicit in the Dockerfile, and because an image that changes its default must
# not silently change ours.
FROM gcr.io/distroless/python3-debian12:nonroot@sha256:7d1042ce588ab97019fe95c24ffca7bc5a82ccdac572511d5e09bda4435c89c5

WORKDIR /app

# PYTHONUTF8: a distroless image carries no locale, so Python's preferred encoding falls back to
# ASCII. Anything that reads a file with `encoding="locale"` then fails on the first non-ASCII byte
# — alembic.ini did, on an em dash in a comment, and the migrations job the whole stack waits on
# died with a UnicodeDecodeError. UTF-8 mode makes the encoding a property of the application
# rather than of the environment it happens to run in.
ENV PYTHONPATH=/deps \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

COPY --from=builder --chown=65532:65532 /deps /deps
COPY --chown=65532:65532 app/ ./app/
# Migrations travel with the image: the running container is the thing that knows which revision its
# code expects, and /startup compares the database against exactly these files.
COPY --chown=65532:65532 alembic.ini ./alembic.ini
COPY --chown=65532:65532 alembic/ ./alembic/

USER 65532:65532

EXPOSE 8002

# ENTRYPOINT is reset deliberately. The distroless base sets `ENTRYPOINT ["/usr/bin/python3.11"]`,
# so an inherited entrypoint would PREPEND python to whatever CMD or `command:` says — turning
# `["python", "-m", "app"]` into `python3.11 python -m app`, which fails with
# "can't open file '/app/python'". Resetting it keeps every command in this repo readable as the
# full command it actually runs, and survives the base image changing its entrypoint.
#
# `python` resolves on PATH (/usr/bin/python), so healthchecks can exec it directly — which they must,
# since a distroless image has no shell for CMD-SHELL.
ENTRYPOINT []

# EXEC form, via app/__main__.py. The shell form this replaced left `/bin/sh` as PID 1
# without exec'ing, so uvicorn never received SIGTERM: `docker stop` took 30,236 ms and ended in
# SIGKILL. BACKEND_WORKERS, APP_HOST and APP_PORT are read from the environment by __main__.py, so
# the bind and the worker count are still runtime-configurable with no rebuild.
CMD ["python", "-m", "app"]
