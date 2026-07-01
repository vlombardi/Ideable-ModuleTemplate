#!/bin/bash
# create-merged-configuration.sh
# Runs at deployment_root side to regenerate the merged .env.config, .env.secrets
# and docker-compose.yml from the per-module files already deployed under
# deployment_root/modules/.
#
# Usage:
#   ./create-merged-configuration.sh [-h|--help]

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Regenerates the merged .env.config, .env.secrets and docker-compose.yml from per-module files"
    echo "already deployed under deployment_root/modules/."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# Detect context: source repo (script in scripts/runtime/config/) vs deployed (script in scripts/)
# Source repo: script is three levels below the project root, so look for project.env.config there.
if [[ -f "$SCRIPT_DIR/../../../project.env.config" ]]; then
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
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


def classify_env_var(key, value, all_vars=None):
    if key not in NOT_SECRET_OVERRIDE:
        for suffix in SECRET_SUFFIXES:
            if key.endswith(suffix):
                return "secrets"
    if all_vars and value:
        stripped = value.strip()
        if stripped.startswith("${") and stripped.endswith("}"):
            ref_key = stripped[2:-1]
            if ref_key in all_vars:
                ref_classification = classify_env_var(ref_key, all_vars[ref_key], all_vars)
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

    def _append_section(title, entries):
        nonlocal module_count
        filtered = []
        for key, line in entries:
            if key in MODULE_IDENTITY_KEYS:
                continue
            if key in merged:
                continue
            merged[key] = line
            filtered.append((key, line))
        section_data.append((title, filtered))
        module_count += 1

    # In source context: read project.env.config + project.env.secrets + module .env.config + .env.secrets
    # In deployed context: read per-module .env.config + .env.secrets (split)
    if is_source_context:
        # Source repo: project.env.config + project.env.secrets + module split files
        _append_section("Project", _read_env_file(project_env_config) + _read_env_file(project_env_secrets))
        hostapp_config = os.path.join(MODULES_DIR, "HostApp", ".env.config")
        hostapp_secrets = os.path.join(MODULES_DIR, "HostApp", ".env.secrets")
        if os.path.exists(hostapp_config) or os.path.exists(hostapp_secrets):
            _append_section("HostApp", _read_env_file(hostapp_config) + _read_env_file(hostapp_secrets))
        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "HostApp":
                    continue
                module_config = os.path.join(MODULES_DIR, module_name, ".env.config")
                module_secrets = os.path.join(MODULES_DIR, module_name, ".env.secrets")
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
        print(f"Generated deployment_root/.env.config ({len(merged)} variables from {module_count} module(s))")

        dst_secrets = os.path.join(DEPLOYMENT_ROOT, ".env.secrets")
        with open(dst_secrets, "w", encoding="utf-8") as f:
            f.write("# AUTO-GENERATED — do not edit manually.\n")
            f.write("# Secrets (passwords, tokens, secret keys).\n")
            f.write("# WARNING: Do not commit this file to version control.\n")
            f.write("".join(secrets_lines))
            f.write("\n")
        secrets_count = sum(1 for line in secrets_lines if "=" in line and not line.startswith("#"))
        print(f"Generated deployment_root/.env.secrets ({secrets_count} secret variables)")

        # Write per-module split files from combined .env
        def _write_module_split(module_dir, src_paths, label):
            os.makedirs(module_dir, exist_ok=True)
            project_keys = {"APP_SLUG", "APP_NAME"}
            module_all_vars = {}
            module_entries = []
            for idx, src_path in enumerate(src_paths):
                if not src_path or not os.path.exists(src_path):
                    continue
                for key, line in _read_env_file(src_path):
                    if idx > 0 and key in project_keys:
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
        if os.path.exists(project_env_config):
            project_env_sources.append(project_env_config)
        if os.path.exists(project_env_secrets):
            project_env_sources.append(project_env_secrets)

        hostapp_dir = os.path.join(DEPLOYMENT_ROOT, "modules", "HostApp")
        hostapp_config = os.path.join(MODULES_DIR, "HostApp", ".env.config")
        hostapp_secrets = os.path.join(MODULES_DIR, "HostApp", ".env.secrets")
        if os.path.exists(hostapp_config) or os.path.exists(hostapp_secrets):
            _write_module_split(hostapp_dir, project_env_sources + [hostapp_config, hostapp_secrets], "HostApp deployed env")
            print(f"  Wrote deployed env → modules/HostApp/.env.config + .env.secrets")

        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "HostApp":
                    continue
                module_config = os.path.join(MODULES_DIR, module_name, ".env.config")
                module_secrets = os.path.join(MODULES_DIR, module_name, ".env.secrets")
                if not os.path.exists(module_config) and not os.path.exists(module_secrets):
                    continue
                module_dir = os.path.join(DEPLOYMENT_ROOT, "modules", module_name)
                _write_module_split(module_dir, project_env_sources + [module_config, module_secrets], f"{module_name} deployed env")
                print(f"  Wrote deployed env → modules/{module_name}/.env.config + .env.secrets")

    else:
        # Deployed context: read per-module .env.config + .env.secrets (or .env fallback)
        # and merge into root-level split files.
        hostapp_dir = os.path.join(MODULES_DIR, "HostApp")
        hostapp_config, hostapp_secrets = _read_split_or_combined(hostapp_dir)
        _append_section("HostApp", hostapp_config + hostapp_secrets)

        if os.path.isdir(MODULES_DIR):
            for module_name in sorted(os.listdir(MODULES_DIR)):
                if module_name == "HostApp":
                    continue
                module_dir = os.path.join(MODULES_DIR, module_name)
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
        print(f"Generated deployment_root/.env.config ({len(merged)} variables from {module_count} module(s))")

        dst_secrets = os.path.join(DEPLOYMENT_ROOT, ".env.secrets")
        with open(dst_secrets, "w", encoding="utf-8") as f:
            f.write("# AUTO-GENERATED — do not edit manually.\n")
            f.write("# Secrets (passwords, tokens, secret keys).\n")
            f.write("# WARNING: Do not commit this file to version control.\n")
            f.write("".join(secrets_lines))
            f.write("\n")
        secrets_count = sum(1 for line in secrets_lines if "=" in line and not line.startswith("#"))
        print(f"Generated deployment_root/.env.secrets ({secrets_count} secret variables)")

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
    # HostApp first, then alphabetically
    hostapp_compose = os.path.join(MODULES_DIR, "HostApp", "docker-compose.yml")
    if os.path.exists(hostapp_compose):
        compose_files.append("modules/HostApp/docker-compose.yml")
        module_order.append("HostApp")
    if os.path.isdir(MODULES_DIR):
        for module_name in sorted(os.listdir(MODULES_DIR)):
            if module_name == "HostApp":
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
    print(f"Generated merged docker-compose.yml (from {len(compose_files)} module(s): {', '.join(module_order)})")

def merge_modules_menu_mapping():
    """Produce the canonical modules_menu_mapping.json for the HostApp runtime.

    If an explicit HostApp mapping exists, use it directly.
    Otherwise, auto-merge menu_mapping arrays from all enabled modules.
    """
    hostapp_mapping_src = os.path.join(MODULES_DIR, "HostApp", "config", "modules_menu_mapping.json")
    dst_dir = os.path.join(MODULES_DIR, "HostApp", "config")
    dst_path = os.path.join(dst_dir, "modules_menu_mapping.json")

    if os.path.isfile(hostapp_mapping_src):
        os.makedirs(dst_dir, exist_ok=True)
        with open(hostapp_mapping_src, "r", encoding="utf-8") as f:
            payload = json.load(f)
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print("Using explicit HostApp modules_menu_mapping.json")
        return

    merged = {"menu_mapping": []}
    merged_count = 0

    if os.path.isdir(MODULES_DIR):
        for module_name in sorted(os.listdir(MODULES_DIR)):
            if module_name == "HostApp":
                continue
            module_mapping_path = os.path.join(MODULES_DIR, module_name, "config", "modules_menu_mapping.json")
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
        print(f"Generated merged modules_menu_mapping.json from {merged_count} module(s)")
    else:
        print("WARNING: No modules_menu_mapping.json found in HostApp or any enabled module")

if __name__ == "__main__":
    print("── Merging module configurations ───────────────────────────────────")
    merge_env_files()
    generate_merged_compose()
    merge_modules_menu_mapping()
    print("── Merge complete ─────────────────────────────────────────────────")
PYTHON_EOF

python3 "$PYTHON_SCRIPT"
