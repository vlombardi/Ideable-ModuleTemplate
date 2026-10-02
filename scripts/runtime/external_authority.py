#!/usr/bin/env python3
"""The external authority — `host` or `host:port` — derived in ONE place, read by several.

`EXTERNAL_BASE_HOST` and `HOSTAPP_TRAEFIK_HTTPS_PORT` have incompatible jobs and are deliberately
kept apart: Traefik's `Host()` matcher compares the hostname with the port STRIPPED, so a port
inside `EXTERNAL_BASE_HOST` silently breaks every route, while an OIDC issuer and the API base need
the port present or the browser is sent to the wrong one. The authority is what the second kind of
consumer needs, and it is a fact about those two variables rather than a third thing to state.

WHY IT IS A MODULE AND NOT TWO SNIPPETS. Two consumers need it at different times:

  - `create-merged-configuration.sh` writes it into the merged `.env.config`, for the deployed stack;
  - `redeploy.sh` needs it BEFORE that, because it sources each module's source `.env.config` under
    `set -u` to make `VITE_*` available to the image builds — and those values are baked in.

Implementing the rule twice would put the `:443` question in two places that can disagree, which is
the shape this whole change exists to remove. Same reasoning as `scripts/runtime/framework_version.py`:
one file computes it, everything else asks.

`:443` IS OMITTED, AND THAT IS NOT COSMETIC. An OIDC issuer must match byte-for-byte what Authentik
emits, and Authentik emits `https://host/...`; `https://host:443/...` is a different string and
fails discovery.

Usage:
    external_authority.py                 # from EXTERNAL_BASE_HOST / HOSTAPP_TRAEFIK_HTTPS_PORT
    external_authority.py --host h --port p
"""
import argparse
import os
import sys

#: The port that must NOT appear in the authority, because it is https' default.
DEFAULT_HTTPS_PORT = "443"


class PortInHostError(ValueError):
    """`EXTERNAL_BASE_HOST` carries a port — the one mistake that breaks Traefik silently."""


class NoHostError(ValueError):
    """No `EXTERNAL_BASE_HOST` at all. Refused rather than returned as an empty authority.

    An empty authority composes `https:///auth`, which every consumer accepts and no consumer can
    use — the same silent-wrong-URL class this derivation exists to remove.
    """


def external_authority(host, port=None):
    """`host` when the stack is on 443, `host:port` otherwise.

    Raises PortInHostError when `host` carries a port: putting it there is the only way to make the
    URLs right without this derivation, and it breaks every Traefik route instead, with no error
    from either side.
    """
    host = (host or "").strip()
    if not host:
        raise NoHostError()
    if ":" in host:
        raise PortInHostError(host)
    port = (port or "").strip() or DEFAULT_HTTPS_PORT
    if port == DEFAULT_HTTPS_PORT:
        return host
    return f"{host}:{port}"


def _message(host):
    return (
        f"EXTERNAL_BASE_HOST must be a HOSTNAME, with no port: got '{host}'.\n"
        "Traefik matches Host() with the port stripped, so a port here breaks every route while "
        "appearing to fix the URLs.\n"
        "Put the port in HOSTAPP_TRAEFIK_HTTPS_PORT (project.env.config) instead — every external "
        "URL derives it from there."
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("EXTERNAL_BASE_HOST", ""))
    ap.add_argument("--port", default=os.environ.get("HOSTAPP_TRAEFIK_HTTPS_PORT", ""))
    args = ap.parse_args(argv)
    try:
        sys.stdout.write(external_authority(args.host, args.port) + "\n")
    except NoHostError:
        sys.stderr.write(
            "EXTERNAL_BASE_HOST is not set. Every external URL is built from it, and an empty "
            "value composes 'https:///...' — accepted everywhere and usable nowhere.\n"
            "Set it in project.env.config.\n")
        return 1
    except PortInHostError as exc:
        sys.stderr.write(_message(exc.args[0]) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
