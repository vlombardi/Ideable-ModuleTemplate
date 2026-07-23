#!/bin/bash
# create-merged-configuration.sh
# Runs at deployment_root side to regenerate the merged .env.config, .env.secrets
# and docker-compose.yml from the per-module files already deployed under
# deployment_root/modules/.
#
# Usage:
#   ./create-merged-configuration.sh [-h|--help] [--regen-routes]

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help] [--regen-routes]"
    echo ""
    echo "Regenerates the merged deployment configuration from per-module files."
    echo ""
    echo "This script performs the following operations:"
    echo "  1. Auto-registers modules from module.json files"
    echo "     - Updates module-registry.json (MF 2.0 registry)"
    echo "     - Generates Traefik routes in dynamic.yml.template"
    echo "     - Validates apiUpstream env vars"
    echo ""
    echo "  2. Merges environment files"
    echo "     - Creates merged .env.config from project, host_app, and all modules"
    echo "     - Creates merged .env.secrets from project, host_app, and all modules"
    echo "     - Generates per-module split env files"
    echo "     - Generates merged .env.secrets.example"
    echo ""
    echo "  3. Merges Docker Compose files"
    echo "     - Creates merged docker-compose.yml from all module compose files"
    echo ""
    echo "  4. Merges menu mapping"
    echo "     - Creates merged modules_menu_mapping.json from all modules"
    echo "     - Prompts for confirmation when overwriting existing file"
    echo ""
    echo "  5. Invalidates cached Authentik blueprint"
    echo "     - Deletes authz-plan.generated.yaml to force regeneration"
    echo ""
    echo "The script detects whether it's running in the source repository or"
    echo "in a deployed environment and adjusts its behavior accordingly."
    echo ""
    echo "Options:"
    echo "  -h, --help        Show this help message"
    echo "  --regen-routes    Force regeneration of all module-owned Traefik routes in"
    echo "                    dynamic.yml.template (purge and re-emit). Without this flag,"
    echo "                    route generation is add-only/idempotent."
    exit 0
fi

TRAEFIK_FORCE_ROUTE_REGEN=0
for arg in "$@"; do
  case "$arg" in
    --regen-routes)
      TRAEFIK_FORCE_ROUTE_REGEN=1
      ;;
  esac
done
export TRAEFIK_FORCE_ROUTE_REGEN

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# Detect context: source repo (script in scripts/runtime/config/) vs deployed (script in scripts/).
# In source context, project.env.config sits one directory above deployment_root.
# In deployed context, deployment_root IS the project root.
if [[ -f "${DEPLOYMENT_ROOT}/../project.env.config" ]]; then
    PROJECT_ROOT="$(cd "${DEPLOYMENT_ROOT}/.." && pwd)"
    DEPLOYMENT_ROOT="${PROJECT_ROOT}/deployment_root"
else
    PROJECT_ROOT="$DEPLOYMENT_ROOT"
fi

export DEPLOYMENT_ROOT
export PROJECT_ROOT

# Load project env so APP_SLUG and other project-wide vars are available
# to the embedded Python script.
PROJECT_ENV_CONFIG="${PROJECT_ROOT}/project.env.config"
PROJECT_ENV_SECRETS="${PROJECT_ROOT}/project.env.secrets"
# Source secrets before config because config files may reference secret variables.
if [[ -f "$PROJECT_ENV_CONFIG" ]]; then
    set +u
    set -a
    if [[ -f "$PROJECT_ENV_SECRETS" ]]; then
        # shellcheck disable=SC1090
        source "$PROJECT_ENV_SECRETS"
    fi
    # shellcheck disable=SC1090
    source "$PROJECT_ENV_CONFIG"
    set +a
    set -u
else
    # Preserve PROJECT_ROOT: deployment_root/.env.config may contain an
    # export PROJECT_ROOT=... line, and sourcing it must not make the embedded
    # Python script believe it is running in the source repo.
    _saved_project_root="$PROJECT_ROOT"
    if [[ -f "$DEPLOYMENT_ROOT/.env.secrets" ]]; then
        set +u
        set -a
        # shellcheck disable=SC1090
        source "$DEPLOYMENT_ROOT/.env.secrets"
        set +a
        set -u
    fi
    if [[ -f "$DEPLOYMENT_ROOT/.env.config" ]]; then
        set +u
        set -a
        # shellcheck disable=SC1090
        source "$DEPLOYMENT_ROOT/.env.config"
        set +a
        set -u
    fi
    PROJECT_ROOT="$_saved_project_root"
fi

PYTHON_SCRIPT=$(mktemp)
trap 'rm -f "$PYTHON_SCRIPT"' EXIT

cat > "$PYTHON_SCRIPT" << 'PYTHON_EOF'
import json
import os
import re
import subprocess
import sys

DEPLOYMENT_ROOT = os.environ.get("DEPLOYMENT_ROOT", "")
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "")
# In source context the modules live under PROJECT_ROOT, not under the generated deployment_root.
if PROJECT_ROOT and PROJECT_ROOT != DEPLOYMENT_ROOT and os.path.isdir(os.path.join(PROJECT_ROOT, "modules")):
    MODULES_DIR = os.path.join(PROJECT_ROOT, "modules")
else:
    MODULES_DIR = os.path.join(DEPLOYMENT_ROOT, "modules")

SECRET_SUFFIXES = (
    "_PASSWORD", "_TOKEN", "_SECRET", "_SECRET_KEY", "_API_KEY", "_API_TOKEN",
)

PORTS_PATHS_SUFFIXES = (
    "_PORT", "_HOST", "_IP", "_PATH", "_URL", "_FOLDER", "_ROOT", "_DIR",
)

PARAMS_URL_OVERRIDE = {
    "AUTHENTIK_JWKS_URL",
    "AUTHENTIK_API_URL",
    "AUTHENTIK_INTERNAL_URL",
    "VITE_API_URL",
    "VITE_OIDC_AUTHORITY",
    "VITE_OIDC_REDIRECT_URI",
    "VITE_OIDC_POST_LOGOUT_REDIRECT_URI",
    "DATABASE_URL",
}

PORTS_PATHS_EXPLICIT = {
    "EXTERNAL_BASE_HOST", "MAIN_HOST", "DATABASE_IP",
    "AUTHENTIK_EXTERNAL_URL",
    "AUTHENTIK_PORT_HTTP", "AUTHENTIK_PORT_HTTPS",
    "FRONTEND_CERT_HOSTS", "FRONTEND_CERT_IP",
}

NOT_SECRET_OVERRIDE = {
    "CLIENT_ID",
    "VITE_OIDC_CLIENT_ID",
}

MODULE_IDENTITY_KEYS = {"MODULE_SLUG", "MODULE_NAME", "MODULE_DOCKER_REGISTRY_PREFIX"}


def classify_env_var(key, value, all_vars=None, _visited=None):
    if _visited is None:
        _visited = set()
    if key in _visited:
        # Circular or self-reference (e.g. APP_SLUG=${APP_SLUG}); treat as params.
        return "params"
    _visited.add(key)

    if key not in NOT_SECRET_OVERRIDE:
        for suffix in SECRET_SUFFIXES:
            if key.endswith(suffix):
                return "secrets"
    if all_vars and value:
        stripped = value.strip()
        if stripped.startswith("${") and stripped.endswith("}"):
            ref_key = stripped[2:-1]
            if ref_key in all_vars:
                ref_classification = classify_env_var(ref_key, all_vars[ref_key], all_vars, _visited)
                if ref_classification == "secrets":
                    return "secrets"
    if key in PORTS_PATHS_EXPLICIT:
        return "ports_paths"
    if key not in PARAMS_URL_OVERRIDE:
        for suffix in PORTS_PATHS_SUFFIXES:
            if key.endswith(suffix):
                return "ports_paths"
    return "params"

def _read_env_keys(env_path):
    keys = set()
    if not os.path.exists(env_path):
        return keys
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.add(key)
    return keys

def _extract_explicit_env_keys(compose_path):
    service_env_keys = {}
    if not os.path.exists(compose_path):
        return service_env_keys
    with open(compose_path, encoding="utf-8") as f:
        lines = f.readlines()
    current_service = None
    in_environment = False
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-") and not stripped.startswith("#"):
            candidate = stripped.rstrip().rstrip(":")
            current_service = candidate
            in_environment = False
            if current_service not in service_env_keys:
                service_env_keys[current_service] = set()
            continue
        if current_service is None:
            continue
        if indent == 4 and stripped.rstrip() == "environment:":
            in_environment = True
            continue
        if in_environment and indent == 4 and not stripped.startswith("-") and ":" in stripped:
            in_environment = False
        if in_environment and indent >= 4:
            env_entry = stripped.lstrip("- ").strip()
            if "=" in env_entry:
                key = env_entry.split("=", 1)[0].strip()
                service_env_keys[current_service].add(key)
            elif ":" in env_entry:
                key = env_entry.split(":", 1)[0].strip()
                if key:
                    service_env_keys[current_service].add(key)
    return service_env_keys

def _extract_environment_lines(yaml_text):
    service_env_lines = {}
    lines = yaml_text.splitlines(keepends=True)
    current_service = None
    in_environment = False
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if line.rstrip() == "services:":
            current_service = None
            in_environment = False
            continue
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
            current_service = stripped.rstrip().rstrip(":")
            in_environment = False
            service_env_lines.setdefault(current_service, [])
            continue
        if current_service is None:
            continue
        if indent == 4 and stripped.rstrip() == "environment:":
            in_environment = True
            continue
        if in_environment and indent == 4 and not stripped.startswith("-") and ":" in stripped:
            in_environment = False
        if in_environment and indent >= 6:
            env_entry = stripped.lstrip("- ").strip()
            if "=" in env_entry:
                key = env_entry.split("=", 1)[0].strip()
            elif ":" in env_entry:
                key = env_entry.split(":", 1)[0].strip()
            else:
                continue
            service_env_lines.setdefault(current_service, []).append((key, line))
    return service_env_lines

def _extract_service_headings(compose_path):
    headings = {}
    if not os.path.exists(compose_path):
        return headings
    with open(compose_path, encoding="utf-8") as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
            service_name = stripped.rstrip().rstrip(":")
            block = []
            j = idx - 1
            while j >= 0:
                prev = lines[j]
                prev_stripped = prev.strip()
                if not prev_stripped:
                    block.append(prev)
                    j -= 1
                    continue
                if prev_stripped.startswith("#") or prev_stripped.startswith("############"):
                    block.append(prev)
                    j -= 1
                    continue
                break
            block.reverse()
            while block and not block[0].strip():
                block.pop(0)
            if block and service_name not in headings:
                headings[service_name] = "".join(block)
    return headings

def _deresolved_compose(yaml_text, env_keys, explicit_env_per_service=None, service_headings=None):
    lines = yaml_text.splitlines(keepends=True)
    output = []
    in_services = False
    in_environment = False
    current_service = None
    env_buffer = []
    env_header_line = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if line.rstrip() == "services:":
            in_services = True
            output.append(line)
            i += 1
            continue
        if in_services:
            if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
                if env_buffer and env_header_line:
                    output.append(env_header_line)
                    output.extend(env_buffer)
                in_environment = False
                env_buffer = []
                env_header_line = None
                service_name = stripped.rstrip().rstrip(":")
                heading_block = None
                if service_headings:
                    heading_block = service_headings.get(service_name)
                if heading_block:
                    if not heading_block.endswith("\n"):
                        heading_block += "\n"
                    output.append(heading_block)
                current_service = service_name
                output.append(line)
                i += 1
                continue
            if indent == 4 and stripped.startswith("env_file:"):
                if env_buffer and env_header_line:
                    output.append(env_header_line)
                    output.extend(env_buffer)
                in_environment = False
                env_buffer = []
                env_header_line = None
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    nxt_stripped = nxt.lstrip()
                    if nxt_indent <= 4 and not nxt_stripped.startswith("-"):
                        break
                    i += 1
                continue
            if indent == 4 and stripped.rstrip() == "environment:":
                in_environment = True
                env_header_line = line
                env_buffer = []
                i += 1
                continue
            if in_environment and indent <= 4 and not stripped.startswith("-") and ":" in stripped:
                key_part = stripped.split(":")[0].strip()
                if key_part and indent == 4:
                    if env_buffer and env_header_line:
                        output.append(env_header_line)
                        output.extend(env_buffer)
                    in_environment = False
                    env_buffer = []
                    env_header_line = None
            if in_environment and indent == 6 and ":" in stripped:
                colon_pos = stripped.index(":")
                key = stripped[:colon_pos].strip()
                if explicit_env_per_service is not None:
                    allowed = explicit_env_per_service.get(current_service, set())
                    if key not in allowed:
                        i += 1
                        continue
                if key in env_keys:
                    line = " " * indent + f"{key}: ${{{key}}}\n"
                env_buffer.append(line)
                i += 1
                continue
            if in_environment and indent >= 4:
                if env_buffer and env_header_line:
                    output.append(env_header_line)
                    output.extend(env_buffer)
                in_environment = False
                env_buffer = []
                env_header_line = None
        output.append(line)
        i += 1
    if env_buffer and env_header_line:
        output.append(env_header_line)
        output.extend(env_buffer)
    return "".join(output)

def _restore_missing_environment_entries(yaml_text, raw_env_lines_per_service, explicit_env_per_service=None):
    if not yaml_text:
        return yaml_text
    lines = yaml_text.splitlines(keepends=True)
    output = []
    current_service = None
    in_environment = False
    env_buffer = []
    env_keys_present = set()
    def _flush_env_block():
        nonlocal env_buffer, env_keys_present
        if not env_buffer:
            return
        missing_lines = []
        raw_entries = raw_env_lines_per_service.get(current_service or "", [])
        allowed_keys = explicit_env_per_service.get(current_service or "", set()) if explicit_env_per_service is not None else None
        for key, raw_line in raw_entries:
            if allowed_keys is not None and key not in allowed_keys:
                continue
            if key not in env_keys_present:
                missing_lines.append(raw_line)
                env_keys_present.add(key)
        output.extend(env_buffer)
        output.extend(missing_lines)
        env_buffer.clear()
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if line.rstrip() == "services:":
            if in_environment:
                _flush_env_block()
            output.append(line)
            current_service = None
            in_environment = False
            continue
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
            if in_environment:
                _flush_env_block()
            current_service = stripped.rstrip().rstrip(":")
            in_environment = False
            env_buffer = []
            env_keys_present = set()
            output.append(line)
            continue
        if current_service and indent == 4 and stripped.rstrip() == "environment:":
            in_environment = True
            env_buffer = [line]
            env_keys_present = set()
            continue
        if in_environment and indent <= 4 and not stripped.startswith("-") and ":" in stripped:
            _flush_env_block()
            in_environment = False
            output.append(line)
            continue
        if in_environment and indent >= 6:
            env_entry = stripped.lstrip("- ").strip()
            if "=" in env_entry:
                key = env_entry.split("=", 1)[0].strip()
            elif ":" in env_entry:
                key = env_entry.split(":", 1)[0].strip()
            else:
                key = ""
            if key:
                env_keys_present.add(key)
            env_buffer.append(line)
            continue
        if in_environment:
            _flush_env_block()
            in_environment = False
        output.append(line)
    if in_environment:
        _flush_env_block()
    return "".join(output)

def _relativize_deployment_root_paths(yaml_text, deployment_root):
    if not yaml_text:
        return yaml_text
    abs_root = os.path.abspath(deployment_root)
    root_prefix = abs_root.rstrip(os.sep) + os.sep
    def _to_relative(abs_path):
        normalized = os.path.abspath(abs_path)
        if normalized == abs_root:
            return "."
        try:
            rel_path = os.path.relpath(normalized, abs_root).replace(os.sep, "/")
            if rel_path.startswith(".."):
                return normalized
            return f"./{rel_path}"
        except ValueError:
            return normalized
    path_pattern = re.compile(rf"{re.escape(root_prefix)}[^\s,\"']*")
    def _replace(match):
        return _to_relative(match.group(0))
    return path_pattern.sub(_replace, yaml_text)

def _ensure_environment_headers(yaml_text, explicit_env_per_service=None):
    if not yaml_text:
        return yaml_text
    lines = yaml_text.splitlines(keepends=True)
    output = []
    current_service = None
    service_has_environment = False
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if line.rstrip() == "services:":
            current_service = None
            service_has_environment = False
            output.append(line)
            continue
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
            current_service = stripped.rstrip().rstrip(":")
            service_has_environment = False
            output.append(line)
            continue
        if current_service and indent == 4 and stripped.rstrip() == "environment:":
            service_has_environment = True
            output.append(line)
            continue
        if (
            current_service
            and not service_has_environment
            and indent == 6
            and stripped.startswith("- ")
            and explicit_env_per_service is not None
        ):
            env_entry = stripped.lstrip("- ").strip()
            if "=" in env_entry:
                key = env_entry.split("=", 1)[0].strip()
                allowed_keys = explicit_env_per_service.get(current_service, set())
                if key in allowed_keys:
                    output.append("    environment:\n")
                    service_has_environment = True
        output.append(line)
    return "".join(output)

def merge_env_files():
    # Determine context: source repo (has project.env.config) vs deployed (has per-module split files)
    project_env_config = os.path.join(PROJECT_ROOT, "project.env.config")
    project_env_secrets = os.path.join(PROJECT_ROOT, "project.env.secrets")
    is_source_context = os.path.exists(project_env_config)

    # section_data: list of (section_title, list_of_(key, line)) pairs
    section_data = []
    merged = {}
    module_count = 0
    module_names = []

    def _read_env_file(env_path):
        """Read an .env file and return list of (key, line) tuples."""
        entries = []
        if not os.path.exists(env_path):
            return entries
        with open(env_path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key = stripped.split("=", 1)[0].strip()
                entries.append((key, line))
        return entries

    def _read_split_or_combined(module_dir):
        """Read per-module .env.config + .env.secrets.
        Returns (config_entries, secrets_entries) where each is a list of (key, line)."""
        config_path = os.path.join(module_dir, ".env.config")
        secrets_path = os.path.join(module_dir, ".env.secrets")

        config_entries = _read_env_file(config_path)
        secrets_entries = _read_env_file(secrets_path)
        return config_entries, secrets_entries

    def _ensure_module_secrets_from_example(module_dir):
        """If a module has .env.secrets.example but no .env.secrets, copy the example
        so the merged configuration has a concrete secrets file to work with."""
        secrets_path = os.path.join(module_dir, ".env.secrets")
        example_path = os.path.join(module_dir, ".env.secrets.example")
        if os.path.exists(secrets_path) or not os.path.exists(example_path):
            return
        with open(example_path, encoding="utf-8") as src:
            content = src.read()
        os.makedirs(module_dir, exist_ok=True)
        with open(secrets_path, "w", encoding="utf-8") as out:
            out.write(content)
        rel_path = os.path.relpath(secrets_path, DEPLOYMENT_ROOT)
        print(f"  Created {rel_path} from .env.secrets.example")

    def _write_root_secrets_example():
        """Generate a merged deployment_root/.env.secrets.example from all available
        per-module .env.secrets.example files (and project.env.secrets.example in
        source context)."""
        example_sources = []
        if is_source_context:
            project_env_secrets_example = os.path.join(PROJECT_ROOT, "project.env.secrets.example")
            if os.path.exists(project_env_secrets_example):
                example_sources.append(("Project", project_env_secrets_example))
        hostapp_example = os.path.join(MODULES_DIR, "host_app", ".env.secrets.example")
        if os.path.exists(hostapp_example):
            example_sources.append(("host_app", hostapp_example))
        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "host_app":
                    continue
                example_path = os.path.join(MODULES_DIR, module_name, ".env.secrets.example")
                if os.path.exists(example_path):
                    example_sources.append((module_name, example_path))

        if not example_sources:
            return

        output_lines = [
            "# AUTO-GENERATED — do not edit manually.\n",
            "# Example secrets for this deployment.\n",
            "# Copy to .env.secrets and replace placeholder values with real secrets.\n",
        ]
        seen_keys = set()
        for title, example_path in example_sources:
            output_lines.append(f"\n# ── {title} ──────────────────────────────────────────\n")
            with open(example_path, encoding="utf-8") as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        output_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
                        continue
                    key = stripped.split("=", 1)[0].strip()
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    # Normalize so the assignment always occupies exactly one line,
                    # regardless of trailing-newline state in the source file.
                    output_lines.append(raw_line.rstrip() + "\n")
            if not output_lines[-1].endswith("\n"):
                output_lines.append("\n")

        dst_example = os.path.join(DEPLOYMENT_ROOT, ".env.secrets.example")
        with open(dst_example, "w", encoding="utf-8") as f:
            f.write("".join(output_lines))
        print(f"Generated deployment_root/.env.secrets.example ({len(example_sources)} source(s))")

    def _copy_module_secrets_example(src_module_dir, dst_module_dir):
        """Copy .env.secrets.example from the source module directory to the
        deployed module directory when it is missing. This ensures deployable
        bundles have the example file even though .env.secrets itself is not
        committed."""
        src_example = os.path.join(src_module_dir, ".env.secrets.example")
        dst_example = os.path.join(dst_module_dir, ".env.secrets.example")
        if not os.path.exists(src_example) or os.path.exists(dst_example):
            return
        os.makedirs(dst_module_dir, exist_ok=True)
        with open(src_example, encoding="utf-8") as f:
            content = f.read()
        with open(dst_example, "w", encoding="utf-8") as out:
            out.write(content)
        rel_path = os.path.relpath(dst_example, DEPLOYMENT_ROOT)
        print(f"  Copied {rel_path} from source module")

    def _append_section(title, entries):
        nonlocal module_count, module_names
        filtered = []
        for key, line in entries:
            if key in MODULE_IDENTITY_KEYS:
                continue
            # The first section is authoritative: project/root values and then
            # host_app values must not be overwritten by remote module defaults.
            if key in merged:
                continue
            merged[key] = line
            filtered.append((key, line))
        if filtered:
            section_data.append((title, filtered))
            module_count += 1
            if title not in ["Project", "host_app"]:
                module_names.append(title)

    # In source context: read project.env.config + project.env.secrets + module .env.config + .env.secrets
    # In deployed context: read per-module .env.config + .env.secrets (split)
    if is_source_context:
        # Source repo: project.env.config + project.env.secrets + module split files
        _append_section("Project", _read_env_file(project_env_config) + _read_env_file(project_env_secrets))
        hostapp_config = os.path.join(MODULES_DIR, "host_app", ".env.config")
        hostapp_secrets = os.path.join(MODULES_DIR, "host_app", ".env.secrets")
        _ensure_module_secrets_from_example(os.path.join(MODULES_DIR, "host_app"))
        if os.path.exists(hostapp_config) or os.path.exists(hostapp_secrets):
            _append_section("host_app", _read_env_file(hostapp_config) + _read_env_file(hostapp_secrets))
        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "host_app":
                    continue
                module_config = os.path.join(MODULES_DIR, module_name, ".env.config")
                module_secrets = os.path.join(MODULES_DIR, module_name, ".env.secrets")
                _ensure_module_secrets_from_example(os.path.join(MODULES_DIR, module_name))
                if os.path.exists(module_config) or os.path.exists(module_secrets):
                    _append_section(module_name, _read_env_file(module_config) + _read_env_file(module_secrets))

        # Build all_vars for transitive classification
        all_vars = {}
        for _title, entries in section_data:
            for key, line in entries:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    all_vars[key] = parts[1].strip()

        # Classify and write root-level split files
        config_pp_lines = []
        config_params_lines = []
        secrets_lines = []
        for section_title, entries in section_data:
            pp = []
            params = []
            secs = []
            for key, line in entries:
                value = all_vars.get(key, "")
                category = classify_env_var(key, value, all_vars)
                if category == "secrets":
                    secs.append(line)
                elif category == "ports_paths":
                    pp.append(line)
                else:
                    params.append(line)
            if pp:
                config_pp_lines.append(f"\n# ── {section_title} ──────────────────────────────────────────\n")
                config_pp_lines.extend(l + "\n" for l in pp)
            if params:
                config_params_lines.append(f"\n# ── {section_title} ──────────────────────────────────────────\n")
                config_params_lines.extend(l + "\n" for l in params)
            if secs:
                secrets_lines.append(f"\n# ── {section_title} ──────────────────────────────────────────\n")
                secrets_lines.extend(l + "\n" for l in secs)

        dst_config = os.path.join(DEPLOYMENT_ROOT, ".env.config")
        with open(dst_config, "w", encoding="utf-8") as f:
            f.write("# AUTO-GENERATED — do not edit manually.\n")
            f.write("# Configuration parameters (ports, paths, behavioural params).\n")
            if config_pp_lines:
                f.write("\n# ════════════════════════════════════════════════════════════════\n")
                f.write("#  Ports & Paths\n")
                f.write("# ════════════════════════════════════════════════════════════════\n")
                f.write("".join(config_pp_lines))
            if config_params_lines:
                f.write("\n# ════════════════════════════════════════════════════════════════\n")
                f.write("#  Params\n")
                f.write("# ════════════════════════════════════════════════════════════════\n")
                f.write("".join(config_params_lines))
            f.write("\n")
        modules_str = ", ".join(module_names) if module_names else "none"
        print(f"- Created merged .env.config from modules: {modules_str}")

        dst_secrets = os.path.join(DEPLOYMENT_ROOT, ".env.secrets")
        with open(dst_secrets, "w", encoding="utf-8") as f:
            f.write("# AUTO-GENERATED — do not edit manually.\n")
            f.write("# Secrets (passwords, tokens, secret keys).\n")
            f.write("# WARNING: Do not commit this file to version control.\n")
            f.write("".join(secrets_lines))
            f.write("\n")
        secrets_count = sum(1 for line in secrets_lines if "=" in line and not line.startswith("#"))
        print(f"- Created merged .env.secrets from modules: {modules_str}")
        _write_root_secrets_example()

        # Write per-module split files from combined .env
        # Project-level variables are excluded from per-module split files
        # because the merged docker-compose.yml uses ${VAR} interpolation from
        # the root .env files, not per-module env_file directives.
        def _write_module_split(module_dir, src_paths, label, exclude_keys=None):
            os.makedirs(module_dir, exist_ok=True)
            project_keys = {"APP_SLUG", "APP_NAME"}
            if exclude_keys:
                project_keys = project_keys | exclude_keys
            module_all_vars = {}
            module_entries = []
            for src_path in src_paths:
                if not src_path or not os.path.exists(src_path):
                    continue
                for key, line in _read_env_file(src_path):
                    # Project-level keys must live only in the merged root
                    # .env.config, not in per-module env files.
                    if key in project_keys:
                        continue
                    if key in module_all_vars:
                        continue
                    parts = line.split("=", 1)
                    module_all_vars[key] = parts[1].strip() if len(parts) == 2 else ""
                    module_entries.append((key, line))

            pp_lines = []
            params_lines = []
            sec_lines = []
            for key, line in module_entries:
                value = module_all_vars.get(key, "")
                category = classify_env_var(key, value, module_all_vars)
                if category == "secrets":
                    sec_lines.append(line + "\n")
                elif category == "ports_paths":
                    pp_lines.append(line + "\n")
                else:
                    params_lines.append(line + "\n")

            dst_config = os.path.join(module_dir, ".env.config")
            with open(dst_config, "w", encoding="utf-8") as out:
                out.write("# AUTO-GENERATED — do not edit manually.\n")
                out.write(f"# {label}\n")
                if pp_lines:
                    out.write("\n# Ports & Paths\n")
                    out.write("".join(pp_lines))
                if params_lines:
                    out.write("\n# Params\n")
                    out.write("".join(params_lines))

            dst_secrets = os.path.join(module_dir, ".env.secrets")
            with open(dst_secrets, "w", encoding="utf-8") as out:
                out.write("# AUTO-GENERATED — do not edit manually.\n")
                out.write(f"# {label} — secrets\n")
                out.write("# WARNING: Do not commit this file to version control.\n")
                if sec_lines:
                    out.write("".join(sec_lines))

        project_env_sources = []
        project_level_keys = set()
        if os.path.exists(project_env_config):
            project_env_sources.append(project_env_config)
            for key, _ in _read_env_file(project_env_config):
                project_level_keys.add(key)
        if os.path.exists(project_env_secrets):
            project_env_sources.append(project_env_secrets)
            for key, _ in _read_env_file(project_env_secrets):
                project_level_keys.add(key)

        hostapp_dir = os.path.join(DEPLOYMENT_ROOT, "modules", "host_app")
        hostapp_config = os.path.join(MODULES_DIR, "host_app", ".env.config")
        hostapp_secrets = os.path.join(MODULES_DIR, "host_app", ".env.secrets")
        if os.path.exists(hostapp_config) or os.path.exists(hostapp_secrets):
            _write_module_split(hostapp_dir, [hostapp_config, hostapp_secrets], "host_app deployed env", exclude_keys=project_level_keys)
            print(f"  Wrote deployed env → modules/host_app/.env.config + .env.secrets")
            _copy_module_secrets_example(os.path.join(MODULES_DIR, "host_app"), hostapp_dir)

        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "host_app":
                    continue
                module_config = os.path.join(MODULES_DIR, module_name, ".env.config")
                module_secrets = os.path.join(MODULES_DIR, module_name, ".env.secrets")
                if not os.path.exists(module_config) and not os.path.exists(module_secrets):
                    continue
                module_dir = os.path.join(DEPLOYMENT_ROOT, "modules", module_name)
                _write_module_split(module_dir, [module_config, module_secrets], f"{module_name} deployed env", exclude_keys=project_level_keys)
                print(f"  Wrote deployed env → modules/{module_name}/.env.config + .env.secrets")
                _copy_module_secrets_example(os.path.join(MODULES_DIR, module_name), module_dir)

    else:
        # Deployed context: preserve the existing merged root .env.config/.env.secrets
        # as the Project section first, so project identity keys (APP_SLUG, APP_NAME)
        # and other project-wide values survive regeneration even when per-module
        # files no longer contain them. Per-module files then supply module-specific
        # keys, with duplicates skipped in favor of the Project section values.
        root_env_config = os.path.join(DEPLOYMENT_ROOT, ".env.config")
        root_env_secrets = os.path.join(DEPLOYMENT_ROOT, ".env.secrets")
        project_entries = _read_env_file(root_env_config) + _read_env_file(root_env_secrets)
        if project_entries:
            _append_section("Project", project_entries)

        # Then read per-module .env.config + .env.secrets (or .env fallback)
        # and merge into root-level split files.
        hostapp_dir = os.path.join(MODULES_DIR, "host_app")
        _ensure_module_secrets_from_example(hostapp_dir)
        hostapp_config, hostapp_secrets = _read_split_or_combined(hostapp_dir)
        _append_section("host_app", hostapp_config + hostapp_secrets)

        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "host_app":
                    continue
                module_dir = os.path.join(MODULES_DIR, module_name)
                _ensure_module_secrets_from_example(module_dir)
                mod_config, mod_secrets = _read_split_or_combined(module_dir)
                if mod_config or mod_secrets:
                    _append_section(module_name, mod_config + mod_secrets)

        # Build all_vars for transitive classification
        all_vars = {}
        for _title, entries in section_data:
            for key, line in entries:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    all_vars[key] = parts[1].strip()

        # Classify and write root-level split files
        config_pp_lines = []
        config_params_lines = []
        secrets_lines = []
        for section_title, entries in section_data:
            pp = []
            params = []
            secs = []
            for key, line in entries:
                value = all_vars.get(key, "")
                category = classify_env_var(key, value, all_vars)
                if category == "secrets":
                    secs.append(line)
                elif category == "ports_paths":
                    pp.append(line)
                else:
                    params.append(line)
            if pp:
                config_pp_lines.append(f"\n# ── {section_title} ──────────────────────────────────────────\n")
                config_pp_lines.extend(l + "\n" for l in pp)
            if params:
                config_params_lines.append(f"\n# ── {section_title} ──────────────────────────────────────────\n")
                config_params_lines.extend(l + "\n" for l in params)
            if secs:
                secrets_lines.append(f"\n# ── {section_title} ──────────────────────────────────────────\n")
                secrets_lines.extend(l + "\n" for l in secs)

        dst_config = os.path.join(DEPLOYMENT_ROOT, ".env.config")
        with open(dst_config, "w", encoding="utf-8") as f:
            f.write("# AUTO-GENERATED — do not edit manually.\n")
            f.write("# Configuration parameters (ports, paths, behavioural params).\n")
            if config_pp_lines:
                f.write("\n# ════════════════════════════════════════════════════════════════\n")
                f.write("#  Ports & Paths\n")
                f.write("# ════════════════════════════════════════════════════════════════\n")
                f.write("".join(config_pp_lines))
            if config_params_lines:
                f.write("\n# ════════════════════════════════════════════════════════════════\n")
                f.write("#  Params\n")
                f.write("# ════════════════════════════════════════════════════════════════\n")
                f.write("".join(config_params_lines))
            f.write("\n")
        modules_str = ", ".join(module_names) if module_names else "none"
        print(f"- Created merged .env.config from modules: {modules_str}")

        dst_secrets = os.path.join(DEPLOYMENT_ROOT, ".env.secrets")
        with open(dst_secrets, "w", encoding="utf-8") as f:
            f.write("# AUTO-GENERATED — do not edit manually.\n")
            f.write("# Secrets (passwords, tokens, secret keys).\n")
            f.write("# WARNING: Do not commit this file to version control.\n")
            f.write("".join(secrets_lines))
            f.write("\n")
        secrets_count = sum(1 for line in secrets_lines if "=" in line and not line.startswith("#"))
        print(f"- Created merged .env.secrets from modules: {modules_str}")
        _write_root_secrets_example()

def build_compose_clean_env(env):
    scrub_prefixes = (
        "POSTGRES_", "APP_", "AUTHENTIK_", "VITE_", "BACKEND_", "FRONTEND_",
        "TEMPLATE_", "HOSTAPP_", "DATABASE_", "TIMESCALE", "NODE_", "CLIENT_",
        "TRAEFIK_", "TLS_", "LE_", "ACME_", "JWT_", "CORS_", "PUBLIC_",
        "INITIAL_", "EXTERNAL_", "MAIN_", "DATA_", "PROJECT_", "MODULE_",
    )
    return {
        k: v
        for k, v in env.items()
        if not any(k.startswith(prefix) for prefix in scrub_prefixes)
    }

def generate_merged_compose():
    compose_files = []
    module_order = []
    # host_app first, then alphabetically
    hostapp_compose = os.path.join(MODULES_DIR, "host_app", "docker-compose.yml")
    if os.path.exists(hostapp_compose):
        compose_files.append("modules/host_app/docker-compose.yml")
        module_order.append("host_app")
    if os.path.isdir(MODULES_DIR):
        for module_name in sorted(os.listdir(MODULES_DIR)):
            if module_name == "host_app":
                continue
            compose_path = os.path.join(MODULES_DIR, module_name, "docker-compose.yml")
            if os.path.exists(compose_path):
                compose_files.append(f"modules/{module_name}/docker-compose.yml")
                module_order.append(module_name)

    if not compose_files:
        print("No compose files found in deployment_root/modules/ — skipped merged docker-compose.yml generation")
        return

    explicit_env_per_service = {}
    service_headings = {}
    for rel_path in compose_files:
        src_path = os.path.join(DEPLOYMENT_ROOT, rel_path)
        svc_keys = _extract_explicit_env_keys(src_path)
        for svc, keys in svc_keys.items():
            if svc not in explicit_env_per_service:
                explicit_env_per_service[svc] = set()
            explicit_env_per_service[svc].update(keys)
        headings = _extract_service_headings(src_path)
        for svc, block in headings.items():
            service_headings.setdefault(svc, block)

    project_slug = os.getenv("APP_SLUG")
    clean_env = build_compose_clean_env(os.environ)
    compose_cmd = ["docker", "compose", "--project-directory", DEPLOYMENT_ROOT]
    # Pass --env-file flags for compose variable interpolation (${VAR} in compose YAML).
    env_config_path = os.path.join(DEPLOYMENT_ROOT, ".env.config")
    env_secrets_path = os.path.join(DEPLOYMENT_ROOT, ".env.secrets")
    if os.path.exists(env_config_path):
        compose_cmd.extend(["--env-file", env_config_path])
    if os.path.exists(env_secrets_path):
        compose_cmd.extend(["--env-file", env_secrets_path])
    if project_slug:
        compose_cmd.extend(["--project-name", project_slug])
    for compose_file in compose_files:
        compose_cmd.extend(["-f", compose_file])
    compose_cmd.append("config")
    compose_cmd.append("--no-interpolate")

    result = subprocess.run(
        compose_cmd,
        cwd=DEPLOYMENT_ROOT,
        capture_output=True,
        text=True,
        env=clean_env,
    )
    if result.returncode != 0:
        print("ERROR: unable to generate merged docker-compose.yml")
        print("compose_cmd: " + " ".join(compose_cmd))
        print(result.stderr.strip())
        sys.exit(result.returncode)

    # Collect all variable names defined in .env.config + .env.secrets.
    env_keys = set()
    env_keys.update(_read_env_keys(os.path.join(DEPLOYMENT_ROOT, ".env.config")))
    env_keys.update(_read_env_keys(os.path.join(DEPLOYMENT_ROOT, ".env.secrets")))
    raw_env_lines_per_service = _extract_environment_lines(result.stdout)

    output = _deresolved_compose(
        result.stdout,
        env_keys,
        explicit_env_per_service,
        service_headings,
    )
    output = _ensure_environment_headers(output, explicit_env_per_service)
    output = _restore_missing_environment_entries(output, raw_env_lines_per_service, explicit_env_per_service)
    output = _relativize_deployment_root_paths(output, DEPLOYMENT_ROOT)

    merged_compose_path = os.path.join(DEPLOYMENT_ROOT, "docker-compose.yml")
    with open(merged_compose_path, "w", encoding="utf-8") as f:
        f.write("# AUTO-GENERATED — do not edit manually.\n")
        f.write("# Edit the source docker-compose.yml in each module and re-run.\n")
        f.write(output)
    modules_str = ", ".join(module_order) if module_order else "none"
    print(f"- Created merged docker-compose.yml from modules: {modules_str}")

def invalidate_authentik_blueprint():
    """Delete the cached authz-plan.generated.yaml so the authentik-bootstrap
    container regenerates it on next start.  This ensures newly added modules'
    authorization contracts are picked up whenever the merged configuration is
    (re)generated."""
    blueprint_path = os.path.join(MODULES_DIR, "host_app", "authentik", "blueprints", "authz-plan.generated.yaml")
    if os.path.isfile(blueprint_path):
        try:
            os.remove(blueprint_path)
            print(f"Invalidated cached authentik blueprint → {blueprint_path}")
        except PermissionError:
            print(f"WARNING: Could not remove cached authentik blueprint (permission denied): {blueprint_path}")
            print("         Attempting with sudo...")
            try:
                subprocess.run(["sudo", "rm", "-f", blueprint_path], check=True, capture_output=True)
                print(f"Invalidated cached authentik blueprint with sudo → {blueprint_path}")
            except subprocess.CalledProcessError as e:
                print(f"WARNING: sudo rm also failed: {e}")
                print("         The authentik-bootstrap container will regenerate it on next start if AUTHORIZATION_PLAN_FORCE_REBUILD is set.")
    else:
        print("No cached authentik blueprint found — will be generated on next bootstrap")

def merge_modules_menu_mapping():
    """Produce the canonical modules_menu_mapping.json for the host_app runtime.

    Always merges menu_mapping arrays from all enabled modules into
    host_app/config/modules_menu_mapping.json. If the destination file
    already exists, prompts the user to choose between overwriting or keeping.
    """
    dst_dir = os.path.join(MODULES_DIR, "host_app", "config")
    dst_path = os.path.join(dst_dir, "modules_menu_mapping.json")

    # If the file already exists, prompt before overwriting
    if os.path.isfile(dst_path):
        print(f"modules_menu_mapping.json already exists at {dst_path}")
        print("Options:")
        print("  [r] Recreate from modules (overwrite)")
        print("  [k] Keep current (skip)")
        try:
            choice = input("Choose [r/k]: ").strip().lower()
        except EOFError:
            print("No interactive input available — keeping existing modules_menu_mapping.json")
            return
        if choice == "k":
            print("Keeping existing modules_menu_mapping.json")
            return
        elif choice != "r":
            print("Invalid choice, keeping existing modules_menu_mapping.json")
            return

    merged = {"menu_mapping": []}
    merged_count = 0

    if os.path.isdir(MODULES_DIR):
        for module_name in sorted(os.listdir(MODULES_DIR)):
            if module_name == "host_app":
                continue
            module_dir = os.path.join(MODULES_DIR, module_name)
            module_mapping_path = os.path.join(module_dir, "config", "modules_menu_mapping.json")
            module_menu_def_path = os.path.join(module_dir, "config", "menu_definition.json")
            
            # Warn if menu_definition.json exists but modules_menu_mapping.json is missing
            if os.path.isfile(module_menu_def_path) and not os.path.isfile(module_mapping_path):
                print(f"WARNING: Module '{module_name}' has menu_definition.json but is missing modules_menu_mapping.json")
            
            if os.path.isfile(module_mapping_path):
                with open(module_mapping_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "menu_mapping" in data and isinstance(data["menu_mapping"], list):
                    merged["menu_mapping"].extend(data["menu_mapping"])
                    merged_count += 1

    if merged["menu_mapping"]:
        os.makedirs(dst_dir, exist_ok=True)
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            f.write("\n")
        modules_str = ", ".join(sorted([m for m in os.listdir(MODULES_DIR) if m != "host_app" and os.path.isdir(os.path.join(MODULES_DIR, m))])) if os.path.isdir(MODULES_DIR) else "none"
        print(f"- Created merged modules_menu_mapping.json from modules: {modules_str}")
    else:
        print("WARNING: No modules_menu_mapping.json found in any enabled module")

def scan_module_json_files():
    """Scan all module directories (excluding host_app) for module.json files.
    Returns a dict mapping module_slug -> module.json content."""
    modules = {}
    if not os.path.isdir(MODULES_DIR):
        return modules
    
    for module_name in sorted(os.listdir(MODULES_DIR)):
        if module_name == "host_app":
            continue
        module_dir = os.path.join(MODULES_DIR, module_name)
        module_json_path = os.path.join(module_dir, "module.json")
        if os.path.isfile(module_json_path):
            try:
                with open(module_json_path, "r", encoding="utf-8") as f:
                    module_data = json.load(f)
                # Use the slug from module.json, fall back to directory name
                slug = module_data.get("slug", module_name)
                module_data["_module_dir"] = module_dir
                modules[slug] = module_data
            except (json.JSONDecodeError, IOError) as e:
                print(f"WARNING: Failed to read {module_json_path}: {e}")
    return modules

def extract_api_upstream_vars(modules):
    """Extract apiUpstream env var names from module.json routes[].
    Returns a set of env var names that must be present in merged .env.config."""
    api_upstream_vars = set()
    for slug, module_data in modules.items():
        custom_routes = module_data.get("routes") or []
        for route_entry in custom_routes:
            if not isinstance(route_entry, dict):
                continue
            api_upstream = route_entry.get("apiUpstream")
            if api_upstream and isinstance(api_upstream, str):
                match = re.match(r'\$\{([^}]+)\}', api_upstream)
                if match:
                    api_upstream_vars.add(match.group(1))
    return api_upstream_vars

def _module_has_frontend(module_data):
    """Check whether a module has a frontend sub-module.

    A module is considered to have a frontend if either:
    - module.json contains a 'frontendPort' key, or
    - a 'frontend/' directory exists inside the module directory.
    """
    if "frontendPort" in module_data:
        return True
    module_dir = module_data.get("_module_dir", "")
    if module_dir and os.path.isdir(os.path.join(module_dir, "frontend")):
        return True
    return False


def update_module_registry(modules):
    """Update module-registry.json with modules from module.json files.
    Adds missing modules and syncs structural fields (entry, remoteEntry, basePath)
    of existing entries to match the expected values derived from the module slug.
    Only modules with a frontend are added as Module Federation remotes."""
    registry_path = os.path.join(MODULES_DIR, "host_app", "config", "module-registry.json")

    # Load existing registry
    existing_registry = {"modules": []}
    if os.path.isfile(registry_path):
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                existing_registry = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"WARNING: Failed to read existing module-registry.json: {e}")

    # Build lookup of existing entries by name
    existing_by_name = {m["name"]: m for m in existing_registry.get("modules", [])}

    expected_fields = {
        "entry": lambda slug: f"/remotes/{slug}/mf-manifest.json",
        "remoteEntry": lambda slug: f"/remotes/{slug}/remoteEntry.js",
        "basePath": lambda slug: f"/{slug}",
    }

    added_count = 0
    updated_count = 0
    skipped_count = 0
    for slug, module_data in modules.items():
        if not _module_has_frontend(module_data):
            skipped_count += 1
            print(f"  Skipping backend-only module: {slug} (no frontend)")
            continue

        display_name = module_data.get("displayName", slug)

        if slug in existing_by_name:
            entry = existing_by_name[slug]
            changed = False
            for field, fn in expected_fields.items():
                expected = fn(slug)
                if entry.get(field) != expected:
                    entry[field] = expected
                    changed = True
            if changed:
                updated_count += 1
                print(f"  Synced registry entry for module: {slug}")
            continue

        new_entry = {
            "name": slug,
            "entry": f"/remotes/{slug}/mf-manifest.json",
            "remoteEntry": f"/remotes/{slug}/remoteEntry.js",
            "displayName": display_name,
            "basePath": f"/{slug}"
        }
        existing_registry["modules"].append(new_entry)
        added_count += 1
        print(f"  Auto-registered module: {slug} ({display_name})")

    if added_count > 0 or updated_count > 0:
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(existing_registry, f, indent=2)
            f.write("\n")
        parts = []
        if added_count:
            parts.append(f"added {added_count}")
        if updated_count:
            parts.append(f"synced {updated_count}")
        if parts:
            modules_str = ", ".join(sorted(modules.keys()))
            print(f"- Updated module-registry.json for modules: {modules_str}")
        else:
            print("- module-registry.json already up to date")
    else:
        print("module-registry.json already up to date")
    if skipped_count > 0:
        print(f"Skipped {skipped_count} backend-only module(s)")

def _load_module_env(module_dir):
    """Load .env.config and .env.secrets from a module directory into a dict.
    Values may reference other vars via ${VAR}; those are resolved against
    the map being built (and os.environ as fallback) as they are read."""
    env_map = {}
    for filename in (".env.config", ".env.secrets"):
        path = os.path.join(module_dir, filename)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip()
                value = re.sub(r'\$\{([^}]+)\}', lambda m: env_map.get(m.group(1), os.environ.get(m.group(1), m.group(0))), value)
                env_map[key] = value
    return env_map

def update_dynamic_yml_template(modules):
    """Update dynamic.yml.template with missing Traefik routes for new modules.
    Adds standard /remotes/<MODULE_SLUG> and /module/<MODULE_SLUG> routes."""
    template_path = os.path.join(MODULES_DIR, "host_app", "traefik", "dynamic.yml.template")

    if not os.path.isfile(template_path):
        print(f"WARNING: dynamic.yml.template not found at {template_path}")
        return

    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    def _section_bounds(content, section_name, next_section_names):
        marker_re = re.compile(r"^  " + re.escape(section_name) + r":\s*$", re.MULTILINE)
        match = marker_re.search(content)
        if not match:
            return None
        start = match.start()
        end = len(content)
        for next_name in next_section_names:
            next_re = re.compile(r"^  " + re.escape(next_name) + r":\s*$", re.MULTILINE)
            next_match = next_re.search(content, match.end())
            if next_match:
                end = min(end, next_match.start())
        return start, end

    def _section_keys(content, section_name, next_section_names):
        bounds = _section_bounds(content, section_name, next_section_names)
        if bounds is None:
            return set()
        start, end = bounds
        section = content[start:end]
        return set(re.findall(r"^    ([a-z0-9_-]+):\s*$", section, re.MULTILINE))

    def _deduplicate_section(content, section_name, next_section_names):
        bounds = _section_bounds(content, section_name, next_section_names)
        if bounds is None:
            return content
        start, end = bounds
        section = content[start:end]
        lines = section.splitlines(keepends=True)
        entry_pattern = re.compile(r"^    ([a-z0-9_-]+):\s*$")
        seen = set()
        output = []
        index = 0
        while index < len(lines):
            match = entry_pattern.match(lines[index].rstrip("\n"))
            if match and match.group(1) in seen:
                index += 1
                while index < len(lines) and not entry_pattern.match(lines[index].rstrip("\n")):
                    index += 1
                continue
            if match:
                seen.add(match.group(1))
            output.append(lines[index])
            index += 1
        return content[:start] + "".join(output) + content[end:]

    def _remove_named_entries(content, section_name, next_section_names, names_to_remove):
        bounds = _section_bounds(content, section_name, next_section_names)
        if bounds is None:
            return content
        start, end = bounds
        section = content[start:end]
        lines = section.splitlines(keepends=True)
        entry_pattern = re.compile(r"^    ([a-z0-9_-]+):\s*$")
        output = []
        index = 0
        while index < len(lines):
            match = entry_pattern.match(lines[index].rstrip("\n"))
            if match and match.group(1) in names_to_remove:
                index += 1
                while index < len(lines) and not entry_pattern.match(lines[index].rstrip("\n")):
                    index += 1
                continue
            output.append(lines[index])
            index += 1
        return content[:start] + "".join(output) + content[end:]

    # Repair duplicates left by earlier non-idempotent runs before adding routes.
    for section_name, next_sections in (
        ("routers", ("middlewares", "services")),
        ("middlewares", ("services",)),
        ("services", ()),
    ):
        template_content = _deduplicate_section(template_content, section_name, next_sections)

    # ── Force regeneration path ────────────────────────────────────────
    # When TRAEFIK_FORCE_ROUTE_REGEN=1, purge all module-owned route blocks
    # before the add-loop so they are re-emitted with current values.
    force_regen = os.environ.get("TRAEFIK_FORCE_ROUTE_REGEN", "0") == "1"
    if force_regen:
        purge = {"routers": set(), "middlewares": set(), "services": set()}
        for slug, module_data in modules.items():
            has_frontend = _module_has_frontend(module_data)
            purge["routers"].add(f"{slug}-module-{slug}")
            purge["middlewares"].add(f"{slug}-module-{slug}-stripprefix")
            purge["services"].add(f"{slug}-module-{slug}")
            if has_frontend:
                purge["routers"].add(f"{slug}-remotes-{slug}")
                purge["middlewares"].add(f"{slug}-remotes-{slug}-stripprefix")
                purge["services"].add(f"{slug}-remotes-{slug}")
            custom_routes = module_data.get("routes") or []
            for route_entry in custom_routes:
                if not isinstance(route_entry, dict):
                    continue
                prefix = route_entry.get("prefix")
                if not prefix or not isinstance(prefix, str) or not prefix.startswith("/"):
                    continue
                normalized_prefix = re.sub(r"[^a-zA-Z0-9]", "-", prefix.lstrip("/"))
                normalized_prefix = re.sub(r"-+", "-", normalized_prefix).strip("-")
                if not normalized_prefix:
                    continue
                route_name = f"{slug}-route-{normalized_prefix}"
                purge["routers"].add(route_name)
                purge["services"].add(route_name)
                if route_entry.get("stripPrefix", False):
                    purge["middlewares"].add(f"{route_name}-stripprefix")
        for section_name, next_sections in (
            ("routers", ("middlewares", "services")),
            ("middlewares", ("services",)),
            ("services", ()),
        ):
            template_content = _remove_named_entries(
                template_content, section_name, next_sections, purge[section_name]
            )
        print("  Force-regen: purged module-owned route blocks from dynamic.yml.template")

    existing_routers = _section_keys(template_content, "routers", ("middlewares", "services"))
    existing_middlewares = _section_keys(template_content, "middlewares", ("services",))
    existing_services = _section_keys(template_content, "services", ())
    new_entries = {"routers": [], "middlewares": [], "services": []}
    added_count = 0

    for slug, module_data in modules.items():
        has_frontend = _module_has_frontend(module_data)
        # Build a merged env map for ${VAR} resolution: os.environ overlaid
        # with this module's on-disk .env.config/.env.secrets values.
        module_env = _load_module_env(module_data.get("_module_dir", ""))
        merged_env = {**os.environ, **module_env}
        route_names = {
            "remotes": f"{slug}-remotes-{slug}",
            "module": f"{slug}-module-{slug}",
        }
        route_added = False

        router_module = f"""    # ── {slug} auto: /module/{slug} ─────────────────────────────────────────
    {route_names['module']}:
      rule: "Host(`${{EXTERNAL_BASE_HOST}}`) && PathPrefix(`/module/{slug}`)"
      priority: 110
      entryPoints:
        - web
        - websecure
      service: {route_names['module']}
      middlewares:
        - {route_names['module']}-stripprefix
      tls:
        certResolver: le

"""
        middleware_module = f"""    {route_names['module']}-stripprefix:
      stripPrefix:
        prefixes:
          - "/module/{slug}"

"""
        service_module = f"""    {route_names['module']}:
      loadBalancer:
        servers:
          - url: "http://{slug}-backend:8002"

"""

        # Only generate /remotes/<slug> routes for modules with a frontend.
        if has_frontend:
            router_remotes = f"""    # ── {slug} auto: /remotes/{slug} ─────────────────────────────────────────
    {route_names['remotes']}:
      rule: "Host(`${{EXTERNAL_BASE_HOST}}`) && PathPrefix(`/remotes/{slug}`)"
      priority: 130
      entryPoints:
        - web
        - websecure
      service: {route_names['remotes']}
      middlewares:
        - {route_names['remotes']}-stripprefix
      tls:
        certResolver: le

"""
            middleware_remotes = f"""    {route_names['remotes']}-stripprefix:
      stripPrefix:
        prefixes:
          - "/remotes/{slug}"

"""
            service_remotes = f"""    {route_names['remotes']}:
      loadBalancer:
        servers:
          - url: "http://{slug}-frontend:80"

"""
            for name, snippet in (
                (route_names["remotes"], router_remotes),
                (route_names["module"], router_module),
            ):
                if name not in existing_routers:
                    new_entries["routers"].append(snippet)
                    existing_routers.add(name)
                    route_added = True
            for name, snippet in (
                (f"{route_names['remotes']}-stripprefix", middleware_remotes),
                (f"{route_names['module']}-stripprefix", middleware_module),
            ):
                if name not in existing_middlewares:
                    new_entries["middlewares"].append(snippet)
                    existing_middlewares.add(name)
                    route_added = True
            for name, snippet in (
                (route_names["remotes"], service_remotes),
                (route_names["module"], service_module),
            ):
                if name not in existing_services:
                    new_entries["services"].append(snippet)
                    existing_services.add(name)
                    route_added = True
        else:
            print(f"  Skipping /remotes/{slug} route (backend-only module)")
            for name, snippet in (
                (route_names["module"], router_module),
            ):
                if name not in existing_routers:
                    new_entries["routers"].append(snippet)
                    existing_routers.add(name)
                    route_added = True
            for name, snippet in (
                (f"{route_names['module']}-stripprefix", middleware_module),
            ):
                if name not in existing_middlewares:
                    new_entries["middlewares"].append(snippet)
                    existing_middlewares.add(name)
                    route_added = True
            for name, snippet in (
                (route_names["module"], service_module),
            ):
                if name not in existing_services:
                    new_entries["services"].append(snippet)
                    existing_services.add(name)
                    route_added = True

        # ── Custom routes from module.json routes[] ──────────────────────
        custom_routes = module_data.get("routes") or []
        for route_entry in custom_routes:
            if not isinstance(route_entry, dict):
                print(f"  WARNING: {slug} routes[] entry is not a dict, skipping")
                continue

            prefix = route_entry.get("prefix")
            if not prefix or not isinstance(prefix, str) or not prefix.startswith("/"):
                print(f"  WARNING: {slug} routes[] entry has invalid or missing prefix, skipping")
                continue

            upstream = route_entry.get("upstream")
            service = route_entry.get("service")
            if (upstream and service) or (not upstream and not service):
                print(f"  WARNING: {slug} routes[] entry '{prefix}' must specify exactly one of upstream or service, skipping")
                continue

            priority = route_entry.get("priority", 120)
            if not isinstance(priority, int) or priority <= 10:
                print(f"  WARNING: {slug} routes[] entry '{prefix}' has invalid priority ({priority}), falling back to 120")
                priority = 120

            strip_prefix = bool(route_entry.get("stripPrefix", False))
            port = route_entry.get("port", 80)
            options = route_entry.get("options") or {}

            normalized_prefix = re.sub(r"[^a-zA-Z0-9]", "-", prefix.lstrip("/"))
            normalized_prefix = re.sub(r"-+", "-", normalized_prefix).strip("-")
            if not normalized_prefix:
                print(f"  WARNING: {slug} routes[] entry '{prefix}' produces empty normalized name, skipping")
                continue

            route_name = f"{slug}-route-{normalized_prefix}"
            middleware_name = f"{route_name}-stripprefix"

            router_entry = f"""    # ── {slug} custom route: {prefix} ─────────────────────────────────────────
    {route_name}:
      rule: "Host(`${{EXTERNAL_BASE_HOST}}`) && PathPrefix(`{prefix}`)"
      priority: {priority}
      entryPoints:
        - web
        - websecure
      service: {route_name}
"""
            if strip_prefix:
                router_entry += f"      middlewares:\n        - {middleware_name}\n"
            router_entry += "      tls:\n        certResolver: le\n\n"

            middleware_entry = ""
            if strip_prefix:
                middleware_entry = f"""    {middleware_name}:
      stripPrefix:
        prefixes:
          - "{prefix}"

"""

            if upstream:
                server_url = re.sub(r'\$\{([^}]+)\}', lambda m: merged_env.get(m.group(1), m.group(0)), upstream)
            else:
                server_url = f"http://{service}:{port}"
            service_entry = f"""    {route_name}:
      loadBalancer:
        servers:
          - url: "{server_url}"

"""

            if options.get("sse"):
                print(f"  DEBUG: {slug} route '{prefix}' options.sse: no special Traefik config needed, ignoring")
            if options.get("websocket"):
                print(f"  DEBUG: {slug} route '{prefix}' options.websocket: upgrade headers pass through by default")
            if options.get("forwardHeaders"):
                print(f"  DEBUG: {slug} route '{prefix}' options.forwardHeaders: not yet implemented, passing through")

            if route_name not in existing_routers:
                new_entries["routers"].append(router_entry)
                existing_routers.add(route_name)
                route_added = True
            if strip_prefix and middleware_name not in existing_middlewares:
                new_entries["middlewares"].append(middleware_entry)
                existing_middlewares.add(middleware_name)
                route_added = True
            if route_name not in existing_services:
                new_entries["services"].append(service_entry)
                existing_services.add(route_name)
                route_added = True

        if route_added:
            added_count += 1
            print(f"  Auto-generated Traefik routes for module: {slug}")

    updated_content = template_content
    if new_entries["routers"]:
        bounds = _section_bounds(updated_content, "middlewares", ("services",))
        if bounds:
            insertion = bounds[0]
        else:
            bounds = _section_bounds(updated_content, "services", ())
            insertion = bounds[0] if bounds else -1
        if insertion != -1:
            updated_content = updated_content[:insertion] + "".join(new_entries["routers"]) + updated_content[insertion:]
    if new_entries["middlewares"]:
        bounds = _section_bounds(updated_content, "services", ())
        if bounds:
            insertion = bounds[0]
            updated_content = updated_content[:insertion] + "".join(new_entries["middlewares"]) + updated_content[insertion:]
    if new_entries["services"]:
        updated_content = updated_content.rstrip() + "\n" + "".join(new_entries["services"])

    if updated_content != template_content:
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        modules_str = ", ".join(sorted(modules.keys())) if modules else "none"
        print(f"- Updated dynamic.yml.template (Traefik routes) for modules: {modules_str}")
    else:
        print("- dynamic.yml.template already up to date")

def auto_register_modules():
    """Auto-register newly pulled modules in module-registry.json and dynamic.yml.template."""
    print("── Auto-registering modules ─────────────────────────────────────────")
    modules = scan_module_json_files()
    
    if not modules:
        print("No module.json files found in modules/")
        return
    
    print(f"Found {len(modules)} module(s) with module.json")
    
    # Validate apiUpstream env vars are defined in module .env.config
    api_upstream_vars = extract_api_upstream_vars(modules)
    if api_upstream_vars:
        print(f"Validating {len(api_upstream_vars)} apiUpstream env var(s)...")
        for var_name in api_upstream_vars:
            # Check if the var is defined in any module's .env.config or .env.secrets
            var_found = False
            for slug, module_data in modules.items():
                module_dir = module_data.get("_module_dir", "")
                if not module_dir:
                    continue
                for env_file in [".env.config", ".env.secrets"]:
                    env_path = os.path.join(module_dir, env_file)
                    if os.path.exists(env_path):
                        env_keys = _read_env_keys(env_path)
                        if var_name in env_keys:
                            var_found = True
                            break
                if var_found:
                    break
            if not var_found:
                print(f"  WARNING: apiUpstream env var '{var_name}' is not defined in any module's .env.config or .env.secrets")
    
    update_module_registry(modules)
    update_dynamic_yml_template(modules)
    print("── Auto-registration complete ───────────────────────────────────────")

if __name__ == "__main__":
    print("── Merging module configurations ───────────────────────────────────")
    auto_register_modules()
    merge_env_files()
    generate_merged_compose()
    merge_modules_menu_mapping()
    invalidate_authentik_blueprint()
    print("── Merge complete ─────────────────────────────────────────────────")
PYTHON_EOF

python3 "$PYTHON_SCRIPT"
