#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
MODULES_DIR="${PROJECT_ROOT}/modules"
ENABLED_FILE="${MODULES_DIR}/enabled.md"

usage() {
  echo "Usage: $0 [module_name ...]"
  echo ""
  echo "Without arguments, validates all enabled modules from modules/enabled.md."
  echo "With arguments, validates only the listed modules."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  echo ""
  echo "Options:"
  echo "  -h, --help  Show this help message"
  exit 0
fi

if [[ ! -f "${ENABLED_FILE}" ]]; then
  echo "ERROR: enabled modules file not found: ${ENABLED_FILE}" >&2
  exit 1
fi

ENABLED_MODULES=()
while IFS= read -r line; do
  ENABLED_MODULES+=("$line")
done < <(python3 - "${ENABLED_FILE}" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
for raw_line in path.read_text(encoding='utf-8').splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#'):
        continue
    match = re.match(r'^([A-Za-z0-9_.-]+)\s*:\s*(local|remote)\s*$', line, re.IGNORECASE)
    if match:
        print(match.group(1))
PY
)

if [[ ${#ENABLED_MODULES[@]} -eq 0 ]]; then
  echo "No local or remote modules found in modules/enabled.md"
  exit 0
fi

if [[ $# -gt 0 ]]; then
  REQUESTED_MODULES=("$@")
else
  REQUESTED_MODULES=("${ENABLED_MODULES[@]}")
fi

module_is_enabled() {
  local candidate="$1"
  local enabled
  for enabled in "${ENABLED_MODULES[@]}"; do
    if [[ "${enabled}" == "${candidate}" ]]; then
      return 0
    fi
  done
  return 1
}

validate_env_file() {
  local env_file="$1"
  local module_name="$2"
  local line_no=0
  local line trimmed key

  if [[ ! -f "${env_file}" ]]; then
    echo "ERROR: [${module_name}] missing required env file: ${env_file}" >&2
    return 1
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line_no=$((line_no + 1))
    trimmed="${line#${line%%[![:space:]]*}}"
    if [[ -z "${trimmed}" || "${trimmed}" == \#* ]]; then
      continue
    fi
    if [[ "${trimmed}" != *"="* ]]; then
      echo "ERROR: [${module_name}] invalid env line ${line_no} in ${env_file}: ${line}" >&2
      return 1
    fi
    key="${trimmed%%=*}"
    key="${key//[[:space:]]/}"
    if [[ -z "${key}" || ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "ERROR: [${module_name}] invalid env key on line ${line_no} in ${env_file}: ${line}" >&2
      return 1
    fi
  done < "${env_file}"
}

validate_env_no_project_level_keys() {
  local env_file="$1"
  local module_name="$2"
  local line_no=0
  local line trimmed key
  local forbidden_keys=("APP_SLUG" "APP_NAME")

  if [[ ! -f "${env_file}" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line_no=$((line_no + 1))
    trimmed="${line#${line%%[![:space:]]*}}"
    if [[ -z "${trimmed}" || "${trimmed}" == \#* ]]; then
      continue
    fi
    if [[ "${trimmed}" != *"="* ]]; then
      continue
    fi
    key="${trimmed%%=*}"
    key="${key//[[:space:]]/}"
    for forbidden in "${forbidden_keys[@]}"; do
      if [[ "${key}" == "${forbidden}" ]]; then
        echo "ERROR: [${module_name}] forbidden project-level key '${forbidden}' must not be defined in module env file ${env_file}:${line_no}" >&2
        return 1
      fi
    done
  done < "${env_file}"
}

validate_env_required_keys() {
  local env_file="$1"
  local module_name="$2"
  local required_keys=("MODULE_SLUG" "MODULE_DOCKER_REGISTRY_PREFIX")
  local key

  if [[ ! -f "${env_file}" ]]; then
    return 0
  fi

  for key in "${required_keys[@]}"; do
    if ! grep -qE "^[[:space:]]*${key}[[:space:]]*=" "${env_file}"; then
      echo "ERROR: [${module_name}] missing required key '${key}' in ${env_file}" >&2
      return 1
    fi
  done
}

validate_compose_file() {
  local compose_file="$1"
  local module_name="$2"
  local module_dir="$3"

  if [[ ! -f "${compose_file}" ]]; then
    echo "ERROR: [${module_name}] missing required docker-compose.yml: ${compose_file}" >&2
    return 1
  fi

  python3 - "${compose_file}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(encoding='utf-8') as handle:
    content = handle.read()

try:
    import yaml  # type: ignore
except Exception:
    # Fallback: at least confirm it looks like YAML
    if 'services:' not in content:
        print(f"ERROR: missing 'services:' section in {path}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

data = yaml.safe_load(content)
if not isinstance(data, dict):
    print(f"ERROR: {path} is not a valid YAML mapping", file=sys.stderr)
    sys.exit(1)

if 'services' not in data or not isinstance(data.get('services'), dict):
    print(f"ERROR: missing 'services:' section in {path}", file=sys.stderr)
    sys.exit(1)

# Basic check: every service must be a mapping
for svc_name, svc_def in data['services'].items():
    if not isinstance(svc_def, dict):
        print(f"ERROR: service '{svc_name}' is not a mapping in {path}", file=sys.stderr)
        sys.exit(1)
    # Env var placeholders are NOT allowed in service names
    if '${' in svc_name or '$(' in svc_name:
        print(f"ERROR: env var placeholder not allowed in service name '{svc_name}' in {path}", file=sys.stderr)
        sys.exit(1)
    # Env var placeholders are NOT allowed in depends_on keys
    if isinstance(svc_def.get('depends_on'), dict):
        for dep_name in svc_def['depends_on']:
            if '${' in dep_name or '$(' in dep_name:
                print(f"ERROR: env var placeholder not allowed in depends_on '{dep_name}' in {path}", file=sys.stderr)
                sys.exit(1)
    elif isinstance(svc_def.get('depends_on'), list):
        for dep_name in svc_def['depends_on']:
            if isinstance(dep_name, str) and ('${' in dep_name or '$(' in dep_name):
                print(f"ERROR: env var placeholder not allowed in depends_on '{dep_name}' in {path}", file=sys.stderr)
                sys.exit(1)

# Env var placeholders are NOT allowed in top-level networks keys
if 'networks' in data and isinstance(data.get('networks'), dict):
    for net_name in data['networks']:
        if '${' in net_name or '$(' in net_name:
            print(f"ERROR: env var placeholder not allowed in networks key '{net_name}' in {path}", file=sys.stderr)
            sys.exit(1)

# Env var placeholders are NOT allowed in top-level volumes keys
if 'volumes' in data and isinstance(data.get('volumes'), dict):
    for vol_name in data['volumes']:
        if '${' in vol_name or '$(' in vol_name:
            print(f"ERROR: env var placeholder not allowed in volumes key '{vol_name}' in {path}", file=sys.stderr)
            sys.exit(1)

# No build: sections allowed — images must be pre-built
for svc_name, svc_def in data['services'].items():
    if isinstance(svc_def, dict) and 'build' in svc_def:
        print(f"ERROR: service '{svc_name}' contains forbidden 'build:' section in {path}", file=sys.stderr)
        sys.exit(1)
    # Every service must reference a pre-built image
    if isinstance(svc_def, dict) and 'image' not in svc_def:
        print(f"ERROR: service '{svc_name}' missing required 'image:' key in {path}", file=sys.stderr)
        sys.exit(1)
    # Volume mounts must never reference SOURCES/ folders
    volumes = svc_def.get('volumes', []) if isinstance(svc_def, dict) else []
    if isinstance(volumes, list):
        for vol in volumes:
            if isinstance(vol, str) and 'SOURCES/' in vol:
                print(f"ERROR: volume mount references SOURCES/ in service '{svc_name}': {vol} in {path}", file=sys.stderr)
                sys.exit(1)
PY
}

validate_config_file() {
  local config_file="$1"
  local module_name="$2"

  if [[ ! -r "${config_file}" ]]; then
    echo "ERROR: [${module_name}] unreadable config file: ${config_file}" >&2
    return 1
  fi

  case "${config_file}" in
    *.json)
      python3 - "${config_file}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open(encoding='utf-8') as handle:
    json.load(handle)
PY
      ;;
    *.yml|*.yaml)
      python3 - "${config_file}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    import yaml  # type: ignore
except Exception:
    print("WARNING: PyYAML not installed, skipping deep YAML validation", file=sys.stderr)
    sys.exit(0)

with path.open(encoding='utf-8') as handle:
    yaml.safe_load(handle)
PY
      ;;
    *)
      # Other config files are validated by readability and existence.
      ;;
  esac
}

validate_module_json() {
  local module_dir="$1"
  local module_name="$2"
  local json_file="${module_dir}/module.json"

  if [[ ! -f "${json_file}" ]]; then
    echo "ERROR: [${module_name}] missing required module.json: ${json_file}" >&2
    return 1
  fi

  python3 - "${json_file}" "${module_name}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
module_name = sys.argv[2]

with path.open(encoding='utf-8') as handle:
    data = json.load(handle)

required_fields = {'name', 'slug', 'displayName', 'role', 'cssPrefix'}
missing = required_fields - set(data.keys())
if missing:
    print(f"ERROR: [{module_name}] module.json missing required fields: {sorted(missing)}", file=sys.stderr)
    sys.exit(1)

if data.get('role') not in ('host', 'remote', 'side'):
    print(f"ERROR: [{module_name}] module.json 'role' must be 'host', 'remote' or 'side', got: {data.get('role')!r}", file=sys.stderr)
    sys.exit(1)

css_prefix = data.get('cssPrefix', '')
if not css_prefix.endswith('-'):
    print(f"ERROR: [{module_name}] module.json 'cssPrefix' must end with '-', got: {css_prefix!r}", file=sys.stderr)
    sys.exit(1)

for port_key in ('frontendPort', 'backendPort'):
    if port_key in data:
        port_val = data[port_key]
        if not isinstance(port_val, int):
            print(f"ERROR: [{module_name}] module.json '{port_key}' must be an integer, got: {port_val!r}", file=sys.stderr)
            sys.exit(1)

# Validate routes[] if present
routes = data.get('routes', [])
if not isinstance(routes, list):
    print(f"ERROR: [{module_name}] module.json 'routes' must be a list", file=sys.stderr)
    sys.exit(1)

RESERVED_PREFIXES = {
    '/', '/api', '/auth/callback', '/health',
    '/if', '/flows', '/application', '/static', '/media',
    '/api/v3', '/ws', '/outpost.goauthentik.io',
}
ALLOWED_OPTIONS = {'sse', 'websocket', 'forwardHeaders'}

seen_prefixes = set()
for i, entry in enumerate(routes):
    prefix = entry.get('prefix', '')
    if not prefix.startswith('/'):
        print(f"ERROR: [{module_name}] routes[{i}] prefix must start with '/', got: {prefix!r}", file=sys.stderr)
        sys.exit(1)
    if prefix in RESERVED_PREFIXES:
        print(f"ERROR: [{module_name}] routes[{i}] prefix '{prefix}' is a reserved namespace", file=sys.stderr)
        sys.exit(1)
    if prefix in seen_prefixes:
        print(f"ERROR: [{module_name}] routes[{i}] prefix '{prefix}' duplicates another routes[] entry", file=sys.stderr)
        sys.exit(1)
    seen_prefixes.add(prefix)

    has_upstream = bool(entry.get('upstream'))
    has_service = bool(entry.get('service'))
    if has_upstream and has_service:
        print(f"ERROR: [{module_name}] routes[{i}] prefix '{prefix}': both 'upstream' and 'service' specified — exactly one required", file=sys.stderr)
        sys.exit(1)
    if not has_upstream and not has_service:
        print(f"ERROR: [{module_name}] routes[{i}] prefix '{prefix}': neither 'upstream' nor 'service' specified — exactly one required", file=sys.stderr)
        sys.exit(1)

    priority = entry.get('priority', 120)
    if not isinstance(priority, int) or priority <= 10:
        print(f"ERROR: [{module_name}] routes[{i}] priority must be an integer > 10, got: {priority!r}", file=sys.stderr)
        sys.exit(1)

    options = entry.get('options', {})
    if not isinstance(options, dict):
        print(f"ERROR: [{module_name}] routes[{i}] 'options' must be an object", file=sys.stderr)
        sys.exit(1)
    unknown = set(options.keys()) - ALLOWED_OPTIONS
    if unknown:
        print(f"WARNING: [{module_name}] routes[{i}] unknown options: {sorted(unknown)} — adapter may ignore them", file=sys.stderr)
PY
}

validate_ideable_framework_specs() {
  local module_dir="$1"
  local module_name="$2"
  local json_file="${module_dir}/module.json"

  if [[ ! -f "${json_file}" ]]; then
    return 0
  fi

  if ! python3 - "${json_file}" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
with path.open(encoding='utf-8') as handle:
    data = json.load(handle)
sys.exit(0 if data.get('role') == 'remote' else 1)
PY
  then
    return 0
  fi

  local required_specs=(
    "SPECS/ideable-framework-specs/base-specs.md"
    "SPECS/ideable-framework-specs/auth-specs.md"
    "SPECS/ideable-framework-specs/module-integration-specs.md"
    "SPECS/ideable-framework-specs/infrastructure-file-list.md"
  )

  if [[ -d "${module_dir}/backend" ]]; then
    required_specs+=("backend/SPECS/ideable-framework-specs/base-specs.md")
  fi
  if [[ -d "${module_dir}/database" ]]; then
    required_specs+=("database/SPECS/ideable-framework-specs/base-specs.md")
  fi
  if [[ -d "${module_dir}/frontend" ]]; then
    required_specs+=(
      "frontend/SPECS/ideable-framework-specs/base_specs.md"
      "frontend/SPECS/ideable-framework-specs/shared-ui-specs.md"
      "frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md"
    )
  fi

  local missing=()
  local spec
  for spec in "${required_specs[@]}"; do
    if [[ ! -f "${module_dir}/${spec}" ]]; then
      missing+=("${spec}")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: [${module_name}] missing required ideable-framework-specs files for remote module:" >&2
    for m in "${missing[@]}"; do
      echo "  ${m}" >&2
    done
    return 1
  fi
}

validate_dockerfile_placement() {
  local module_dir="$1"
  local module_name="$2"
  local bad_files=()

  while IFS= read -r dockerfile; do
    # Allow only if path ends with /SOURCES/Dockerfile
    if [[ "${dockerfile}" != */SOURCES/Dockerfile ]]; then
      bad_files+=("${dockerfile}")
    fi
  done < <(find "${module_dir}" -name 'Dockerfile' -type f 2>/dev/null)

  if [[ ${#bad_files[@]} -gt 0 ]]; then
    echo "ERROR: [${module_name}] Dockerfile(s) found outside of <sub_module>/SOURCES/ (see general-guidelines.md Dockerfiles section):" >&2
    for f in "${bad_files[@]}"; do
      echo "  ${f}" >&2
    done
    return 1
  fi
}

validate_module() {
  local module_name="$1"
  local module_dir="${MODULES_DIR}/${module_name}"
  local config_dir="${module_dir}/config"

  if [[ ! -d "${module_dir}" ]]; then
    echo "ERROR: module folder not found: ${module_dir}" >&2
    return 1
  fi

  if [[ ! -d "${config_dir}" ]]; then
    echo "ERROR: [${module_name}] missing required config folder: ${config_dir}" >&2
    return 1
  fi

  validate_module_json "${module_dir}" "${module_name}"

  # host_app in remote module repos is a runtime-only skeleton (no SPECS/ or sub-module SOURCES/).
  # Skip source-level validation and only validate runtime artifacts.
  if [[ "${module_name}" == "host_app" && ! -d "${module_dir}/SPECS" ]]; then
    echo "  [${module_name}] Runtime-only host_app detected; skipping full module validation."
    validate_env_file "${module_dir}/.env.config" "${module_name}"
    validate_env_file "${module_dir}/.env.secrets" "${module_name}"
    validate_env_file "${module_dir}/.env.config.example" "${module_name}"
    validate_env_file "${module_dir}/.env.secrets.example" "${module_name}"
    validate_env_required_keys "${module_dir}/.env.config" "${module_name}"
    validate_env_required_keys "${module_dir}/.env.config.example" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.config" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.secrets" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.config.example" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.secrets.example" "${module_name}"
    validate_compose_file "${module_dir}/docker-compose.yml" "${module_name}" "${module_dir}"
  else
    validate_ideable_framework_specs "${module_dir}" "${module_name}"

    if [[ ! -f "${module_dir}/SPECS/dependencies.md" ]]; then
      echo "ERROR: [${module_name}] missing required SPECS/dependencies.md: ${module_dir}/SPECS/dependencies.md" >&2
      return 1
    fi

    validate_dockerfile_placement "${module_dir}" "${module_name}"

    validate_env_file "${module_dir}/.env.config" "${module_name}"
    validate_env_file "${module_dir}/.env.secrets" "${module_name}"
    validate_env_file "${module_dir}/.env.config.example" "${module_name}"
    validate_env_file "${module_dir}/.env.secrets.example" "${module_name}"
    validate_env_required_keys "${module_dir}/.env.config" "${module_name}"
    validate_env_required_keys "${module_dir}/.env.config.example" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.config" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.secrets" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.config.example" "${module_name}"
    validate_env_no_project_level_keys "${module_dir}/.env.secrets.example" "${module_name}"
    validate_compose_file "${module_dir}/docker-compose.yml" "${module_name}" "${module_dir}"
  fi

  config_files=()
  while IFS= read -r line; do
    config_files+=("$line")
  done < <(find "${config_dir}" -type f | sort)

  if [[ ${#config_files[@]} -eq 0 ]]; then
    echo "ERROR: [${module_name}] config folder is empty: ${config_dir}" >&2
    return 1
  fi

  local module_role
  module_role=$(python3 - "${module_dir}/module.json" <<'PY'
import json, sys
from pathlib import Path
with Path(sys.argv[1]).open(encoding='utf-8') as f:
    print(json.load(f).get('role', ''), end='')
PY
)

  if [[ "${module_role}" != "side" && ! -f "${config_dir}/authorization.yaml" ]]; then
    # Runtime-only host_app uses pre-built images; authorization is baked in
    if [[ "${module_name}" == "host_app" && ! -d "${module_dir}/SPECS" ]]; then
      :
    else
      echo "ERROR: [${module_name}] missing required config/authorization.yaml: ${config_dir}/authorization.yaml" >&2
      return 1
    fi
  fi

  local config_file
  for config_file in "${config_files[@]}"; do
    if [[ -d "${config_file}" ]]; then
      continue
    fi
    validate_config_file "${config_file}" "${module_name}"
  done

  echo "[${module_name}] validation passed"
}

for module_name in "${REQUESTED_MODULES[@]}"; do
  if ! module_is_enabled "${module_name}"; then
    echo "ERROR: requested module is not enabled: ${module_name}" >&2
    exit 1
  fi
  validate_module "${module_name}"
done

# Cross-module routes[] prefix collision check
python3 - "${MODULES_DIR}" "${REQUESTED_MODULES[@]}" <<'PY'
import json
import sys
from pathlib import Path

modules_dir = Path(sys.argv[1])
module_names = sys.argv[2:]

prefix_owner = {}
collision_found = False

for name in module_names:
    mj = modules_dir / name / "module.json"
    if not mj.is_file():
        continue
    with mj.open(encoding="utf-8") as f:
        data = json.load(f)
    for entry in data.get("routes", []):
        prefix = entry.get("prefix", "")
        if prefix in prefix_owner:
            print(f"ERROR: routes[] prefix '{prefix}' collision between modules '{prefix_owner[prefix]}' and '{name}'", file=sys.stderr)
            collision_found = True
        else:
            prefix_owner[prefix] = name

if collision_found:
    sys.exit(1)
PY

echo "Module validation complete"
