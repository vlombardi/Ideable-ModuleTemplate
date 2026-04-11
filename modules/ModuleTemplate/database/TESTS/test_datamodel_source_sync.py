from pathlib import Path


def test_sources_datamodel_exists_and_defines_template_items() -> None:
    datamodel_path = (
        Path(__file__).resolve().parents[1]
        / "SOURCES"
        / "initdb"
        / "datamodel.sql"
    )

    assert datamodel_path.exists()

    content = datamodel_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS template_items" in content
    assert "CREATE INDEX IF NOT EXISTS idx_template_items_name" in content
