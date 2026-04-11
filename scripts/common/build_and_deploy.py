import argparse
import json
import os
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULES_DIR = os.path.join(PROJECT_ROOT, "modules")
DEPLOYMENT_ROOT_DIR = os.path.join(PROJECT_ROOT, "deployment_root")


def run(cmd, cwd=None):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT)
    if result.returncode != 0:
        print(f"ERROR: command failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def read_enabled_modules():
    """Parse modules/enabled.md and return a list of (module_name, mode) tuples.
    
    Mode can be:
    - 'build': Module has local SOURCES/ and should be built from source
    - 'remote': Module should use pre-built images (no local SOURCES/)
    
    Example enabled.md lines:
        HostApp: enabled-remote    # Use pre-built images
        DigitalShelter: enabled     # Build from local SOURCES/
    """
    enabled_path = os.path.join(MODULES_DIR, "enabled.md")
    if not os.path.exists(enabled_path):
        print(f"ERROR: {enabled_path} not found")
        sys.exit(1)
    enabled = []
    with open(enabled_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            # Match both 'enabled' and 'enabled-remote' patterns
            m = re.match(r"^(\w+)\s*:\s*enabled(?:-(\w+))?\s*$", line, re.IGNORECASE)
            if m:
                module_name = m.group(1)
                sub_mode = m.group(2)
                mode = 'remote' if sub_mode and sub_mode.lower() == 'remote' else 'build'
                enabled.append((module_name, mode))
    return enabled


def read_module_metadata(module_name, module_path):
    """Read module.json metadata for a module, with safe defaults."""
    module_json_path = os.path.join(module_path, "module.json")
    defaults = {
        "name": module_name,
        "slug": module_name.lower(),
        "displayName": module_name,
        "role": "remote",
    }
    if not os.path.isfile(module_json_path):
        return defaults
    with open(module_json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {
        "name": payload.get("name") or defaults["name"],
        "slug": payload.get("slug") or defaults["slug"],
        "displayName": payload.get("displayName") or defaults["displayName"],
        "role": payload.get("role") or defaults["role"],
        "frontendPort": payload.get("frontendPort", 3001),
        "backendPort": payload.get("backendPort", 8002),
    }


def find_module_compose_file(module_name, module_path, module_slug):
    """Find module compose file. Canonical name is docker-compose.yml inside the module folder."""
    candidates = [
        os.path.join(module_path, "docker-compose.yml"),
        # legacy slug-based names kept as fallback
        os.path.join(module_path, f"docker-compose.{module_slug}.yml"),
        os.path.join(module_path, f"docker-compose.{module_name.lower()}.yml"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


def discover_submodules(module_path):
    """Return sub-module names that have a SOURCES/ folder, sorted alphabetically."""
    submodules = []
    print(f"  [DEBUG] Scanning {module_path} for submodules...")
    for entry in sorted(os.listdir(module_path)):
        submodule_path = os.path.join(module_path, entry)
        is_dir = os.path.isdir(submodule_path)
        has_sources = os.path.isdir(os.path.join(submodule_path, "SOURCES")) if is_dir else False
        print(f"    [DEBUG] Checking {entry}: is_dir={is_dir}, has_sources={has_sources}")
        if is_dir and has_sources:
            submodules.append(entry)
    return submodules


def classify_submodule(submodule_path):
    """
    Returns a tuple (has_dockerfile, has_file_artifacts).
    - has_dockerfile: True if SOURCES/Dockerfile exists → build a Docker image
    - has_file_artifacts: True if SOURCES/ contains files other than Dockerfile → copy to DIST/
    """
    sources_path = os.path.join(submodule_path, "SOURCES")
    has_dockerfile = os.path.isfile(os.path.join(sources_path, "Dockerfile"))
    non_docker_files = [
        f for f in os.listdir(sources_path) if f != "Dockerfile"
    ]
    has_file_artifacts = len(non_docker_files) > 0
    return has_dockerfile, has_file_artifacts


def get_app_slug():
    app_slug = os.getenv("APP_SLUG")
    if not app_slug:
        print("ERROR: APP_SLUG must be set in the environment (.env) to derive Docker image names")
        sys.exit(1)
    return app_slug


def load_module_env(module_path):
    """Load environment variables from module's .env file."""
    env_file = os.path.join(module_path, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value


def read_module_env_map(module_path):
    """Read module .env as a key/value map without mutating process env."""
    env_map = {}
    env_file = os.path.join(module_path, ".env")
    if not os.path.exists(env_file):
        return env_map
    with open(env_file, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_map[key.strip()] = value.strip().strip('"').strip("'")
    return env_map


def moduletemplate_entities_db_matches_hostapp_db(module_path):
    """Return True when ModuleTemplate entities DB target points to HostApp DB."""
    env_map = read_module_env_map(module_path)

    entities_target = (
        env_map.get("TEMPLATE_ENTITIES_DB_HOST", "template-database"),
        env_map.get("TEMPLATE_ENTITIES_DB_PORT", "5432"),
        env_map.get("TEMPLATE_ENTITIES_DB_NAME", env_map.get("TEMPLATE_POSTGRES_DB", "")),
        env_map.get("TEMPLATE_ENTITIES_DB_USER", env_map.get("TEMPLATE_POSTGRES_USER", "")),
        env_map.get("TEMPLATE_ENTITIES_DB_PASSWORD", env_map.get("TEMPLATE_POSTGRES_PASSWORD", "")),
    )

    hostapp_target = (
        env_map.get("HOSTAPP_DB_HOST", ""),
        env_map.get("HOSTAPP_DB_PORT", ""),
        env_map.get("HOSTAPP_DB_NAME", ""),
        env_map.get("HOSTAPP_DB_USER", ""),
        env_map.get("HOSTAPP_DB_PASSWORD", ""),
    )

    return all(hostapp_target) and entities_target == hostapp_target


def _service_block_bounds(lines, service_name):
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"{service_name}:" and line.startswith("  "):
            start = idx
            break
    if start is None:
        return None, None

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z0-9_.-]+:\s*$", lines[idx]):
            end = idx
            break
    return start, end


def remove_service_from_compose(content, service_name):
    lines = content.splitlines()
    start, end = _service_block_bounds(lines, service_name)
    if start is None:
        return content
    del lines[start:end]
    return "\n".join(lines) + "\n"


def remove_backend_dependency(content, backend_service, dependency_service):
    lines = content.splitlines()
    start, end = _service_block_bounds(lines, backend_service)
    if start is None:
        return content

    depends_on_idx = None
    for idx in range(start, end):
        if lines[idx].strip() == "depends_on:":
            depends_on_idx = idx
            break
    if depends_on_idx is None:
        return content

    dep_idx = None
    for idx in range(depends_on_idx + 1, end):
        if lines[idx].strip() == f"{dependency_service}:" and lines[idx].startswith("      "):
            dep_idx = idx
            break
        if re.match(r"^    [A-Za-z0-9_.-]+:\s*$", lines[idx]):
            break
    if dep_idx is None:
        return content

    dep_end = dep_idx + 1
    while dep_end < end:
        line = lines[dep_end]
        if line.startswith("      ") and line.strip().endswith(":"):
            break
        if re.match(r"^    [A-Za-z0-9_.-]+:\s*$", line):
            break
        dep_end += 1

    del lines[dep_idx:dep_end]
    return "\n".join(lines) + "\n"


def image_name(module_name, submodule_name, module_slug=None):
    """Derive a deterministic Docker image name from module and sub-module names.
    
    HostApp uses pattern:        {app_slug}/hostapp-{service}:latest
    All other modules use:       {app_slug}/{service}:latest
    
    The non-HostApp pattern matches the docker-compose.yml image names inherited
    from ModuleTemplate (e.g. template/backend -> sra/backend after module-init).
    """
    app_slug = module_slug or get_app_slug()
    module_lower = module_name.lower()
    submodule_lower = submodule_name.lower()
    
    # HostApp uses 'hostapp-' prefix in image names
    if module_lower == "hostapp":
        return f"{app_slug}/hostapp-{submodule_lower}:latest"
    # All other modules (ModuleTemplate-derived): {app_slug}/{service}:latest
    else:
        return f"{app_slug}/{submodule_lower}:latest"


def clean_dist(submodule_path):
    dist_path = os.path.join(submodule_path, "DIST")
    if os.path.exists(dist_path):
        shutil.rmtree(dist_path)
    os.makedirs(dist_path, exist_ok=True)


def specs_build_script(submodule_path):
    """
    Return the path to SPECS/build.sh if it exists for this sub-module, else None.
    When present, the script is the authoritative non-standard build for that sub-module.
    """
    script = os.path.join(submodule_path, "SPECS", "build.sh")
    return script if os.path.isfile(script) else None


def _inject_favicon(submodule_path, sources_path):
    """Copy favicon from SPECS/ into SOURCES/public/ before the frontend Docker build."""
    specs_dir = os.path.join(submodule_path, "SPECS")
    public_dir = os.path.join(sources_path, "public")
    favicon_names = ["favicon.svg", "favicon.ico", "favicon.png"]
    for name in favicon_names:
        src = os.path.join(specs_dir, name)
        if os.path.isfile(src):
            os.makedirs(public_dir, exist_ok=True)
            dst = os.path.join(public_dir, name)
            shutil.copy2(src, dst)
            print(f"  [frontend] Injected {name} from SPECS/ into SOURCES/public/")
            return
    print("  [frontend] Warning: no favicon found in SPECS/ (looked for favicon.svg, favicon.ico, favicon.png)")


def build_submodule(module_name, submodule_name, submodule_path, module_slug=None):
    """Build a single sub-module: Docker image and/or file artifacts."""
    has_dockerfile, has_file_artifacts = classify_submodule(submodule_path)
    sources_path = os.path.join(submodule_path, "SOURCES")

    if not has_dockerfile and not has_file_artifacts:
        print(f"  [{submodule_name}] SOURCES/ is empty — skipping")
        return

    if has_dockerfile:
        img = image_name(module_name, submodule_name, module_slug)
        print(f"  [{submodule_name}] Building Docker image: {img}")

        build_cmd = ["docker", "build", "--progress=plain", "--no-cache", "-t", img]
        if submodule_name.lower() == "frontend":
            vite_env = {
                k: v for k, v in os.environ.items() if k.startswith("VITE_") and v
            }
            if not vite_env:
                print(
                    "ERROR: no VITE_* environment variables found while building the frontend image. "
                    "Load the module .env before running this script (so Vite can inline its compile-time config)."
                )
                sys.exit(1)
            for k in sorted(vite_env.keys()):
                build_cmd.extend(["--build-arg", f"{k}={vite_env[k]}"])

            _inject_favicon(submodule_path, sources_path)

        build_cmd.append(sources_path)
        run(build_cmd)

    elif has_file_artifacts:
        print(f"  [{submodule_name}] Copying file artifacts to DIST/")
        clean_dist(submodule_path)
        dist_path = os.path.join(submodule_path, "DIST")
        for item in sorted(os.listdir(sources_path)):
            if item == "Dockerfile":
                continue
            src = os.path.join(sources_path, item)
            dst = os.path.join(dist_path, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        print(f"  [{submodule_name}] File artifacts copied to {dist_path}")


def deploy_submodule(module_name, submodule_name, submodule_path):
    """Copy a sub-module's DIST/ to the correct path inside deployment_root/."""
    dist_path = os.path.join(submodule_path, "DIST")
    if not os.path.exists(dist_path) or not os.listdir(dist_path):
        print(f"  [{submodule_name}] No DIST/ to deploy — skipping")
        return
    dst = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", module_name, submodule_name)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(dist_path, dst)
    print(f"  [{submodule_name}] Deployed DIST/ → {dst}")


def deploy_module_root(module_name, module_path, module_meta):
    """Copy module compose file to deployment_root/modules/<MODULE>/docker-compose.yml.
    
    Converts relative bind mount paths (e.g., ./database/, ./authentik/) from the
    module's perspective to be relative to deployment_root (e.g., ./modules/<MODULE>/database/).
    This ensures correct resolution when Docker Compose merges multiple compose files.
    
    The .env files are NOT copied here — they are merged into a single
    deployment_root/.env by merge_env_files() after all modules are processed.
    """
    import re
    
    dst_root = DEPLOYMENT_ROOT_DIR
    module_slug = module_meta["slug"]
    deployed_compose_rel = ""  # relative to deployment_root/, used for compose -f flags

    src_compose = find_module_compose_file(module_name, module_path, module_slug)
    if os.path.exists(src_compose):
        # Deploy compose into deployment_root/modules/<MODULE>/docker-compose.yml
        dst_module_dir = os.path.join(dst_root, "modules", module_name)
        os.makedirs(dst_module_dir, exist_ok=True)
        dst_compose = os.path.join(dst_module_dir, "docker-compose.yml")
        
        # Read compose content
        with open(src_compose, 'r') as f:
            content = f.read()

        if module_name == "ModuleTemplate" and moduletemplate_entities_db_matches_hostapp_db(module_path):
            content = remove_service_from_compose(content, "template-database")
            content = remove_backend_dependency(content, "template-backend", "template-database")
            print("  [ModuleTemplate] Entities DB target matches HostApp DB — template-database service disabled")
        
        # Docker Compose resolves all relative bind mount paths from --project-directory
        # (deployment_root), not from each module file location.
        # Convert: ./database/initdb/file.sql -> ./modules/ModuleName/database/initdb/file.sql
        # for every module, including HostApp.
        module_prefix = f"./modules/{module_name}/"

        # Match volume entries: - ./path:/container/path (short syntax)
        content = re.sub(
            r'(^|\n)(\s*-\s+)(\.\/[^\s:"\']+)(:[^\n]*)',
            lambda m: f"{m.group(1)}{m.group(2)}{module_prefix}{m.group(3).lstrip('./')}{m.group(4)}",
            content
        )

        # Match source: entries (long syntax)
        content = re.sub(
            r'(source:\s+)(\.\/[^\s\n]+)',
            lambda m: f"{m.group(1)}{module_prefix}{m.group(2).lstrip('./')}",
            content
        )
        
        # Write modified compose file
        with open(dst_compose, 'w') as f:
            f.write(content)
        
        deployed_compose_rel = f"modules/{module_name}/docker-compose.yml"
        print(f"  [{module_name}] Deployed {deployed_compose_rel} (paths made deployment-relative)")

    config_src = os.path.join(module_path, "config")
    if os.path.isdir(config_src):
        dst_module_dir = os.path.join(dst_root, "modules", module_name)
        config_dst = os.path.join(dst_module_dir, "config")
        if os.path.exists(config_dst):
            shutil.rmtree(config_dst)
        shutil.copytree(config_src, config_dst)
        print(f"  [{module_name}] Deployed config/ → {config_dst}")

    return deployed_compose_rel


def generate_traefik_dynamic_template(enabled_module_data):
    """Generate dynamic.yml.template with routes for all enabled remote modules.

    Writes to:
    - SOURCES/dynamic.yml.template (so it gets baked into the traefik image on local builds)
    - deployment_root/modules/HostApp/traefik/dynamic.yml.template (volume-mounted at runtime,
      overriding the baked-in template — this is how SRA/remote deployments get correct routes)
    """
    traefik_sources = os.path.join(MODULES_DIR, "HostApp", "traefik", "SOURCES")
    sources_template_path = os.path.join(traefik_sources, "dynamic.yml.template")

    remote_modules = [
        (name, meta)
        for name, path, meta in enabled_module_data
        if meta.get("role") != "host"
    ]

    BASE_HOST = "${EXTERNAL_BASE_HOST}"

    routers_block = ""
    middlewares_block = ""
    services_block = ""

    for _name, meta in remote_modules:
        slug = meta["slug"]
        backend_port = meta.get("backendPort", 8002)
        routers_block += f"""
    # ── {meta['displayName']} remote frontend ─────────────────────────────────────────
    {slug}-frontend:
      rule: "(Host(`{BASE_HOST}`) || Host(`localhost`) || Host(`127.0.0.1`)) && PathPrefix(`/remotes/{slug}`)"
      priority: 130
      entryPoints:
        - web
        - websecure
      service: {slug}-frontend
      middlewares:
        - {slug}-stripprefix
      tls:
        certResolver: le

    # ── {meta['displayName']} backend (API + docs + health) ──────────────────────────
    {slug}-backend:
      rule: "(Host(`{BASE_HOST}`) || Host(`localhost`) || Host(`127.0.0.1`)) && PathPrefix(`/module/{slug}`)"
      priority: 110
      entryPoints:
        - web
        - websecure
      service: {slug}-backend
      middlewares:
        - {slug}-module-stripprefix
      tls:
        certResolver: le
"""
        middlewares_block += f"""
    {slug}-stripprefix:
      stripPrefix:
        prefixes:
          - "/remotes/{slug}"

    {slug}-module-stripprefix:
      stripPrefix:
        prefixes:
          - "/module/{slug}"
"""
        services_block += f"""
    {slug}-frontend:
      loadBalancer:
        servers:
          - url: "http://{slug}-frontend:80"

    {slug}-backend:
      loadBalancer:
        servers:
          - url: "http://{slug}-backend:{backend_port}"
"""

    content = f"""http:
  routers:
    # ── Authentik standard paths (UI, flows, static, its own /api/v3) ────
    # Priority 150 beats backend's /api catch-all for /api/v3.
    authentik-core:
      rule: "Host(`{BASE_HOST}`) && (PathPrefix(`/if`) || PathPrefix(`/flows`) || PathPrefix(`/application`) || PathPrefix(`/static`) || PathPrefix(`/media`) || PathPrefix(`/api/v3`) || PathPrefix(`/ws`))"
      priority: 150
      entryPoints:
        - websecure
      service: authentik
      tls:
        certResolver: le

    # ── Authentik embedded outpost callback ──────────────────────────────
    # Priority 15 required per Authentik docs to beat frontend catch-all.
    authentik-outpost:
      rule: "Host(`{BASE_HOST}`) && PathPrefix(`/outpost.goauthentik.io`)"
      priority: 15
      entryPoints:
        - websecure
      service: authentik
      tls:
        certResolver: le

    # ── Backend API (/api/*) ───────────────────────────────────────────────
    # No forwardAuth: the frontend sends Authorization: Bearer <JWT> and the
    # backend validates it directly against Authentik's JWKS endpoint.
    # Note: Backend routes already have /api prefix, so no stripPrefix needed.
    backend:
      rule: "Host(`{BASE_HOST}`) && PathPrefix(`/api`)"
      priority: 100
      entryPoints:
        - websecure
      service: backend
      tls:
        certResolver: le

    # ── Backend health endpoint at root level ───────────────────────────────
    # Health check at root for container healthchecks and monitoring tools.
    backend-health:
      rule: "Host(`{BASE_HOST}`) && Path(`/health`)"
      priority: 120
      entryPoints:
        - websecure
      service: backend
      tls:
        certResolver: le
{routers_block}
    # ── OIDC callback — must NOT be behind forwardAuth ───────────────────
    # oidc-client-ts posts the auth code here; forwardAuth would intercept
    # and redirect again before the SPA can exchange the code.
    auth-callback:
      rule: "Host(`{BASE_HOST}`) && PathPrefix(`/auth/callback`)"
      priority: 50
      entryPoints:
        - websecure
      service: frontend
      tls:
        certResolver: le

    # ── React frontend (catch-all) — NO forwardAuth ──────────────────────
    # The SPA manages its own OIDC session via oidc-client-ts.
    # Traefik must serve it unconditionally; the app redirects to /login
    # internally when unauthenticated.
    frontend:
      rule: "Host(`{BASE_HOST}`) && PathPrefix(`/`)"
      priority: 10
      entryPoints:
        - websecure
      service: frontend
      tls:
        certResolver: le

  middlewares:
    # Security headers
    security-headers:
      headers:
        frameDeny: true
        browserXssFilter: true
        contentTypeNosniff: true
        stsIncludeSubdomains: true
        stsPreload: true
        stsSeconds: 31536000
        referrerPolicy: "strict-origin-when-cross-origin"

    api-stripprefix:
      stripPrefix:
        prefixes:
          - "/api"
{middlewares_block}
    # Rate limiting — protect API from abuse
    api-ratelimit:
      rateLimit:
        average: 100
        burst: 50

  services:
    authentik:
      loadBalancer:
        servers:
          - url: "http://authentik-server:9000"

    backend:
      loadBalancer:
        servers:
          - url: "http://backend:8001"

    frontend:
      loadBalancer:
        servers:
          - url: "http://frontend:80"
{services_block}"""

    slugs = [meta['slug'] for _, meta in remote_modules]

    # Write to SOURCES (for image rebuild path)
    if os.path.isfile(sources_template_path):
        with open(sources_template_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [traefik] Updated SOURCES/dynamic.yml.template for modules: {', '.join(slugs) or '(none)'}")

    # Always write to deployment_root (volume-mount path, used by remote HostApp deployments)
    deploy_traefik_dir = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", "traefik")
    os.makedirs(deploy_traefik_dir, exist_ok=True)
    deploy_template_path = os.path.join(deploy_traefik_dir, "dynamic.yml.template")
    with open(deploy_template_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [traefik] Generated deployment_root traefik/dynamic.yml.template for modules: {', '.join(slugs) or '(none)'}")


def generate_modules_menu_mapping(enabled_module_data):
    """Build modules_menu_mapping.json from each enabled module's config/menu_definition.json.

    Reads each non-HostApp module's menu_definition.json, injects 'module' (slug) and
    'module_menu_item_code_path' fields recursively, and writes the merged result to
    deployment_root/modules/HostApp/config/modules_menu_mapping.json.
    This replaces the static file so the mapping is always consistent with enabled modules.
    """
    def annotate(items, slug, path_prefix):
        result = []
        for item in items:
            code = item.get("menu_item_code", "")
            path = f"{path_prefix}.{code}" if path_prefix else code
            entry = {k: v for k, v in item.items() if k != "sub_items"}
            entry["module"] = slug
            entry["module_menu_item_code_path"] = path
            sub = item.get("sub_items", [])
            entry["sub_items"] = annotate(sub, slug, path)
            result.append(entry)
        return result

    mapping = []
    for module_name, module_path, module_meta in enabled_module_data:
        if module_meta.get("role") == "host":
            continue
        menu_def_path = os.path.join(module_path, "config", "menu_definition.json")
        if not os.path.isfile(menu_def_path):
            continue
        with open(menu_def_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        slug = module_meta.get("slug", module_name.lower())
        items = data.get("menu_definition", [])
        mapping.extend(annotate(items, slug, ""))

    payload = json.dumps({"menu_mapping": mapping}, indent=2)

    # Write to deployment_root config dir (runtime volume mount)
    dst_dir = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", "config")
    os.makedirs(dst_dir, exist_ok=True)
    dst_path = os.path.join(dst_dir, "modules_menu_mapping.json")
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(payload)

    # Write to src/config/ so it gets baked into the frontend bundle at build time
    src_config_dir = os.path.join(MODULES_DIR, "HostApp", "frontend", "SOURCES", "src", "config")
    if os.path.isdir(src_config_dir):
        src_config_path = os.path.join(src_config_dir, "modules_menu_mapping.json")
        with open(src_config_path, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"  [HostApp] Updated src/config/modules_menu_mapping.json ({len(mapping)} top-level entries)")
    else:
        print(f"  [HostApp] Generated modules_menu_mapping.json ({len(mapping)} top-level entries)")


def merge_env_files(enabled_module_data, remote_hostapp=False):
    """Merge all modules' .env files into a single deployment_root/.env.
    
    Rules:
    - Each module's .env is appended in order (host module first, then remotes).
    - A key defined in an earlier module is NOT overwritten by a later module.
    - The merged file is the single source of truth for all deployed compose files.
    
    Args:
        enabled_module_data: List of (module_name, module_path, module_meta) tuples
        remote_hostapp: If True, also include HostApp .env from modules/HostApp/
    """
    merged: dict[str, str] = {}   # key → raw line (preserves comments inline)
    merged_lines: list[str] = []  # final output lines in insertion order
    module_count = 0

    # Process remote HostApp .env first if present (it acts as the host)
    if remote_hostapp:
        hostapp_env = os.path.join(MODULES_DIR, "HostApp", ".env")
        if os.path.exists(hostapp_env):
            section_header = "\n# ── HostApp ──────────────────────────────────────────\n"
            section_lines: list[str] = []
            with open(hostapp_env) as f:
                for raw_line in f:
                    line = raw_line.rstrip("\n")
                    stripped = line.strip()
                    # Blank lines and comment-only lines are always included
                    if not stripped or stripped.startswith("#"):
                        section_lines.append(line)
                        continue
                    # Extract key (handle inline comments and quoted values)
                    key = stripped.split("=", 1)[0].strip()
                    if key in merged:
                        # Key already defined by a previous module — skip but note it
                        section_lines.append(f"# [merged: {key} already defined above]")
                    else:
                        merged[key] = line
                        section_lines.append(line)
            merged_lines.append(section_header)
            merged_lines.extend(section_lines)
            module_count += 1

    for module_name, module_path, module_meta in enabled_module_data:
        env_file = os.path.join(module_path, ".env")
        if not os.path.exists(env_file):
            continue
        section_header = f"\n# ── {module_name} ──────────────────────────────────────────\n"
        section_lines: list[str] = []
        with open(env_file) as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                stripped = line.strip()
                # Blank lines and comment-only lines are always included
                if not stripped or stripped.startswith("#"):
                    section_lines.append(line)
                    continue
                # Extract key (handle inline comments and quoted values)
                key = stripped.split("=", 1)[0].strip()
                if key in merged:
                    # Key already defined by a previous module — skip but note it
                    section_lines.append(f"# [merged: {key} already defined above]")
                else:
                    merged[key] = line
                    section_lines.append(line)
        merged_lines.append(section_header)
        merged_lines.extend(section_lines)
        module_count += 1

    dst_env = os.path.join(DEPLOYMENT_ROOT_DIR, ".env")
    with open(dst_env, "w") as f:
        f.write("# AUTO-GENERATED — do not edit manually.\n")
        f.write("# This file is the merge of all enabled modules' .env files.\n")
        f.write("# Edit the source .env in each module folder and re-run build_and_deploy.py.\n")
        f.write("\n".join(merged_lines))
        f.write("\n")
    print(f"Generated merged deployment_root/.env ({len(merged)} variables from {module_count} module(s))")

    # Copy the merged .env into each deployed module folder so that
    # `env_file: - .env` in per-module compose files resolves correctly.
    if remote_hostapp:
        hostapp_deploy_env = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", ".env")
        shutil.copy2(dst_env, hostapp_deploy_env)
        print(f"  Copied merged .env → modules/HostApp/.env")
    
    for module_name, _, _ in enabled_module_data:
        dst_module_env = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", module_name, ".env")
        shutil.copy2(dst_env, dst_module_env)
        print(f"  Copied merged .env → modules/{module_name}/.env")


def generate_module_registry_json(enabled_module_data):
    """Build module-registry.json from enabled modules and write it to deployment_root/modules/HostApp/config/.

    Each non-HostApp module with a module.json contributes one entry:
      { "name": "<slug>", "entry": "/remotes/<slug>/mf-manifest.json",
        "displayName": "<displayName>", "basePath": "/<slug>" }

    The file is mounted into the frontend container as a volume (read-only),
    overriding the baked-in public/module-registry.json from the image.
    This works without rebuilding the HostApp frontend image.
    """
    modules = []
    for module_name, module_path, module_meta in enabled_module_data:
        if module_meta.get("role") == "host":
            continue
        slug = module_meta.get("slug", module_name.lower())
        display_name = module_meta.get("displayName", module_name)
        modules.append({
            "name": slug,
            "entry": f"/remotes/{slug}/mf-manifest.json",
            "displayName": display_name,
            "basePath": f"/{slug}",
        })

    dst_dir = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", "config")
    os.makedirs(dst_dir, exist_ok=True)
    dst_path = os.path.join(dst_dir, "module-registry.json")
    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump({"modules": modules}, f, indent=2)
    print(f"  [HostApp] Generated module-registry.json ({len(modules)} module(s)) → {dst_path}")


def _read_env_keys(env_path):
    """Return the set of variable names defined in an .env file."""
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
    """Parse a source compose file and return {service_name: set_of_explicit_env_keys}.

    Only includes keys declared directly in each service's `environment:` block.
    Keys promoted from `env_file:` are NOT included — those are the unwanted ones.
    """
    import re
    service_env_keys: dict[str, set] = {}
    if not os.path.exists(compose_path):
        return service_env_keys
    with open(compose_path, encoding="utf-8") as f:
        lines = f.readlines()

    current_service = None
    in_environment = False
    service_indent = None

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Detect service name: top-level key under `services:` (indent == 2)
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-") and not stripped.startswith("#"):
            candidate = stripped.rstrip().rstrip(":")
            # Avoid matching keys like `depends_on`, `healthcheck` etc at wrong level
            # We track by checking if we're under services — good enough for well-formed compose
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
            # List form:  - KEY=value  or  - KEY=${VAR}
            env_entry = stripped.lstrip("- ").strip()
            if "=" in env_entry:
                key = env_entry.split("=", 1)[0].strip()
                service_env_keys[current_service].add(key)
            # Map form:  KEY: value  or  KEY: ${VAR}
            elif ":" in env_entry:
                key = env_entry.split(":", 1)[0].strip()
                if key:
                    service_env_keys[current_service].add(key)

    return service_env_keys


def _deresolved_compose(yaml_text, env_keys, explicit_env_per_service=None):
    """Post-process `docker compose config` output.

    - Strips `env_file:` entries (they must not appear in the final merged compose).
    - For each service's environment block, keeps ONLY keys that were explicitly
      declared in the source compose (using explicit_env_per_service). Keys that
      came from env_file expansion are dropped.
    - Replaces resolved values with ${KEY} references for keys present in env_keys.
    - Removes empty `environment:` blocks entirely.

    explicit_env_per_service: dict {service_name: set_of_allowed_keys} built from
    source compose files. If None, all keys are kept (backwards-compatible).
    """
    lines = yaml_text.splitlines(keepends=True)
    output = []
    in_services = False
    in_environment = False
    current_service = None
    env_buffer = []  # Buffer environment entries, only output if non-empty
    env_header_line = None  # Store the "environment:" line

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Detect top-level `services:` section
        if line.rstrip() == "services:":
            in_services = True
            output.append(line)
            i += 1
            continue

        if in_services:
            # Service name: indent==2, ends with ':'
            if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
                # Flush any pending environment buffer before changing service
                if env_buffer and env_header_line:
                    output.append(env_header_line)
                    output.extend(env_buffer)
                in_environment = False
                env_buffer = []
                env_header_line = None
                current_service = stripped.rstrip().rstrip(":")
                output.append(line)
                i += 1
                continue

            # Skip env_file entries entirely
            if indent == 4 and stripped.startswith("env_file:"):
                # Flush any pending environment buffer before skipping
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

            # Detect `environment:` block start
            if indent == 4 and stripped.rstrip() == "environment:":
                in_environment = True
                env_header_line = line  # Buffer the header, don't output yet
                env_buffer = []
                i += 1
                continue

            # Leaving environment block
            if in_environment and indent <= 4 and not stripped.startswith("-") and ":" in stripped:
                key_part = stripped.split(":")[0].strip()
                if key_part and indent == 4:
                    # Flush environment buffer if we have entries
                    if env_buffer and env_header_line:
                        output.append(env_header_line)
                        output.extend(env_buffer)
                    in_environment = False
                    env_buffer = []
                    env_header_line = None

            # Inside environment block: filter to explicit keys only, then deresolve
            if in_environment and indent == 6 and ":" in stripped:
                colon_pos = stripped.index(":")
                key = stripped[:colon_pos].strip()
                # Drop keys not explicitly declared in the source compose
                if explicit_env_per_service is not None:
                    allowed = explicit_env_per_service.get(current_service, set())
                    if key not in allowed:
                        i += 1
                        continue
                # Replace resolved value with ${KEY} ref if key is in .env
                if key in env_keys:
                    line = " " * indent + f"{key}: ${{{key}}}\n"
                env_buffer.append(line)
                i += 1
                continue

            # If we're in environment block but this line doesn't match above,
            # we need to flush the buffer before outputting the line
            if in_environment and indent >= 4:
                if env_buffer and env_header_line:
                    output.append(env_header_line)
                    output.extend(env_buffer)
                in_environment = False
                env_buffer = []
                env_header_line = None

        output.append(line)
        i += 1

    # Flush any remaining environment buffer at end of file
    if env_buffer and env_header_line:
        output.append(env_header_line)
        output.extend(env_buffer)

    return "".join(output)


def generate_merged_compose(compose_files):
    """Generate deployment_root/docker-compose.yml from per-module compose files.

    Each service receives only the environment variables it explicitly declares
    in its source compose file — not the full env_file dump. Values for keys
    defined in the merged .env are replaced with ${KEY} references.
    """
    if not compose_files:
        print("No compose files deployed — skipped merged docker-compose.yml generation")
        return

    # Collect explicit environment keys per service from all deployed source composes.
    # compose_files are relative to DEPLOYMENT_ROOT_DIR, e.g. "modules/HostApp/docker-compose.yml"
    explicit_env_per_service: dict[str, set] = {}
    for rel_path in compose_files:
        src_path = os.path.join(DEPLOYMENT_ROOT_DIR, rel_path)
        svc_keys = _extract_explicit_env_keys(src_path)
        for svc, keys in svc_keys.items():
            if svc not in explicit_env_per_service:
                explicit_env_per_service[svc] = set()
            explicit_env_per_service[svc].update(keys)

    # Run with a clean environment (no inherited shell vars) so only the .env
    # files drive variable resolution.
    clean_env = {k: v for k, v in os.environ.items() if not any(
        k.startswith(p) for p in (
            "POSTGRES_", "APP_", "AUTHENTIK_", "VITE_", "BACKEND_", "FRONTEND_",
            "TEMPLATE_", "HOSTAPP_", "DATABASE_", "TIMESCALE", "NODE_", "CLIENT_",
            "TRAEFIK_", "TLS_", "LE_", "ACME_", "JWT_", "CORS_", "PUBLIC_",
            "INITIAL_", "EXTERNAL_", "MAIN_", "DATA_", "PROJECT_",
        )
    )}
    compose_cmd = ["docker", "compose", "--project-directory", DEPLOYMENT_ROOT_DIR]
    for compose_file in compose_files:
        compose_cmd.extend(["-f", compose_file])
    compose_cmd.append("config")

    result = subprocess.run(
        compose_cmd,
        cwd=DEPLOYMENT_ROOT_DIR,
        capture_output=True,
        text=True,
        env=clean_env,
    )
    if result.returncode != 0:
        print("ERROR: unable to generate merged docker-compose.yml")
        print("compose_cmd: " + " ".join(compose_cmd))
        print(result.stderr.strip())
        sys.exit(result.returncode)

    # Collect all variable names defined in the merged .env.
    merged_env_path = os.path.join(DEPLOYMENT_ROOT_DIR, ".env")
    env_keys = _read_env_keys(merged_env_path)

    # Post-process: keep only explicitly declared env keys per service,
    # replace resolved values with ${KEY} refs, strip env_file entries.
    output = _deresolved_compose(result.stdout, env_keys, explicit_env_per_service)

    merged_compose_path = os.path.join(DEPLOYMENT_ROOT_DIR, "docker-compose.yml")
    with open(merged_compose_path, "w", encoding="utf-8") as f:
        f.write("# AUTO-GENERATED — do not edit manually.\n")
        f.write("# Edit the source docker-compose.yml in each module and re-run build_and_deploy.py.\n")
        f.write(output)
    print("Generated merged docker-compose.yml")


def generate_module_registry(enabled_module_data):
    """Generate module-registry.json for enabled remote modules and copy to HostApp frontend."""
    registry_modules = []
    host_frontend_public_dir = ""

    for module_name, module_path, module_meta in enabled_module_data:
        module_slug = module_meta["slug"]
        module_role = module_meta["role"]
        module_display_name = module_meta["displayName"]

        if module_role == "remote":
            registry_modules.append(
                {
                    "name": module_slug,
                    "entry": f"/remotes/{module_slug}/mf-manifest.json",
                    "displayName": module_display_name,
                    "basePath": f"/{module_slug}",
                }
            )

        if module_role == "host" and not host_frontend_public_dir:
            host_frontend_public_dir = os.path.join(module_path, "frontend", "SOURCES", "public")

    registry_modules.sort(key=lambda item: item["name"])
    registry = {"modules": registry_modules}

    registry_output_path = os.path.join(DEPLOYMENT_ROOT_DIR, "module-registry.json")
    with open(registry_output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")
    print(f"Generated module-registry.json ({len(registry_modules)} module(s))")

    if host_frontend_public_dir:
        os.makedirs(host_frontend_public_dir, exist_ok=True)
        host_registry_path = os.path.join(host_frontend_public_dir, "module-registry.json")
        shutil.copy2(registry_output_path, host_registry_path)
        print(f"Updated HostApp frontend registry → {host_registry_path}")
    else:
        print("WARNING: no enabled host module found; skipped HostApp module-registry.json copy")


def generate_scripts(module_names, compose_files):
    """Generate start.sh, stop.sh and status.sh in deployment_root/."""
    modules_label = ", ".join(module_names)
    compose_flags = " ".join([f"-f {compose_file}" for compose_file in compose_files])
    # Use env -i to strip the inherited shell environment so that only the
    # .env files inside each module folder drive variable resolution.
    # PATH and HOME are preserved so docker is found and TLS certs work.
    compose_cmd = (
        f'env -i PATH="$PATH" HOME="$HOME" '
        f'docker compose --project-directory "$PWD" {compose_flags}'
    ).strip()

    start_script = os.path.join(DEPLOYMENT_ROOT_DIR, "start.sh")
    with open(start_script, "w") as f:
        f.write(f"""#!/bin/bash
# Auto-generated start script for: {modules_label}

set -e

# Ensure the shared external network exists
docker network inspect ideable_network >/dev/null 2>&1 || docker network create ideable_network

echo "Starting services ({modules_label})..."
{compose_cmd} up -d

echo ""
echo "Waiting for services to initialize..."
sleep 5

echo ""
echo "Services started. Current status:"
{compose_cmd} ps

echo ""
echo "Done! Services are running."
echo "View logs:     {compose_cmd} logs -f"
echo "Status:        ./status.sh"
echo "Stop services: ./stop.sh"
""")
    os.chmod(start_script, 0o755)
    print("Generated start.sh")

    stop_script = os.path.join(DEPLOYMENT_ROOT_DIR, "stop.sh")
    with open(stop_script, "w") as f:
        f.write(f"""#!/bin/bash
# Auto-generated stop script for: {modules_label}

set -e

echo "Stopping services ({modules_label})..."
{compose_cmd} down

echo ""
echo "Services stopped."
echo "To start again: ./start.sh"
""")
    os.chmod(stop_script, 0o755)
    print("Generated stop.sh")

    status_script = os.path.join(DEPLOYMENT_ROOT_DIR, "status.sh")
    with open(status_script, "w") as f:
        f.write(f"""#!/bin/bash
# Auto-generated status script for: {modules_label}

{compose_cmd} ps
""")
    os.chmod(status_script, 0o755)
    print("Generated status.sh")


def parse_args():
    parser = argparse.ArgumentParser(description="Build and deploy enabled modules")
    parser.add_argument(
        "--only-modules",
        dest="only_modules",
        default="",
        help="Comma-separated module names to build/deploy (e.g. HostApp,ModuleTemplate). Empty = all enabled modules.",
    )
    parser.add_argument(
        "--only-submodules",
        dest="only_submodules",
        default="",
        help="Comma-separated submodule names to build/deploy (e.g. frontend,backend). Empty = all.",
    )
    parser.add_argument(
        "--skip-module-root-deploy",
        action="store_true",
        help="Skip deploying module-root docker-compose.yml and .env to deployment_root/.",
    )
    parser.add_argument(
        "--skip-generate-scripts",
        action="store_true",
        help="Skip generating deployment_root/start.sh and deployment_root/stop.sh.",
    )
    return parser.parse_args()


def normalize_name_set(csv: str):
    return {p.strip().lower() for p in csv.split(",") if p.strip()} if csv else set()


if __name__ == "__main__":
    args = parse_args()

    only_modules = normalize_name_set(args.only_modules)
    only_submodules = normalize_name_set(args.only_submodules)

    enabled_module_tuples = read_enabled_modules()
    if not enabled_module_tuples:
        print("No enabled modules found in modules/enabled.md — nothing to do.")
        sys.exit(0)

    enabled_module_data = []
    remote_hostapp_compose = None
    for module_name, mode in enabled_module_tuples:
        if only_modules and module_name.lower() not in only_modules:
            continue
        
        # Handle remote modules (pre-built images, no local SOURCES/)
        if mode == 'remote':
            if module_name == 'HostApp':
                # Check for modules/HostApp/docker-compose.yml
                hostapp_compose_path = os.path.join(MODULES_DIR, "HostApp", "docker-compose.yml")
                if os.path.exists(hostapp_compose_path):
                    remote_hostapp_compose = hostapp_compose_path
                    print(f"[HostApp] Remote mode detected — will use pre-built images from {hostapp_compose_path}")
                else:
                    print(f"ERROR: HostApp marked as remote but {hostapp_compose_path} not found.")
                    print(f"  modules/HostApp/docker-compose.yml must be present in every repo (master and module repos).")
                    sys.exit(1)
            else:
                print(f"WARNING: Module {module_name} marked as remote but remote compose not defined — skipping")
            continue
        
        # Build mode - module must have local SOURCES/
        module_path = os.path.join(MODULES_DIR, module_name)
        if not os.path.isdir(module_path):
            print(f"WARNING: module folder not found: {module_path} — skipping")
            continue
        module_meta = read_module_metadata(module_name, module_path)
        enabled_module_data.append((module_name, module_path, module_meta))

    if not enabled_module_data and not remote_hostapp_compose:
        print("No enabled module folders found — nothing to do.")
        sys.exit(0)

    os.makedirs(DEPLOYMENT_ROOT_DIR, exist_ok=True)
    generate_module_registry(enabled_module_data)

    enabled_names = [name for name, _, _ in enabled_module_data]
    if remote_hostapp_compose:
        enabled_names.insert(0, 'HostApp (remote)')
    print(f"Enabled modules: {', '.join(enabled_names)}")

    # Generate traefik dynamic config (before image build if local, always for volume-mount path)
    generate_traefik_dynamic_template(enabled_module_data)

    # ── Build step ────────────────────────────────────────────────────────────
    print("\n── Build Process ────────────────────────────────────────────────────")
    # Environment variables to clear between modules to prevent cross-contamination
    env_vars_to_clear = ['APP_SLUG', 'APP_NAME', 'POSTGRES_DB', 'POSTGRES_USER',
                         'POSTGRES_PASSWORD', 'POSTGRES_PORT', 'BACKEND_PORT',
                         'FRONTEND_PORT', 'FRONTEND_EXTERNAL_PORT', 'DATABASE_URL']
    for module_name, module_path, module_meta in enabled_module_data:
        print(f"\n[{module_name}] Discovering sub-modules...")
        # Clear previous module's env vars and load current module's .env
        for var in env_vars_to_clear:
            os.environ.pop(var, None)
        load_module_env(module_path)
        # Use APP_SLUG from env (as compose files do), not slug from module.json
        app_slug = os.environ.get('APP_SLUG')
        if not app_slug:
            print(f"ERROR: APP_SLUG not set in {module_path}/.env")
            sys.exit(1)
        submodules = discover_submodules(module_path)
        if only_submodules:
            submodules = [s for s in submodules if s.lower() in only_submodules]
        if not submodules:
            print(f"[{module_name}] No sub-modules with SOURCES/ found — skipping")
            continue
        print(f"[{module_name}] Sub-modules to build: {', '.join(submodules)}")
        for submodule_name in submodules:
            submodule_path = os.path.join(module_path, submodule_name)
            custom_script = specs_build_script(submodule_path)
            print(f"  DEBUG: submodule_path={submodule_path}, custom_script={custom_script}")
            if custom_script:
                print(f"  [{submodule_name}] Running SPECS/build.sh: {custom_script}")
                run(["bash", custom_script])
            else:
                print(f"  [{submodule_name}] No SPECS/build.sh found, using generic build")
                build_submodule(module_name, submodule_name, submodule_path, app_slug)

    # ── Deploy step ───────────────────────────────────────────────────────────
    print("\n── Deploy Process ───────────────────────────────────────────────────")
    deployed_compose_files = []
    
    # Deploy remote HostApp first if present
    if remote_hostapp_compose:
        print("\n[HostApp] Deploying remote HostApp compose...")
        hostapp_module_dir = os.path.join(MODULES_DIR, "HostApp")
        hostapp_deploy_dir = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp")
        os.makedirs(hostapp_deploy_dir, exist_ok=True)

        # Read and rewrite paths (same logic as deploy_module_root) so that
        # relative bind mounts like ./database/ resolve correctly under
        # deployment_root/modules/HostApp/ instead of deployment_root/ root.
        with open(remote_hostapp_compose, "r") as f:
            hostapp_content = f.read()
        module_prefix = "./modules/HostApp/"
        hostapp_content = re.sub(
            r'(^|\n)(\s*-\s+)(\.\/[^\s:"\']+)(:[^\n]*)',
            lambda m: f"{m.group(1)}{m.group(2)}{module_prefix}{m.group(3).lstrip('./')}{m.group(4)}",
            hostapp_content
        )
        hostapp_content = re.sub(
            r'(source:\s+)(\.\/[^\s\n]+)',
            lambda m: f"{m.group(1)}{module_prefix}{m.group(2).lstrip('./')}",
            hostapp_content
        )
        dst_hostapp_compose = os.path.join(hostapp_deploy_dir, "docker-compose.yml")
        with open(dst_hostapp_compose, "w") as f:
            f.write(hostapp_content)
        deployed_compose_files.append("modules/HostApp/docker-compose.yml")
        print(f"  [HostApp] Deployed modules/HostApp/docker-compose.yml (paths made deployment-relative)")

        config_src = os.path.join(hostapp_module_dir, "config")
        if os.path.isdir(config_src):
            config_dst = os.path.join(hostapp_deploy_dir, "config")
            if os.path.exists(config_dst):
                shutil.rmtree(config_dst)
            shutil.copytree(config_src, config_dst)
            print(f"  [HostApp] Deployed config/ → {config_dst}")

        # Deploy HostApp sub-module DIST/ folders (database, authentik, traefik, etc.)
        # These are needed by the HostApp compose bind mounts at runtime.
        for entry in sorted(os.listdir(hostapp_module_dir)):
            submodule_path = os.path.join(hostapp_module_dir, entry)
            dist_path = os.path.join(submodule_path, "DIST")
            if os.path.isdir(submodule_path) and os.path.isdir(dist_path) and os.listdir(dist_path):
                deploy_submodule("HostApp", entry, submodule_path)

    for module_name, module_path, module_meta in enabled_module_data:
        print(f"\n[{module_name}] Deploying sub-modules...")
        submodules = discover_submodules(module_path)
        if only_submodules:
            submodules = [s for s in submodules if s.lower() in only_submodules]
        for submodule_name in submodules:
            submodule_path = os.path.join(module_path, submodule_name)
            deploy_submodule(module_name, submodule_name, submodule_path)
        if not args.skip_module_root_deploy:
            deployed_compose = deploy_module_root(module_name, module_path, module_meta)
            if deployed_compose:
                deployed_compose_files.append(deployed_compose)

    # Generate HostApp config files from enabled modules
    if not args.skip_module_root_deploy:
        generate_modules_menu_mapping(enabled_module_data)
        generate_module_registry_json(enabled_module_data)

    # Merge all module .env files into a single deployment_root/.env
    if not args.skip_module_root_deploy:
        merge_env_files(enabled_module_data, remote_hostapp=bool(remote_hostapp_compose))

    if deployed_compose_files:
        generate_merged_compose(deployed_compose_files)

    if not args.skip_generate_scripts:
        generate_scripts([name for name, _, _ in enabled_module_data], deployed_compose_files)

    print("\n── Build and Deployment Complete ────────────────────────────────────")
    print("Run './deployment_root/start.sh' to start containers.")
    print("Run './deployment_root/stop.sh' to stop containers.")
