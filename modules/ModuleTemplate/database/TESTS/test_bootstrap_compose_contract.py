from pathlib import Path


def test_compose_uses_dedicated_bootstrap_for_dual_db_one_time_sql() -> None:
    compose_path = (
        Path(__file__).resolve().parents[2]
        / "docker-compose.yml"
    )
    content = compose_path.read_text(encoding="utf-8")

    assert "template-bootstrap:" in content
    assert "until PGPASSWORD=\"${TEMPLATE_ENTITIES_DB_PASSWORD}\" pg_isready" in content
    assert "until PGPASSWORD=\"${TEMPLATE_AUTH_DB_PASSWORD}\" pg_isready" in content

    assert "./database/initdb/datamodel.sql:/module/datamodel.sql:ro" in content
    assert "./database/initdb/authorization.sql:/module/authorization.sql:ro" in content

    assert "template_datamodel_v1" in content
    assert "template_authorization_v1" in content

    assert "template-authz-bootstrap:" not in content
    assert "/docker-entrypoint-initdb.d/datamodel.sql" not in content

    assert "template-backend:" in content
    assert "template-bootstrap:" in content
    assert "template-database:\n        condition: service_healthy" not in content
    assert "./menu_definition.json:/usr/share/nginx/html/menu_definition.json:ro" in content
