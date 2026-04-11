from pathlib import Path


def test_sources_authorization_exists_and_defines_template_items_permissions() -> None:
    authorization_path = (
        Path(__file__).resolve().parents[1]
        / "SOURCES"
        / "initdb"
        / "authorization.sql"
    )

    assert authorization_path.exists()

    content = authorization_path.read_text(encoding="utf-8")
    assert "template.items.read" in content
    assert "template.items.create" in content
    assert "template.items.update" in content
    assert "template.items.delete" in content
    assert "ON CONFLICT" in content
