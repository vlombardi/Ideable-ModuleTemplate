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
    match = re.match(r'^([A-Za-z0-9_.-]+)\s*:\s*enabled(?:-(\w+))?\s*$', line, re.IGNORECASE)
    if match:
        print(match.group(1))
PY
)

if [[ ${#ENABLED_MODULES[@]} -eq 0 ]]; then
  echo "No enabled modules found in modules/enabled.md"
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
    echo "ERROR: [${module_name}] missing required .env file: ${env_file}" >&2
    return 1
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line_no=$((line_no + 1))
    trimmed="${line#${line%%[![:space:]]*}}"
    if [[ -z "${trimmed}" || "${trimmed}" == \#* ]]; then
      continue
    fi
    if [[ "${trimmed}" != *"="* ]]; then
      echo "ERROR: [${module_name}] invalid .env line ${line_no}: ${line}" >&2
      return 1
    fi
    key="${trimmed%%=*}"
    key="${key//[[:space:]]/}"
    if [[ -z "${key}" || ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "ERROR: [${module_name}] invalid .env key on line ${line_no}: ${line}" >&2
      return 1
    fi
  done < "${env_file}"
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

  validate_env_file "${module_dir}/.env" "${module_name}"
  validate_compose_file "${module_dir}/docker-compose.yml" "${module_name}" "${module_dir}"

  config_files=()
  while IFS= read -r line; do
    config_files+=("$line")
  done < <(find "${config_dir}" -type f | sort)

  if [[ ${#config_files[@]} -eq 0 ]]; then
    echo "ERROR: [${module_name}] config folder is empty: ${config_dir}" >&2
    return 1
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

echo "Module validation complete"
