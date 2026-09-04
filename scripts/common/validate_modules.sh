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

# `local` or `remote` for a module, from modules/enabled.md — empty when it is not enabled.
# The mode is what decides whether a module's images are BUILT here or CONSUMED from a registry,
# and therefore which of the two tags applies to it.
module_mode() {
  local candidate="$1"
  python3 - "${ENABLED_FILE}" "${candidate}" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
wanted = sys.argv[2].lower()
for raw_line in path.read_text(encoding='utf-8').splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#'):
        continue
    match = re.match(r'^([A-Za-z0-9_.-]+)\s*:\s*(local|remote)\s*$', line, re.IGNORECASE)
    if match and match.group(1).lower() == wanted:
        print(match.group(2).lower())
        break
PY
}

# A module enabled as `remote` must say which published release it consumes — before the build.
#
# Without this, the failure arrives from compose as `manifest unknown` AFTER a two-minute build,
# naming an image tag derived from the consumer's own commit: a build that exists in no registry
# because this project never made it. The check costs nothing and the message names the cause.
validate_consumed_image_tag() {
  local module_dir="$1"
  local module_name="$2"
  local mode="$3"

  [[ "${mode}" == "remote" ]] || return 0

  python3 - "${module_dir}/module.json" "${module_name}" "${PROJECT_ROOT}" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

json_path, module_name, project_root = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

try:
    data = json.loads(json_path.read_text(encoding='utf-8'))
except (OSError, ValueError) as exc:
    print(f"ERROR: [{module_name}] module.json unreadable: {exc}", file=sys.stderr)
    sys.exit(1)

tag = str(data.get('consumedImageTag') or '').strip()
if not tag:
    print(f"ERROR: [{module_name}] is enabled as `remote` but declares no 'consumedImageTag' in "
          f"module.json.", file=sys.stderr)
    print(f"  A remote module's images are built and published elsewhere, so the tag to pull "
          f"cannot come from this repository's commit.", file=sys.stderr)
    print(f'  ACTION: add "consumedImageTag": "<published-release>" to '
          f"modules/{module_name}/module.json.", file=sys.stderr)
    sys.exit(1)

# The tag must not be this repository's own build identity. That is the defect being prevented, and
# it is worth naming precisely rather than checking a shape: a project that pinned IMAGE_TAG to its
# commit as a workaround would otherwise pass this check while still pulling an image nobody built.
try:
    sha = subprocess.run(['git', '-C', str(project_root), 'rev-parse', '--short', 'HEAD'],
                         capture_output=True, text=True, check=True).stdout.strip()
except (subprocess.CalledProcessError, FileNotFoundError):
    sha = ''

if sha and tag in (sha, f'{sha}-dirty'):
    print(f"ERROR: [{module_name}] is declared `remote` but its consumedImageTag is this "
          f"repository's local commit ({tag!r}).", file=sys.stderr)
    print(f"  Nobody published that build: the images come from the project that owns this module, "
          f"and compose would fail with `manifest unknown` after the build has already run.",
          file=sys.stderr)
    print(f"  ACTION: set consumedImageTag to a release published by that project.", file=sys.stderr)
    sys.exit(1)

# A moving tag resolves, so this cannot be an error without breaking every project that consumes a
# `latest` publish today. It is still the thing `rules/general-guidelines.md` § *Image tags are
# immutable* argues against, and saying so is the only way the argument reaches the person who can
# act on it.
if re.fullmatch(r'latest|stable|main|master|edge', tag, re.IGNORECASE):
    print(f"WARNING: [{module_name}] consumedImageTag is the moving tag {tag!r}. Two different "
          f"publishes answer to it, so 'which build is running?' has no answer here and a pull can "
          f"replace a working image. Prefer a published release tag.")
PY
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

from datetime import datetime

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

# Module identity for the seed lifecycle. `version` is OPTIONAL: during development a
# module is conceptually always "latest", and forcing a bump would be busywork that gets skipped. The
# seed is therefore triggered by the module's authorization-contract hash, not by this field — version
# and buildDateTime exist so a conflict report can name a release a human recognises.
if 'version' in data and not (isinstance(data['version'], str) and data['version'].strip()):
    print(f"ERROR: [{module_name}] module.json 'version', when present, must be a non-empty string, got: {data['version']!r}", file=sys.stderr)
    sys.exit(1)

if 'buildDateTime' in data:
    build_dt = data['buildDateTime']
    if not isinstance(build_dt, str) or not build_dt.strip():
        print(f"ERROR: [{module_name}] module.json 'buildDateTime' must be a non-empty ISO-8601 string, got: {build_dt!r}", file=sys.stderr)
        sys.exit(1)
    try:
        datetime.fromisoformat(build_dt.replace('Z', '+00:00'))
    except ValueError:
        print(f"ERROR: [{module_name}] module.json 'buildDateTime' must be ISO-8601, got: {build_dt!r}", file=sys.stderr)
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

# The entity named by `<entity>:read_all_tenants` must have a table, and the message must say
# which of the three names it actually checked.
#
# Three naming systems have to agree on this entity: the permission prefix in
# config/authorization.yaml, the collection route segment, and the table in app/models.py. By
# default they are one token; a module that cannot manage that declares the mapping in module.json
# (`crossTenantEntity`). Before this check, a module whose names disagreed learned it from a whole
# tenancy suite going red at import.
#
# **Two of the three, and it says so.** This runs pre-build: there is no stack and no
# `/openapi.json`, so the route cannot be checked here — that half stays in the suite, which now
# reports it as one readable failure. A check claiming to have verified three names while verifying
# two is the same over-stated signal being fixed everywhere else in this change.
validate_cross_tenant_entity_naming() {
  local module_dir="$1"
  local module_name="$2"

  local authz="${module_dir}/config/authorization.yaml"
  local models="${module_dir}/backend/SOURCES/app/models.py"
  [[ -f "${authz}" && -f "${models}" ]] || return 0

  python3 - "${authz}" "${models}" "${module_dir}/module.json" "${module_name}" <<'PY'
import json
import re
import sys
from pathlib import Path

authz, models, module_json, module_name = (Path(sys.argv[1]), Path(sys.argv[2]),
                                           Path(sys.argv[3]), sys.argv[4])

permissions = re.findall(r'-\s*([\w-]+):read_all_tenants\b', authz.read_text(encoding='utf-8'))
if not permissions:
    # Not every module grants a cross-tenant read. Absence is a legitimate design, not a defect,
    # and the tenancy suite says so in its own words when it needs one.
    sys.exit(0)
entity = permissions[0]

tables = re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]", models.read_text(encoding='utf-8'))
if not tables:
    sys.exit(0)  # a module with no models has nothing to disagree about

declared = {}
if module_json.is_file():
    try:
        meta = json.loads(module_json.read_text(encoding='utf-8'))
        declared = meta.get('crossTenantEntity') or {}
        declared = declared if isinstance(declared, dict) else {}
    except ValueError:
        declared = {}

declared_table = str(declared.get('table') or '').strip()
if declared_table:
    if declared_table not in tables:
        print(f"ERROR: [{module_name}] module.json crossTenantEntity.table is "
              f"{declared_table!r}, which no __tablename__ in "
              f"{models.name} declares.", file=sys.stderr)
        print(f"  tables declared: {sorted(tables)}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)

if not [t for t in tables if t == entity or t.endswith(f'_{entity}')]:
    print(f"ERROR: [{module_name}] the cross-tenant entity and the models disagree about this "
          f"module's entity names.", file=sys.stderr)
    print(f"  permission entity : {entity}   (from `{entity}:read_all_tenants` in "
          f"config/authorization.yaml)", file=sys.stderr)
    print(f"  tables declared   : {sorted(tables)}   (in backend/SOURCES/app/models.py)",
          file=sys.stderr)
    print(f"  collection route  : NOT CHECKED HERE — it comes from the running backend's "
          f"/openapi.json, and this validation runs before the build. The tenancy suite checks it.",
          file=sys.stderr)
    print(f"  By default all three are one token. When they cannot be, declare the mapping instead "
          f"of renaming — add to modules/{module_name}/module.json:", file=sys.stderr)
    print(f'      "crossTenantEntity": {{"collectionRoute": "/<route>", "table": "<table>"}}',
          file=sys.stderr)
    print(f"  See auth-specs.md §5.5.", file=sys.stderr)
    sys.exit(1)
PY
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

  local module_mode_value
  module_mode_value="$(module_mode "${module_name}")"
  validate_consumed_image_tag "${module_dir}" "${module_name}" "${module_mode_value}"
  validate_cross_tenant_entity_naming "${module_dir}" "${module_name}"

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

  # --- schema ownership -----------------------------------------------------------------------
  # Invariant: when a module has migrations, Alembic is the ONLY thing that writes DDL. This is
  # a static check because it must run at build time, where no database exists; the behavioural
  # gates live in scripts/dev/schema.sh verify. Both matter — this one catches the rule being
  # broken in the repository, that one catches the schema being wrong in a database.
  if [[ -d "${module_dir}/backend/SOURCES/alembic" ]]; then
    local ddl='CREATE[[:space:]]+TABLE|ALTER[[:space:]]+TABLE|DROP[[:space:]]+TABLE|CREATE[[:space:]]+INDEX'

    # The bootstrap job seeds data; it must not define schema. A bootstrap that created tables
    # is how four au_* columns survived in deployed databases with no file declaring them.
    if [[ -f "${module_dir}/docker-compose.yml" ]] &&
       sed -n '/SYNC-MANAGED-BEGIN: bootstrap-service/,/SYNC-MANAGED-END: bootstrap-service/p' \
         "${module_dir}/docker-compose.yml" | grep -qiE "${ddl}"; then
      echo "ERROR: [${module_name}] the bootstrap job contains DDL — Alembic owns the schema." >&2
      echo "       Move it to a migration: scripts/dev/schema.sh migration ${module_name} -m '...'" >&2
      return 1
    fi

    # Every SQL file under database/, wherever it lives. The first version of this check looked
    # only in database/SOURCES/initdb/ — host_app keeps its init files directly in
    # database/SPECS/, so the check found nothing to inspect and passed while an initdb script
    # was creating four tables on every fresh volume. A gate that looks in the wrong place is
    # not a gate.
    local sql_file
    while IFS= read -r sql_file; do
      [[ -f "${sql_file}" ]] || continue
      local base="$(basename "${sql_file}")"
      # schema.sql is the GENERATED rendering of the migrations; it is documentation and nothing
      # applies it. It must say so on line one, or it is indistinguishable from a hand-written
      # definition someone will eventually wire up.
      if [[ "${base}" == "schema.sql" ]]; then
        if ! head -1 "${sql_file}" | grep -qE "GENERATED|RETIRED"; then
          echo "ERROR: [${module_name}] ${sql_file#"${module_dir}/"} looks hand-written." >&2
          echo "       Regenerate it: scripts/dev/schema.sh schema-sql ${module_name}" >&2
          return 1
        fi
        continue
      fi
      # A retired file is inert by declaration; keep it readable but never applied.
      head -1 "${sql_file}" | grep -q "RETIRED" && continue
      if grep -qiE "${ddl}" "${sql_file}"; then
        echo "ERROR: [${module_name}] ${sql_file#"${module_dir}/"} contains DDL." >&2
        echo "       Alembic owns the schema; SQL files here seed DATA only. Move it to a" >&2
        echo "       migration: scripts/dev/schema.sh migration ${module_name} -m '...'" >&2
        return 1
      fi
    done < <(find "${module_dir}/database" -name '*.sql' 2>/dev/null)

    # --- bootstrap contract ----------------------------------------------------------------
    # A module's seed.sql runs on EVERY deploy, so it must be idempotent. That rule replaces the
    # one-shot ledger for seeds, and it removes an order-dependent trap: a ledger entry recorded
    # by an earlier run once stopped a block from re-running, leaving module_runtime_meta absent
    # at deploy time.
    local seed_spec="${module_dir}/database/SPECS/seed.sql"
    if [[ -f "${seed_spec}" ]]; then
      if ! python3 - "${seed_spec}" <<'PYSEED'
import re, sys

text = open(sys.argv[1], encoding="utf-8").read()
# Strip comments so an example INSERT in a comment is not treated as real.
text = re.sub(r"--[^\n]*", "", text)
offenders = []
for statement in text.split(";"):
    if not re.search(r"\bINSERT\s+INTO\b", statement, re.I):
        continue
    upper = statement.upper()
    if "ON CONFLICT" in upper or "WHERE NOT EXISTS" in upper:
        continue
    offenders.append(" ".join(statement.split())[:70])
if offenders:
    print("\n".join(offenders))
    sys.exit(1)
PYSEED
      then
        echo "ERROR: [${module_name}] seed.sql has INSERTs that are not idempotent (shown above)." >&2
        echo "       It runs on every deploy: use ON CONFLICT DO NOTHING or WHERE NOT EXISTS." >&2
        return 1
      fi

      # And it must actually be applied by something, or it is a file that does nothing —
      # which is what host_app shipped between the move to Alembic migrations and the bootstrap contract.
      if [[ -f "${module_dir}/docker-compose.yml" ]] &&
         ! grep -q "seed.sql:/module/seed.sql" "${module_dir}/docker-compose.yml"; then
        echo "ERROR: [${module_name}] seed.sql exists but no job mounts and applies it." >&2
        echo "       Add a one-shot seed job ordered after the migrations job." >&2
        return 1
      fi
    fi

    # create_all() is what Alembic replaced: it creates what is missing and alters nothing, so a
    # deployed schema can never evolve, and it runs DDL in every uvicorn worker.
    if grep -rqE 'metadata\.create_all\(' "${module_dir}/backend/SOURCES/app" 2>/dev/null; then
      echo "ERROR: [${module_name}] create_all() found — the schema is Alembic's now." >&2
      return 1
    fi
  fi

  # --- tenancy declaration ---------------------------------------------------------------------
  # Every model must say whether its rows belong to a tenant. Unlike a missing filter, a missing
  # `tenant_id` raises nothing and logs nothing — the table simply holds every customer's rows and
  # the queries over it look correct — so it has to fail here, at build time, where no database
  # exists yet. The behavioural half lives in the isolation tests.
  if [[ -d "${module_dir}/backend/SOURCES/app" ]]; then
    if ! python3 "${SCRIPT_DIR}/check_tenancy_markers.py" \
         "${module_dir}/backend/SOURCES/app" --module "${module_name}"; then
      return 1
    fi
  fi

  # --- the application DB role -----------------------------------------------------------------
  # A tenant-scoped module defends its rows with RLS, and RLS cannot constrain a superuser, so the
  # backend must connect as the restricted role the bootstrap job creates. Both halves of that fail
  # silently in a running system — the role is simply absent, or the owner's URL works perfectly
  # while every policy is decorative — which is why they are checked here, where no database exists.
  if ! python3 "${SCRIPT_DIR}/check_app_db_role.py" "${module_dir}" --module "${module_name}"; then
    return 1
  fi

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

# Inter-module dependency resolution (module.json `dependsOn`): validate that every
# declared prerequisite is enabled + provides the requested capability, and that the
# dependency graph is acyclic. Prints the resolved providers-first order.
echo ""
echo "Resolving inter-module dependencies..."
python3 "${SCRIPT_DIR}/module_deps.py" --modules-dir "${MODULES_DIR}"

# Module Federation shared-singleton skew. Modules deploy independently, so nothing else compares
# the `requiredVersion` each declares — and a singleton loaded twice at different versions fails
# in the end user's browser, where it looks like the shell broke. Failing here keeps that fault
# at deploy time, attributed to the module that introduced it.
echo ""
echo "Checking Module Federation shared dependencies..."
python3 "${SCRIPT_DIR}/check_shared_versions.py"

echo "Module validation complete"
