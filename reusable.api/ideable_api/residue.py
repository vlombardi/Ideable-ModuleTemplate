"""Remove, after a test run, the rows it created in a module's entity tables.

    python -m ideable_api.residue --snapshot                 # prints {"<table>": [ids…]} as the LAST line
    python -m ideable_api.residue --purge --since -          # the snapshot on stdin; removes what it lacks
    python -m ideable_api.residue --purge --since - --dry-run

WHY. A test suite cleans up after itself, and when a spec aborts the row it made stays: measured,
`E2E-mupkaw90 SubItemsParent` sat in `template_items` until someone looked. What is missing is PROVENANCE
— which rows are the run's — and a snapshot records it: the rows that exist before the suites are
"known", and whatever exists afterwards and is not known was created by the run, by any creator.

WHAT IT COVERS. Every table a module declares as an entity (`app.entities`' registry), found the same way
in every backend, so a remote module gets this with the framework and lists nothing.

ROW-LEVEL SECURITY. The application's role is subject to it, and a cleanup that needed a privileged
role would be a second, wider door. So it uses the two mechanisms the policies already have: the rows to
remove are SEEN with `app.cross_tenant_read = on` (every tenant, including one that no longer exists —
the measured leak's tenant was gone) and DELETED with `app.tenant_ids` set to exactly the tenants of those
rows. Both are transaction-local.

SAFETY. Tables are cleaned children first (the reverse of the model's dependency order). A row a foreign
key still protects is KEPT and reported, never forced. The `<table>_version` rows of a removed row go with
it. The gate FAILS CLOSED: `E2E_TEST_USERS_ENABLED=true` AND an `IDEABLE_EXECUTION_MODE` that is given and
is not `prod` — a module's container carries neither, so the runner passes both from the deployed config,
and an absent value refuses. Unlike host_app's persona gate, an absent mode is not read as "dev": this
deletion spans every module's data.

ASSUMPTION. Nobody else writes to the stack while the suites run: a row created by someone else in that
window is indistinguishable from a test's.
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import Table, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger("ideable_api.residue")

_CHUNK = 500

#: `(session, setting, value)` — set a transaction-local Postgres setting. Injected so the behaviour can
#: be exercised against a database that has none (the tests use SQLite with foreign keys on).
SetLocal = Callable[[Session, str, str], None]


def postgres_set_local(session: Session, setting: str, value: str) -> None:
    session.execute(text("SELECT set_config(:setting, :value, true)"), {"setting": setting, "value": value})


def gate_refusal(env: Mapping[str, str]) -> str | None:
    """Why the purge may not run, or None when it may. Fails closed: absence refuses."""
    if str(env.get("E2E_TEST_USERS_ENABLED", "")).strip().lower() != "true":
        return "E2E_TEST_USERS_ENABLED is not true"
    mode = str(env.get("IDEABLE_EXECUTION_MODE", "")).strip().lower()
    if not mode:
        return "IDEABLE_EXECUTION_MODE is not given (an absent mode is not read as dev)"
    if mode == "prod":
        return "the execution mode is prod"
    return None


@dataclass
class TableReport:
    table: str
    removed: list = field(default_factory=list)
    kept: list = field(default_factory=list)  # (id, reason)
    versions_removed: int = 0


def _pk(table: Table):
    columns = list(table.primary_key.columns)
    if len(columns) != 1:
        raise ValueError(f"{table.name}: residue handles single-column primary keys only")
    return columns[0]


def _tenant_column(table: Table):
    return table.c.tenant_id if "tenant_id" in table.c else None


def children_first(tables: Iterable[Table]) -> list[Table]:
    """The tables in deletion order: the reverse of the model's dependency order."""
    wanted = {t.name: t for t in tables}
    if not wanted:
        return []
    metadata = next(iter(wanted.values())).metadata
    return [t for t in reversed(metadata.sorted_tables) if t.name in wanted]


def _rows(session: Session, table: Table, set_local: SetLocal) -> list[tuple]:
    """Every row's (pk, tenant) — across tenants, so a row of a vanished tenant is seen."""
    set_local(session, "app.cross_tenant_read", "on")
    tenant = _tenant_column(table)
    columns = [_pk(table)] + ([tenant] if tenant is not None else [])
    return [tuple(row) for row in session.execute(table.select().with_only_columns(*columns))]


def snapshot(session: Session, tables: Iterable[Table], set_local: SetLocal = postgres_set_local) -> dict[str, list]:
    """`{table: [pk, …]}` for every declared entity table."""
    out: dict[str, list] = {}
    for table in children_first(tables):
        out[table.name] = sorted(row[0] for row in _rows(session, table, set_local))
        session.rollback()  # the settings are transaction-local; end the read cleanly
    return out


def _delete_ids(session: Session, table: Table, ids: list) -> int:
    done = 0
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        done += session.execute(table.delete().where(_pk(table).in_(chunk))).rowcount or 0
    return done


def purge(
    session: Session,
    tables: Iterable[Table],
    since: Mapping[str, list],
    *,
    dry_run: bool = False,
    set_local: SetLocal = postgres_set_local,
) -> list[TableReport]:
    """Remove, from every declared entity table, the rows `since` does not hold."""
    reports: list[TableReport] = []
    for table in children_first(tables):
        if table.name not in since:
            # A table the snapshot never saw: everything in it would look new. Not guessing.
            logger.warning("%s is not in the snapshot — left alone", table.name)
            continue
        known = set(since[table.name])
        current = _rows(session, table, set_local)
        fresh = [row for row in current if row[0] not in known]
        report = TableReport(table.name)
        if not fresh:
            session.rollback()
            continue
        if dry_run:
            report.removed = [row[0] for row in fresh]
            session.rollback()
            reports.append(report)
            continue
        tenant = _tenant_column(table)
        if tenant is not None:
            tenants = sorted({row[1] for row in fresh if row[1] is not None})
            set_local(session, "app.tenant_ids", ",".join(str(t) for t in tenants))
        ids = [row[0] for row in fresh]
        try:
            with session.begin_nested():
                _delete_ids(session, table, ids)
            report.removed = ids
        except IntegrityError:
            # Something a foreign key protects is in the batch: row by row, keeping what is blocked.
            for row_id in ids:
                try:
                    with session.begin_nested():
                        _delete_ids(session, table, [row_id])
                    report.removed.append(row_id)
                except IntegrityError as error:
                    report.kept.append((row_id, _reason(error)))
        version = table.metadata.tables.get(f"{table.name}_version")
        if version is not None and report.removed and "id" in version.c:
            report.versions_removed = session.execute(
                version.delete().where(version.c.id.in_(report.removed))
            ).rowcount or 0
        session.commit()
        reports.append(report)
    return reports


def _reason(error: IntegrityError) -> str:
    original = getattr(error, "orig", None)
    diag = getattr(original, "diag", None)
    table = getattr(diag, "table_name", None)
    return f"still referenced by {table}" if table else "still referenced by another row"


def summary(reports: list[TableReport], dry_run: bool) -> str:
    removed = sum(len(r.removed) for r in reports)
    kept = sum(len(r.kept) for r in reports)
    verb = "would remove" if dry_run else "removed"
    parts = [f"residue: {verb} {removed} row(s) in {len([r for r in reports if r.removed])} table(s)"]
    if kept:
        parts.append(f"kept {kept} a foreign key protects")
    return "; ".join(parts)


def _module(package: str) -> tuple[Session, list[Table]]:
    """The running module's session and its declared entity tables.

    The package is a PARAMETER, not an import: the framework runs in every backend and cannot name one
    (`test_the_backend_framework_is_shared.py`). Every backend's package is `app`, so that is the
    default; the module's `entities` registers and freezes the descriptors on import, and its
    `database` carries the session factory.
    """
    importlib.import_module(f"{package}.entities")
    database = importlib.import_module(f"{package}.database")

    from .entities import all_entity_descriptors

    tables = {d.model.__table__ for d in all_entity_descriptors().values()}
    return database.SessionLocal(), list(tables)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", action="store_true", help="print the rows that exist, as JSON, and exit")
    parser.add_argument("--purge", action="store_true", help="remove the rows a snapshot lacks")
    parser.add_argument("--since", metavar="FILE", help="with --purge: the snapshot (`-` is stdin)")
    parser.add_argument("--dry-run", action="store_true", help="with --purge: report only; change nothing")
    parser.add_argument("--package", default="app", help="the module's backend package (default: app)")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    logging.basicConfig(level=logging.INFO, format="[residue] %(levelname)s %(message)s", stream=sys.stderr)

    if args.snapshot == args.purge:
        parser.error("choose --snapshot or --purge")
    if args.purge and not args.since:
        parser.error("--purge needs --since <snapshot> (`-` for stdin)")

    if args.purge:
        refusal = gate_refusal(env)
        if refusal:
            logger.error("refusing: %s", refusal)
            return 1
        raw = sys.stdin.read() if args.since == "-" else open(args.since, encoding="utf-8").read()
        since: Mapping[str, Any] = json.loads(raw)

    session, tables = _module(args.package)
    try:
        if args.snapshot:
            print(json.dumps(snapshot(session, tables)))
            return 0
        reports = purge(session, tables, since, dry_run=args.dry_run)
        for report in reports:
            logger.info("%s: %s %d row(s)%s", report.table, "would remove" if args.dry_run else "removed",
                        len(report.removed), f", {report.versions_removed} version row(s)" if report.versions_removed else "")
            for row_id, why in report.kept:
                logger.warning("%s: kept %s — %s", report.table, row_id, why)
        print(summary(reports, args.dry_run))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
