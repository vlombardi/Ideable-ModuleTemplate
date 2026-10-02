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


def _module_slug() -> str:
    """This module's slug, from the one file that travels with it.

    NOT `$MODULE_SLUG`: every module's .env.config defines it, the merged deployment_root file
    carries host_app's value, and the runner exports it per module — so the same lookup resolves
    differently depending on which file is found first. `module.json` cannot be shadowed, and it
    is what backend/TESTS/conftest.py already reads for the same reason.
    """
    import json

    return json.loads((MODULE_ROOT / "module.json").read_text(encoding="utf-8"))["slug"]


def test_compose_uses_dedicated_bootstrap_for_dual_db_one_time_sql() -> None:
    # Container names are ${APP_SLUG}.${MODULE_SLUG}.<role> (the bootstrap container is
    # ".bootstrap"); the module's DB env vars and one-time script_keys are prefixed by
    # the module's slug (e.g. <SLUG>_ENTITIES_DB_* / <slug>_datamodel_v1).
    module_slug = _module_slug()
    MSLUG = module_slug.upper()
    compose_path = MODULE_ROOT / "docker-compose.yml"
    assert compose_path.exists(), f"docker-compose.yml not found at {compose_path}"
    content = compose_path.read_text(encoding="utf-8")

    assert 'container_name: ${APP_SLUG}.${MODULE_SLUG}.bootstrap' in content, \
        "docker-compose.yml must define a project-prefixed bootstrap container"
    assert f'pg_isready -h "${{{MSLUG}_ENTITIES_DB_HOST}}"' in content, \
        "bootstrap must wait for the entities DB using pg_isready"

    # datamodel.sql is deliberately NOT mounted any more: the bootstrap seeds DATA, and Alembic
    # owns every CREATE/ALTER/DROP. A bootstrap that also created tables was a second owner of the
    # schema, which is how four au_* columns survived in deployed databases that no file declared.
    assert "datamodel.sql" not in content, \
        "datamodel.sql is retired — the migrations job owns the schema"
    # Usage, not mention: the compose comments discuss the retired ledger keys and the trap they
    # caused, and a bare substring search reads that history as a violation.
    ledger_writes = [
        line for line in content.splitlines()
        if "module_bootstrap_execution" in line and "INSERT INTO" in line.upper()
    ]
    assert not ledger_writes, \
        f"the seed step records ledger keys again: {ledger_writes}. seed.sql is idempotent and " \
        f"runs on every deploy; the ledger is reserved for non-idempotent one-shots."
    assert "./config/authorization.yaml:/module/authorization.yaml:ro" in content, \
        "authorization.yaml must be mounted from the module-level config folder"
    assert "./database/initdb/seed.sql:/module/seed.sql:ro" in content, \
        "seed.sql must be mounted (never baked) so a deployment can customise initial data"

    # The schema is applied by a one-shot job that must finish before anything uses the database.
    assert '"alembic", "upgrade", "head"' in content, \
        "no migrations job applies the schema"
    migrations = content.split("SYNC-MANAGED-BEGIN: migrations-job", 1)[1] \
                        .split("SYNC-MANAGED-END: migrations-job", 1)[0]
    assert 'restart: "no"' in migrations, \
        "a restarting one-shot can never satisfy service_completed_successfully"
    bootstrap = content.split("SYNC-MANAGED-BEGIN: bootstrap-service", 1)[1] \
                       .split("SYNC-MANAGED-END: bootstrap-service", 1)[0]
    assert f"{module_slug}-migrations" in bootstrap, \
        "the seed job must wait for the migrations: it inserts into tables they create"
    for ddl in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE"):
        assert ddl not in bootstrap.upper(), f"the bootstrap job contains {ddl}"

    # The REPLICABLE services must NOT carry a container_name: it is a unique name, so a second
    # replica collides on it and only one starts. This assertion is inverted from what it was — the
    # old contract required the fixed name, which is exactly what capped the backend at one instance.
    for service in ("backend", "frontend"):
        assert f'container_name: ${{APP_SLUG}}.${{MODULE_SLUG}}.{service}' not in content, (
            f"the {service} declares a container_name, so it cannot be replicated — Compose names "
            f"replicas <project>-<service>-<n>. Scripts must find it by label, not by name."
        )
    # One-shot jobs keep theirs: they are never replicated, and the deploy waits on them by name.
    assert 'container_name: ${APP_SLUG}.${MODULE_SLUG}.bootstrap' in content
    assert 'container_name: ${APP_SLUG}.${MODULE_SLUG}.migrations' in content

    # Replica count and the published port range have to move together: a fixed published port fails
    # outright with more than one replica ("port is already allocated") and only one replica starts.
    for var in (f"{MSLUG}_BACKEND_REPLICAS", f"{MSLUG}_FRONTEND_REPLICAS"):
        assert f"replicas: ${{{var}:-1}}" in content, f"{var} does not drive deploy.replicas"
    # One variable holding the whole compose port spec, so a deployment picks a guaranteed port or a
    # scalable range deliberately. Hard-coding either would make one of the two cases impossible.
    assert f'"${{{MSLUG}_BACKEND_PUBLISH:-' in content, (
        "the backend's published port is not switchable between a guaranteed port and a range"
    )

    # Traefik runs the FILE provider only, so container labels are never read. A traefik.* label here
    # describes routing that nothing performs, next to a dynamic.yml that actually performs it.
    assert "traefik.http.routers" not in content, (
        "traefik.* routing labels are dead configuration — routing lives in "
        "host_app/traefik/SOURCES/dynamic.yml.template"
    )

    assert "./config/menu_definition.json:/usr/share/nginx/html/menu_definition.json:ro" in content
