#!/usr/bin/env python3
"""Push locally built module images to a Docker registry.

Usage:
  python3 scripts/common/push_module_images_to_registry.py -a
  python3 scripts/common/push_module_images_to_registry.py -a -t v1.0.0-latest
  python3 scripts/common/push_module_images_to_registry.py host_app module_template
  python3 scripts/common/push_module_images_to_registry.py -a -t v1.0.0-latest --single-arch
  python3 scripts/common/push_module_images_to_registry.py -a -t v1.0.0-latest --platform linux/amd64,linux/arm64

Each module's `.env.config` file may declare `MODULE_DOCKER_REGISTRY_PREFIX` (e.g.
`ghcr.io/OWNER`). The push script reads this per-module value to know which
registry to push to. If a module does not set `MODULE_DOCKER_REGISTRY_PREFIX`, the
optional `--registry` CLI argument is used as a fallback.

The script validates the selected modules, checks that the expected local Docker
images exist, and by default builds and pushes a multi-arch manifest with docker
buildx. Use --single-arch to tag/push the existing local image instead.

Multi-arch pushes bootstrap a dedicated docker-container buildx builder when the
current builder cannot handle multi-platform output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = PROJECT_ROOT / "modules"
PROJECT_ENV_PATH = PROJECT_ROOT / "project.env.config"
ENABLED_PATH = MODULES_DIR / "enabled.md"

REQUIRED_COMMON_FILES = (".env.config", "docker-compose.yml", "module.json")

MULTIARCH_BUILDER_NAME = "ideable-multiarch-builder"

IMAGE_LINE_RE = re.compile(r"^\s*image:\s*([^\s#]+)\s*$", re.IGNORECASE)
ENABLED_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)\s*:\s*(?P<status>local|remote|disabled)\s*$",
    re.IGNORECASE,
)
ALT_ENABLED_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)\s+(?P<status>local|remote|disabled)(?:\s+(?P<mode>local|remote))?\s*$",
    re.IGNORECASE,
)


@dataclass
class ModulePushReport:
    name: str
    slug: str
    status: str
    path: Path
    validation_errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    local_images: list[str] = field(default_factory=list)
    pushed_images: list[tuple[str, str]] = field(default_factory=list)
    push_errors: list[str] = field(default_factory=list)
    registry: str = ""

    @property
    def has_errors(self) -> bool:
        return bool(self.validation_errors or self.push_errors)

    @property
    def pushed_count(self) -> int:
        return len(self.pushed_images)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Push locally built Docker images for enabled modules to a registry",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Process every enabled module declared as 'local' in modules/enabled.md",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List available modules from modules/enabled.md and exit.",
    )
    parser.add_argument(
        "-t",
        "--tag",
        dest="tag",
        default="",
        help="Optional tag to append to every pushed image (e.g. v1.0.0-latest)",
    )
    parser.add_argument(
        "--single-arch",
        action="store_true",
        help="Push the existing local single-arch image instead of building a multi-arch manifest.",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Force a full rebuild without Docker cache (default: on). Use --no-no-cache to allow cached layers.",
    )
    parser.add_argument(
        "--platform",
        dest="platform",
        default="linux/amd64,linux/arm64",
        help="Comma-separated platform list for multi-arch builds (default: linux/amd64,linux/arm64)",
    )
    parser.add_argument(
        "--registry",
        dest="registry",
        default="",
        help="Optional fallback registry prefix (e.g. ghcr.io, ghcr.io/OWNER) used when a module's .env does not define MODULE_DOCKER_REGISTRY_PREFIX.",
    )
    parser.add_argument(
        "modules",
        nargs="*",
        help="One or more module names to process (e.g. host_app module_template)",
    )
    return parser.parse_args()


def read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "MODULE_DOCKER_REGISTRY_PREFIX" and value and not value.endswith("/"):
            value = value + "/"
        env[key] = value
    return env


def resolve_git_owner() -> str:
    env_owner = os.getenv("GITHUB_REPOSITORY_OWNER", "").strip()
    if env_owner:
        return env_owner

    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""

    remote_url = completed.stdout.strip()
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?$", remote_url)
    if match:
        return match.group("owner")
    return ""


def resolve_registry_prefix(registry_arg: str, label: str = "--registry") -> str:
    """Resolve and optionally expand a registry prefix."""
    registry = registry_arg.strip().rstrip("/")
    if not registry:
        return ""
    if registry == "ghcr.io":
        owner = resolve_git_owner()
        if owner:
            registry = f"ghcr.io/{owner}"
        else:
            print(
                f"ERROR: {label} is ghcr.io but no repository owner could be resolved. "
                "Use ghcr.io/<owner> or export GITHUB_REPOSITORY_OWNER."
            )
            sys.exit(1)
    return registry


def parse_enabled_modules() -> dict[str, str]:
    if not ENABLED_PATH.exists():
        print(f"ERROR: {ENABLED_PATH} not found")
        sys.exit(1)

    enabled: dict[str, str] = {}
    for raw_line in ENABLED_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        match = ENABLED_LINE_RE.match(line) or ALT_ENABLED_LINE_RE.match(line)
        if not match:
            continue

        name = match.group("name")
        status = match.group("status").lower()
        mode = match.groupdict().get("mode")
        if status == "remote" or (mode and mode.lower() == "remote"):
            enabled[name] = "remote"
        elif status == "disabled":
            enabled[name] = "disabled"
        else:
            enabled[name] = "local"
    return enabled


def read_module_json(module_path: Path, module_name: str) -> dict[str, object]:
    module_json_path = module_path / "module.json"
    if not module_json_path.exists():
        return {
            "name": module_name,
            "slug": module_name.lower(),
            "role": "remote",
        }
    with module_json_path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return {
        "name": payload.get("name") or module_name,
        "slug": payload.get("slug") or module_name.lower(),
        "role": payload.get("role") or "remote",
    }


def validate_module_layout(module_name: str, module_path: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_COMMON_FILES:
        if not (module_path / relative).is_file():
            errors.append(f"missing required file: {relative}")

    # menu_definition.json is only required for modules that actually have a frontend
    if module_name != "host_app" and (module_path / "frontend").exists():
        if not (module_path / "config/menu_definition.json").is_file():
            errors.append("missing required file: config/menu_definition.json")
    return errors


def read_local_images(module_name: str, module_slug: str, compose_path: Path, app_slug: str = "") -> list[str]:
    if not compose_path.is_file():
        return []

    # Read MODULE_DOCKER_REGISTRY_PREFIX so we can resolve compose placeholders.
    env = read_env_file(compose_path.parent / ".env.config")
    registry_prefix = env.get("MODULE_DOCKER_REGISTRY_PREFIX", "").strip()
    # Compose files keep the slash after the placeholder.
    registry_prefix = registry_prefix.rstrip("/")

    app_slug = app_slug or "ideable"
    expected_prefix = f"{module_slug}."
    hostapp_prefix = "hostapp."
    images: list[str] = []
    seen: set[str] = set()
    for raw_line in compose_path.read_text(encoding="utf-8").splitlines():
        match = IMAGE_LINE_RE.match(raw_line)
        if not match:
            continue
        image = match.group(1).strip()
        if image in seen:
            continue

        # Resolve env placeholders to get the actual image reference.
        # Compose uses: image: ${MODULE_DOCKER_REGISTRY_PREFIX}/${MODULE_SLUG}.backend:latest
        if registry_prefix:
            resolved = image.replace("${MODULE_DOCKER_REGISTRY_PREFIX}", registry_prefix)
        else:
            # Empty prefix: remove placeholder AND the following slash.
            resolved = re.sub(r'\$\{MODULE_DOCKER_REGISTRY_PREFIX\}/', '', image)
        resolved = resolved.replace("${APP_SLUG}", app_slug)
        resolved = resolved.replace("${MODULE_SLUG}", module_slug)

        # Strip registry prefix (if present) to obtain the local image name.
        if registry_prefix and resolved.startswith(f"{registry_prefix}/"):
            local_name = resolved[len(registry_prefix) + 1:]
        else:
            local_name = resolved

        # Include module-local images (pattern: MODULE_SLUG.<submodule>)
        # and host_app images referenced by this module's compose.
        if local_name.startswith(expected_prefix) or local_name.startswith(hostapp_prefix):
            images.append(local_name)
            seen.add(image)
            seen.add(local_name)
    return images


def docker_image_exists(image_ref: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image_ref],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def run_docker_command(args: list[str]) -> tuple[bool, str]:
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode == 0, completed.stdout.strip()


def ensure_multiarch_builder(builder_name: str) -> tuple[bool, str]:
    inspect_ok, inspect_output = run_docker_command(["docker", "buildx", "inspect", builder_name])
    if inspect_ok and "Driver:        docker-container" in inspect_output:
        bootstrap_ok, bootstrap_output = run_docker_command(["docker", "buildx", "inspect", "--bootstrap", builder_name])
        if bootstrap_ok:
            return True, builder_name
        return False, f"docker buildx inspect --bootstrap {builder_name} failed: {bootstrap_output}"

    if inspect_ok and "Driver:" in inspect_output:
        return False, (
            f"existing buildx builder '{builder_name}' uses a non-docker-container driver; "
            "multi-arch builds require a docker-container builder"
        )

    create_ok, create_output = run_docker_command([
        "docker", "buildx", "create",
        "--name", builder_name,
        "--driver", "docker-container",
    ])
    if not create_ok:
        return False, f"docker buildx create failed for {builder_name}: {create_output}"

    bootstrap_ok, bootstrap_output = run_docker_command(["docker", "buildx", "inspect", "--bootstrap", builder_name])
    if not bootstrap_ok:
        return False, f"docker buildx inspect --bootstrap {builder_name} failed: {bootstrap_output}"

    return True, builder_name


def push_image(local_ref: str, target_ref: str) -> tuple[bool, str]:
    tag_ok, tag_output = run_docker_command(["docker", "tag", local_ref, target_ref])
    if not tag_ok:
        return False, f"docker tag failed for {local_ref} -> {target_ref}: {tag_output}"

    push_ok, push_output = run_docker_command(["docker", "push", target_ref])
    if not push_ok:
        return False, f"docker push failed for {target_ref}: {push_output}"

    return True, push_output


def find_module_dir_by_slug(target_slug: str) -> tuple[str, Path] | None:
    """Find a module directory whose module.json declares the given slug."""
    for mod_dir in MODULES_DIR.iterdir():
        if not mod_dir.is_dir():
            continue
        mod_json = read_module_json(mod_dir, mod_dir.name)
        if mod_json.get("slug") == target_slug:
            return mod_dir.name, mod_dir
    return None


def find_sources_for_image(image_ref: str, app_slug: str = "") -> Path | None:
    """Locate the SOURCES directory whose Dockerfile produced the given image."""
    base = image_ref.rsplit(":", 1)[0]
    parts = base.split(".")
    if len(parts) < 2:
        return None
    module_slug = parts[0]
    service = ".".join(parts[1:])
    mod_info = find_module_dir_by_slug(module_slug)
    if mod_info is None:
        return None
    _module_name, module_path = mod_info
    sources = module_path / service / "SOURCES"
    if (sources / "Dockerfile").is_file():
        return sources

    # Fallback: image suffix may not match directory name
    # e.g. hostapp.authentik-bootstrap is built from authentik/SOURCES/
    for suffix in ("-bootstrap", "-server", "-worker"):
        if service.endswith(suffix):
            alt_service = service[: -len(suffix)]
            alt_sources = module_path / alt_service / "SOURCES"
            if (alt_sources / "Dockerfile").is_file():
                return alt_sources
    return None


def push_image_multiarch(
    target_ref: str,
    sources_dir: Path,
    platforms: str,
    builder_name: str,
    no_cache: bool = True,
) -> tuple[bool, str]:
    """Build and push a multi-arch image manifest using docker buildx."""
    build_cmd = [
        "docker", "buildx", "build",
        "--builder", builder_name,
        "--platform", platforms,
        "--push",
        "-t", target_ref,
    ]
    if no_cache:
        build_cmd.append("--no-cache")
    build_cmd.append(str(sources_dir))
    ok, output = run_docker_command(build_cmd)
    if not ok:
        return False, f"docker buildx build failed for {target_ref}: {output}"
    return True, output


def select_modules(args: argparse.Namespace, enabled_modules: dict[str, str]) -> list[str]:
    if args.all and args.modules:
        print("ERROR: use either -a/--all or explicit module names, not both")
        sys.exit(1)

    if args.all:
        return [name for name, status in enabled_modules.items() if status == "local"]

    if not args.modules:
        print("ERROR: provide -a/--all or at least one module name")
        sys.exit(1)

    unique_modules: list[str] = []
    seen: set[str] = set()
    for module_name in args.modules:
        if module_name in seen:
            continue
        unique_modules.append(module_name)
        seen.add(module_name)
    return unique_modules


def find_case_insensitive_enabled_module(requested_name: str, enabled_modules: dict[str, str]) -> str:
    requested_lower = requested_name.lower()
    for canonical_name in enabled_modules:
        if canonical_name.lower() == requested_lower:
            return canonical_name
    return ""


def print_summary(reports: list[ModulePushReport], tag: str = "") -> None:
    print()
    print("=" * 72)
    print("Docker image push summary")
    print("=" * 72)
    print(f"Project root:       {PROJECT_ROOT}")
    print(f"Project env:        {PROJECT_ENV_PATH}")
    if tag:
        print(f"Image tag:          {tag}")
    print(f"Modules processed:  {len(reports)}")
    print(f"Modules pushed:     {sum(1 for r in reports if r.pushed_count > 0 and not r.has_errors and not r.skipped_reason)}")
    print(f"Modules skipped:    {sum(1 for r in reports if r.skipped_reason)}")
    print(f"Modules with errs:  {sum(1 for r in reports if r.has_errors)}")
    print()

    for report in reports:
        print(f"- {report.name} ({report.status})")
        print(f"  slug: {report.slug}")
        print(f"  path: {report.path}")
        if report.registry:
            print(f"  registry: {report.registry}")
        if report.skipped_reason:
            print(f"  skipped: {report.skipped_reason}")
        if report.validation_errors:
            print("  validation errors:")
            for error in report.validation_errors:
                print(f"    - {error}")
        if report.local_images:
            print("  local images:")
            for image in report.local_images:
                print(f"    - {image}")
        if report.pushed_images:
            print("  pushed images:")
            for local_ref, target_ref in report.pushed_images:
                print(f"    - {local_ref} -> {target_ref}")
        if report.push_errors:
            print("  push errors:")
            for error in report.push_errors:
                print(f"    - {error}")
        print()


def list_modules(enabled_modules: dict[str, str]) -> None:
    """Print available modules from modules/enabled.md."""
    if not enabled_modules:
        print("No modules found in modules/enabled.md")
        return
    print(f"{'Module':<30} {'Status':<10}")
    print(f"{'-' * 30} {'-' * 10}")
    for name, status in sorted(enabled_modules.items()):
        print(f"{name:<30} {status:<10}")


def main() -> int:
    args = parse_args()
    fallback_registry = resolve_registry_prefix(args.registry)
    enabled_modules = parse_enabled_modules()

    if args.list:
        list_modules(enabled_modules)
        return 0

    requested_modules = select_modules(args, enabled_modules)

    # Respect IDEABLE_VERSION from project.env as the default push tag
    project_env = read_env_file(PROJECT_ENV_PATH)
    ideable_version = project_env.get("IDEABLE_VERSION", "")
    app_slug = project_env.get("APP_SLUG", "ideable")

    multiarch_builder_name = MULTIARCH_BUILDER_NAME
    if not args.single_arch:
        builder_ok, builder_result = ensure_multiarch_builder(multiarch_builder_name)
        if not builder_ok:
            print(f"ERROR: {builder_result}")
            return 1
        multiarch_builder_name = builder_result

    reports: list[ModulePushReport] = []
    errors_found = False

    for module_name in requested_modules:
        module_path = MODULES_DIR / module_name
        enabled_status = enabled_modules.get(module_name)

        canonical_enabled_name = find_case_insensitive_enabled_module(module_name, enabled_modules)
        if enabled_status is None and canonical_enabled_name:
            report = ModulePushReport(
                name=module_name,
                slug=module_name.lower(),
                status="not-enabled",
                path=module_path,
                validation_errors=[
                    f"module name casing does not match modules/enabled.md; use '{canonical_enabled_name}' instead of '{module_name}'"
                ],
            )
            reports.append(report)
            errors_found = True
            continue

        if not module_path.is_dir():
            report = ModulePushReport(
                name=module_name,
                slug=module_name.lower(),
                status="missing",
                path=module_path,
                validation_errors=["module folder not found"],
            )
            reports.append(report)
            errors_found = True
            continue

        module_meta = read_module_json(module_path, module_name)
        module_slug = str(module_meta.get("slug") or module_name.lower())
        role = str(module_meta.get("role") or "remote")
        status = enabled_status or "not-enabled"
        report = ModulePushReport(
            name=module_name,
            slug=module_slug,
            status=status,
            path=module_path,
        )

        if enabled_status is None:
            report.validation_errors.append("module is not declared in modules/enabled.md")
            errors_found = True
            reports.append(report)
            continue

        if enabled_status == "disabled":
            report.validation_errors.append("module is declared as disabled in modules/enabled.md")
            errors_found = True
            reports.append(report)
            continue

        if enabled_status == "remote":
            report.skipped_reason = "module is marked remote; registry push must be handled by the owning project"
            reports.append(report)
            continue

        report.validation_errors.extend(validate_module_layout(module_name, module_path))
        if role == "host" and module_name != "host_app":
            report.validation_errors.append(f"module.json role is '{role}' but module is not host_app")
        if role != "host" and module_name == "host_app":
            report.validation_errors.append("host_app module.json must declare role 'host'")

        compose_path = module_path / "docker-compose.yml"
        report.local_images = read_local_images(module_name, module_slug, compose_path, app_slug)

        if report.validation_errors:
            errors_found = True
            reports.append(report)
            continue

        if not report.local_images:
            report.skipped_reason = "no locally built images were found in docker-compose.yml"
            reports.append(report)
            continue

        # Determine per-module registry: MODULE_DOCKER_REGISTRY_PREFIX from .env.config, then CLI fallback.
        module_env = read_env_file(module_path / ".env.config")
        module_registry_raw = module_env.get("MODULE_DOCKER_REGISTRY_PREFIX", "").strip()
        if module_registry_raw:
            module_registry = resolve_registry_prefix(module_registry_raw, label=f"module {module_name} MODULE_DOCKER_REGISTRY_PREFIX")
        elif fallback_registry:
            module_registry = fallback_registry
        else:
            report.push_errors.append(
                f"module {module_name}: no MODULE_DOCKER_REGISTRY_PREFIX in .env.config and no --registry fallback provided"
            )
            errors_found = True
            reports.append(report)
            continue
        report.registry = module_registry

        for local_ref in report.local_images:
            target_ref = f"{module_registry}/{local_ref}".replace("//", "/")
            effective_tag = args.tag or ideable_version
            if effective_tag:
                base_ref = target_ref.rsplit(":", 1)[0]
                target_ref = f"{base_ref}:{effective_tag}"

            if not args.single_arch:
                sources_dir = find_sources_for_image(local_ref, app_slug)
                if sources_dir is None:
                    report.push_errors.append(
                        f"cannot locate SOURCES/Dockerfile for {local_ref} — skipping multi-arch build"
                    )
                    errors_found = True
                    continue
                print(f"[buildx] {module_name}: {local_ref} -> {target_ref} ({args.platform})")
                ok, output = push_image_multiarch(target_ref, sources_dir, args.platform, multiarch_builder_name, no_cache=args.no_cache)
            else:
                if not docker_image_exists(local_ref):
                    report.push_errors.append(f"local image not found: {local_ref}")
                    errors_found = True
                    continue
                ok, output = push_image(local_ref, target_ref)

            if not ok:
                report.push_errors.append(output)
                errors_found = True
                continue
            report.pushed_images.append((local_ref, target_ref))
            print(f"[push] {module_name}: {local_ref} -> {target_ref}")
            if output:
                print(output)

        reports.append(report)

    print_summary(reports, args.tag)
    return 1 if errors_found else 0


if __name__ == "__main__":
    raise SystemExit(main())
