"""The module's schema definition, after Alembic took ownership of it.

These tests used to assert that `SOURCES/initdb/datamodel.sql` existed, declared tables, and used
`CREATE TABLE IF NOT EXISTS`. That contract is gone deliberately: that file declared tables the
ORM also declared, the two drifted (four `au_*` columns survived in deployed databases that no
file in the repository declared), and idempotent DDL is precisely what made the drift invisible —
`IF NOT EXISTS` creates but never alters.

What replaces it: `app/models.py` is the one authored definition, the migrations apply it, and
`database/SPECS/schema.sql` is a generated rendering of the result for reading. So the assertions
below check that the rendering exists, is marked generated, and describes a real schema — and that
nothing has quietly reintroduced an applied definition alongside it.

See database/SPECS/ideable-framework-specs/schema-workflow.md.
"""
import ast
import re
from pathlib import Path

_DATABASE = Path(__file__).resolve().parents[1]
_MODULE = _DATABASE.parent
SCHEMA_PATH = _DATABASE / "SPECS" / "schema.sql"


#: The framework's own tables. These names are identical in every module — that is what makes them
#: the framework's — so they are the one thing here that may be written literally.
FRAMEWORK_TABLES = (
    "transaction",
    "transaction_meta",
    "module_bootstrap_execution",
    "module_runtime_meta",
)


def _model_tables() -> dict[str, bool]:
    """Every table this module AUTHORS, mapped to whether it is `__versioned__`.

    Parsed with `ast` rather than matched with a regex, because the versioned flag decides whether a
    `<table>_version` twin is expected and getting that wrong fails on a module that has done nothing
    wrong. The earlier version assumed **every** entity was versioned and appended a twin for each —
    correct only by accident here, where the single reference entity happens to be versioned, and
    wrong in any module carrying a plain lookup table. Found 2026-08-29 when host_app, which has six
    unversioned entities, was given this same guard.
    """
    models = _MODULE / "backend" / "SOURCES" / "app" / "models.py"
    assert models.is_file(), (
        f"{models.relative_to(_MODULE.parents[1])} not found — the schema has no authored source, "
        f"so there is nothing to check the rendering against"
    )
    tree = ast.parse(models.read_text(encoding="utf-8"))
    out: dict[str, bool] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        table, versioned = None, False
        for stmt in node.body:
            targets = (stmt.targets if isinstance(stmt, ast.Assign)
                       else [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
            for t in targets:
                if not isinstance(t, ast.Name):
                    continue
                if t.id == "__tablename__" and isinstance(getattr(stmt, "value", None), ast.Constant):
                    table = stmt.value.value
                elif t.id == "__versioned__":
                    versioned = True
        if table:
            out[table] = versioned
    assert out, "app/models.py declares no __tablename__ — the extraction has drifted"
    return out


def test_generated_schema_exists() -> None:
    assert SCHEMA_PATH.exists(), (
        f"database/SPECS/schema.sql not found — regenerate it with "
        f"`scripts/dev/schema.sh schema-sql {_MODULE.name}`"
    )


def test_generated_schema_declares_itself_generated() -> None:
    """A schema file that does not say it is generated is one somebody will edit."""
    first_line = SCHEMA_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "GENERATED" in first_line, (
        "schema.sql must announce on line one that it is generated and applied by nothing"
    )


def test_generated_schema_defines_the_expected_tables() -> None:
    content = SCHEMA_PATH.read_text(encoding="utf-8")
    tables = set(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(?:public\.)?(\w+)", content))
    # This module's own entities, the framework tables, and the Continuum audit trail: a rendering
    # missing the audit tables is the fresh-install bug this task shipped and then fixed.
    expected = set(FRAMEWORK_TABLES)
    for entity, versioned in _model_tables().items():
        expected.add(entity)
        # Only a `__versioned__` model has a Continuum twin. Expecting one for every entity makes a
        # module with a plain lookup table fail for a table that should not exist.
        if versioned:
            expected.add(f"{entity}_version")
    missing = sorted(expected - tables)
    assert not missing, (
        f"schema.sql does not describe {missing} — regenerate it with "
        f"`scripts/dev/schema.sh schema-sql {_MODULE.name}`"
    )


def test_no_applied_ddl_alongside_the_migrations() -> None:
    """Nothing under initdb/ may define schema — that is the second-owner failure mode."""
    initdb = _DATABASE / "SOURCES" / "initdb"
    offenders = []
    for path in list(initdb.glob("*.sql")) + list((_DATABASE / "SPECS").glob("*.sql")):
        if path.name == "schema.sql":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"CREATE TABLE|ALTER TABLE|DROP TABLE", text, re.I):
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} contain DDL. Alembic owns the schema; files here seed DATA only."
    )
