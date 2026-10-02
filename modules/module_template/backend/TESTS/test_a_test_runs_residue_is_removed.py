"""What a test run created in a module's entity tables is removed; what was there before is not.

Exercised, not read: a real database engine with foreign keys ENFORCED (SQLite), a parent/child/grandchild
model with `tenant_id` and `<table>_version` rows like a module's, and a table the registry does not know
that points at a parent (so a foreign key can protect a row). Postgres' two row-level-security settings are
captured by an injected `set_local`, which is how the tests see that the cleanup uses exactly the
mechanisms the policies offer and no more.
"""
import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, Text, create_engine, event, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
def residue(app_module):
    import ideable_api.residue as residue
    return residue


class _Db:
    """parent <- child <- grandchild (declared), parent_version (history), pin (NOT declared) -> parent."""

    def __init__(self):
        engine = create_engine("sqlite://", connect_args={"isolation_level": None})

        @event.listens_for(engine, "connect")
        def _fk(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "begin")
        def _begin(connection):
            connection.exec_driver_sql("BEGIN")

        metadata = MetaData()
        self.parent = Table("parent", metadata, Column("id", Integer, primary_key=True),
                            Column("name", Text), Column("tenant_id", Integer))
        self.child = Table("child", metadata, Column("id", Integer, primary_key=True),
                           Column("parent_id", ForeignKey("parent.id"), nullable=False), Column("tenant_id", Integer))
        self.grandchild = Table("grandchild", metadata, Column("id", Integer, primary_key=True),
                                Column("child_id", ForeignKey("child.id"), nullable=False), Column("tenant_id", Integer))
        self.version = Table("parent_version", metadata, Column("id", Integer, primary_key=True),
                             Column("transaction_id", Integer, primary_key=True))
        self.pin = Table("pin", metadata, Column("id", Integer, primary_key=True),
                         Column("parent_id", ForeignKey("parent.id"), nullable=False))
        metadata.create_all(engine)
        self.session = sessionmaker(engine)()
        self.declared = [self.parent, self.child, self.grandchild]
        self.calls: list[tuple[str, str]] = []

    def set_local(self, _session, setting, value):
        self.calls.append((setting, value))

    def insert(self, table, **values):
        self.session.execute(table.insert().values(**values))

    def ids(self, table):
        return sorted(r[0] for r in self.session.execute(table.select().with_only_columns(table.c.id)))


@pytest.fixture
def db():
    d = _Db()
    # Before the run: one of each, tenant 1.
    d.insert(d.parent, id=1, name="seed", tenant_id=1)
    d.insert(d.child, id=1, parent_id=1, tenant_id=1)
    d.insert(d.grandchild, id=1, child_id=1, tenant_id=1)
    d.insert(d.version, id=1, transaction_id=1)
    d.session.commit()
    return d


def _snap(residue, d):
    return residue.snapshot(d.session, d.declared, d.set_local)


def test_the_snapshot_lists_every_declared_table_and_nothing_else(residue, db):
    assert _snap(residue, db) == {"parent": [1], "child": [1], "grandchild": [1]}


def test_what_the_run_created_is_removed_children_first_and_what_was_there_is_not(residue, db):
    since = _snap(residue, db)
    # The run: a whole new branch (parent 2 <- child 2 <- grandchild 2) in tenant 7, a new child of the SEED parent.
    db.insert(db.parent, id=2, name="run", tenant_id=7)
    db.insert(db.child, id=2, parent_id=2, tenant_id=7)
    db.insert(db.grandchild, id=2, child_id=2, tenant_id=7)
    db.insert(db.child, id=3, parent_id=1, tenant_id=1)
    db.session.commit()
    reports = residue.purge(db.session, db.declared, since, set_local=db.set_local)
    assert db.ids(db.parent) == [1] and db.ids(db.child) == [1] and db.ids(db.grandchild) == [1]
    assert sum(len(r.removed) for r in reports) == 4
    assert all(not r.kept for r in reports)


def test_a_row_a_foreign_key_protects_is_kept_and_reported_not_forced(residue, db):
    since = _snap(residue, db)
    db.insert(db.parent, id=2, name="run", tenant_id=7)
    db.insert(db.parent, id=3, name="run2", tenant_id=7)
    db.insert(db.pin, id=1, parent_id=2)  # a table the registry does not know points at parent 2
    db.session.commit()
    reports = residue.purge(db.session, db.declared, since, set_local=db.set_local)
    assert db.ids(db.parent) == [1, 2], "parent 3 goes, parent 2 is protected"
    parent = next(r for r in reports if r.table == "parent")
    assert parent.removed == [3] and [row for row, _ in parent.kept] == [2]
    assert "still referenced" in parent.kept[0][1]


def test_the_version_rows_of_a_removed_row_go_with_it_and_only_those(residue, db):
    since = _snap(residue, db)
    db.insert(db.parent, id=2, name="run", tenant_id=7)
    db.insert(db.version, id=2, transaction_id=5)
    db.session.commit()
    reports = residue.purge(db.session, db.declared, since, set_local=db.set_local)
    assert db.ids(db.version) == [1]
    assert next(r for r in reports if r.table == "parent").versions_removed == 1


def test_a_dry_run_reports_and_changes_nothing(residue, db):
    since = _snap(residue, db)
    db.insert(db.parent, id=2, name="run", tenant_id=7)
    db.session.commit()
    reports = residue.purge(db.session, db.declared, since, dry_run=True, set_local=db.set_local)
    assert db.ids(db.parent) == [1, 2]
    assert reports[0].removed == [2]


def test_a_table_the_snapshot_never_saw_is_left_alone(residue, db):
    since = {"parent": [1], "child": [1]}  # no grandchild
    db.insert(db.grandchild, id=2, child_id=1, tenant_id=1)
    db.session.commit()
    residue.purge(db.session, db.declared, since, set_local=db.set_local)
    assert db.ids(db.grandchild) == [1, 2], "everything in an unknown table would look new; it is not guessed"


def test_the_cleanup_uses_exactly_the_two_row_level_security_settings_the_policies_offer(residue, db):
    since = _snap(residue, db)
    db.calls.clear()
    db.insert(db.parent, id=2, name="run", tenant_id=7)
    db.insert(db.parent, id=3, name="run2", tenant_id=9)
    db.session.commit()
    residue.purge(db.session, db.declared, since, set_local=db.set_local)
    assert ("app.cross_tenant_read", "on") in db.calls, "the rows are SEEN across tenants"
    assert ("app.tenant_ids", "7,9") in db.calls, "and deleted under exactly the tenants of the rows removed"
    assert {setting for setting, _ in db.calls} == {"app.cross_tenant_read", "app.tenant_ids"}


@pytest.mark.parametrize("env,refused", [
    ({"E2E_TEST_USERS_ENABLED": "true", "IDEABLE_EXECUTION_MODE": "dev"}, False),
    ({"E2E_TEST_USERS_ENABLED": "TRUE", "IDEABLE_EXECUTION_MODE": "staging"}, False),
    ({"E2E_TEST_USERS_ENABLED": "true", "IDEABLE_EXECUTION_MODE": "prod"}, True),
    ({"E2E_TEST_USERS_ENABLED": "true", "IDEABLE_EXECUTION_MODE": "PROD"}, True),
    ({"E2E_TEST_USERS_ENABLED": "true"}, True),
    ({"E2E_TEST_USERS_ENABLED": "true", "IDEABLE_EXECUTION_MODE": ""}, True),
    ({"IDEABLE_EXECUTION_MODE": "dev"}, True),
    ({"E2E_TEST_USERS_ENABLED": "false", "IDEABLE_EXECUTION_MODE": "dev"}, True),
    ({}, True),
])
def test_the_gate_fails_closed(residue, env, refused):
    assert (residue.gate_refusal(env) is not None) is refused


def test_a_refused_purge_deletes_nothing_and_does_not_even_read_the_snapshot(residue, capsys):
    assert residue.main(["--purge", "--since", "-"], env={}) == 1
    assert residue.main(["--purge", "--since", "-"], env={"E2E_TEST_USERS_ENABLED": "true", "IDEABLE_EXECUTION_MODE": "prod"}) == 1
