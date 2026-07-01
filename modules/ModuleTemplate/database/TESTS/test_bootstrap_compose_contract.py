from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]


def _read_env(key: str) -> str:
    env_path = MODULE_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise KeyError(f"{key} not found in .env")


def _get_slug() -> str:
    return _read_env("APP_SLUG")


def test_compose_uses_dedicated_bootstrap_for_dual_db_one_time_sql() -> None:
    slug = _read_env("APP_SLUG")
    SLUG = slug.upper()
    compose_path = MODULE_ROOT / "docker-compose.yml"
    assert compose_path.exists(), f"docker-compose.yml not found at {compose_path}"
    content = compose_path.read_text(encoding="utf-8")

    assert f'container_name: ${{APP_SLUG}}.${{MODULE_SLUG}}.template-bootstrap' in content, \
        f"docker-compose.yml must define a project-prefixed bootstrap container"
    assert f'PGPASSWORD="${{{SLUG}_ENTITIES_DB_PASSWORD}}" pg_isready' in content, \
        "bootstrap must wait for entities DB using pg_isready"

    assert "./database/initdb/datamodel.sql:/module/datamodel.sql:ro" in content, \
        "datamodel.sql must be mounted into bootstrap container"
    assert "./config/authorization.yaml:/module/authorization.yaml:ro" in content, \
        "authorization.yaml must be mounted from the module-level config folder"
    assert "./database/initdb/seed.sql:/module/seed.sql:ro" in content, \
        "seed.sql must be mounted into bootstrap container"

    assert f"{slug}_datamodel_v1" in content, \
        "bootstrap must use a versioned script_key for datamodel execution tracking"
    assert "/docker-entrypoint-initdb.d/datamodel.sql" not in content, \
        "datamodel.sql must not use docker-entrypoint-initdb.d (not idempotent)"

    assert f'container_name: ${{APP_SLUG}}.${{MODULE_SLUG}}.template-backend' in content
    assert f'container_name: ${{APP_SLUG}}.${{MODULE_SLUG}}.template-bootstrap' in content
    assert "./config/menu_definition.json:/usr/share/nginx/html/menu_definition.json:ro" in content
