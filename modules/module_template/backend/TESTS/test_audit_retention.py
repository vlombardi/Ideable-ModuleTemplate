"""Audit tables are time-partitioned, with compression and retention driven by configuration.

Continuum writes 3–4 rows per modifying request and nothing ever pruned them: the audit tables
grew monotonically, backups lengthened, and restore drifted past the backup/restore RTO. They are now
TimescaleDB hypertables, so old chunks can be compressed and expired.

Two things this task measured rather than assumed:

- **The shared `transaction` sequence is not the write bottleneck.** 10,000 POSTs at c=50 gave 357
  writes/s through the API; the identical 4-row write pattern via pgbench gave 1,157 tps. The
  application delivers ~31% of the database's ceiling, so sequence CACHE, a per-module versioning
  schema, or replacing Continuum would each buy nothing measurable today.
- **Chunk exclusion works**: a 10-day window over 60 days of history scanned 2 chunks of 9.
"""
import re
from pathlib import Path

# Derived, never named: this file is force-synced verbatim into every remote module project, where
# the module and its entities carry the module's own names (rules/testing-guidelines.md).
_MODULE_DIR = Path(__file__).resolve().parents[2]


def _entity_tables() -> set[str]:
    """The tables this module AUTHORS, read from the one authored definition.

    A literal `template_items` in a force-synced test asserts about the reference module's example
    entity, which a real module does not have — so the check silently stopped applying to the only
    tables it protects. `app/models.py` is the schema's source of truth, and `__tablename__` is
    still the right answer in a module whose entities are companies and assets.
    """
    models = _MODULE_DIR / "backend" / "SOURCES" / "app" / "models.py"
    tables = set(re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]",
                            models.read_text(encoding="utf-8")))
    assert tables, "app/models.py declares no __tablename__ — the extraction has drifted"
    return tables


_APP = Path(__file__).resolve().parents[1] / "SOURCES" / "app"
_VERSIONS = _APP.parent / "alembic" / "versions"
_MIGRATIONS = "".join(p.read_text(encoding="utf-8") for p in _VERSIONS.glob("*.py"))
_PARTITIONING = (_APP / "audit_partitioning.py").read_text(encoding="utf-8")
_RETENTION_SH = (
    Path(__file__).resolve().parents[4] / "scripts" / "runtime" / "config" / "audit-retention.sh"
).read_text(encoding="utf-8")


class TestPartitioningMetadata:
    """The conversion has to be in the ORM metadata, or autogenerate proposes undoing it."""

    def test_partition_column_is_declared_not_null(self):
        assert "nullable=False" in _PARTITIONING

    def test_partition_column_has_a_server_default(self):
        """Continuum's INSERT omits the column, and TimescaleDB rejects a NULL partition value
        before a row-level BEFORE INSERT trigger can fill it. A trigger here returned 500 on
        every write to a versioned entity."""
        assert "server_default=text('now()')" in _PARTITIONING

    def test_primary_keys_include_the_partition_column(self):
        """TimescaleDB requires every unique index to contain the partition column."""
        assert "PrimaryKeyConstraint(*key_columns, PARTITION_COLUMN)" in _PARTITIONING

    def test_the_partition_index_is_declared_descending(self):
        """create_hypertable() builds it DESC; declared ASC, autogenerate churns it every run."""
        assert "table.c[PARTITION_COLUMN].desc()" in _PARTITIONING

    def test_metadata_is_applied_in_the_app_and_in_alembic(self):
        for path in (_APP / "main.py", _VERSIONS.parent / "env.py"):
            assert "apply_audit_partitioning_metadata" in path.read_text(encoding="utf-8"), (
                f"{path.name} does not apply the partitioning metadata — the two would disagree"
            )


class TestMigration:

    def test_tables_become_hypertables(self):
        assert "create_hypertable" in _MIGRATIONS
        for table in {"transaction"} | {f"{t}_version" for t in _entity_tables()}:
            assert table in _MIGRATIONS

    def test_no_trigger_fills_the_partition_column(self):
        """The trigger approach failed; a default cannot lose the race.

        The migrations were squashed into one baseline, so the default is now declared on the column
        as it is created rather than applied by a later ALTER. Asserted as the *property* — the
        partition column has a `now()` default and nothing installs a trigger — because tying it to
        one migration's spelling is what made this test fail on a squash that changed nothing about
        the behaviour.
        """
        assert "CREATE TRIGGER set_issued_at" not in _MIGRATIONS
        assert "audit_version_issued_at" not in _MIGRATIONS
        declares_default = (
            "ALTER COLUMN issued_at SET DEFAULT now()" in _MIGRATIONS
            or re.search(
                # Bounded and non-greedy: the column declaration spans two lines and contains
                # its own parentheses, so `[^)]*` cannot cross it.
                r"'issued_at'[\s\S]{0,200}?server_default=sa\.text\('now\(\)'\)",
                _MIGRATIONS, re.S,
            ) is not None
        )
        assert declares_default, (
            "the partition column has no now() default — Continuum's INSERT omits it and "
            "TimescaleDB rejects a NULL partition value before any row-level trigger runs"
        )

    def test_a_not_null_column_is_never_added_without_a_backfill(self):
        """A NOT NULL column cannot be added to a populated table without dating history wrongly.

        Checked per migration and per column rather than against one named revision: the rule is
        about every migration that ever tightens a column, and the revision that used to hold the
        only example has been squashed away. What survives is the baseline's adoption branch for
        `tenant_id`, and the next migration to do this will be caught too.
        """
        pattern = re.compile(r"ALTER COLUMN (\w+) SET NOT NULL")
        checked = 0
        for path in sorted(_VERSIONS.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for match in pattern.finditer(source):
                column, tighten = match.group(1), match.start()
                before = source[:tighten]
                # A column created NOT NULL in the same migration needs no backfill: there are no
                # rows yet. Only a column ADDed to an existing table does.
                if f"ADD COLUMN {column}" not in before and \
                        f"ADD COLUMN IF NOT EXISTS {column}" not in before:
                    continue
                checked += 1
                assert re.search(rf"UPDATE \w+ SET {column} =", before), (
                    f"{path.name} tightens {column} to NOT NULL after adding it to an existing "
                    f"table, with no backfill in between — the ALTER fails on any populated "
                    f"database"
                )
        assert checked, (
            "no add-then-tighten sequence found to check — if the pattern has genuinely gone, "
            "delete this test rather than leaving it passing vacuously"
        )

    def test_chunk_interval_is_configurable(self):
        assert "AUDIT_CHUNK_INTERVAL" in _MIGRATIONS


class TestRetentionIsConfigurationNotCode:

    def test_policies_are_applied_at_runtime_from_env(self):
        """Changing how long audit history stays online must not require a migration."""
        for var in ("AUDIT_COMPRESS_AFTER", "AUDIT_RETAIN_FOR", "AUDIT_ARCHIVE_DIR"):
            assert var in _RETENTION_SH
        assert "add_retention_policy" not in _MIGRATIONS, (
            "retention belongs to the deployment, not to the schema"
        )

    def test_retention_is_off_by_default(self):
        """Deleting audit history is never a default."""
        assert 'RETAIN_FOR="${AUDIT_RETAIN_FOR-}"' in _RETENTION_SH

    def test_retention_refuses_to_run_without_an_archive(self):
        """A retention policy that runs before archival is data loss on a schedule."""
        assert "AUDIT_ARCHIVE_OPTOUT" in _RETENTION_SH
        assert "Dropping audit chunks without archiving them is data loss" in _RETENTION_SH

    def test_archive_is_checksummed(self):
        """'Archived' must be verifiable, not assumed."""
        assert "shasum -a 256" in _RETENTION_SH

    def test_policy_application_is_idempotent(self):
        """It runs on every deploy and must converge, not accumulate policies."""
        assert "remove_compression_policy" in _RETENTION_SH
        assert "remove_retention_policy" in _RETENTION_SH
