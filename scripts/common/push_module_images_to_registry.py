#!/usr/bin/env python3
"""Push locally built module images to a configured Docker registry.

Usage:
  python3 scripts/common/push_module_images_to_registry.py -a
  python3 scripts/common/push_module_images_to_registry.py -a -t v1.0.0-latest
  python3 scripts/common/push_module_images_to_registry.py HostApp ModuleTemplate
  python3 scripts/common/push_module_images_to_registry.py -a -t v1.0.0-latest --single-arch
  python3 scripts/common/push_module_images_to_registry.py -a -t v1.0.0-latest --platform linux/amd64,linux/arm64

The script reads repo-root project.env for DOCKER_REGISTRY (fallback:
HOSTAPP_DOCKER_REGISTRY, then ghcr.io), validates the selected modules, checks
that the expected local Docker images exist, and by default builds and pushes a
multi-arch manifest with docker buildx. Use --single-arch to tag/push the
existing local image instead.

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
PROJECT_ENV_PATH = PROJECT_ROOT / "project.env"
ENABLED_PATH = MODULES_DIR / "enabled.md"

REQUIRED_COMMON_FILES = (".env", "docker-compose.yml", "module.json")
REQUIRED_CONFIG_FILES = {
    "HostApp": ("config/modules_menu_mapping.json",),
    "default": ("config/menu_definition.json",),
}

MULTIARCH_BUILDER_NAME = "ideable-multiarch-builder"

IMAGE_LINE_RE = re.compile(r"^\s*image:\s*([^\s#]+)\s*$", re.IGNORECASE)
ENABLED_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)\s*:\s*(?P<status>enabled(?:-remote)?|disabled)\s*$",
    re.IGNORECASE,
)
ALT_ENABLED_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)\s+(?P<status>enabled(?:-remote)?|disabled)(?:\s+(?P<mode>local|remote))?\s*$",
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
        help="Process every enabled module declared as 'enabled' in modules/enabled.md",
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
        "--platform",
        dest="platform",
        default="linux/amd64,linux/arm64",
        help="Comma-separated platform list for --multi-arch (default: linux/amd64,linux/arm64)",
    )
    parser.add_argument(
        "modules",
        nargs="*",
        help="One or more module names to process (e.g. HostApp ModuleTemplate)",
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
        env[key.strip()] = value.strip().strip('"').strip("'")
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


def load_registry_prefix() -> tuple[str, str]:
    project_env = read_env_file(PROJECT_ENV_PATH)
    raw_registry = (
        project_env.get("DOCKER_REGISTRY")
        or project_env.get("HOSTAPP_DOCKER_REGISTRY")
        or "ghcr.io"
    ).strip().rstrip("/")
    registry = raw_registry
    source = "DOCKER_REGISTRY"
    if not project_env.get("DOCKER_REGISTRY") and project_env.get("HOSTAPP_DOCKER_REGISTRY"):
        source = "HOSTAPP_DOCKER_REGISTRY"
    elif not project_env.get("DOCKER_REGISTRY") and not project_env.get("HOSTAPP_DOCKER_REGISTRY"):
        source = "default"
    if registry == "ghcr.io":
        owner = resolve_git_owner()
        if owner:
            registry = f"ghcr.io/{owner}"
            source = f"{source}+git_owner"
        else:
            print(
                "ERROR: DOCKER_REGISTRY is ghcr.io but no repository owner could be resolved. "
                "Set DOCKER_REGISTRY to ghcr.io/<owner> or export GITHUB_REPOSITORY_OWNER."
            )
            sys.exit(1)
    return registry, source


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
        if status == "enabled-remote" or (mode and mode.lower() == "remote"):
            enabled[name] = "enabled-remote"
        elif status == "disabled":
            enabled[name] = "disabled"
        else:
            enabled[name] = "enabled"
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

    config_files = REQUIRED_CONFIG_FILES["HostApp"] if module_name == "HostApp" else REQUIRED_CONFIG_FILES["default"]
    for relative in config_files:
        if not (module_path / relative).is_file():
            errors.append(f"missing required file: {relative}")
    return errors


def read_local_images(module_name: str, module_slug: str, compose_path: Path) -> list[str]:
    if not compose_path.is_file():
        return []

    expected_prefix = f"{module_slug}-" if module_name == "HostApp" else f"{module_slug}/"
    images: list[str] = []
    seen: set[str] = set()
    for raw_line in compose_path.read_text(encoding="utf-8").splitlines():
        match = IMAGE_LINE_RE.match(raw_line)
        if not match:
            continue
        image = match.group(1).strip()
        if image in seen:
            continue
        if image.startswith(expected_prefix):
            images.append(image)
            seen.add(image)
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


def find_sources_for_image(module_name: str, module_slug: str, image_ref: str) -> Path | None:
    """Locate the SOURCES directory whose Dockerfile produced the given image."""
    base = image_ref.rsplit(":", 1)[0]
    if module_name == "HostApp":
        prefix = f"{module_slug}-"
    else:
        prefix = f"{module_slug}/"
    if not base.startswith(prefix):
        return None
    service = base[len(prefix):]
    sources = MODULES_DIR / module_name / service / "SOURCES"
    if (sources / "Dockerfile").is_file():
        return sources
    return None


def push_image_multiarch(
    target_ref: str,
    sources_dir: Path,
    platforms: str,
    builder_name: str,
) -> tuple[bool, str]:
    """Build and push a multi-arch image manifest using docker buildx."""
    build_cmd = [
        "docker", "buildx", "build",
        "--builder", builder_name,
        "--platform", platforms,
        "--push",
        "-t", target_ref,
        str(sources_dir),
    ]
    ok, output = run_docker_command(build_cmd)
    if not ok:
        return False, f"docker buildx build failed for {target_ref}: {output}"
    return True, output


def select_modules(args: argparse.Namespace, enabled_modules: dict[str, str]) -> list[str]:
    if args.all and args.modules:
        print("ERROR: use either -a/--all or explicit module names, not both")
        sys.exit(1)

    if args.all:
        return [name for name, status in enabled_modules.items() if status == "enabled"]

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


def print_summary(registry: str, registry_source: str, reports: list[ModulePushReport], tag: str = "") -> None:
    print()
    print("=" * 72)
    print("Docker image push summary")
    print("=" * 72)
    print(f"Project root:       {PROJECT_ROOT}")
    print(f"Project env:        {PROJECT_ENV_PATH}")
    print(f"Registry prefix:    {registry} ({registry_source})")
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


def main() -> int:
    args = parse_args()
    registry, registry_source = load_registry_prefix()
    enabled_modules = parse_enabled_modules()
    requested_modules = select_modules(args, enabled_modules)

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

        if enabled_status == "enabled-remote":
            report.skipped_reason = "module is marked enabled-remote; registry push must be handled by the owning project"
            reports.append(report)
            continue

        report.validation_errors.extend(validate_module_layout(module_name, module_path))
        if role == "host" and module_name != "HostApp":
            report.validation_errors.append(f"module.json role is '{role}' but module is not HostApp")
        if role != "host" and module_name == "HostApp":
            report.validation_errors.append("HostApp module.json must declare role 'host'")

        compose_path = module_path / "docker-compose.yml"
        report.local_images = read_local_images(module_name, module_slug, compose_path)

        if report.validation_errors:
            errors_found = True
            reports.append(report)
            continue

        if not report.local_images:
            report.skipped_reason = "no locally built images were found in docker-compose.yml"
            reports.append(report)
            continue

        for local_ref in report.local_images:
            target_ref = f"{registry}/{local_ref}".replace("//", "/")
            if args.tag:
                base_ref = target_ref.rsplit(":", 1)[0]
                target_ref = f"{base_ref}:{args.tag}"

            if not args.single_arch:
                sources_dir = find_sources_for_image(module_name, module_slug, local_ref)
                if sources_dir is None:
                    report.push_errors.append(
                        f"cannot locate SOURCES/Dockerfile for {local_ref} — skipping multi-arch build"
                    )
                    errors_found = True
                    continue
                print(f"[buildx] {module_name}: {local_ref} -> {target_ref} ({args.platform})")
                ok, output = push_image_multiarch(target_ref, sources_dir, args.platform, multiarch_builder_name)
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

    print_summary(registry, registry_source, reports, args.tag)
    return 1 if errors_found else 0


if __name__ == "__main__":
    raise SystemExit(main())
