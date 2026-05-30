#!/usr/bin/env python3
"""
Authentik Bootstrap Script
Automatically creates an OAuth2/OIDC application on first startup
"""

import os
import sys
import time
import json
import base64
import uuid
import mimetypes
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict
from pathlib import Path
import textwrap

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore


_TRUE_STRINGS = {"1", "true", "yes", "on"}
_FALSE_STRINGS = {"0", "false", "no", "off"}


SCRIPT_PATH = Path(__file__).resolve()


def _load_merged_deployment_env() -> None:
    candidate_paths = [
        SCRIPT_PATH.parent / "hostapp" / ".env",
        SCRIPT_PATH.parent / ".env",
    ]
    candidate_paths.extend(parent / ".env" for parent in SCRIPT_PATH.parents)

    seen_paths = set()
    for env_path in candidate_paths:
        if env_path in seen_paths:
            continue
        seen_paths.add(env_path)
        if not env_path.is_file():
            continue

        try:
            content = env_path.read_text(encoding="utf-8")
        except OSError:
            continue

        if "This file is the merge of all enabled modules' .env files." not in content:
            continue

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"').strip("'")
        break


_load_merged_deployment_env()


def log(message):
    """Log with timestamp"""
    print(f"[BOOTSTRAP] {message}", flush=True)


def _coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    return bool(value)

# Configuration
AUTHENTIK_URL = os.getenv("AUTHENTIK_URL", "http://authentik-server:9000")
AUTHENTIK_TOKEN = os.getenv("AUTHENTIK_BOOTSTRAP_TOKEN")

SADMIN_USERNAME = os.getenv("SADMIN_USERNAME", "sadmin")
SADMIN_EMAIL = os.getenv("SADMIN_EMAIL", "sadmin@localhost")
SADMIN_PASSWORD = os.getenv("SADMIN_PASSWORD", "sadmin")
SADMIN_IS_SUPERUSER = os.getenv("SADMIN_IS_SUPERUSER", "true").strip().lower() not in {"0", "false", "no", "off"}
AUTHENTIK_DEFAULT_USER_PASSWORD = os.getenv("AUTHENTIK_DEFAULT_USER_PASSWORD", "").strip()
APP_SLUG = os.getenv("APP_SLUG")
if not APP_SLUG:
    raise RuntimeError("APP_SLUG must be set")

APP_NAME = os.getenv("APP_NAME") or APP_SLUG
EXTERNAL_BASE_HOST = os.getenv("EXTERNAL_BASE_HOST")
_derived_base_url = f"https://{EXTERNAL_BASE_HOST}" if EXTERNAL_BASE_HOST else ""
APP_URL = os.getenv("APP_URL", _derived_base_url or "https://localhost")
APP_CALLBACK_URL = os.getenv(
    "APP_CALLBACK_URL",
    (f"{_derived_base_url}/auth/callback" if _derived_base_url else "https://localhost/auth/callback"),
)
APP_SWAGGER_CALLBACK_URL = os.getenv(
    "APP_SWAGGER_CALLBACK_URL",
    (f"{_derived_base_url}/api/docs/oauth2-redirect" if _derived_base_url else "https://localhost/api/docs/oauth2-redirect"),
)
MODULE_SWAGGER_CALLBACK_URL = os.getenv(
    "MODULE_SWAGGER_CALLBACK_URL",
    "",
).strip()
CLIENT_ID = os.getenv("CLIENT_ID") or f"{APP_SLUG}-client"
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SERVICE_CLIENT_ID = os.getenv("SERVICE_CLIENT_ID") or f"{APP_SLUG}-svc"
SERVICE_CLIENT_SECRET = os.getenv("SERVICE_CLIENT_SECRET")
LOGIN_BRAND_NAME = os.getenv("AUTHENTIK_LOGIN_BRAND_NAME") or APP_NAME
HIDE_LOGIN_LOGO = (os.getenv("AUTHENTIK_HIDE_LOGIN_LOGO", "true").strip().lower() not in {"0", "false", "no", "off"})
LOGIN_BG_IMAGE_FILE = os.getenv("AUTHENTIK_LOGIN_BG_IMAGE_FILE", "").strip()
LOGIN_BG_FILL_COLOR = os.getenv("AUTHENTIK_LOGIN_BG_COLOR", "#ffffff").strip().strip('"').strip("'") or "#ffffff"
AUTHENTIK_ACCESS_CODE_VALIDITY = os.getenv("AUTHENTIK_ACCESS_CODE_VALIDITY", "minutes=1").strip()
AUTHENTIK_ACCESS_TOKEN_VALIDITY = os.getenv("AUTHENTIK_ACCESS_TOKEN_VALIDITY", "minutes=5").strip()
AUTHENTIK_REFRESH_TOKEN_VALIDITY = os.getenv("AUTHENTIK_REFRESH_TOKEN_VALIDITY", "days=30").strip()


def _discover_hostapp_root(script_path: Path) -> Path:
    """Return the HostApp module root regardless of packaging layout.

    During local development the script lives under
    modules/HostApp/authentik/SOURCES/, while in deployment it is copied to
    modules/HostApp/authentik/.  When executed inside the bootstrap container
    it may even be mounted at /bootstrap/bootstrap_authentik.py with only the
    HostApp module directory bound in.  We look for a directory containing the
    HostApp authorization spec and module metadata, with an optional override
    via HOSTAPP_ROOT.
    """

    def _is_hostapp_root(path: Path) -> bool:
        module_json = path / "module.json"
        
        log(f"  [DEBUG] Checking root candidate: {path}")
        log(f"  [DEBUG]   - module.json: {module_json.exists()}")
        
        if module_json.exists():
            log(f"HOSTAPP_ROOT detected via module.json only: {path}")
            return True
        return False

    env_root = os.getenv("HOSTAPP_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if _is_hostapp_root(candidate):
            return candidate

    for parent in list(script_path.parents):
        if _is_hostapp_root(parent):
            return parent

    raise RuntimeError(
        "Unable to locate HostApp root. Set HOSTAPP_ROOT to modules/HostApp."
    )


HOSTAPP_ROOT = _discover_hostapp_root(SCRIPT_PATH)
MODULES_ROOT = HOSTAPP_ROOT.parent
REPO_ROOT = MODULES_ROOT.parent
HOSTAPP_AUTHORIZATION_FILE = Path("/bootstrap/config/authorization.yaml")
ENABLED_MODULES_FILE = MODULES_ROOT / "enabled.md"
AVAILABLE_PERMISSIONS_REGISTRY_NAME = "app:available-permissions-registry"
AVAILABLE_PERMISSIONS_ATTRIBUTE = "available_permissions"
ROLES_MAPPING_REGISTRY_NAME = "app:permissions-to-role-registry"
ROLES_MAPPING_ATTRIBUTE = "roles_mapping"
PROFILE_ROLES_REGISTRY_NAME = "app:roles-to-profile-registry"
PROFILE_ROLES_ATTRIBUTE = "profile_roles"
REGISTRY_KIND_ATTRIBUTE = "hostapp_registry"
REGISTRY_KIND_AVAILABLE_PERMISSIONS = "available_permissions"
REGISTRY_KIND_ROLES_MAPPING = "roles_mapping"
REGISTRY_KIND_PROFILE_ROLES = "profile_roles"


def _discover_background_image_file() -> str:
    candidates = [
        "/bootstrap/config/login_bg.svg",
        "/bootstrap/config/login_bg.png",
        "/bootstrap/config/login_bg.jpg",
        "/bootstrap/config/login_bg.jpeg",
        "/bootstrap/config/login_bg.gif",
        "/bootstrap/config/login_bg.webp",
        "/bootstrap/assets/login_bg.svg",
        "/bootstrap/assets/login_bg.png",
        "/bootstrap/assets/login_bg.jpg",
        "/bootstrap/assets/login_bg.jpeg",
        "/bootstrap/assets/login_bg.gif",
        "/bootstrap/assets/login_bg.webp",
        "/bootstrap/assets/background.gif",
        "/bootstrap/assets/background.jpeg",
        "/bootstrap/assets/background.jpg",
        "/bootstrap/assets/background.png",
        "/bootstrap/assets/background.webp",
        "/bootstrap/background.jpeg",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


if not LOGIN_BG_IMAGE_FILE:
    LOGIN_BG_IMAGE_FILE = _discover_background_image_file()


def _build_background_data_url(background_image_file: str) -> str:
    if not background_image_file:
        return ""
    if not os.path.isfile(background_image_file):
        return ""
    mime_type, _ = mimetypes.guess_type(background_image_file)
    if not mime_type:
        mime_type = "image/jpeg"
    if background_image_file.lower().endswith(".svg"):
        mime_type = "image/svg+xml"
    with open(background_image_file, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


LOGIN_BG_IMAGE_URL = os.getenv("AUTHENTIK_LOGIN_BG_IMAGE_URL", "").strip() or _build_background_data_url(LOGIN_BG_IMAGE_FILE)


def _discover_favicon_file() -> str:
    candidates = [
        "/bootstrap/config/favicon.svg",
        "/bootstrap/config/favicon.ico",
        "/bootstrap/config/favicon.png",
        "/bootstrap/assets/favicon.svg",
        "/bootstrap/assets/favicon.ico",
        "/bootstrap/assets/favicon.png",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


LOGIN_FAVICON_FILE = os.getenv("AUTHENTIK_LOGIN_FAVICON_FILE", "").strip() or _discover_favicon_file()
LOGIN_FAVICON_URL = _build_background_data_url(LOGIN_FAVICON_FILE) if LOGIN_FAVICON_FILE else ""

TRANSPARENT_PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def _build_composite_flow_bg(image_file: str, fill_color: str) -> str:
    """Build an opaque SVG with fill_color background + centered logo.

    The login page background is rendered inside a nested Shadow DOM
    (ak-flow-executor → ak-locale-context) with PF4's dark background
    colour and background-size:cover.  Neither CSS custom properties nor
    ::part() selectors can reach two shadow-DOM levels deep, so we bake
    the fill colour and image sizing directly into the SVG.
    """
    if not image_file or not os.path.isfile(image_file):
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
            f'<rect width="1" height="1" fill="{fill_color}"/></svg>'
        )
    else:
        image_data_url = _build_background_data_url(image_file)
        # 5760×1080 canvas — very wide so that PF4's background-size:cover
        # always scales by viewport height, not width.  The logo is centred
        # and sized to the full canvas height.
        cw, ch = 5760, 1080
        lw, lh = ch, ch          # logo = square, full height
        lx = (cw - lw) // 2
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {cw} {ch}">'
            f'<rect width="{cw}" height="{ch}" fill="{fill_color}"/>'
            f'<image href="{image_data_url}" x="{lx}" y="0" '
            f'width="{lw}" height="{lh}" '
            f'preserveAspectRatio="xMidYMid meet"/>'
            f'</svg>'
        )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


LOGIN_FLOW_BG_URL = _build_composite_flow_bg(LOGIN_BG_IMAGE_FILE, LOGIN_BG_FILL_COLOR)


def _build_default_login_css(app_name: str, background_image_url: str, fill_color: str) -> str:
    """CSS custom property overrides scoped to the login flow only.

    The login UI lives two Shadow DOM levels deep
    (ak-flow-executor → ak-locale-context).  HTML injection is
    blocked (Authentik escapes tags), but CSS custom properties
    DO cascade through Shadow DOM boundaries when set on an ancestor.
    By scoping them to ak-flow-executor instead of :root/body, the
    overrides only affect the login flow and never bleed into the
    admin panel or other Authentik pages.
    """
    return f"""
ak-flow-executor {{
  /* ── Authentik custom properties (cascade into Shadow DOM) ── */
  --ak-dark-background: rgba(255,255,255,0.5) !important;
  --ak-dark-foreground: #151515 !important;
  --ak-light-foreground: #151515 !important;
  --ak-text-color: #151515 !important;
  --ak-flow-footer-color: transparent !important;

  /* ── PF4 login card ── */
  --pf-c-login__main--BackgroundColor: rgba(255,255,255,0.5) !important;
  --pf-c-login__main-body--PaddingBottom: 1rem !important;
  --pf-c-login__main-body--PaddingRight: 2rem !important;
  --pf-c-form-control--BackgroundColor: #ffffff !important;
  --pf-c-form-control--Color: #151515 !important;
  --pf-c-form-control--PlaceholderColor: #6a6e73 !important;
  --pf-global--Color--100: #151515 !important;
  --pf-global--Color--200: #4f5255 !important;
  --pf-global--BackgroundColor--100: #ffffff !important;
  --pf-v5-global--Color--100: #151515 !important;
  --pf-v5-global--Color--200: #4f5255 !important;
  --pf-v5-global--BackgroundColor--100: #ffffff !important;
  --pf-v5-c-form-control--BackgroundColor: #ffffff !important;
  --pf-v5-c-form-control--Color: #151515 !important;
  --pf-v5-c-form-control--placeholder--Color: #6a6e73 !important;

  /* ── PF4 background image area ── */
  --pf-c-background-image--BackgroundColor: {fill_color} !important;
  --pf-c-background-image--Filter: none !important;

  /* ── PF4 footer links (hide "Powered by authentik") ── */
  --pf-c-login__main-footer-links--PaddingTop: 0 !important;
  --pf-c-login__main-footer-links--PaddingBottom: 0 !important;

  /* ── PF4 global overrides ── */
  --pf-global--BackgroundColor--dark-100: {fill_color} !important;
}}

/* ── Force white background on username/password inputs ── */
ak-flow-executor input[type="text"],
ak-flow-executor input[type="password"],
ak-flow-executor input[type="email"],
ak-flow-executor input[type="username"],
ak-flow-executor input.pf-c-form-control,
ak-flow-executor .pf-c-form-control {{
  background-color: #ffffff !important;
  color: #151515 !important;
}}

ak-flow-executor input:focus {{
  background-color: #ffffff !important;
  color: #151515 !important;
}}
""".strip()


LOGIN_CUSTOM_CSS = os.getenv(
    "AUTHENTIK_LOGIN_CUSTOM_CSS",
    _build_default_login_css(APP_NAME, LOGIN_BG_IMAGE_URL, LOGIN_BG_FILL_COLOR),
)

def log(message):
    """Log with timestamp"""
    print(f"[BOOTSTRAP] {message}", flush=True)


def _read_yaml_dict(path: Path):
    """Read a YAML file and return a dict (or None if unavailable)."""
    if yaml is None:
        log("  ✗ PyYAML unavailable.")
        return None
    if not path.exists():
        log(f"  ✗ Authorization file not found: {path}")
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
            if isinstance(data, dict):
                return data
            raise ValueError("Root node must be a mapping")
    except Exception as exc:
        log(f"  ✗ Failed to read authorization contract '{path}': {exc}")
        return None


def _parse_enabled_modules(enabled_modules_file: "Path | None" = None):
    """Return enabled module names from modules/enabled.md."""
    modules: list[str] = []
    target = Path(enabled_modules_file) if enabled_modules_file else ENABLED_MODULES_FILE
    if not target.exists():
        log(f"  ⚠ modules/enabled.md not found ({target})")
        return modules
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.split("#", 1)[0].strip()
        if not stripped or ":" not in stripped:
            continue
        name_part, status_part = stripped.split(":", 1)
        status_tokens = status_part.strip().split()
        status = status_tokens[0] if status_tokens else ""
        if not status.lower().startswith("enabled"):
            continue
        modules.append(name_part.strip())
    return modules


def _discover_module_slug(module_root: Path, fallback: str) -> str:
    module_json = module_root / "module.json"
    if module_json.exists():
        try:
            data = json.loads(module_json.read_text(encoding="utf-8"))
            slug = data.get("slug")
            if isinstance(slug, str) and slug:
                return slug
        except Exception as exc:
            log(f"  ⚠ Could not parse {module_json}: {exc}")
    return fallback.lower()


def _load_authorization_contract(path: Path, module_name: str, slug: str, is_hostapp: bool):
    raw = _read_yaml_dict(path)
    if raw is None:
        return None

    module_section = raw.get("module") or {}
    if isinstance(module_section, dict):
        slug = module_section.get("slug") or slug

    claims_section = raw.get("claims") or {}
    namespaces = claims_section.get("namespaces") or {}
    permission_claim = namespaces.get("permissions")
    menu_claim = namespaces.get("menu_access")
    company_claim = namespaces.get("company_ids")

    if is_hostapp:
        slug = slug or "hostapp"
        permission_claim = permission_claim or "hostapp.permissions"
        menu_claim = menu_claim or "hostapp.menu_access"
        company_claim = company_claim or "hostapp.company_ids"
    else:
        slug = slug or module_name.lower()
        permission_claim = permission_claim or f"{slug}.permissions"
        menu_claim = menu_claim or f"{slug}.menu_access"
        company_claim = company_claim or f"{slug}.company_ids"

    superadmin_values = claims_section.get("superadmin_values")
    if not isinstance(superadmin_values, list):
        superadmin_values = []
    if is_hostapp and not superadmin_values:
        superadmin_values = ["superadmin"]

    def _ensure_list(value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    return {
        "source": module_name,
        "slug": slug,
        "path": str(path),
        "is_hostapp": is_hostapp,
        "permission_claim": permission_claim,
        "menu_claim": menu_claim,
        "company_claim": company_claim,
        "superadmin_values": superadmin_values,
        "data": {
            "users": _ensure_list(raw.get("users")),
            "profiles": _ensure_list(raw.get("profiles")),
            "roles": _ensure_list(raw.get("roles")),
            "permissions": _ensure_list(raw.get("permissions")),
            "role_permissions": _ensure_list(raw.get("role_permissions")),
            "profile_roles": _ensure_list(raw.get("profile_roles")),
        },
    }


def load_authorization_contracts(
    hostapp_auth_path: "Path | None" = None,
    modules_root: "Path | None" = None,
):
    """Load HostApp + enabled module authorization contracts.

    Parameters
    ----------
    hostapp_auth_path:
        Explicit path to HostApp's authorization.yaml.  Defaults to
        HOSTAPP_AUTHORIZATION_FILE (auto-discovered from candidates).
    modules_root:
        Explicit path to the modules/ directory.  Defaults to MODULES_ROOT.
    """
    effective_hostapp_auth = Path(hostapp_auth_path) if hostapp_auth_path else HOSTAPP_AUTHORIZATION_FILE
    effective_modules_root = Path(modules_root) if modules_root else MODULES_ROOT
    enabled_modules_file = effective_modules_root / "enabled.md"

    contracts = []
    hostapp_contract = None

    if effective_hostapp_auth.exists():
        hostapp_contract = _load_authorization_contract(
            effective_hostapp_auth, "HostApp", "hostapp", True
        )
        if hostapp_contract:
            contracts.append(hostapp_contract)
    else:
        log(f"  ✗ HostApp authorization spec not found at {effective_hostapp_auth}")

    if hostapp_contract is None:
        raise RuntimeError("HostApp authorization contract is required for bootstrap")

    enabled_modules = _parse_enabled_modules(enabled_modules_file)
    if enabled_modules:
        for module_name in enabled_modules:
            if module_name.lower() == "hostapp":
                continue
            module_root = effective_modules_root / module_name
            config_path = module_root / "config" / "authorization.yaml"
            if not config_path.exists():
                log(f"  ⚠ Skipping module '{module_name}': authorization.yaml not found ({config_path})")
                continue
            slug = _discover_module_slug(module_root, module_name)
            contract = _load_authorization_contract(config_path, module_name, slug, False)
            if contract:
                contracts.append(contract)
    else:
        # Deployment-root scan: read modules/*/config/authorization.yaml when
        # enabled.md is not available.
        for module_root in sorted(effective_modules_root.iterdir()):
            if not module_root.is_dir():
                continue
            module_name = module_root.name
            if module_name.lower() == "hostapp":
                continue
            config_path = module_root / "config" / "authorization.yaml"
            if not config_path.exists():
                continue
            slug = _discover_module_slug(module_root, module_name)
            contract = _load_authorization_contract(config_path, module_name, slug, False)
            if contract:
                contracts.append(contract)

    return contracts


def build_authorization_plan(contracts):
    """Normalize contracts into a single plan consumed by bootstrap."""
    profiles: dict[str, dict] = {}
    roles: dict[str, dict] = {}
    permission_meta: dict[str, dict] = {}
    role_permissions: dict[str, set] = defaultdict(set)
    profile_roles: dict[str, set] = defaultdict(set)
    user_profiles: dict[str, set] = defaultdict(set)
    user_definitions: dict[str, dict] = {}
    hostapp_permission_claim = "hostapp.permissions"
    hostapp_company_claim = "hostapp.company_ids"
    superadmin_claim_values: list[str] = ["superadmin"]

    def _normalize_permission_fields(raw_perm: dict, source_name: str) -> tuple[str, str, str]:
        raw_name = (raw_perm.get("name") or "").strip()
        legacy_resource = (raw_perm.get("resource") or "").strip()
        legacy_action = (raw_perm.get("action") or "").strip()

        resource = ""
        action = ""
        name = raw_name

        if raw_name and ":" in raw_name:
            resource, action = (part.strip() for part in raw_name.split(":", 1))
        elif legacy_resource and legacy_action:
            resource, action = legacy_resource, legacy_action
            name = f"{resource}:{action}"
        elif raw_name and "." in raw_name:
            # Legacy dot-separated format: "prefix.resource.action" → "prefix.resource:action"
            # The last dot-separated segment is the action; everything before is the resource.
            resource, action = raw_name.rsplit(".", 1)
            name = f"{resource}:{action}"
            log(f"  ⚠ Deprecated dot-format permission '{raw_name}' in {source_name} — "
                f"use '{name}' instead")
        else:
            raise RuntimeError(
                "Permission entries must declare name as '<resource>:<action>'"
                f" (source={source_name}, raw={raw_perm})"
            )

        if not resource or not action:
            raise RuntimeError(
                f"Invalid permission '{raw_name or name}' in {source_name}: missing resource/action"
            )

        if resource.lower().endswith("_menu") and action != "view":
            raise RuntimeError(
                f"Menu permission '{resource}:{action}' must use action 'view' (source={source_name})"
            )

        return name, resource, action

    def _ensure_slug_prefixed_resource(slug: str, resource: str) -> str:
        if not slug:
            return resource
        prefix = f"{slug}."
        if resource.startswith(prefix):
            return resource
        return f"{prefix}{resource}"

    for contract in contracts:
        data = contract.get("data", {})
        source = contract.get("source", "Unknown")

        if contract.get("is_hostapp"):
            hostapp_permission_claim = contract.get("permission_claim", hostapp_permission_claim)
            hostapp_company_claim = contract.get("company_claim", hostapp_company_claim)
            superadmin_claim_values = contract.get("superadmin_values") or superadmin_claim_values

        for profile in data.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            name = profile.get("profile") or profile.get("ext_profile")
            if not name:
                continue
            description = profile.get("description") or ""
            existing = profiles.get(name)
            if not existing and not profile.get("ext_profile"):
                profiles[name] = {
                    "description": description or "",
                    "source": source,
                }

        for role in data.get("roles", []):
            if not isinstance(role, dict):
                continue
            name = role.get("role") or role.get("ext_role")
            if not name:
                continue
            description = role.get("description") or ""
            if name not in roles and not role.get("ext_role"):
                roles[name] = {
                    "description": description or "",
                    "source": source,
                }

        module_slug = contract.get("slug") or "hostapp"
        perm_aliases = contract.setdefault("_permission_name_map", {})

        for perm in data.get("permissions", []):
            if not isinstance(perm, dict):
                continue
            try:
                normalized_name, resource, action = _normalize_permission_fields(perm, source)
            except RuntimeError as exc:
                raise RuntimeError(str(exc)) from exc

            spec_name = normalized_name

            if not contract.get("is_hostapp"):
                resource = _ensure_slug_prefixed_resource(module_slug, resource)
                normalized_name = f"{resource}:{action}"

            permission_meta[normalized_name] = {
                "resource": resource,
                "action": action,
                "module": module_slug or "hostapp",
                "description": perm.get("description") or "",
            }
            perm_aliases[spec_name] = normalized_name

        for role_perm in data.get("role_permissions", []):
            role_name = role_perm.get("role") if isinstance(role_perm, dict) else None
            perm_list = role_perm.get("permissions") if isinstance(role_perm, dict) else []
            if not role_name or not isinstance(perm_list, list):
                continue
            for perm_name in perm_list:
                if not perm_name:
                    continue
                normalized_perm_name = perm_aliases.get(perm_name, perm_name)
                role_permissions[role_name].add(normalized_perm_name)

        # Also extract role permissions from nested roles[].permissions (ModuleTemplate format)
        for role in data.get("roles", []):
            if not isinstance(role, dict):
                continue
            role_name = role.get("role") or role.get("ext_role")
            perm_list = role.get("permissions")
            if not role_name or not isinstance(perm_list, list):
                continue
            for perm_name in perm_list:
                if not perm_name:
                    continue
                normalized_perm_name = perm_aliases.get(perm_name, perm_name)
                role_permissions[role_name].add(normalized_perm_name)

        for profile_role in data.get("profile_roles", []):
            profile_name = profile_role.get("profile") if isinstance(profile_role, dict) else None
            role_list = profile_role.get("roles") if isinstance(profile_role, dict) else []
            if not profile_name or not isinstance(role_list, list):
                continue
            for role_name in role_list:
                if role_name:
                    profile_roles[profile_name].add(role_name)

        # Also extract profile roles from nested profiles[].roles (ModuleTemplate format)
        for profile in data.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            profile_name = profile.get("profile") or profile.get("ext_profile")
            role_list = profile.get("roles")
            if not profile_name or not isinstance(role_list, list):
                continue
            for role_name in role_list:
                if role_name:
                    profile_roles[profile_name].add(role_name)

        for user in data.get("users", []):
            if not isinstance(user, dict):
                continue
            username = user.get("username") or user.get("ext_user")
            profile_list = user.get("profiles") or []
            if not username or not isinstance(profile_list, list):
                continue

            record = user_definitions.setdefault(username, {})
            user_profiles.setdefault(username, set())
            record.setdefault("profiles", set()).update({p for p in profile_list if p})

            email = user.get("email") or user.get("mail")
            if email:
                record["email"] = email

            full_name = user.get("full_name") or user.get("name")
            if full_name:
                record["full_name"] = full_name

            if "is_active" in user:
                record["is_active"] = _coerce_bool(user.get("is_active"), True)

            if "superadmin" in user:
                record["is_superuser"] = _coerce_bool(user.get("superadmin"), False)

            if "is_superuser" in user:
                record["is_superuser"] = _coerce_bool(user.get("is_superuser"), False)

            if user.get("password"):
                record["password"] = user.get("password")

            if user.get("password_env"):
                record["password_env"] = user.get("password_env")

            if user.get("attributes"):
                record["attributes"] = user.get("attributes")

            for profile_name in profile_list:
                if profile_name:
                    user_profiles[username].add(profile_name)

    normalized_role_permissions = {
        role: sorted(list(perms)) for role, perms in role_permissions.items() if perms
    }
    normalized_profile_roles = {
        profile: sorted(list(roles_for_profile))
        for profile, roles_for_profile in profile_roles.items()
        if roles_for_profile
    }

    available_permissions = [
        {
            "name": name,
            "resource": meta.get("resource"),
            "action": meta.get("action"),
            "module": meta.get("module") or "hostapp",
            "description": meta.get("description"),
        }
        for name, meta in sorted(permission_meta.items())
    ]

    user_definitions_payload = {}
    for username, meta in user_definitions.items():
        payload = dict(meta)
        profiles_set = payload.get("profiles")
        if isinstance(profiles_set, set):
            payload["profiles"] = sorted(list(profiles_set))
        user_definitions_payload[username] = payload

    return {
        "profiles": profiles,
        "roles": roles,
        "role_permissions": normalized_role_permissions,
        "roles_mapping": normalized_role_permissions,
        "profile_roles": normalized_profile_roles,
        "user_profiles": {user: sorted(values) for user, values in user_profiles.items()},
        "users": user_definitions_payload,
        "hostapp_permission_claim": hostapp_permission_claim,
        "hostapp_company_claim": hostapp_company_claim,
        "superadmin_claim_values": superadmin_claim_values,
        "available_permissions": available_permissions,
    }


def render_scope_mapping_expression(plan: dict) -> str:
    superadmin_values_json = json.dumps(plan.get("superadmin_claim_values") or [])
    permission_claim_json = json.dumps(plan.get("hostapp_permission_claim") or "hostapp.permissions")
    company_claim_json = json.dumps(plan.get("hostapp_company_claim") or "hostapp.company_ids")
    active_profile_claim_json = json.dumps("hostapp.active_profile")
    permissions_registry_name_json = json.dumps(AVAILABLE_PERMISSIONS_REGISTRY_NAME)
    permissions_registry_key_json = json.dumps(AVAILABLE_PERMISSIONS_ATTRIBUTE)
    roles_registry_name_json = json.dumps(ROLES_MAPPING_REGISTRY_NAME)
    roles_registry_key_json = json.dumps(ROLES_MAPPING_ATTRIBUTE)
    profile_roles_registry_name_json = json.dumps(PROFILE_ROLES_REGISTRY_NAME)
    profile_roles_registry_key_json = json.dumps(PROFILE_ROLES_ATTRIBUTE)
    profile_roles_fallback_json = json.dumps(plan.get("profile_roles") or {})
    roles_mapping_fallback_json = json.dumps(plan.get("roles_mapping") or {})
    permission_meta_fallback_json = json.dumps(plan.get("available_permissions") or [])
    template = textwrap.dedent(
        """
        # Ideable Permissions Claims Mapping
        # This expression collects permissions and menu access based on the active profile.

        SUPERADMIN_VALUES = __SUPERADMIN_VALUES__
        HOSTAPP_PERMISSION_CLAIM = __PERMISSION_CLAIM__
        COMPANY_CLAIM = __COMPANY_CLAIM__
        ACTIVE_PROFILE_CLAIM = __ACTIVE_PROFILE_CLAIM__
        PERMISSIONS_REGISTRY_NAME = __PERMISSIONS_REGISTRY_NAME__
        PERMISSIONS_REGISTRY_KEY = __PERMISSIONS_REGISTRY_KEY__
        ROLES_MAPPING_REGISTRY_NAME = __ROLES_REGISTRY_NAME__
        ROLES_MAPPING_REGISTRY_KEY = __ROLES_REGISTRY_KEY__
        PROFILE_ROLES_REGISTRY_NAME = __PROFILE_ROLES_REGISTRY_NAME__
        PROFILE_ROLES_REGISTRY_KEY = __PROFILE_ROLES_REGISTRY_KEY__

        # 1. Helper to extract single value from potentially list-wrapped attributes
        def _extract_single(v):
            if v is None: return None
            if isinstance(v, (list, tuple, set)):
                return str(v[0]).strip() if v else None
            return str(v).strip()

        def _normalize_name(v):
            value = _extract_single(v)
            return value.lower() if value else None

        # 2. Load registries from known registry groups
        def _load_registries():
            p_lookup = {}
            r_map = {}
            prof_r = {}
            
            def _get_attr(g_name, a_key):
                try:
                    g = ak_group_by(name=g_name)
                    if g:
                        attrs = getattr(g, "attributes", {}) or {}
                        return attrs.get(a_key)
                except: pass
                return None

            raw_perms = _get_attr(PERMISSIONS_REGISTRY_NAME, PERMISSIONS_REGISTRY_KEY) or []
            p_lookup = {entry.get("name"): entry for entry in raw_perms if entry.get("name")}
            r_map = _get_attr(ROLES_MAPPING_REGISTRY_NAME, ROLES_MAPPING_REGISTRY_KEY) or {}
            prof_r = _get_attr(PROFILE_ROLES_REGISTRY_NAME, PROFILE_ROLES_REGISTRY_KEY) or {}
            
            return p_lookup, r_map, prof_r

        PERMISSION_LOOKUP, ROLES_MAPPING, PROFILE_ROLES = _load_registries()

        # Inline fallbacks (plan data at bootstrap time) in case registry lookup fails
        if not PROFILE_ROLES:
            PROFILE_ROLES = __FALLBACK_PROFILE_ROLES__
        if not ROLES_MAPPING:
            ROLES_MAPPING = __FALLBACK_ROLES_MAPPING__
        if not PERMISSION_LOOKUP:
            PERMISSION_LOOKUP = {e["name"]: e for e in __FALLBACK_PERMISSION_META__ if e.get("name")}

        # 3. Collect permissions from groups
        def _collect_claims(target_groups):
            res = {}
            for g in target_groups:
                g_name = getattr(g, "name", None)
                if not g_name: continue

                g_name_norm = _normalize_name(g_name)
                
                # Get role names for this group (profile) from registry
                role_names = PROFILE_ROLES.get(g_name)
                if not role_names and g_name_norm:
                    # tolerate registries written with normalized keys
                    role_names = PROFILE_ROLES.get(g_name_norm)
                if not role_names:
                    try:
                        role_names = [r.name for r in g.roles.all()]
                    except:
                        role_names = []
                
                if not role_names: continue
                
                for r_name in role_names:
                    perms = ROLES_MAPPING.get(r_name, [])
                    for p_name in perms:
                        meta = PERMISSION_LOOKUP.get(p_name, {})
                        mod = meta.get("module") or "hostapp"
                        action = meta.get("action")
                        resource = meta.get("resource")
                        
                        p_claim = f"{mod}.permissions"
                        m_claim = f"{mod}.menu_access"
                        
                        if action == "menu_access" and resource:
                            res.setdefault(m_claim, set()).add(resource)
                        else:
                            res.setdefault(p_claim, set()).add(p_name)
            return res

        # 4. Main resolution logic
        u = user
        # In Authentik, attributes can be on the user object or nested in request
        u_attrs = getattr(u, "attributes", {}) or {}
        if not u_attrs and hasattr(request, "user"):
            u_attrs = getattr(request.user, "attributes", {}) or {}
        
        # Determine active profile - try multiple possible keys
        active_profile = None
        for key in [ACTIVE_PROFILE_CLAIM, "hostapp.active_profile", "active_profile", "active_profile_claim", "hostapp_active_profile"]:
            val = u_attrs.get(key)
            if val:
                active_profile = _extract_single(val)
                if active_profile:
                    break

        # Determine target groups for permission collection
        try:
            all_user_groups = list(u.ak_groups.all())
        except:
            try:
                all_user_groups = list(u.groups.all())
            except:
                all_user_groups = []

        if active_profile:
            # STRICT FILTERING: only use the group matching the active profile
            ap_lower = _normalize_name(active_profile)
            target_groups = [
                g for g in all_user_groups
                if _normalize_name(getattr(g, "name", "")) == ap_lower
            ]
            
            if not target_groups:
                try:
                    g_direct = ak_group_by(name=active_profile)
                    if g_direct:
                        target_groups = [g_direct]
                    elif ap_lower:
                        # Last-resort exact lookup across all groups by normalized name.
                        for candidate in all_user_groups:
                            if _normalize_name(getattr(candidate, "name", "")) == ap_lower:
                                target_groups = [candidate]
                                break
                except: pass
        else:
            # Default: use all user groups
            target_groups = all_user_groups

        # Collect claims
        claims = _collect_claims(target_groups)
        
        # Add active profile claim explicitly
        if active_profile:
            claims.setdefault(ACTIVE_PROFILE_CLAIM, set()).add(active_profile)
            
        # Add company IDs
        company_ids = set()
        for attr in (COMPANY_CLAIM, "user_companies", "company_ids"):
            val = u_attrs.get(attr)
            if val:
                if isinstance(val, (list, tuple, set)):
                    company_ids.update(str(x).strip() for x in val if x)
                elif isinstance(val, str):
                    company_ids.update(x.strip() for x in val.split(",") if x.strip())
                else:
                    company_ids.add(str(val).strip())
        if company_ids:
            claims.setdefault(COMPANY_CLAIM, set()).update(company_ids)

        # 5. Superadmin Override
        # ONLY trigger superadmin bypass if 'admin' profile is active OR no profile is active.
        is_ak_superuser = getattr(u, "is_superuser", False)
        if is_ak_superuser:
            if not active_profile or active_profile.lower() == "admin":
                for val in SUPERADMIN_VALUES:
                    claims.setdefault(HOSTAPP_PERMISSION_CLAIM, set()).add(val)

        # Return formatted claims
        # We ensure the permission claim is ALWAYS present if it was intended to be emitted,
        # even if empty, to prevent backends from falling back to unsafe superadmin overrides.
        res = {k: sorted(list(v)) for k, v in claims.items() if v}
        if HOSTAPP_PERMISSION_CLAIM not in res:
            res[HOSTAPP_PERMISSION_CLAIM] = []
        return res
        """
    ).strip()
    return (
        template
        .replace("__SUPERADMIN_VALUES__", superadmin_values_json)
        .replace("__PERMISSION_CLAIM__", permission_claim_json)
        .replace("__COMPANY_CLAIM__", company_claim_json)
        .replace("__ACTIVE_PROFILE_CLAIM__", active_profile_claim_json)
        .replace("__PERMISSIONS_REGISTRY_NAME__", permissions_registry_name_json)
        .replace("__PERMISSIONS_REGISTRY_KEY__", permissions_registry_key_json)
        .replace("__ROLES_REGISTRY_NAME__", roles_registry_name_json)
        .replace("__ROLES_REGISTRY_KEY__", roles_registry_key_json)
        .replace("__PROFILE_ROLES_REGISTRY_NAME__", profile_roles_registry_name_json)
        .replace("__PROFILE_ROLES_REGISTRY_KEY__", profile_roles_registry_key_json)
        .replace("__FALLBACK_PROFILE_ROLES__", profile_roles_fallback_json)
        .replace("__FALLBACK_ROLES_MAPPING__", roles_mapping_fallback_json)
        .replace("__FALLBACK_PERMISSION_META__", permission_meta_fallback_json)
    )


def ensure_permissions_scope_mapping(plan: dict):
    """Create or update the property mapping emitting permissions/menu claims."""
    mapping_name = "Ideable Permissions Claims"
    expression = render_scope_mapping_expression(plan)

    try:
        existing = api_request("propertymappings/provider/scope/") or {}
        for mapping in existing.get("results", []):
            if mapping.get("name") == mapping_name:
                api_request(
                    f"propertymappings/provider/scope/{mapping['pk']}/",
                    method="PATCH",
                    data={"expression": expression, "scope_name": "hostapp"},
                )
                log(f"  ✓ Updated scope mapping '{mapping_name}' ({mapping['pk']})")
                return mapping
        created = api_request(
            "propertymappings/provider/scope/",
            method="POST",
            data={
                "name": mapping_name,
                "scope_name": "hostapp",
                "expression": expression,
            },
        )
        log(f"  ✓ Created scope mapping '{mapping_name}' ({created['pk']})")
        return created
    except Exception as exc:
        log(f"  ✗ Warning: could not create scope mapping: {exc}")
        return None


def wait_for_authentik(max_attempts=60, delay=5):
    """Wait for Authentik to be ready (public health endpoint, no token required)"""
    log("Waiting for Authentik to be ready...")
    
    health_url = f"{AUTHENTIK_URL}/-/health/live/"
    
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    log("✓ Authentik is ready!")
                    return True
        except Exception as e:
            log(f"Attempt {attempt}/{max_attempts}: {e}")
            time.sleep(delay)
    
    log("✗ Authentik did not become ready in time")
    return False

def api_request(endpoint, method="GET", data=None):
    """Execute an API request to Authentik"""
    url = f"{AUTHENTIK_URL}/api/v3/{endpoint}"
    headers = {
        "Authorization": f"Bearer {AUTHENTIK_TOKEN}",
        "Content-Type": "application/json"
    }
    
    request_data = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=request_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        log(f"HTTP Error {e.code} on {method} {endpoint}: {error_body}")
        
        # If 404 and GET, return None
        if e.code == 404 and method == "GET":
            return None
        raise


def _find_user_by_username(username: str):
    """Return user dict if found, else None."""
    try:
        result = api_request(f"core/users/?username={urllib.parse.quote(username)}")
        if result and result.get("results"):
            for u in result["results"]:
                if u.get("username") == username:
                    return u
    except Exception:
        pass

    try:
        result = api_request(f"core/users/?search={urllib.parse.quote(username)}")
        if result and result.get("results"):
            for u in result["results"]:
                if u.get("username") == username:
                    return u
    except Exception:
        pass

    return None


def _set_user_password(user_pk, password: str) -> bool:
    """Set password for user. Return True if successful."""
    payload_candidates = [
        {"password": password},
        {"password": password, "confirm_password": password},
        {"password": password, "password_repeat": password},
        {"new_password": password},
    ]
    for payload in payload_candidates:
        try:
            api_request(f"core/users/{user_pk}/set_password/", method="POST", data=payload)
            return True
        except Exception:
            continue
    return False


def _build_user_payload(meta: dict, *, for_create: bool) -> dict:
    payload: dict[str, object] = {}

    email = meta.get("email") or meta.get("mail")
    if isinstance(email, str) and email.strip():
        payload["email"] = email.strip()

    full_name = meta.get("full_name") or meta.get("name")
    if isinstance(full_name, str) and full_name.strip():
        payload["name"] = full_name.strip()

    if "is_active" in meta:
        payload["is_active"] = _coerce_bool(meta.get("is_active"), True)
    elif for_create:
        payload["is_active"] = True

    if "is_superuser" in meta:
        payload["is_superuser"] = _coerce_bool(meta.get("is_superuser"), False)
    elif for_create:
        payload.setdefault("is_superuser", False)

    attributes = meta.get("attributes")
    if isinstance(attributes, dict):
        payload["attributes"] = attributes

    return payload


def _resolve_user_password(username: str, meta: dict) -> str | None:
    env_key = meta.get("password_env")
    if isinstance(env_key, str) and env_key.strip():
        env_name = env_key.strip()
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return env_value
        log(f"  ℹ password_env '{env_name}' for user '{username}' is not set; skipping")

    password_value = meta.get("password")
    if isinstance(password_value, str) and password_value.strip():
        return password_value.strip()

    if AUTHENTIK_DEFAULT_USER_PASSWORD:
        return AUTHENTIK_DEFAULT_USER_PASSWORD

    return None


def ensure_sadmin_user():
    """Ensure a deterministic local admin exists (sadmin) for UI login."""
    log(f"Ensuring Authentik user '{SADMIN_USERNAME}' exists...")
    user = _find_user_by_username(SADMIN_USERNAME)

    desired = {
        "username": SADMIN_USERNAME,
        "name": "Super Admin",
        "is_active": True,
        "is_superuser": SADMIN_IS_SUPERUSER,
        "email": SADMIN_EMAIL,
    }

    if not user:
        created = api_request("core/users/", method="POST", data=desired)
        user_pk = created.get("pk")
        if not user_pk:
            raise RuntimeError("Failed to create sadmin user: missing pk in response")
        log(f"✓ Created user '{SADMIN_USERNAME}' (ID: {user_pk})")
    else:
        user_pk = user.get("pk")
        patch = {k: v for k, v in desired.items() if k != "username"}
        api_request(f"core/users/{user_pk}/", method="PATCH", data=patch)
        log(f"✓ Updated user '{SADMIN_USERNAME}' (ID: {user_pk})")

    if _set_user_password(user_pk, SADMIN_PASSWORD):
        log(f"✓ Password set for '{SADMIN_USERNAME}'")
    else:
        log(f"✗ WARNING: could not set password for '{SADMIN_USERNAME}'")

def get_default_authorization_flow():
    """Get the default authorization flow"""
    try:
        flows = api_request("flows/instances/?designation=authorization&ordering=slug")
        if flows and flows.get("results"):
            flow = flows["results"][0]
            log(f"Using authorization flow: {flow['slug']}")
            return flow["pk"]
    except Exception as e:
        log(f"Warning: Could not fetch default authorization flow: {e}")
    
    # Fallback to standard default flow
    return "default-provider-authorization-implicit-consent"

def get_default_signing_key():
    """Fetch the first available certificate keypair (used to sign JWTs)"""
    try:
        keys = api_request("crypto/certificatekeypairs/?ordering=name&has_key=true")
        if keys and keys.get("results"):
            key = keys["results"][0]
            log(f"Using signing key: {key['name']} ({key['pk']})")
            return key["pk"]
    except Exception as e:
        log(f"Warning: Could not fetch signing key: {e}")
    return None

def get_default_invalidation_flow():
    """Get the default invalidation flow"""
    try:
        flows = api_request("flows/instances/?designation=invalidation&ordering=slug")
        if flows and flows.get("results"):
            flow = flows["results"][0]
            log(f"Using invalidation flow: {flow['slug']}")
            return flow["pk"]
    except Exception as e:
        log(f"Warning: Could not fetch default invalidation flow: {e}")
    
    # Fallback to standard invalidation flow
    return "default-provider-invalidation-flow"

def check_application_exists(slug):
    """Check if the application already exists"""
    result = api_request(f"core/applications/{slug}/")
    return result is not None

def check_provider_exists(client_id):
    """Check if the provider already exists"""
    try:
        providers = api_request(f"providers/oauth2/?client_id={urllib.parse.quote(client_id)}")
        if providers and providers.get("results"):
            return providers["results"][0]["pk"]
    except Exception as e:
        log(f"Error checking provider: {e}")
    return None

def get_default_scope_mappings():
    """Fetch PKs for the standard openid/email/profile/offline_access scope mappings"""
    try:
        result = api_request("propertymappings/provider/scope/")
        if result and result.get("results"):
            wanted_scopes = {"openid", "email", "profile", "offline_access"}
            pks = [m["pk"] for m in result["results"]
                   if m.get("scope_name") in wanted_scopes
                   or any(w in m.get("name", "") for w in wanted_scopes)]
            log(f"Using scope mappings: {pks}")
            return pks
    except Exception as e:
        log(f"Warning: Could not fetch scope mappings: {e}")
    return []


def _get_brand_endpoint_prefix():
    """Discover the brands endpoint prefix across Authentik versions."""
    candidates = [
        "core/brands/",
        "brands/brands/",
        "brands/",
    ]
    for endpoint in candidates:
        try:
            result = api_request(endpoint)
            if isinstance(result, dict) and "results" in result:
                return endpoint, result
        except Exception:
            continue
    return None, None


def ensure_login_branding():
    """Apply login page branding (CSS + title + optional logo hide) automatically."""
    endpoint_prefix, listing = _get_brand_endpoint_prefix()
    if not endpoint_prefix or listing is None:
        log("Warning: could not discover Authentik brands API endpoint; skipping login branding")
        return

    if isinstance(listing, dict):
        brands = listing.get("results") or []
    elif isinstance(listing, list):
        brands = listing
    else:
        brands = []
    if not brands:
        log("Warning: no brand found in Authentik; skipping login branding")
        return

    patched_count = 0
    for brand in brands:
        identifiers = [
            brand.get("brand_uuid"),
            brand.get("pk"),
            brand.get("id"),
            brand.get("uuid"),
            brand.get("slug"),
        ]
        identifiers = [str(i) for i in identifiers if i is not None and str(i).strip()]
        if not identifiers:
            continue

        title_field = next((f for f in ("branding_title", "title", "name") if f in brand), "name")
        css_field = next((f for f in ("branding_custom_css", "custom_css") if f in brand), None)
        logo_field = next((f for f in ("branding_logo", "logo") if f in brand), None)
        favicon_field = next((f for f in ("branding_favicon", "favicon") if f in brand), None)
        flow_bg_field = next((f for f in ("branding_default_flow_background", "default_flow_background", "flow_background") if f in brand), None)

        patch_payload = {
            title_field: LOGIN_BRAND_NAME,
        }
        if css_field and LOGIN_CUSTOM_CSS.strip():
            patch_payload[css_field] = LOGIN_CUSTOM_CSS
        if favicon_field and LOGIN_FAVICON_URL:
            patch_payload[favicon_field] = LOGIN_FAVICON_URL
        if logo_field:
            patch_payload[logo_field] = TRANSPARENT_PIXEL
        if flow_bg_field and LOGIN_FLOW_BG_URL:
            patch_payload[flow_bg_field] = LOGIN_FLOW_BG_URL
        # Force light theme so the login card is white (blends with white bg)
        attrs_field = next((f for f in ("attributes",) if f in brand), None)
        if attrs_field:
            existing_attrs = brand.get(attrs_field) or {}
            existing_attrs.setdefault("settings", {})
            existing_attrs["settings"]["theme"] = "light"
            patch_payload[attrs_field] = existing_attrs

        patched = False
        for identifier in identifiers:
            try:
                api_request(
                    f"{endpoint_prefix}{urllib.parse.quote(identifier)}/",
                    method="PATCH",
                    data=patch_payload,
                )
                patched = True
                patched_count += 1
                break
            except Exception:
                continue

        if not patched:
            display_name = brand.get("name") or brand.get("branding_title") or "<unknown>"
            log(f"Warning: could not patch brand '{display_name}' with identifiers {identifiers}")

    if patched_count == 0:
        log("Warning: no brand patched")
    else:
        log(f"✓ Login branding applied to {patched_count} brand(s) via endpoint '{endpoint_prefix}'")

def ensure_flow_title():
    """Rename the default authentication flow title to use APP_NAME.

    The Authentik worker may reset the flow title after initial creation,
    so we retry several times with a delay to ensure persistence.
    """
    desired_title = f"Welcome to {APP_NAME}!"
    slug = "default-authentication-flow"
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            flow = api_request(f"flows/instances/{slug}/")
            if flow.get("title") == desired_title:
                log(f"✓ Flow title already set to '{desired_title}'")
                return
            api_request(
                f"flows/instances/{slug}/",
                method="PATCH",
                data={"title": desired_title},
            )
            # Verify the change stuck
            time.sleep(3)
            flow = api_request(f"flows/instances/{slug}/")
            if flow.get("title") == desired_title:
                log(f"✓ Flow title updated to '{desired_title}' (attempt {attempt})")
                return
            log(f"Flow title reverted after PATCH (attempt {attempt}), retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            log(f"Warning: flow title attempt {attempt} failed: {e}")
            if attempt < max_attempts:
                time.sleep(5)
    log(f"Warning: could not persist flow title after {max_attempts} attempts")


def create_oauth2_provider():
    """Create an OAuth2/OIDC provider"""
    provider_name = f"{APP_NAME} Provider"
    
    # Check if it already exists — if so, ensure scope mappings are up to date
    existing_provider = check_provider_exists(CLIENT_ID)
    if existing_provider:
        log(f"✓ Provider with client_id '{CLIENT_ID}' already exists (ID: {existing_provider}) — syncing scopes")
        sync_data = {
            "property_mappings": get_default_scope_mappings(),
            "redirect_uris": [
                {"url": APP_CALLBACK_URL, "matching_mode": "strict"},
                {"url": APP_SWAGGER_CALLBACK_URL, "matching_mode": "strict"},
                {"url": "http://localhost:3000/auth/callback", "matching_mode": "strict"},
            ],
        }
        if MODULE_SWAGGER_CALLBACK_URL:
            sync_data["redirect_uris"].insert(2, {"url": MODULE_SWAGGER_CALLBACK_URL, "matching_mode": "strict"})
        try:
            api_request(f"providers/oauth2/{existing_provider}/", method="PATCH", data=sync_data)
            log(f"✓ Provider scope mappings synced")
        except Exception as e:
            log(f"Warning: could not sync provider scopes: {e}")
        return existing_provider
    
    # Get authorization and invalidation flows
    auth_flow = get_default_authorization_flow()
    invalidation_flow = get_default_invalidation_flow()
    
    provider_data = {
        "name": provider_name,
        "authorization_flow": auth_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "public",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "property_mappings": get_default_scope_mappings(),
        "redirect_uris": [
            {
                "url": APP_CALLBACK_URL,
                "matching_mode": "strict",
            },
            {
                "url": APP_SWAGGER_CALLBACK_URL,
                "matching_mode": "strict",
            },
            {
                "url": "http://localhost:3000/auth/callback",
                "matching_mode": "strict",
            }
        ],
        "signing_key": get_default_signing_key(),
        "sub_mode": "user_username",
        "include_claims_in_id_token": True,
        "issuer_mode": "per_provider",
        "access_code_validity": AUTHENTIK_ACCESS_CODE_VALIDITY,
        "access_token_validity": AUTHENTIK_ACCESS_TOKEN_VALIDITY,
        "refresh_token_validity": AUTHENTIK_REFRESH_TOKEN_VALIDITY,
    }

    if MODULE_SWAGGER_CALLBACK_URL:
        provider_data["redirect_uris"].insert(2, {
            "url": MODULE_SWAGGER_CALLBACK_URL,
            "matching_mode": "strict",
        })
    
    log(f"Creating OAuth2 provider '{provider_name}'...")
    provider = api_request("providers/oauth2/", method="POST", data=provider_data)
    log(f"✓ Provider created with ID: {provider['pk']}")
    return provider["pk"]

def find_application_by_provider(provider_pk):
    """Return (slug, pk) of the application linked to provider_pk, or (None, None)."""
    try:
        result = api_request(f"core/applications/?provider={provider_pk}")
        if result and result.get("results"):
            app = result["results"][0]
            return app.get("slug"), app.get("pk")
    except Exception as e:
        log(f"Warning: could not query applications by provider: {e}")
    return None, None


def delete_stale_application(slug):
    """Delete an application by slug, ignoring 404 errors."""
    try:
        api_request(f"core/applications/{urllib.parse.quote(slug)}/", method="DELETE")
        log(f"✓ Deleted stale application '{slug}'")
    except Exception as e:
        log(f"Warning: could not delete stale application '{slug}': {e}")


def create_application(provider_id):
    """Create the application and link it to the provider"""
    # If the provider already existed, check whether its linked application uses a
    # different slug (i.e. APP_SLUG was renamed between bootstrap runs).  Remove the
    # stale app so the current slug becomes the canonical one.
    stale_slug, _ = find_application_by_provider(provider_id)
    if stale_slug and stale_slug != APP_SLUG:
        log(f"Detected stale application slug '{stale_slug}' (expected '{APP_SLUG}') — removing…")
        delete_stale_application(stale_slug)

    if check_application_exists(APP_SLUG):
        log(f"✓ Application '{APP_SLUG}' already exists")
        
        # Update the provider if necessary
        try:
            app_data = {"provider": provider_id}
            api_request(f"core/applications/{APP_SLUG}/", method="PATCH", data=app_data)
            log(f"✓ Application updated with provider ID: {provider_id}")
        except Exception as e:
            log(f"Warning: Could not update application: {e}")
        return
    
    app_data = {
        "name": APP_NAME,
        "slug": APP_SLUG,
        "provider": provider_id,
        "meta_launch_url": APP_URL,
        "policy_engine_mode": "any",
        "open_in_new_tab": True
    }
    
    log(f"Creating application '{APP_NAME}'...")
    app = api_request("core/applications/", method="POST", data=app_data)
    log(f"✓ Application created: {app['slug']}")

def create_service_account_provider():
    """Create a confidential OAuth2 provider for service accounts / automated tests.

    Uses a separate client_id ({APP_SLUG}-svc) and confidential client_type so
    that the client_credentials grant works without affecting the public browser
    PKCE provider.
    """
    if not SERVICE_CLIENT_SECRET:
        log("SERVICE_CLIENT_SECRET not set — skipping service account provider")
        return None

    existing = check_provider_exists(SERVICE_CLIENT_ID)
    if existing:
        log(f"✓ Service account provider '{SERVICE_CLIENT_ID}' already exists (ID: {existing}) — syncing secret and scopes")
        try:
            api_request(f"providers/oauth2/{existing}/", method="PATCH", data={
                "client_secret": SERVICE_CLIENT_SECRET,
                "client_type": "confidential",
                "property_mappings": get_default_scope_mappings(),
            })
            log("✓ Service account provider synced")
        except Exception as e:
            log(f"Warning: could not sync service account provider: {e}")
        return existing

    auth_flow = get_default_authorization_flow()
    invalidation_flow = get_default_invalidation_flow()
    provider_data = {
        "name": f"{APP_NAME} Service Account Provider",
        "authorization_flow": auth_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "confidential",
        "client_id": SERVICE_CLIENT_ID,
        "client_secret": SERVICE_CLIENT_SECRET,
        "property_mappings": get_default_scope_mappings(),
        "redirect_uris": [{"matching_mode": "strict", "url": "http://localhost/svc-callback"}],
        "signing_key": get_default_signing_key(),
        "sub_mode": "user_username",
        "include_claims_in_id_token": True,
        "issuer_mode": "per_provider",
        "access_code_validity": AUTHENTIK_ACCESS_CODE_VALIDITY,
        "access_token_validity": AUTHENTIK_ACCESS_TOKEN_VALIDITY,
        "refresh_token_validity": AUTHENTIK_REFRESH_TOKEN_VALIDITY,
    }
    log(f"Creating service account OAuth2 provider '{SERVICE_CLIENT_ID}'...")
    provider = api_request("providers/oauth2/", method="POST", data=provider_data)
    log(f"✓ Service account provider created with ID: {provider['pk']}")
    return provider["pk"]


def create_service_account_application(provider_id):
    """Create the application linked to the service account provider."""
    if provider_id is None:
        return
    svc_slug = f"{APP_SLUG}-svc"
    if check_application_exists(svc_slug):
        log(f"✓ Service account application '{svc_slug}' already exists")
        try:
            api_request(f"core/applications/{svc_slug}/", method="PATCH", data={"provider": provider_id})
        except Exception as e:
            log(f"Warning: could not update service account application: {e}")
        return
    app_data = {
        "name": f"{APP_NAME} Service Account",
        "slug": svc_slug,
        "provider": provider_id,
        "policy_engine_mode": "any",
        "open_in_new_tab": False,
    }
    log(f"Creating service account application '{svc_slug}'...")
    app = api_request("core/applications/", method="POST", data=app_data)
    log(f"✓ Service account application created: {app['slug']}")


def print_summary():
    """Print a configuration summary"""
    print("\n" + "="*70)
    print("🎉 Bootstrap completed successfully!")
    print("="*70)
    print(f"\n📱 Authentik Admin Interface:")
    print(f"   URL: {AUTHENTIK_URL}/if/admin/")
    print(f"   Username: sadmin")
    print(f"   Password: (from AUTHENTIK_BOOTSTRAP_PASSWORD)")
    
    print(f"\n🔐 OAuth2/OIDC Configuration:")
    print(f"   Application: {APP_NAME}")
    print(f"   Client ID: {CLIENT_ID}")
    print(f"   Client Secret: {CLIENT_SECRET}")
    print(f"   Callback URL: {APP_CALLBACK_URL}")
    
    print(f"\n🔗 OAuth2 Endpoints:")
    print(f"   Authorization: {AUTHENTIK_URL}/application/o/authorize/")
    print(f"   Token: {AUTHENTIK_URL}/application/o/token/")
    print(f"   UserInfo: {AUTHENTIK_URL}/application/o/userinfo/")
    print(f"   JWKS: {AUTHENTIK_URL}/application/o/{APP_SLUG}/jwks/")
    print(f"   OpenID Config: {AUTHENTIK_URL}/application/o/{APP_SLUG}/.well-known/openid-configuration")
    
    print("\n" + "="*70 + "\n")

def ensure_bootstrap_token():
    """Upsert the bootstrap token into Authentik's DB.

    Authentik seeds AUTHENTIK_BOOTSTRAP_TOKEN into authentik_core_token only
    once — on the very first init of a fresh DB.  On redeployments against an
    existing DB the row is not recreated, so bootstrap_authentik.py would poll
    the API for 5 minutes and then fail.

    This function connects directly to PostgreSQL and upserts the token row
    before the API polling loop, making redeployments idempotent.
    """
    pg_host = os.getenv("AUTHENTIK_POSTGRES_HOST", "timescaledb")
    pg_port = int(os.getenv("AUTHENTIK_POSTGRES_PORT", "5432"))
    pg_user = os.getenv("AUTHENTIK_POSTGRES_USER", "authentik")
    pg_password = os.getenv("AUTHENTIK_POSTGRES_PASSWORD", "")
    pg_db = os.getenv("AUTHENTIK_POSTGRES_DB", "authentik")

    if not AUTHENTIK_TOKEN:
        return

    log("Pre-flight: ensuring bootstrap token exists in Authentik DB...")
    try:
        import psycopg2
    except ImportError:
        log("  psycopg2 not available — skipping token upsert (will rely on Authentik seeding)")
        return

    # Wait for PostgreSQL to be reachable before attempting upsert
    for attempt in range(1, 31):
        try:
            conn = psycopg2.connect(
                host=pg_host, port=pg_port, user=pg_user,
                password=pg_password, dbname=pg_db,
                connect_timeout=5,
            )
            conn.autocommit = True
            break
        except Exception as e:
            log(f"  DB not ready (attempt {attempt}/30): {e} — retrying in 5s...")
            time.sleep(5)
    else:
        log("  WARNING: Could not connect to DB for token upsert — will rely on Authentik seeding")
        return

    try:
        with conn.cursor() as cur:
            # Resolve akadmin user pk — Authentik creates it during migrations
            cur.execute("SELECT id FROM authentik_core_user WHERE username = 'akadmin' LIMIT 1")
            row = cur.fetchone()
            if not row:
                log("  akadmin user not found yet — skipping token upsert (DB migrations may not be done)")
                return
            akadmin_id = row[0]
            token_uuid = str(uuid.uuid4())

            cur.execute("""
                INSERT INTO authentik_core_token
                    (intent, key, token_uuid, user_id, description, expiring, expires, identifier)
                VALUES
                    ('api', %s, %s, %s, 'Bootstrap token (auto-upserted)', false, NOW() + INTERVAL '100 years', 'authentik-bootstrap-token')
                ON CONFLICT (identifier) DO UPDATE
                    SET key = EXCLUDED.key,
                        token_uuid = EXCLUDED.token_uuid,
                        user_id = EXCLUDED.user_id,
                        expiring = false,
                        expires = NOW() + INTERVAL '100 years'
            """, (AUTHENTIK_TOKEN, token_uuid, akadmin_id))
            log("  ✓ Bootstrap token upserted into authentik_core_token")
    except Exception as e:
        log(f"  WARNING: Token upsert failed: {e} — will rely on Authentik seeding")
    finally:
        conn.close()


def _find_group_by_name(name: str):
    """Return group dict if found, else None."""
    try:
        result = api_request(f"core/groups/?name={urllib.parse.quote(name)}")
        if result and result.get("results"):
            for g in result["results"]:
                if g.get("name") == name:
                    return g
    except Exception:
        pass
    return None


def ensure_profiles_from_plan(plan):
    profiles = plan.get("profiles", {})
    for name, meta in profiles.items():
        description = (meta or {}).get("description")
        attributes = {"description": description} if description else None
        existing = _find_group_by_name(name)
        if existing:
            patch: dict[str, dict] = {}
            current_attrs = existing.get("attributes") or {}
            if attributes and current_attrs.get("description") != description:
                patch["attributes"] = attributes
            if patch:
                api_request(f"core/groups/{existing['pk']}/", method="PATCH", data=patch)
                log(f"  ✓ Updated group '{name}' description")
            else:
                log(f"  ✓ Group '{name}' ready")
            continue

        payload = {"name": name}
        if attributes:
            payload["attributes"] = attributes
        api_request("core/groups/", method="POST", data=payload)
        log(f"  ✓ Created group '{name}'")


def _ensure_registry_group(name: str, attributes: dict):
    existing = _find_group_by_name(name)
    payload = {"name": name, "attributes": attributes}
    if existing:
        current_attrs = existing.get("attributes") or {}
        if current_attrs != attributes:
            api_request(f"core/groups/{existing['pk']}/", method="PATCH", data={"attributes": attributes})
            log(f"  ✓ Updated registry group '{name}'")
        else:
            log(f"  ✓ Registry group '{name}' ready")
        return

    api_request("core/groups/", method="POST", data=payload)
    log(f"  ✓ Created registry group '{name}'")


def ensure_users_from_plan(plan):
    users_meta = plan.get("users") or {}
    if not users_meta:
        log("  ℹ No plan-managed users defined")
        return

    for username in sorted(users_meta.keys()):
        meta = users_meta.get(username) or {}
        if not username or not isinstance(meta, dict):
            continue
        if username == SADMIN_USERNAME:
            log(f"  ℹ Skipping '{username}' (managed via ensure_sadmin_user)")
            continue

        existing = _find_user_by_username(username)
        desired = _build_user_payload(meta, for_create=existing is None)
        user_pk = None

        if existing:
            patch: dict[str, object] = {}
            for field, value in desired.items():
                if field == "attributes":
                    current_attrs = existing.get("attributes") or {}
                    if current_attrs != value:
                        patch[field] = value
                else:
                    if existing.get(field) != value:
                        patch[field] = value
            if patch:
                api_request(f"core/users/{existing['pk']}/", method="PATCH", data=patch)
                log(f"  ✓ Updated user '{username}'")
            else:
                log(f"  ✓ User '{username}' ready")
            user_pk = existing.get("pk")
        else:
            payload = {"username": username}
            payload.update(desired)
            payload.setdefault("is_active", True)
            payload.setdefault("is_superuser", False)
            created = api_request("core/users/", method="POST", data=payload)
            user_pk = created.get("pk")
            log(f"  ✓ Created user '{username}'")

        password_value = _resolve_user_password(username, meta)
        if password_value and user_pk:
            if _set_user_password(user_pk, password_value):
                log(f"  ✓ Synced password for '{username}'")
            else:
                log(f"  ✗ WARNING: could not set password for '{username}'")
        elif not password_value:
            log(f"  ℹ Skipping password sync for '{username}' (no password provided)")


def ensure_plan_registries(plan: dict):
    permissions_payload = {
        AVAILABLE_PERMISSIONS_ATTRIBUTE: plan.get("available_permissions") or [],
        REGISTRY_KIND_ATTRIBUTE: REGISTRY_KIND_AVAILABLE_PERMISSIONS,
    }
    roles_payload = {
        ROLES_MAPPING_ATTRIBUTE: plan.get("roles_mapping") or {},
        REGISTRY_KIND_ATTRIBUTE: REGISTRY_KIND_ROLES_MAPPING,
    }
    profile_roles_payload = {
        PROFILE_ROLES_ATTRIBUTE: plan.get("profile_roles") or {},
        REGISTRY_KIND_ATTRIBUTE: REGISTRY_KIND_PROFILE_ROLES,
    }
    _ensure_registry_group(AVAILABLE_PERMISSIONS_REGISTRY_NAME, permissions_payload)
    _ensure_registry_group(ROLES_MAPPING_REGISTRY_NAME, roles_payload)
    _ensure_registry_group(PROFILE_ROLES_REGISTRY_NAME, profile_roles_payload)


def ensure_user_group_memberships(plan):
    user_profiles = plan.get("user_profiles", {})
    if not user_profiles:
        return
    for username, profiles in user_profiles.items():
        user = _find_user_by_username(username)
        if not user:
            log(f"  ⚠ User '{username}' not found while assigning profiles")
            continue
        user_pk = user.get("pk")
        for profile_name in profiles:
            group = _find_group_by_name(profile_name)
            if not group:
                log(f"  ✗ Group '{profile_name}' not found for user '{username}'")
                continue
            group_pk = group.get("pk")
            try:
                api_request(f"core/groups/{group_pk}/add_user/", method="POST", data={"pk": user_pk})
                log(f"  ✓ Added '{username}' to '{profile_name}'")
            except Exception as exc:
                log(f"  ℹ Could not add '{username}' to '{profile_name}': {exc}")


def _get_provider_pk_by_client_id(client_id: str):
    """Find OAuth2 provider PK by client_id."""
    try:
        providers = api_request(f"providers/oauth2/?client_id={urllib.parse.quote(client_id)}")
        if providers and providers.get("results"):
            return providers["results"][0].get("pk")
    except Exception:
        pass
    return None


def update_provider_scope_mappings(mapping_pk: str):
    """Append the custom scope mapping to both browser and service-account providers."""
    for client_id in (CLIENT_ID, SERVICE_CLIENT_ID):
        provider_pk = _get_provider_pk_by_client_id(client_id)
        if not provider_pk:
            log(f"  ✗ Provider with client_id '{client_id}' not found")
            continue
        try:
            # Fetch current mappings
            provider = api_request(f"providers/oauth2/{provider_pk}/")
            current = provider.get("property_mappings", [])
            if mapping_pk in current:
                log(f"  ✓ Provider '{client_id}' already has scope mapping")
                continue
            api_request(f"providers/oauth2/{provider_pk}/", method="PATCH", data={
                "property_mappings": current + [mapping_pk],
            })
            log(f"  ✓ Added scope mapping to provider '{client_id}'")
        except Exception as e:
            log(f"  ✗ Could not update provider '{client_id}': {e}")


def _find_role_by_name(name: str):
    """Return RBAC role dict if found, else None."""
    try:
        result = api_request(f"rbac/roles/?search={urllib.parse.quote(name)}")
        if result and result.get("results"):
            for r in result["results"]:
                if r.get("name") == name:
                    return r
    except Exception:
        pass
    return None


def ensure_roles_from_plan(plan):
    roles_meta = plan.get("roles", {})
    profile_roles = plan.get("profile_roles", {})
    profiles_meta = plan.get("profiles", {})

    primary_group_for_role: dict[str, str] = {}
    for profile_name, role_names in profile_roles.items():
        profile_source = (profiles_meta.get(profile_name) or {}).get("source")
        for role_name in role_names:
            role_source = (roles_meta.get(role_name) or {}).get("source")
            if primary_group_for_role.get(role_name):
                if role_source and profile_source == role_source:
                    primary_group_for_role[role_name] = profile_name
                continue
            primary_group_for_role[role_name] = profile_name

    for name, meta in roles_meta.items():
        description = (meta or {}).get("description") or ""
        existing = _find_role_by_name(name)
        role_pk = None
        if existing:
            patch: dict[str, object] = {}
            if description and existing.get("description") != description:
                patch["description"] = description
            if patch:
                api_request(f"rbac/roles/{existing['pk']}/", method="PATCH", data=patch)
                log(f"  ✓ Updated role '{name}'")
            else:
                log(f"  ✓ Role '{name}' ready")
            role_pk = existing.get("pk")
        else:
            created = api_request(
                "rbac/roles/",
                method="POST",
                data={
                    "name": name,
                    "description": description or None,
                },
            )
            role_pk = created.get("pk")
            log(f"  ✓ Created role '{name}'")

        group_name = primary_group_for_role.get(name)
        if role_pk and group_name:
            group = _find_group_by_name(group_name)
            if not group:
                log(f"  ✗ Group '{group_name}' not found for role '{name}' assignment")
                continue
            try:
                api_request(
                    f"rbac/roles/{role_pk}/",
                    method="PATCH",
                    data={"group": group.get("pk")},
                )
                log(f"  ✓ Linked role '{name}' to group '{group_name}'")
            except Exception as exc:
                log(f"  ℹ Could not link role '{name}' to group '{group_name}': {exc}")


def load_authorization_plan_data():
    contracts = load_authorization_contracts()
    if not contracts:
        raise RuntimeError("No authorization contracts available")
    if yaml is None:
        raise RuntimeError("PyYAML is required to load authorization contracts")
    return build_authorization_plan(contracts)


def ensure_authorization_entities():
    """Bootstrap authorization: ingest contracts, sync groups/roles/claims."""
    log("Ensuring authorization entities...")
    plan = load_authorization_plan_data()
    ensure_profiles_from_plan(plan)
    ensure_roles_from_plan(plan)
    ensure_plan_registries(plan)
    ensure_users_from_plan(plan)
    ensure_user_group_memberships(plan)

    mapping = ensure_permissions_scope_mapping(plan)
    if mapping:
        update_provider_scope_mappings(mapping.get("pk"))

    log("Authorization entities done.")


def main():
    """Main bootstrap function"""
    log("Starting Authentik bootstrap process...")
    
    # Validation
    if not AUTHENTIK_TOKEN:
        log("✗ ERROR: AUTHENTIK_BOOTSTRAP_TOKEN not set")
        sys.exit(1)
    
    if not CLIENT_SECRET:
        log("✗ ERROR: CLIENT_SECRET not set")
        sys.exit(1)
    
    # Wait for Authentik to be ready
    if not wait_for_authentik():
        log("✗ ERROR: Authentik startup timeout")
        sys.exit(1)

    # Pre-flight: upsert bootstrap token into DB so redeployments against
    # existing Authentik DBs don't fail waiting for a token that was never
    # re-seeded by Authentik.
    ensure_bootstrap_token()

    # Wait until the bootstrap token is accepted (migrations + internal bootstrap must finish)
    log("Waiting for bootstrap token to become valid...")
    token_ready = False
    for attempt in range(1, 61):
        try:
            result = api_request("core/tokens/")
            if result is not None:
                log("✓ Bootstrap token accepted by Authentik API")
                token_ready = True
                break
        except Exception:
            pass
        log(f"Token not yet valid (attempt {attempt}/60), retrying in 5s...")
        time.sleep(5)
    if not token_ready:
        log("✗ ERROR: Bootstrap token never became valid")
        sys.exit(1)
    
    try:
        ensure_sadmin_user()

        # Create OAuth2 provider (public — browser PKCE flow)
        provider_id = create_oauth2_provider()

        # Create application
        create_application(provider_id)

        # Create confidential service account provider + application (for client_credentials / tests)
        svc_provider_id = create_service_account_provider()
        create_service_account_application(svc_provider_id)

        # Bootstrap authorization entities (groups, scope mapping, provider updates)
        ensure_authorization_entities()

        # Apply login branding automatically
        ensure_login_branding()

        # Set flow title
        ensure_flow_title()

        # Print summary
        print_summary()
        
        sys.exit(0)
        
    except Exception as e:
        log(f"✗ ERROR during bootstrap: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
