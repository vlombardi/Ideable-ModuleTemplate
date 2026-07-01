import re
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_SPEC_PATH = MODULE_ROOT / "SPECS" / "authorization.yaml"
DATAMODEL_PATH = MODULE_ROOT / "database" / "SOURCES" / "initdb" / "datamodel.sql"


def _read_env(key: str) -> str:
    env_path = MODULE_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise KeyError(f"{key} not found in .env")


def _get_slug() -> str:
    return _read_env("APP_SLUG")


def _get_main_entity_names() -> list[str]:
    content = DATAMODEL_PATH.read_text(encoding="utf-8")
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", content)


def _get_yaml_contract_text() -> str:
    return AUTHORIZATION_SPEC_PATH.read_text(encoding="utf-8")


def test_spec_authorization_exists() -> None:
    assert AUTHORIZATION_SPEC_PATH.exists(), "authorization.yaml not found in SPECS/"


def test_spec_authorization_is_idempotent() -> None:
    content = _get_yaml_contract_text()
    assert "idempotent: true" in content, \
        "authorization.yaml must declare idempotent bootstrap behavior"


def test_spec_authorization_is_consumed_by_bootstrap_compose() -> None:
    compose_path = MODULE_ROOT / "docker-compose.yml"
    content = compose_path.read_text(encoding="utf-8")
    assert "./SPECS/authorization.yaml:/module/authorization.yaml:ro" in content, \
        "docker-compose.yml must mount the module-level SPECS authorization contract directly"


def test_spec_authorization_defines_permissions_for_all_entities() -> None:
    slug = _get_slug()
    entities = _get_main_entity_names()
    assert entities, "No tables found in datamodel.sql"

    content = _get_yaml_contract_text()
    prefix = f"{slug}_"
    for entity in entities:
        entity_part = entity[len(prefix):] if entity.startswith(prefix) else entity
        entity_slug = entity_part.replace("_", ".")
        for action in ("read", "create", "update", "delete"):
            permission = f"{slug}.{entity_slug}.{action}"
            assert permission in content, \
                f"authorization.yaml missing permission: {permission}"
