#!/usr/bin/env python3
"""Generate an Authentik blueprint from the merged authorization contracts.

Usage (called automatically by build_and_deploy.py):
    python generate_authentik_blueprint.py \\
        --hostapp-auth-yaml <path/to/HostApp/config/authorization.yaml> \\
        --modules-root     <path/to/modules/> \\
        --output-blueprint <path/to/deployment_root/.../blueprints/authz-plan.generated.yaml>
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled by build tooling
    yaml = None  # type: ignore

SCRIPT_PATH = Path(__file__).resolve()
ENV_PATH = SCRIPT_PATH.parents[3] / ".env"
if ENV_PATH.is_file():
    try:
        content = ENV_PATH.read_text(encoding="utf-8")
    except OSError:
        content = ""
    if content and "This file is the merge of all enabled modules' .env files." in content:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")

from bootstrap_authentik import (  # type: ignore
    AVAILABLE_PERMISSIONS_ATTRIBUTE,
    AVAILABLE_PERMISSIONS_REGISTRY_NAME,
    PROFILE_ROLES_ATTRIBUTE,
    PROFILE_ROLES_REGISTRY_NAME,
    REGISTRY_KIND_ATTRIBUTE,
    REGISTRY_KIND_AVAILABLE_PERMISSIONS,
    REGISTRY_KIND_PROFILE_ROLES,
    REGISTRY_KIND_ROLES_MAPPING,
    ROLES_MAPPING_ATTRIBUTE,
    ROLES_MAPPING_REGISTRY_NAME,
    build_authorization_plan,
    load_authorization_contracts,
    log,
    render_scope_mapping_expression,
)

SOURCES_DIR = SCRIPT_PATH.parent
HOSTAPP_ROOT = SOURCES_DIR.parents[1]
DEFAULT_BLUEPRINT_PATH = SOURCES_DIR / "blueprints" / "authz-plan.generated.yaml"
DEFAULT_HOSTAPP_AUTH_YAML = HOSTAPP_ROOT / "config" / "authorization.yaml"


def _build_group_entry(name: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "model": "authentik_core.group",
        "identifiers": {"name": name},
        "attrs": {"name": name},
    }
    description = (meta or {}).get("description")
    if description:
        entry["attrs"]["attributes"] = {"description": description}
    return entry


def build_generation_log(plan: Dict[str, Any], blueprint: Dict[str, Any]) -> str:
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    lines: list[str] = [f"Blueprint generation log — {timestamp}", ""]

    lines.append("## app:available-permissions-registry")
    lines.append(f"- entries: {len(plan.get('available_permissions') or [])}")
    for permission in plan.get("available_permissions") or []:
        lines.append(
            f"  - {permission.get('name')}: resource={permission.get('resource')} action={permission.get('action')} module={permission.get('module')}"
        )
    lines.append("")

    lines.append("## app:permissions-to-role-registry")
    roles_mapping = plan.get("roles_mapping") or {}
    if roles_mapping:
        for role_name in sorted(roles_mapping):
            perms = ", ".join(roles_mapping.get(role_name) or [])
            lines.append(f"  - {role_name}: {perms}")
    else:
        lines.append("  - (empty)")
    lines.append("")

    lines.append("## app:roles-to-profile-registry")
    profile_roles = plan.get("profile_roles") or {}
    if profile_roles:
        for profile_name in sorted(profile_roles):
            roles = ", ".join(profile_roles.get(profile_name) or [])
            lines.append(f"  - {profile_name}: {roles}")
    else:
        lines.append("  - (empty)")
    lines.append("")

    lines.append("## Property Mappings")
    property_mappings = [entry for entry in blueprint.get("entries", []) if str(entry.get("model", "")).startswith("authentik_propertymapping.")]
    if property_mappings:
        for entry in property_mappings:
            lines.append(f"  - {entry.get('model')} :: {entry.get('identifiers', {})}")
            attrs = entry.get("attrs") or {}
            for key, value in attrs.items():
                rendered = yaml.safe_dump(value, sort_keys=False).strip() if yaml else str(value)
                lines.append(f"      {key}:")
                lines.extend(f"        {line}" for line in rendered.splitlines())
    else:
        lines.append("  - (none)")

    return "\n".join(lines) + "\n"


def _build_role_entry(name: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "model": "authentik_rbac.role",
        "identifiers": {"name": name},
        "attrs": {"name": name},
    }
    description = (meta or {}).get("description")
    if description:
        entry["attrs"]["description"] = description
    return entry


def _build_role_assignment_entries(profile_roles: Dict[str, list[str]]) -> list[Dict[str, Any]]:
    entries: list[Dict[str, Any]] = []
    for profile_name, roles in sorted(profile_roles.items()):
        for role_name in roles:
            entries.append(
                {
                    "model": "authentik_rbac.rolebinding",
                    "identifiers": {
                        "group__name": profile_name,
                        "role__name": role_name,
                    },
                    "attrs": {
                        "group": {"name": profile_name},
                        "role": {"name": role_name},
                    },
                }
            )
    return entries


def _build_scope_mapping_entry(plan: Dict[str, Any]) -> Dict[str, Any]:
    expression = render_scope_mapping_expression(plan)
    return {
        "model": "authentik_propertymapping.provider_scopemapping",
        "identifiers": {"name": "Ideable Permissions Claims"},
        "attrs": {
            "name": "Ideable Permissions Claims",
            "scope_name": "hostapp",
            "expression": expression,
        },
    }


def build_blueprint(plan: Dict[str, Any]) -> Dict[str, Any]:
    entries: list[Dict[str, Any]] = []

    for name, meta in sorted((plan.get("profiles") or {}).items()):
        entries.append(_build_group_entry(name, meta))

    for name, meta in sorted((plan.get("roles") or {}).items()):
        entries.append(_build_role_entry(name, meta))

    entries.extend(_build_role_assignment_entries(plan.get("profile_roles") or {}))
    entries.append(_build_scope_mapping_entry(plan))

    entries.append(
        {
            "model": "authentik_core.group",
            "identifiers": {"name": AVAILABLE_PERMISSIONS_REGISTRY_NAME},
            "attrs": {
                "name": AVAILABLE_PERMISSIONS_REGISTRY_NAME,
                "attributes": {
                    AVAILABLE_PERMISSIONS_ATTRIBUTE: plan.get("available_permissions") or [],
                    REGISTRY_KIND_ATTRIBUTE: REGISTRY_KIND_AVAILABLE_PERMISSIONS,
                },
            },
        }
    )

    entries.append(
        {
            "model": "authentik_core.group",
            "identifiers": {"name": ROLES_MAPPING_REGISTRY_NAME},
            "attrs": {
                "name": ROLES_MAPPING_REGISTRY_NAME,
                "attributes": {
                    ROLES_MAPPING_ATTRIBUTE: plan.get("roles_mapping") or {},
                    REGISTRY_KIND_ATTRIBUTE: REGISTRY_KIND_ROLES_MAPPING,
                },
            },
        }
    )

    entries.append(
        {
            "model": "authentik_core.group",
            "identifiers": {"name": PROFILE_ROLES_REGISTRY_NAME},
            "attrs": {
                "name": PROFILE_ROLES_REGISTRY_NAME,
                "attributes": {
                    PROFILE_ROLES_ATTRIBUTE: plan.get("profile_roles") or {},
                    REGISTRY_KIND_ATTRIBUTE: REGISTRY_KIND_PROFILE_ROLES,
                },
            },
        }
    )

    entries.append(
        {
            "model": "blueprint.note",
            "identifiers": {"slug": "authz-plan"},
            "attrs": {
                "title": "Authorization Plan Guidance",
                "content": (
                    "Generated from HostApp + module authorization.yaml contracts. "
                    "Update Authentik providers to reference the HostApp Permissions Claim mapping."
                ),
            },
        }
    )

    return {
        "version": 1,
        "metadata": {
            "name": "HostApp Authorization Blueprint",
            "labels": {
                "generated-by": "generate_authentik_blueprint.py",
            },
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the Authentik authorization blueprint."
    )
    parser.add_argument(
        "--hostapp-auth-yaml",
        default=str(DEFAULT_HOSTAPP_AUTH_YAML),
        help="Path to HostApp's authorization.yaml "
             f"(default: {DEFAULT_HOSTAPP_AUTH_YAML})",
    )
    parser.add_argument(
        "--modules-root",
        default=None,
        help="Path to the modules/ directory. Defaults to auto-discovery via HOSTAPP_ROOT.",
    )
    parser.add_argument(
        "--output-blueprint",
        default=str(DEFAULT_BLUEPRINT_PATH),
        help=f"Destination for the blueprint YAML (default: {DEFAULT_BLUEPRINT_PATH})",
    )
    parser.add_argument(
        "--log-path",
        default="",
        help="Optional path for a readable blueprint generation log.",
    )
    args = parser.parse_args()

    hostapp_auth_yaml = Path(args.hostapp_auth_yaml)
    modules_root = Path(args.modules_root) if args.modules_root else None
    blueprint_path = Path(args.output_blueprint).expanduser().resolve()

    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to generate the authorization plan. "
            "Install it with: pip install pyyaml"
        )

    contracts = load_authorization_contracts(
        hostapp_auth_path=hostapp_auth_yaml,
        modules_root=modules_root,
    )
    plan = build_authorization_plan(contracts)
    blueprint = build_blueprint(plan)

    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    blueprint_path.write_text(yaml.safe_dump(blueprint, sort_keys=False), encoding="utf-8")
    log(f"Authorization blueprint written to {blueprint_path}")

    if args.log_path:
        log_path = Path(args.log_path).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(build_generation_log(plan, blueprint), encoding="utf-8")
        log(f"Blueprint generation log written to {log_path}")


if __name__ == "__main__":  # pragma: no cover
    main()
