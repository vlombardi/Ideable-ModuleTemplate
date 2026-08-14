from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[4]


# The framework generates env at build time from the root project.env.config /
# project.env.secrets, and at deploy time merges them (with each enabled module's
# .env.config / .env.secrets) into deployment_root/.env.config / .env.secrets. There
# is no single `.env` file — resolve keys from those canonical files (APP_SLUG is a
# project-level var, defined in project.env.config / deployment_root/.env.config).
def _read_env(key: str) -> str:
    env_candidates = [
        PROJECT_ROOT / "deployment_root" / ".env.config",
        PROJECT_ROOT / "deployment_root" / ".env.secrets",
        PROJECT_ROOT / "project.env.config",
        PROJECT_ROOT / "project.env.secrets",
        MODULE_ROOT / ".env.config",
        MODULE_ROOT / ".env.secrets",
    ]
    for env_path in env_candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    raise KeyError(f"{key} not found in project/deployment/module env config files")


def _get_slug() -> str:
    return _read_env("APP_SLUG")


def test_compose_uses_dedicated_bootstrap_for_dual_db_one_time_sql() -> None:
    # Container names are ${APP_SLUG}.${MODULE_SLUG}.<role> (the bootstrap container is
    # ".bootstrap"); the module's DB env vars and one-time script_keys are prefixed by
    # MODULE_SLUG (e.g. TEMPLATE_ENTITIES_DB_* / template_datamodel_v1).
    module_slug = _read_env("MODULE_SLUG")
    MSLUG = module_slug.upper()
    compose_path = MODULE_ROOT / "docker-compose.yml"
    assert compose_path.exists(), f"docker-compose.yml not found at {compose_path}"
    content = compose_path.read_text(encoding="utf-8")

    assert 'container_name: ${APP_SLUG}.${MODULE_SLUG}.bootstrap' in content, \
        "docker-compose.yml must define a project-prefixed bootstrap container"
    assert f'pg_isready -h "${{{MSLUG}_ENTITIES_DB_HOST}}"' in content, \
        "bootstrap must wait for the entities DB using pg_isready"

    assert "./database/initdb/datamodel.sql:/module/datamodel.sql:ro" in content, \
        "datamodel.sql must be mounted into bootstrap container"
    assert "./config/authorization.yaml:/module/authorization.yaml:ro" in content, \
        "authorization.yaml must be mounted from the module-level config folder"
    assert "./database/initdb/seed.sql:/module/seed.sql:ro" in content, \
        "seed.sql must be mounted into bootstrap container"

    assert f"{module_slug}_datamodel_v1" in content, \
        "bootstrap must use a versioned, module-scoped script_key for datamodel execution tracking"
    assert "/docker-entrypoint-initdb.d/datamodel.sql" not in content, \
        "datamodel.sql must not use docker-entrypoint-initdb.d (not idempotent)"

    assert 'container_name: ${APP_SLUG}.${MODULE_SLUG}.backend' in content
    assert 'container_name: ${APP_SLUG}.${MODULE_SLUG}.bootstrap' in content
    assert "./config/menu_definition.json:/usr/share/nginx/html/menu_definition.json:ro" in content
