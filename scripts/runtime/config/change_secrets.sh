#!/usr/bin/env bash
# Interactively change secret-like env vars in project.env.secrets and module .env.secrets files.
# Usage: ./scripts/runtime/change_secrets.sh [-h|--help]
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [-h|--help]"
    echo ""
    echo "Scans project.env.secrets (or .env.secrets in deployed context) and enabled modules'"
    echo "env files for explicit secret-like"
    echo "assignments (keys ending in _PASSWORD, _TOKEN, _SECRET, _SECRET_KEY),"
    echo "prompts for new values with current values as defaults, and overwrites"
    echo "the files in place."
    echo ""
    echo "Options:"
    echo "  -h, --help  Show this help message"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Detect context: source repo (script in scripts/runtime/config/) vs deployed (script in scripts/)
if [[ -f "$SCRIPT_DIR/../../project.env.secrets" ]]; then
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
    PROJECT_ENV_NAME="project.env.secrets"
else
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    PROJECT_ENV_NAME=".env.secrets"
fi
export PROJECT_ROOT
export PROJECT_ENV_NAME

python3 <<'PY'
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

PROJECT_ROOT = Path(os.environ["PROJECT_ROOT"])
PROJECT_ENV_NAME = os.environ.get("PROJECT_ENV_NAME", "project.env.secrets")
MODULES_DIR = PROJECT_ROOT / "modules"
ENABLED_PATH = MODULES_DIR / "enabled.md"
TARGET_SUFFIXES = ("_PASSWORD", "_TOKEN", "_SECRET", "_SECRET_KEY")


def is_enabled_module_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return bool(re.match(r"^(\w+)\s*:\s*(local|remote)\s*$", stripped, re.IGNORECASE))


def read_enabled_modules() -> list[str]:
    if not ENABLED_PATH.exists():
        if not MODULES_DIR.is_dir():
            print(f"ERROR: {MODULES_DIR} not found", file=sys.stderr)
            sys.exit(1)
        enabled = []
        for entry in sorted(MODULES_DIR.iterdir()):
            if entry.is_dir() and any(
                (entry / name).exists() for name in (".env.secrets", ".env.config")
            ):
                enabled.append(entry.name)
        return enabled
    enabled = []
    for raw_line in ENABLED_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(\w+)\s*:\s*(local|remote)\s*$", raw_line.strip(), re.IGNORECASE)
        if match:
            enabled.append(match.group(1))
    return enabled


def is_secret_key(key: str) -> bool:
    return key.endswith(TARGET_SUFFIXES)


def is_explicit_assignment(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if value.startswith("$") or "${" in value:
        return False
    return True


def split_value_and_comment(raw_value: str) -> tuple[str, str]:
    value = raw_value.rstrip("\n")
    in_single = False
    in_double = False
    for idx, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == '#' and not in_single and not in_double:
            if idx == 0 or value[idx - 1].isspace():
                return value[:idx].rstrip(), value[idx:]
    return value.strip(), ""


def collect_targets() -> list[Path]:
    targets = [PROJECT_ROOT / PROJECT_ENV_NAME]
    for module_name in read_enabled_modules():
        module_secrets = MODULES_DIR / module_name / ".env.secrets"
        if module_secrets.exists():
            targets.append(module_secrets)
    return targets


def collect_secret_occurrences(targets: list[Path]):
    occurrences = OrderedDict()
    for path in targets:
        for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = raw_line.split("=", 1)
            key = key.strip()
            if not is_secret_key(key):
                continue
            value, _comment = split_value_and_comment(raw_value)
            if not is_explicit_assignment(value):
                continue
            entry = occurrences.setdefault(
                key,
                {
                    "current": value,
                    "locations": [],
                },
            )
            entry["locations"].append((path, lineno))
    return occurrences


def prompt_for_values(occurrences):
    updates = {}
    if not occurrences:
        print("No explicit secret-like env vars were found in project.env.secrets or enabled module .env.secrets files.")
        return updates

    print("Found the following explicit secret-like env vars:\n")
    for key, data in occurrences.items():
        locations = ", ".join(f"{path.relative_to(PROJECT_ROOT)}:{lineno}" for path, lineno in data["locations"])
        current = data["current"]
        print(f"- {key}")
        print(f"  current: {current}")
        print(f"  files:   {locations}")
        new_value = prompt_input(f"  new value [{current}]: ").strip()
        updates[key] = current if new_value == "" else new_value
        print()
    return updates


def prompt_input(prompt: str) -> str:
    if sys.stdin.isatty():
        return input(prompt)

    try:
        with open("/dev/tty", "r", encoding="utf-8") as tty_in:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return tty_in.readline().rstrip("\n")
    except OSError:
        print(
            "ERROR: change_secrets.sh requires an interactive terminal. "
            "Run it from a shell session attached to a TTY.",
            file=sys.stderr,
        )
        sys.exit(1)


def replace_key_value_in_line(raw_line: str, key: str, new_value: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*)$")
    match = pattern.match(raw_line)
    if not match:
        return raw_line
    prefix = match.group(1)
    remainder = match.group(2)
    value, comment = split_value_and_comment(remainder)
    _ = value  # retained for clarity; value is replaced unconditionally
    return f"{prefix}{new_value}{(' ' + comment) if comment and not comment.startswith(' ') else comment}"


def update_file(path: Path, updates: dict[str, str]) -> bool:
    original_lines = path.read_text(encoding="utf-8").splitlines()
    changed = False
    new_lines = []
    for raw_line in original_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw_line)
            continue
        key = raw_line.split("=", 1)[0].strip()
        if key in updates and is_secret_key(key):
            replacement = replace_key_value_in_line(raw_line, key, updates[key])
            if replacement != raw_line:
                changed = True
            new_lines.append(replacement)
        else:
            new_lines.append(raw_line)
    if changed:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    os.environ["PROJECT_ROOT"] = str(PROJECT_ROOT)
    targets = collect_targets()
    occurrences = collect_secret_occurrences(targets)
    updates = prompt_for_values(occurrences)
    if not updates:
        return 0

    changed_files = []
    for path in targets:
        if update_file(path, updates):
            changed_files.append(path.relative_to(PROJECT_ROOT))

    if changed_files:
        print("Updated files:")
        for rel_path in changed_files:
            print(f"- {rel_path}")
    else:
        print("No files were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
