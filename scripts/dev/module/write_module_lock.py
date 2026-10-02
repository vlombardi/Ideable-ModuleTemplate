#!/usr/bin/env python3
"""Write `module.lock.json` from what the registry actually holds.

The lock is generated, never typed: every digest in it is the answer the registry gave for a published
tag, read with `docker buildx imagetools inspect`. A digest a person retypes is the hand-maintained
duplicate this repository has already watched rot. Nothing is recorded for a tag the registry does not
hold — the run stops, and no file is written.

    python3 scripts/dev/module/write_module_lock.py --version 1.2.0
    python3 scripts/dev/module/write_module_lock.py --version 1.2.0 --module sra --registry ghcr.io/owner

THE MODULE is the one this project owns: `--module`, else the single `local` module of
`modules/enabled.md` that is not host_app. THE IMAGES are the module's own, read from its
`docker-compose.yml` (`${MODULE_SLUG}.<component>:` refs, the file that decides which images exist) —
the way `write_framework_lock.py` reads host_app's. THE REGISTRY is `--registry`, else the module's
`MODULE_DOCKER_REGISTRY_PREFIX`. The file is written through `scripts/runtime/module_version.py`, the
one module that knows the schema; this script only gathers the facts.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "runtime"))

import module_version as mv  # noqa: E402  — after the path insert, on purpose


def die(message: str) -> None:
    print(f"[module-lock] {message}", file=sys.stderr)
    raise SystemExit(1)


def registry_digest(ref: str) -> str:
    """The digest the registry resolves `ref` to — the index digest for a multi-arch image."""
    done = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest.Digest}}"],
        capture_output=True, text=True,
    )
    digest = done.stdout.strip().strip('"')
    if done.returncode != 0 or not digest:
        die(f"the registry did not resolve {ref}: {done.stderr.strip() or 'no digest returned'}. "
            f"Nothing is recorded for a tag the registry does not hold.")
    return digest


def detect_module(root: Path) -> str:
    """The module this project owns: the single local module of enabled.md other than host_app."""
    enabled = root / "modules" / "enabled.md"
    found = []
    if enabled.is_file():
        for line in enabled.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            name, status = [part.strip() for part in line.split(":", 1)]
            if status.lower() == "local" and name != "host_app":
                found.append(name)
    if len(found) != 1:
        die(f"cannot tell which module to release: modules/enabled.md has {found or 'no'} local module(s) besides "
            f"host_app. Name it with --module.")
    return found[0]


def image_names(module_dir: Path, slug: str) -> list[str]:
    compose = module_dir / "docker-compose.yml"
    if not compose.is_file():
        die(f"{compose} is needed to list the module's images")
    components = sorted(set(re.findall(r"\$\{MODULE_SLUG\}\.([A-Za-z0-9_-]+):", compose.read_text(encoding="utf-8"))))
    if not components:
        die(f"{compose} references no ${{MODULE_SLUG}}.<component> image")
    return [f"{slug}.{component}" for component in components]


def env_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    found = [line.split("=", 1)[1].strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.startswith(f"{key}=")]
    return found[-1] if found else ""


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="the module project's root (default: this one)")
    parser.add_argument("--print-module", action="store_true", help="print the module this project owns (its directory name) and stop")
    parser.add_argument("--version", help="the release the lock is written for (X.Y.Z)")
    parser.add_argument("--module", help="the module's directory name under modules/ (default: the project's own)")
    parser.add_argument("--registry", help="registry prefix, e.g. ghcr.io/owner (default: the module's MODULE_DOCKER_REGISTRY_PREFIX)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.print_module:
        print(args.module or detect_module(root))
        return 0
    if not args.version:
        die("--version is required")
    if not re.match(r"^\d+\.\d+\.\d+$", args.version):
        die(f"'{args.version}' is not X.Y.Z (a module has releases, no `latest`)")

    module = args.module or detect_module(root)
    module_dir = root / "modules" / module
    descriptor = json.loads((module_dir / "module.json").read_text(encoding="utf-8")) if (module_dir / "module.json").is_file() else {}
    slug = descriptor.get("slug") or module.lower()
    registry = (args.registry or env_value(module_dir / ".env.config", "MODULE_DOCKER_REGISTRY_PREFIX")).rstrip("/")
    if not registry:
        die(f"no registry: pass --registry or set MODULE_DOCKER_REGISTRY_PREFIX in modules/{module}/.env.config")

    images: dict[str, str] = {}
    for name in image_names(module_dir, slug):
        ref = f"{registry}/{name}:{args.version}"
        print(f"[module-lock] {ref}")
        images[name] = registry_digest(ref)
    lock = mv.build_lock(version=args.version, published_at=now_utc(), name=descriptor.get("name") or module,
                         slug=slug, registry=registry, images=images)
    path = mv.write_lock(lock, root)
    print(f"[module-lock] wrote {path} for {slug} {args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
