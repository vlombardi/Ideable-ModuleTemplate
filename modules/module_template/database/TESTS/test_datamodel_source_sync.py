import re
from pathlib import Path


DATAMODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "SOURCES"
    / "initdb"
    / "datamodel.sql"
)


def test_sources_datamodel_exists() -> None:
    assert DATAMODEL_PATH.exists(), "datamodel.sql not found in SOURCES/initdb/"


def test_sources_datamodel_defines_at_least_one_table() -> None:
    content = DATAMODEL_PATH.read_text(encoding="utf-8")
    tables = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", content)
    assert tables, "datamodel.sql must define at least one table with CREATE TABLE IF NOT EXISTS"


def test_sources_datamodel_uses_idempotent_ddl() -> None:
    content = DATAMODEL_PATH.read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in content, \
        "datamodel.sql must use IF NOT EXISTS for idempotent DDL"
