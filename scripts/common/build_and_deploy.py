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


def read_env_file(env_path, *, overwrite=True):
    """Read simple KEY=VALUE pairs from an env file into os.environ."""
    if not env_path or not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if overwrite or key not in os.environ:
                os.environ[key] = value


def find_project_env_path():
    """Return the repo-root project-wide env file."""
    candidates = [os.path.join(PROJECT_ROOT, "project.env")]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return ""


def load_project_context():
    """Load project-wide env vars before module envs are processed."""
    project_env_path = find_project_env_path()
    if not project_env_path:
        print("ERROR: no project env found (expected repo-root project.env)")
        sys.exit(1)
    for key in ("APP_SLUG", "APP_NAME", "COMPOSE_PROJECT_NAME"):
        os.environ.pop(key, None)
    read_env_file(project_env_path, overwrite=True)
    if not os.getenv("APP_SLUG"):
        print(f"ERROR: APP_SLUG must be set in {project_env_path}")
        sys.exit(1)
    os.environ.setdefault("COMPOSE_PROJECT_NAME", os.getenv("APP_SLUG"))
    return project_env_path


def build_compose_clean_env(env):
    """Return the environment used while resolving the merged compose file.

    Module-local identity variables are intentionally stripped so a later-loaded
    module cannot leak its slug/name into the merged docker compose config.
    """
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


def run(cmd, cwd=None, failure_context=None, failure_advice=None):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT)
    if result.returncode != 0:
        print(f"ERROR: command failed with exit code {result.returncode}")
        if failure_context:
            print(f"ERROR: {failure_context}")
        if failure_advice:
            print(f"ACTION: {failure_advice}")
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

    HostApp uses pattern:        hostapp-{service}:latest
    All other modules use:       <module.json slug>/{service}:latest

    Remote modules derive their image namespace from module.json slug, not from
    the project-wide APP_SLUG, to allow independent module distribution.
    """
    module_lower = module_name.lower()
    submodule_lower = submodule_name.lower()

    # HostApp uses unprefixed 'hostapp-' image names
    if module_lower == "hostapp":
        return f"hostapp-{submodule_lower}:latest"
    # All other modules (ModuleTemplate-derived): {module_slug}/{service}:latest
    else:
        module_slug_value = module_slug or get_app_slug()
        return f"{module_slug_value}/{submodule_lower}:latest"


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


def build_submodule(module_name, submodule_name, submodule_path, module_slug=None, compose_image=None, project_slug=None):
    """Build a single sub-module: Docker image and/or file artifacts."""
    has_dockerfile, has_file_artifacts = classify_submodule(submodule_path)
    sources_path = os.path.join(submodule_path, "SOURCES")

    if not has_dockerfile and not has_file_artifacts:
        print(f"  [{submodule_name}] SOURCES/ is empty — skipping")
        return

    if has_dockerfile:
        img = compose_image or image_name(module_name, submodule_name, module_slug)
        if "${" in img:
            project_slug = project_slug or get_app_slug()
            resolved_module_slug = module_slug or module_name.lower()
            img = (
                img.replace("${APP_SLUG}", project_slug)
                   .replace("${MODULE_SLUG}", resolved_module_slug)
            )
        if compose_image:
            print(f"  [{submodule_name}] Building Docker image from compose override: {img}")
        else:
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

        build_cmd.append(sources_path)
        run(
            build_cmd,
            failure_context=(
                f"[{module_name}/{submodule_name}] Docker image build failed for {img}"
            ),
            failure_advice=(
                "Fix the build error above and rerun the deployment. "
                "The deploy has been aborted; do not continue with a partial build."
            ),
        )

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
    """Copy a sub-module's DIST/ (and config/ if present) to deployment_root/."""
    dist_path = os.path.join(submodule_path, "DIST")
    if not os.path.exists(dist_path) or not os.listdir(dist_path):
        print(f"  [{submodule_name}] No DIST/ to deploy — skipping")
        return
    dst = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", module_name, submodule_name)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(dist_path, dst)
    print(f"  [{submodule_name}] Deployed DIST/ → {dst}")
    config_src = os.path.join(submodule_path, "config")
    if os.path.isdir(config_src):
        config_dst = os.path.join(dst, "config")
        shutil.copytree(config_src, config_dst, dirs_exist_ok=True)
        print(f"  [{submodule_name}] Merged config/ → {config_dst}")


def _rewrite_build_context_path(relative_path: str, module_prefix: str) -> str:
    """Rewrite a compose build.context path to deployment_root-relative form.

    The source compose files are authored from the module directory, but the
    generated deployment_root compose is executed with deployment_root as the
    project directory. For module-local build contexts that target a DIST/
    folder, the deployed compose should point at the flattened copied directory
    instead of the source artifact folder.
    """
    path = relative_path.strip()
    if not path.startswith("./"):
        return path

    rewritten = f"{module_prefix}{path.lstrip('./')}"
    if rewritten.endswith("/DIST"):
        rewritten = rewritten[:-len("/DIST")]
    return rewritten


def deploy_module_root(module_name, module_path, module_meta, project_slug=None):
    """Copy module compose file to deployment_root/modules/<MODULE>/docker-compose.yml.
    
    Converts relative bind mount paths (e.g., ./database/, ./authentik/) from the
    module's perspective to be relative to deployment_root (e.g., ./modules/<MODULE>/database/).
    It also resolves ${MODULE_SLUG} to the concrete module slug so container names
    stay unique after all module env files are merged into deployment_root/.env.
    
    The .env files are NOT copied here — they are merged into a single
    deployment_root/.env by merge_env_files() after all modules are processed.
    """
    import re
    
    dst_root = DEPLOYMENT_ROOT_DIR
    module_slug = module_meta["slug"]
    project_slug = project_slug or os.getenv("APP_SLUG") or os.getenv("COMPOSE_PROJECT_NAME") or ""
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

        # Resolve module-local slug placeholders before the compose files are merged.
        # This keeps runtime container names unique even though deployment_root/.env
        # is shared across all enabled modules.
        content = content.replace("${MODULE_SLUG}", module_slug)

        # Normalize legacy container names to the project-prefixed dotted format.
        # Example:
        #   sra-backend -> secriskass.sra.backend
        #   secriskass-sra-backend -> secriskass.sra.backend
        # Already-correct names like secriskass.sra.backend are preserved.
        if module_name != "HostApp" and project_slug:
            container_name_pattern = re.compile(r'^(\s*container_name:\s*)([^\s#]+)(\s*)$', re.MULTILINE)

            def _normalize_container_name(match):
                prefix = match.group(1)
                name = match.group(2)
                suffix_ws = match.group(3)
                desired_prefix = f"{project_slug}.{module_slug}."
                resolved_name = name.replace("${APP_SLUG}", project_slug).replace("${MODULE_SLUG}", module_slug)
                if resolved_name.startswith(desired_prefix):
                    return f"{prefix}{resolved_name}{suffix_ws}"

                if name.startswith(desired_prefix):
                    return match.group(0)

                suffix = resolved_name
                suffix = re.sub(rf'^{re.escape(project_slug)}[.-]', '', suffix)
                suffix = re.sub(rf'^{re.escape(module_slug)}[.-]', '', suffix)
                suffix = suffix.lstrip('.-')
                if not suffix:
                    return match.group(0)
                return f"{prefix}{desired_prefix}{suffix}{suffix_ws}"

            content = container_name_pattern.sub(_normalize_container_name, content)

        # Match volume entries: - ./path:/container/path (short syntax)
        # Also matches - .:target
        content = re.sub(
            r'(^|\n)(\s*-\s+)(\.(?:\/[^\s:"\']*)?)(:[^\n]*)',
            lambda m: f"{m.group(1)}{m.group(2)}{module_prefix}{m.group(3).lstrip('./')}{m.group(4)}",
            content
        )

        # Match source: entries (long syntax)
        content = re.sub(
            r'(source:\s+)(\.\/[^\s\n]+)',
            lambda m: f"{m.group(1)}{module_prefix}{m.group(2).lstrip('./')}",
            content
        )

        # Match build.context entries (long syntax)
        content = re.sub(
            r'(^|\n)(\s*context:\s+)(\.\/[^\s\n]+)(\s*$)',
            lambda m: f"{m.group(1)}{m.group(2)}{_rewrite_build_context_path(m.group(3), module_prefix)}{m.group(4)}",
            content,
            flags=re.MULTILINE,
        )

        # Ensure networks are NOT marked as external so Docker Compose creates them automatically.
        # Replace "external: true" with "driver: bridge" for known networks, preserving indentation.
        content = re.sub(
            r'^(\s+)(ideable_network:.*)\n(\s+)external:\s*true\s*$',
            r'\1\2\n\3driver: bridge',
            content,
            flags=re.MULTILINE
        )
        content = re.sub(
            r'^(\s+)(timescale_network:.*)\n(\s+)external:\s*true\s*$',
            r'\1\2\n\3driver: bridge',
            content,
            flags=re.MULTILINE
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

    auth_spec_src = os.path.join(module_path, "config", "authorization.yaml")
    if os.path.isfile(auth_spec_src):
        dst_module_dir = os.path.join(dst_root, "modules", module_name)
        config_dst = os.path.join(dst_module_dir, "config")
        os.makedirs(config_dst, exist_ok=True)
        auth_spec_dst = os.path.join(config_dst, "authorization.yaml")
        if not os.path.isfile(auth_spec_dst):
            shutil.copy2(auth_spec_src, auth_spec_dst)
            print(f"  [{module_name}] Deployed authorization.yaml → {auth_spec_dst}")

    module_json_src = os.path.join(module_path, "module.json")
    if os.path.isfile(module_json_src):
        dst_module_dir = os.path.join(dst_root, "modules", module_name)
        os.makedirs(dst_module_dir, exist_ok=True)
        module_json_dst = os.path.join(dst_module_dir, "module.json")
        shutil.copy2(module_json_src, module_json_dst)
        print(f"  [{module_name}] Deployed module.json → {module_json_dst}")

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


def generate_modules_menu_mapping():
    """Copy HostApp's canonical modules_menu_mapping.json into deployed runtime locations.

    The HostApp config file under modules/HostApp/config/ is the single source of truth.
    This helper mirrors that file into deployment_root/modules/HostApp/config/ and into
    the frontend source config directory so runtime mounts and any build-time fallbacks
    stay aligned without regenerating the mapping from enabled modules.
    """
    source_path = os.path.join(MODULES_DIR, "HostApp", "config", "modules_menu_mapping.json")
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"HostApp menu mapping not found: {source_path}")

    with open(source_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    dst_dir = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", "config")
    os.makedirs(dst_dir, exist_ok=True)
    dst_path = os.path.join(dst_dir, "modules_menu_mapping.json")
    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    src_config_dir = os.path.join(MODULES_DIR, "HostApp", "frontend", "SOURCES", "src", "config")
    if os.path.isdir(src_config_dir):
        src_config_path = os.path.join(src_config_dir, "modules_menu_mapping.json")
        with open(src_config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print("  [HostApp] Mirrored modules_menu_mapping.json from modules/HostApp/config → src/config and deployment_root")
    else:
        print("  [HostApp] Mirrored modules_menu_mapping.json from modules/HostApp/config → deployment_root")


def merge_env_files(enabled_module_data, remote_hostapp=False, project_env_path=""):
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

    hostapp_env = os.path.join(MODULES_DIR, "HostApp", ".env")
    hostapp_module_entry = next((item for item in enabled_module_data if item[0] == "HostApp"), None)

    def _append_env_section(env_path: str, section_title: str) -> None:
        nonlocal module_count
        if not os.path.exists(env_path):
            return
        section_header = f"\n# ── {section_title} ──────────────────────────────────────────\n"
        section_lines: list[str] = []
        with open(env_path) as f:
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
                    # Key already defined by a previous section — skip but note it
                    section_lines.append(f"# [merged: {key} already defined above]")
                else:
                    merged[key] = line
                    section_lines.append(line)
        merged_lines.append(section_header)
        merged_lines.extend(section_lines)
        module_count += 1

    # Process project-wide env first if present and distinct from HostApp .env.
    if project_env_path and os.path.exists(project_env_path):
        print(f"  [env] Merging project env from {project_env_path}")
        if os.path.abspath(project_env_path) != os.path.abspath(hostapp_env):
            section_header = "\n# ── Project ───────────────────────────────────────────\n"
            section_lines: list[str] = []
            with open(project_env_path) as f:
                for raw_line in f:
                    line = raw_line.rstrip("\n")
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        section_lines.append(line)
                        continue
                    key = stripped.split("=", 1)[0].strip()
                    if key in merged:
                        section_lines.append(f"# [merged: {key} already defined above]")
                    else:
                        merged[key] = line
                        section_lines.append(line)
            merged_lines.append(section_header)
            merged_lines.extend(section_lines)
            module_count += 1

    # Process HostApp .env first so the top-level deployment_root/.env always
    # resolves HostApp compose placeholders with the host module identity.
    # Remote modules have their MODULE_SLUG placeholders resolved earlier when
    # their module compose files are copied into deployment_root/modules/.
    if remote_hostapp or hostapp_module_entry:
        _append_env_section(hostapp_env, "HostApp")

    # Then process all remaining modules in enabled order.
    for module_name, module_path, module_meta in enabled_module_data:
        if module_name == "HostApp":
            continue
        env_file = os.path.join(module_path, ".env")
        if not os.path.exists(env_file):
            continue
        _append_env_section(env_file, module_name)

    dst_env = os.path.join(DEPLOYMENT_ROOT_DIR, ".env")
    with open(dst_env, "w") as f:
        f.write("# AUTO-GENERATED — do not edit manually.\n")
        f.write("# This file is the merge of all enabled modules' .env files.\n")
        f.write("# Edit the source .env in each module folder and re-run build_and_deploy.py.\n")
        f.write("\n".join(merged_lines))
        f.write("\n")
    print(f"Generated merged deployment_root/.env ({len(merged)} variables from {module_count} module(s))")

    # Copy project + module env into each deployed module folder so that
    # `env_file: - .env` in per-module compose files resolves correctly without
    # losing module-specific identity values (APP_SLUG, MODULE_* vars, etc.).
    def _write_env_concat(dst_path: str, src_paths: list[str], label: str) -> None:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        unique_src_paths = []
        seen_paths = set()
        for src_path in src_paths:
            if not src_path:
                continue
            abs_src = os.path.abspath(src_path)
            if abs_src in seen_paths:
                continue
            seen_paths.add(abs_src)
            unique_src_paths.append(src_path)
        project_keys = {"APP_SLUG", "APP_NAME", "COMPOSE_PROJECT_NAME"}
        with open(dst_path, "w", encoding="utf-8") as out:
            out.write("# AUTO-GENERATED — do not edit manually.\n")
            out.write(f"# {label}\n")
            for idx, src_path in enumerate(unique_src_paths):
                if not os.path.exists(src_path):
                    continue
                with open(src_path, encoding="utf-8") as src:
                    text = src.read()
                    if idx == 0:
                        out.write(text)
                        if text and not text.endswith("\n"):
                            out.write("\n")
                        continue
                    for raw_line in text.splitlines():
                        line = raw_line.rstrip("\n")
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#") or "=" not in stripped:
                            out.write(line + "\n")
                            continue
                        key = stripped.split("=", 1)[0].strip()
                        if key in project_keys:
                            continue
                        out.write(line + "\n")

    project_env_sources = [project_env_path] if project_env_path else []
    if remote_hostapp:
        hostapp_deploy_env = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", ".env")
        _write_env_concat(hostapp_deploy_env, project_env_sources + [os.path.join(MODULES_DIR, "HostApp", ".env")], "HostApp deployed env")
        print(f"  Wrote deployed env → modules/HostApp/.env")
    
    for module_name, module_path, _ in enabled_module_data:
        dst_module_env = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", module_name, ".env")
        _write_env_concat(dst_module_env, project_env_sources + [os.path.join(module_path, ".env")], f"{module_name} deployed env")
        print(f"  Wrote deployed env → modules/{module_name}/.env")

    if "COMPOSE_PROJECT_NAME" not in merged:
        compose_project_name = os.getenv("COMPOSE_PROJECT_NAME") or os.getenv("APP_SLUG")
        if compose_project_name:
            with open(dst_env, "a", encoding="utf-8") as f:
                f.write("COMPOSE_PROJECT_NAME=" + compose_project_name + "\n")
            if remote_hostapp:
                hostapp_deploy_env = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", ".env")
                with open(hostapp_deploy_env, "a", encoding="utf-8") as f:
                    f.write("COMPOSE_PROJECT_NAME=" + compose_project_name + "\n")
            for module_name, _, _ in enabled_module_data:
                dst_module_env = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", module_name, ".env")
                with open(dst_module_env, "a", encoding="utf-8") as f:
                    f.write("COMPOSE_PROJECT_NAME=" + compose_project_name + "\n")


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
        if module_meta.get("role") != "remote":
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


def _extract_environment_lines(yaml_text):
    """Return raw environment list/map lines per service from compose output.

    The returned mapping preserves the exact rendered env lines so a later
    post-process step can restore any explicit keys that were dropped while
    filtering the merged compose output.
    """
    service_env_lines: dict[str, list[tuple[str, str]]] = {}
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
    """Map service names to the comment blocks that precede them."""
    headings: dict[str, str] = {}
    if not os.path.exists(compose_path):
        return headings

    with open(compose_path, encoding="utf-8") as f:
        lines = f.readlines()

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
            service_name = stripped.rstrip().rstrip(":")
            block: list[str] = []
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


def _extract_service_images(compose_path):
    """Return {service_name: image_tag} for services declaring an image."""
    images: dict[str, str] = {}
    if not os.path.exists(compose_path):
        return images

    with open(compose_path, encoding="utf-8") as f:
        lines = f.readlines()

    in_services = False
    current_service = None

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if stripped.rstrip() == "services:" and indent == 0:
            in_services = True
            continue

        if not in_services:
            continue

        if indent == 2 and stripped.rstrip().endswith(":") and not stripped.startswith("-"):
            current_service = stripped.rstrip().rstrip(":")
            continue

        if current_service is None:
            continue

        if indent == 4 and stripped.startswith("image:"):
            image_value = stripped.split(":", 1)[1].strip()
            if image_value:
                images[current_service] = image_value
            continue

        # Leaving services section once indentation drops back to zero and line ends with ':'
        if indent == 0 and stripped.rstrip().endswith(":") and stripped.rstrip() != "services:":
            in_services = False
            current_service = None

    return images


def _resolve_compose_image_for_submodule(module_name, module_slug, submodule_name, service_images):
    """Return compose-declared image for submodule, or None if not found."""
    if not service_images:
        return None

    sub_lower = submodule_name.lower()
    slug_lower = (module_slug or "").lower()
    module_lower = (module_name or "").lower()

    candidates = [sub_lower]
    if slug_lower:
        candidates.append(f"{slug_lower}-{sub_lower}")
        candidates.append(f"{slug_lower}_{sub_lower}")
    if module_lower and module_lower != slug_lower:
        candidates.append(f"{module_lower}-{sub_lower}")
        candidates.append(f"{module_lower}_{sub_lower}")

    lower_map = {svc.lower(): image for svc, image in service_images.items()}
    for candidate in candidates:
        if candidate in lower_map:
            return lower_map[candidate]

    for svc, image in service_images.items():
        svc_lower = svc.lower()
        if svc_lower.endswith(f"-{sub_lower}") or svc_lower.endswith(f"_{sub_lower}"):
            return image

    return None


def _deresolved_compose(yaml_text, env_keys, explicit_env_per_service=None, service_headings=None):
    """Post-process `docker compose config` output.

    - Strips `env_file:` entries (they must not appear in the final merged compose).
    - For each service's environment block, keeps ONLY keys that were explicitly
      declared in the source compose (using explicit_env_per_service). Keys that
      came from env_file expansion are dropped.
    - Replaces resolved values with ${KEY} references for keys present in env_keys.
    - Removes empty `environment:` blocks entirely.

    explicit_env_per_service: dict {service_name: set_of_allowed_keys} built from
    source compose files. If None, all keys are kept (backwards-compatible).
    service_headings: dict {service_name: str_comment_block} added before each service.
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


def _restore_missing_environment_entries(yaml_text, raw_env_lines_per_service, explicit_env_per_service=None):
    """Restore explicit env entries that disappeared during compose filtering."""
    if not yaml_text:
        return yaml_text

    lines = yaml_text.splitlines(keepends=True)
    output = []
    current_service = None
    in_environment = False
    env_buffer = []
    env_keys_present: set[str] = set()

    def _flush_env_block():
        nonlocal env_buffer, env_keys_present
        if not env_buffer:
            return
        missing_lines: list[str] = []
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
        env_buffer = []

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


def _relativize_deployment_root_paths(yaml_text, deployment_root=DEPLOYMENT_ROOT_DIR):
    """Rewrite absolute deployment-root paths to use relative references.

    docker compose config expands bind mounts and similar file paths into absolute
    paths. We convert any absolute path rooted under deployment_root back to
    ./relative/path form so the generated file is portable and avoids mount
    permission issues on macOS.
    """
    if not yaml_text:
        return yaml_text

    abs_root = os.path.abspath(deployment_root)
    # Ensure prefix ends with a separator to avoid partial matches
    root_prefix = abs_root.rstrip(os.sep) + os.sep

    def _to_relative(abs_path: str) -> str:
        normalized = os.path.abspath(abs_path)
        if normalized == abs_root:
            return "."
        try:
            rel_path = os.path.relpath(normalized, abs_root).replace(os.sep, "/")
            if rel_path.startswith(".."):
                # Path is outside deployment_root, keep absolute or use PROJECT_ROOT if available
                return normalized
            return f"./{rel_path}"
        except ValueError:
            return normalized

    # Find absolute paths that start with our root
    path_pattern = re.compile(rf"{re.escape(root_prefix)}[^\s,\"']*")

    def _replace(match):
        return _to_relative(match.group(0))

    return path_pattern.sub(_replace, yaml_text)


def _ensure_environment_headers(yaml_text, explicit_env_per_service=None):
    """Restore missing `environment:` headers before env list entries.

    Some merged compose outputs can retain the env list items but drop the
    surrounding `environment:` key, which makes the YAML invalid. This pass
    uses the explicit env key registry to insert the missing header when the
    service has list-form env entries but no active environment block.
    """
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


def generate_merged_compose(compose_files, project_slug):
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
    service_headings: dict[str, str] = {}
    for rel_path in compose_files:
        src_path = os.path.join(DEPLOYMENT_ROOT_DIR, rel_path)
        svc_keys = _extract_explicit_env_keys(src_path)
        for svc, keys in svc_keys.items():
            if svc not in explicit_env_per_service:
                explicit_env_per_service[svc] = set()
            explicit_env_per_service[svc].update(keys)
        headings = _extract_service_headings(src_path)
        for svc, block in headings.items():
            service_headings.setdefault(svc, block)

    # Run with a clean environment (no inherited shell vars) so only the .env
    # files drive variable resolution.
    clean_env = build_compose_clean_env(os.environ)
    compose_cmd = ["docker", "compose", "--project-directory", DEPLOYMENT_ROOT_DIR]
    if project_slug:
        compose_cmd.extend(["--project-name", project_slug])
    for compose_file in compose_files:
        compose_cmd.extend(["-f", compose_file])
    compose_cmd.append("config")
    compose_cmd.append("--no-interpolate")

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
    raw_env_lines_per_service = _extract_environment_lines(result.stdout)

    # Post-process: keep only explicitly declared env keys per service,
    # replace resolved values with ${KEY} refs, strip env_file entries.
    output = _deresolved_compose(
        result.stdout,
        env_keys,
        explicit_env_per_service,
        service_headings,
    )
    output = _ensure_environment_headers(output, explicit_env_per_service)
    output = _restore_missing_environment_entries(output, raw_env_lines_per_service, explicit_env_per_service)
    output = _relativize_deployment_root_paths(output)

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


def copy_runtime_scripts():
    """Copy runtime helper scripts from scripts/runtime into deployment_root/."""
    runtime_dir = os.path.join(PROJECT_ROOT, "scripts", "runtime")
    if not os.path.isdir(runtime_dir):
        print(f"WARNING: runtime scripts folder not found: {runtime_dir}")
        return

    os.makedirs(DEPLOYMENT_ROOT_DIR, exist_ok=True)
    for script_name in ("generate_authentik_blueprint_from_authorization_files.sh", "start.sh", "stop.sh", "status.sh"):
        src = os.path.join(runtime_dir, script_name)
        if not os.path.isfile(src):
            print(f"WARNING: runtime script not found: {src}")
            continue
        dst = os.path.join(DEPLOYMENT_ROOT_DIR, script_name)
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755)
        print(f"Copied runtime script → {dst}")

    generator_src = os.path.join(
        PROJECT_ROOT,
        "modules",
        "HostApp",
        "authentik",
        "SOURCES",
        "generate_authentik_blueprint.py",
    )
    bootstrap_src = os.path.join(
        PROJECT_ROOT,
        "modules",
        "HostApp",
        "authentik",
        "SOURCES",
        "bootstrap_authentik.py",
    )
    generator_dst_dir = os.path.join(DEPLOYMENT_ROOT_DIR, "modules", "HostApp", "authentik")
    if os.path.isfile(generator_src) and os.path.isdir(generator_dst_dir):
        generator_dst = os.path.join(generator_dst_dir, "generate_authentik_blueprint.py")
        shutil.copy2(generator_src, generator_dst)
        print(f"Copied Authentik blueprint generator → {generator_dst}")
    if os.path.isfile(bootstrap_src) and os.path.isdir(generator_dst_dir):
        bootstrap_dst = os.path.join(generator_dst_dir, "bootstrap_authentik.py")
        shutil.copy2(bootstrap_src, bootstrap_dst)
        print(f"Copied Authentik bootstrap module → {bootstrap_dst}")


def run_authentik_blueprint_generation():
    """Generate the Authentik blueprint and readable log inside deployment_root."""
    script_path = os.path.join(DEPLOYMENT_ROOT_DIR, "generate_authentik_blueprint_from_authorization_files.sh")
    if not os.path.isfile(script_path):
        print(f"WARNING: blueprint generation script not found: {script_path}")
        return

    print("\n── Authentik Blueprint Generation ───────────────────────────────────")
    run(
        [script_path],
        cwd=DEPLOYMENT_ROOT_DIR,
        failure_context="[HostApp] Authentik blueprint generation failed",
        failure_advice=(
            "Fix the blueprint generation error and rerun the deployment. "
            "The deploy has been aborted; do not continue with a partial build."
        ),
    )


def run_module_validation(module_names=None):
    validator = os.path.join(PROJECT_ROOT, "scripts", "common", "validate_modules.sh")
    if not os.path.isfile(validator):
        print(f"ERROR: module validator not found: {validator}")
        sys.exit(1)

    cmd = ["bash", validator]
    if module_names:
        cmd.extend(module_names)

    print("\n── Module Validation ─────────────────────────────────────────────────")
    run(
        cmd,
        failure_context="module validation failed",
        failure_advice=(
            "Fix the validation errors above and rerun the deployment. "
            "The deploy has been aborted; do not continue with invalid module files."
        ),
    )


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
    return parser.parse_args()


def normalize_name_set(csv: str):
    return {p.strip().lower() for p in csv.split(",") if p.strip()} if csv else set()


if __name__ == "__main__":
    args = parse_args()

    project_env_path = load_project_context()
    project_slug = os.getenv("APP_SLUG")
    project_compose_name = os.getenv("COMPOSE_PROJECT_NAME") or project_slug

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
    env_vars_to_clear = ['APP_SLUG', 'APP_NAME', 'MODULE_SLUG', 'MODULE_NAME', 'COMPOSE_PROJECT_NAME', 'POSTGRES_DB', 'POSTGRES_USER',
                         'POSTGRES_PASSWORD', 'POSTGRES_PORT', 'BACKEND_PORT',
                         'FRONTEND_PORT', 'FRONTEND_EXTERNAL_PORT', 'DATABASE_URL']
    for module_name, module_path, module_meta in enabled_module_data:
        print(f"\n[{module_name}] Discovering sub-modules...")
        # Clear previous module's env vars and load current module's .env
        for var in env_vars_to_clear:
            os.environ.pop(var, None)
        load_module_env(module_path)
        # Use project.env for HostApp identity and module.json slug for all other modules.
        app_slug = project_slug if module_name == 'HostApp' else (module_meta.get("slug") or module_name.lower())
        if not app_slug:
            print(f"ERROR: module slug not set for {module_name}")
            sys.exit(1)
        submodules = discover_submodules(module_path)
        if only_submodules:
            submodules = [s for s in submodules if s.lower() in only_submodules]
        if not submodules:
            print(f"[{module_name}] No sub-modules with SOURCES/ found — skipping")
            continue
        print(f"[{module_name}] Sub-modules to build: {', '.join(submodules)}")

        compose_file = find_module_compose_file(module_name, module_path, module_meta.get("slug") or module_name.lower())
        compose_images = _extract_service_images(compose_file) if compose_file else {}
        module_slug_for_resolution = module_meta.get("slug") or module_name.lower()

        for submodule_name in submodules:
            submodule_path = os.path.join(module_path, submodule_name)
            custom_script = specs_build_script(submodule_path)
            print(f"  DEBUG: submodule_path={submodule_path}, custom_script={custom_script}")
            if custom_script:
                print(f"  [{submodule_name}] Running SPECS/build.sh: {custom_script}")
                run(
                    ["bash", custom_script],
                    failure_context=(
                        f"[{module_name}/{submodule_name}] SPECS/build.sh failed: {custom_script}"
                    ),
                    failure_advice=(
                        "Fix the script or its inputs and rerun the deployment. "
                        "The deploy has been aborted; do not continue with a partial build."
                    ),
                )
            else:
                print(f"  [{submodule_name}] No SPECS/build.sh found, using generic build")
                compose_image = _resolve_compose_image_for_submodule(
                    module_name,
                    module_slug_for_resolution,
                    submodule_name,
                    compose_images,
                )
                build_submodule(
                    module_name,
                    submodule_name,
                    submodule_path,
                    app_slug,
                    compose_image,
                    project_slug,
                )

    validation_module_names = [module_name for module_name, _ in enabled_module_tuples]
    if only_modules:
        validation_module_names = [name for name in validation_module_names if name.lower() in only_modules]
    run_module_validation(validation_module_names)

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
            r'(^|\n)(\s*-\s+)(\.(?:\/[^\s:"\']*)?)(:[^\n]*)',
            lambda m: f"{m.group(1)}{m.group(2)}{module_prefix}{m.group(3).lstrip('./')}{m.group(4)}",
            hostapp_content
        )
        hostapp_content = re.sub(
            r'(source:\s+)(\.\/[^\s\n]+)',
            lambda m: f"{m.group(1)}{module_prefix}{m.group(2).lstrip('./')}",
            hostapp_content
        )
        # Ensure networks are NOT marked as external so Docker Compose creates them automatically
        hostapp_content = re.sub(
            r'^(\s+)(ideable_network:.*)\n(\s+)external:\s*true\s*$',
            r'\1\2\n\3driver: bridge',
            hostapp_content,
            flags=re.MULTILINE
        )
        hostapp_content = re.sub(
            r'^(\s+)(timescale_network:.*)\n(\s+)external:\s*true\s*$',
            r'\1\2\n\3driver: bridge',
            hostapp_content,
            flags=re.MULTILINE
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

        hostapp_module_json = os.path.join(hostapp_module_dir, "module.json")
        if os.path.isfile(hostapp_module_json):
            hostapp_module_json_dst = os.path.join(hostapp_deploy_dir, "module.json")
            shutil.copy2(hostapp_module_json, hostapp_module_json_dst)
            print(f"  [HostApp] Deployed module.json → {hostapp_module_json_dst}")

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
            deployed_compose = deploy_module_root(module_name, module_path, module_meta, project_slug)
            if deployed_compose:
                deployed_compose_files.append(deployed_compose)

    # Sync HostApp config files from their canonical source in modules/HostApp/config
    if not args.skip_module_root_deploy:
        generate_modules_menu_mapping()
        generate_module_registry_json(enabled_module_data)

    # Merge all module .env files into a single deployment_root/.env
    if not args.skip_module_root_deploy:
        merge_env_files(
            enabled_module_data,
            remote_hostapp=bool(remote_hostapp_compose),
            project_env_path=project_env_path,
        )

    if deployed_compose_files:
        generate_merged_compose(deployed_compose_files, project_compose_name)

    copy_runtime_scripts()
    run_authentik_blueprint_generation()

    print("\n── Build and Deployment Complete ────────────────────────────────────")
    print("Run './deployment_root/start.sh' to start containers.")
    print("Run './deployment_root/stop.sh' to stop containers.")
