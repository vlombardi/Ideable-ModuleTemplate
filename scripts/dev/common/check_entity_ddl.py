#!/usr/bin/env python3
"""Fail the build when an entity is missing the framework DDL its declarations promise.

Adding an entity means writing nine pieces of DDL, of which Alembic autogenerate writes one. The
other eight are repeated by hand, and **two of them fail silently**:

- **A primary key that does not contain the partition column.** Alembic implements no autogenerate
  detection for free-standing PRIMARY KEY constraint changes, so a wrong PK produces an *empty
  migration* rather than an error. "It generated nothing" reads as "nothing to do".
- **A missing server-side default on the version table's `issued_at`.** `compare_server_default` is
  off by default, so autogenerate cannot see it at all. Continuum writes version rows inside its own
  flush without naming the column, so without the default those rows carry a NULL partition key and
  the hypertable rejects them at insert time — far from the migration that caused it.

Everything here is derived from what the module DECLARES, never from a hardcoded table list: the
models are the source of truth (`__tenant_scoped__`, `__versioned__`, `__filterable__`,
`__tablename__`) and the generated `database/SPECS/schema.sql` is what the migrations actually
produced. A disagreement between those two is the finding.

Offline by design — it reads files, never a database — so it runs in the CI gate where no stack
exists.

    scripts/dev/common/check_entity_ddl.py                 # every module with a backend
    scripts/dev/common/check_entity_ddl.py module_template # one module
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: `pg_dump` does not render `create_hypertable` at all — the conversion lives in the TimescaleDB
#: catalog, not in the schema DDL. So the hypertable check reads the migrations instead, which is
#: also where a reviewer would look for it.
_HYPERTABLE_LITERAL = re.compile(r"create_hypertable\(\s*['\"]([\w.]+)['\"]", re.I)
_HYPERTABLE_ANY = re.compile(r"create_hypertable\(", re.I)


def _conversion_helpers(tree: ast.AST) -> set[str]:
    """Names of functions whose body performs the conversion.

    A literal handed to one of these names IS a converted table, even though the name never appears
    inside `create_hypertable(`. The body is read with `ast.unparse`, so a mention in a comment does
    not qualify — only code and strings the function actually carries.
    """
    helpers = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _HYPERTABLE_ANY.search(ast.unparse(node)):
                helpers.add(node.name)
    return helpers


def _string_arguments(call: ast.Call) -> set[str]:
    """Every string literal passed to `call`, positionally or by keyword."""
    passed = [*call.args, *(kw.value for kw in call.keywords)]
    return {a.value.split(".")[-1] for a in passed
            if isinstance(a, ast.Constant) and isinstance(a.value, str)}


def _hypertables(migrations_src: str) -> set[str]:
    """Table names converted to hypertables by these migrations.

    Three call shapes, because this check exists to catch a table nobody remembered to convert, not
    to police how the conversion is spelled — and each shape after the first was found by a module
    whose tables demonstrably ARE hypertables being told they were not:

        SELECT create_hypertable('transaction', 'issued_at', …)      -- literal
        for table in AUDIT_TABLES:                                    -- loop over a tuple
            op.execute(f"SELECT create_hypertable('{table}', …)")
        _to_hypertable("assessment_version")                          -- through a helper

    For the loop form the name is not in the call at all, so the string members of tuple/list
    constants are taken as candidates. The helper form is the same problem one step further out:
    the name is a literal, but it sits at a call to a function of the migration's own, whose body
    binds it as a query parameter — the safer spelling, and the one a checker matching call text
    penalised. So a function whose body performs the conversion lends its name to the search, and
    the literals passed to it count.

    Both heuristics are deliberately generous. A name they add that is not a table cannot hide an
    unconverted one, because the comparison is *required ⊆ found*; a shape they miss reports a
    module's correct implementation as a defect it cannot fix, which is the failure that matters.

    Annotated constants count as much as bare ones. `AUDIT_HYPERTABLES = (...)` is an `ast.Assign`
    and `AUDIT_HYPERTABLES: tuple[str, ...] = (...)` is an `ast.AnnAssign`; matching only the first
    made the more modern spelling silently invisible, and cost a debugging cycle in which the fix
    appeared to change nothing.
    """
    found = {m.group(1).split(".")[-1] for m in _HYPERTABLE_LITERAL.finditer(migrations_src)}
    if not _HYPERTABLE_ANY.search(migrations_src):
        return found
    try:
        tree = ast.parse(migrations_src)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, (ast.Tuple, ast.List)):
            for el in node.value.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    found.add(el.value.split(".")[-1])
    helpers = _conversion_helpers(tree)
    if helpers:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in helpers:
                found |= _string_arguments(node)
    return found


class Entity:
    """One model's declarations, as the module itself states them."""

    def __init__(self, cls: ast.ClassDef):
        self.name = cls.name
        self.table: str | None = None
        self.tenant_scoped = False
        self.versioned = False
        self.filterable: tuple[str, ...] = ()
        for node in cls.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if not isinstance(t, ast.Name) or node.value is None:
                    continue
                if t.id == "__tablename__" and isinstance(node.value, ast.Constant):
                    self.table = node.value.value
                elif t.id == "__tenant_scoped__" and isinstance(node.value, ast.Constant):
                    self.tenant_scoped = bool(node.value.value)
                elif t.id == "__versioned__":
                    self.versioned = True
                elif t.id == "__filterable__" and isinstance(node.value, (ast.Tuple, ast.List)):
                    self.filterable = tuple(
                        e.value for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    )


def _entities(models_py: Path) -> list[Entity]:
    tree = ast.parse(models_py.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            e = Entity(node)
            if e.table:
                out.append(e)
    return out


def _table_block(schema: str, table: str) -> str:
    """The `CREATE TABLE … ( … );` body for one table, schema-qualified or not."""
    m = re.search(
        rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?{re.escape(table)}\s*\((.*?)\n\);",
        schema, re.S | re.I,
    )
    return m.group(1) if m else ""


def _has(schema: str, pattern: str) -> bool:
    return re.search(pattern, schema, re.I | re.S) is not None


def check_module(module_dir: Path) -> list[str]:
    """Return a list of findings — empty means the module's DDL matches its declarations."""
    models_py = module_dir / "backend" / "SOURCES" / "app" / "models.py"
    schema_sql = module_dir / "database" / "SPECS" / "schema.sql"
    versions = module_dir / "backend" / "SOURCES" / "alembic" / "versions"
    if not models_py.is_file() or not schema_sql.is_file():
        return []

    schema = schema_sql.read_text(encoding="utf-8")
    migrations = "".join(
        p.read_text(encoding="utf-8") for p in sorted(versions.glob("*.py"))
    ) if versions.is_dir() else ""
    hypertables = _hypertables(migrations)

    findings: list[str] = []
    mod = module_dir.name

    def miss(table: str, what: str, why: str) -> None:
        findings.append(f"{mod}.{table}: {what}\n      {why}")

    for e in _entities(models_py):
        table = e.table
        assert table
        if not _has(schema, rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?{re.escape(table)}\s*\("):
            miss(table, "declared by a model but absent from schema.sql",
                 "regenerate with `scripts/dev/common/schema.sh schema-sql <module>`, or the migration "
                 "that creates it was never written")
            continue

        # --- tenancy -------------------------------------------------------------------------
        tenant_tables = [table] + ([f"{table}_version"] if e.versioned else [])
        if e.tenant_scoped:
            for t in tenant_tables:
                if not _has(schema, rf"ALTER TABLE\s+(?:ONLY\s+)?(?:\w+\.)?{re.escape(t)}\s+ENABLE ROW LEVEL SECURITY"):
                    miss(t, "row level security is not ENABLEd",
                         "a tenant-scoped table without RLS holds every customer's rows and its "
                         "queries look correct")
                if not _has(schema, rf"ALTER TABLE\s+(?:ONLY\s+)?(?:\w+\.)?{re.escape(t)}\s+FORCE ROW LEVEL SECURITY"):
                    miss(t, "row level security is enabled but not FORCEd",
                         "without FORCE the table owner bypasses every policy, and the application "
                         "role is the owner on a fresh install")
                for policy in ("tenant_isolation", "tenant_cross_read"):
                    if not _has(schema, rf"CREATE POLICY\s+{policy}\s+ON\s+(?:\w+\.)?{re.escape(t)}\b"):
                        miss(t, f"policy `{policy}` is missing",
                             "RLS with no policy denies everything; RLS with only one of the pair "
                             "either leaks or blocks the cross-tenant reader")
            # tenant_id must LEAD a composite index, or a query scans every tenant then filters
            if not _has(schema, rf"CREATE INDEX[^;]*ON\s+(?:\w+\.)?{re.escape(table)}\s+USING\s+\w+\s*\(\s*tenant_id\b"):
                miss(table, "no index leads with tenant_id",
                     "a query then touches every tenant's rows and filters afterwards, which costs "
                     "back what tenant scoping is for")

        # --- substring filters need trigram indexes -------------------------------------------
        for column in e.filterable:
            if not _has(schema, rf"CREATE INDEX[^;]*ON\s+(?:\w+\.)?{re.escape(table)}\s+USING\s+gin\s*\([^)]*\b{re.escape(column)}\b[^)]*gin_trgm_ops"):
                miss(table, f"`{column}` is declared __filterable__ but has no trigram GIN index",
                     "the filter is `ILIKE '%term%'` — a LEADING wildcard, which no B-tree can "
                     "serve, so every keystroke is a sequential scan")

        # --- the audit twin, and the two silent failures ---------------------------------------
        if e.versioned:
            vt = f"{table}_version"
            if not _has(schema, rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?{re.escape(vt)}\s*\("):
                miss(vt, "the Continuum version table is missing",
                     "the model is __versioned__, so Continuum declares this table and a migration "
                     "must create it — the audit trail has nowhere to write")
                continue

            body = _table_block(schema, vt)
            if not re.search(r"issued_at[^,\n]*DEFAULT", body, re.I):
                miss(vt, "`issued_at` has no server-side DEFAULT  [SILENT]",
                     "autogenerate cannot see this: compare_server_default is off by default. "
                     "Continuum writes version rows without naming the column, so without the "
                     "default they carry a NULL partition key and the hypertable rejects them")

            pk = re.search(
                rf"ALTER TABLE\s+(?:ONLY\s+)?(?:\w+\.)?{re.escape(vt)}\s+ADD CONSTRAINT[^;]*PRIMARY KEY\s*\(([^)]*)\)",
                schema, re.I | re.S,
            ) or re.search(r"PRIMARY KEY\s*\(([^)]*)\)", body, re.I)
            if not pk:
                miss(vt, "no primary key found  [SILENT]",
                     "Alembic emits an EMPTY migration for primary-key changes, so a missing or "
                     "wrong PK is never reported by autogenerate")
            elif "issued_at" not in pk.group(1):
                miss(vt, f"the primary key ({pk.group(1).strip()}) does not contain the partition "
                         f"column  [SILENT]",
                     "TimescaleDB refuses the hypertable conversion unless every unique index "
                     "contains the partition column — and Alembic reports PK problems as an empty "
                     "migration, never as an error")

            if vt not in hypertables:
                miss(vt, "no create_hypertable(...) in any migration",
                     "pg_dump does not render the conversion, so this is checked against the "
                     "migrations; without it audit growth is unbounded and retention cannot expire "
                     "anything")
    return findings


def main(argv: list[str]) -> int:
    wanted = argv[1:]
    modules = sorted(
        d for d in (REPO / "modules").iterdir()
        if d.is_dir() and (d / "backend" / "SOURCES" / "app" / "models.py").is_file()
        and (not wanted or d.name in wanted)
    )
    if not modules:
        print("no module with backend models found — the discovery is broken, not the repo",
              file=sys.stderr)
        return 1

    total = 0
    for m in modules:
        findings = check_module(m)
        total += len(findings)
        status = f"{len(findings)} finding(s)" if findings else "ok"
        print(f"[entity-ddl] {m.name}: {status}")
        for f in findings:
            print(f"    ✗ {f}")
    if total:
        print(f"\n[entity-ddl] {total} finding(s). Each is DDL a declaration promised and the "
              f"schema does not have.\n"
              f"[entity-ddl] The two marked [SILENT] are the ones autogenerate cannot report: it "
              f"emits an empty\n[entity-ddl] migration for primary keys, and does not compare "
              f"server defaults unless asked.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
