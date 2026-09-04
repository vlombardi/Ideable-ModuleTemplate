"""baseline schema

The whole schema of a fresh installation, in one migration. It replaces a five-revision chain
(baseline → trigram indexes → audit partitioning → partition-default convergence → tenant scoping)
that described the same end state as a sequence of edits, three of which existed only to convert a
database into a shape a fresh one is simply created in:

- a decompress-every-chunk dance, because TimescaleDB refuses `ADD COLUMN` on a compressed
  hypertable and `tenant_id` had to be added to one;
- a convergence revision that replaced a BEFORE INSERT trigger with a column default, for databases
  that had already applied the trigger version;
- an add-nullable / backfill / SET NOT NULL sequence for `tenant_id`.

None of that is reachable from an empty database, and there is no installation carrying the
intermediate shapes, so keeping it meant carrying three migrations whose only readers were
databases that do not exist. Squashed per `scripts/dev/schema.sh squash`; deployed databases are
stamped at this revision rather than re-running it.

This is the ONE migration allowed to be conditional, and it stays conditional per table. An earlier
version probed a single table (`template_items`) and assumed the rest of the schema tracked it: on a
fresh install the bootstrap had already created that one table, the probe took the adoption branch,
and the Continuum audit tables were never created at all. Per-table checks make that class of
mistake impossible — whatever state a database is in, this migration converges it.

What it does NOT do is transform an audit trail that already exists in an older shape. Creating what
is absent is safe and idempotent; rewriting a populated hypertable is neither, and the migrations
that did it are the ones being removed here.

Every migration AFTER this one must be unconditional, or the revision history stops describing the
schema and this whole design is pointless.

Revision ID: a1c0de5f1e2b
Revises:
Create Date: 2026-08-19
"""
from typing import Sequence, Union

import os

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c0de5f1e2b'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Audit metadata belongs to SQLAlchemy-Continuum, not to inline columns (audit-trail-specs.md
# §2.2bis). `CREATE TABLE IF NOT EXISTS` in a long-retired datamodel.sql created these once and
# never removed them, so databases that predate Alembic still carry them while no file declares
# them. Nothing reads them: the audit trail sources its timestamps from `transaction.issued_at`.
LEGACY_AUDIT_COLUMNS = (
    'au_creation_timestamp',
    'au_last_update_timestamp',
    'au_created_by_user',
    'au_last_updated_by_user',
)

# Sizes a chunk of the audit hypertables. A build-time shape, not a policy: the compression and
# retention windows are applied at runtime from the environment
# (scripts/runtime/config/audit-retention.sh), so changing how long audit data is kept never needs
# a migration. Baking a policy into the schema is how a deployment loses the ability to tune it.
CHUNK_INTERVAL = os.getenv('AUDIT_CHUNK_INTERVAL', '7 days')

AUDIT_TABLES = ('transaction', 'template_items_version')
TENANT_SCOPED_TABLES = ('template_items', 'template_items_version')


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    # `pg_trgm` serves the leading-wildcard ILIKE filters; `timescaledb` partitions the audit
    # tables. Both are extensions rather than schema, so IF NOT EXISTS is the whole story.
    op.execute('CREATE EXTENSION IF NOT EXISTS timescaledb')
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    # --- framework tables (every module has these) ---------------------------------------------
    # Created here rather than by the bootstrap job: a bootstrap that creates tables is a second
    # owner of the schema, which is exactly how the au_* drift was born. The bootstrap writes rows.
    if 'module_bootstrap_execution' not in existing:
        op.create_table(
            'module_bootstrap_execution',
            sa.Column('script_key', sa.Text(), nullable=False),
            sa.Column('executed_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('script_key'),
        )
    if 'module_runtime_meta' not in existing:
        op.create_table(
            'module_runtime_meta',
            sa.Column('key', sa.Text(), nullable=False),
            sa.Column('value', sa.TIMESTAMP(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('key'),
        )

    # --- the module's own entity ----------------------------------------------------------------
    if 'template_items' not in existing:
        op.create_table(
            'template_items',
            sa.Column('id', sa.Integer(), nullable=False),
            # NOT NULL by design: a row with no tenant is a row no filter excludes, which is
            # exactly the leak this column exists to prevent.
            sa.Column('tenant_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        _create_item_indexes(set())
    else:
        # Adoption path: reconcile a schema that predates Alembic. Column and index work only —
        # cheap, idempotent, and nothing here rewrites a table.
        inspector = sa.inspect(bind)
        columns = {c['name'] for c in inspector.get_columns('template_items')}
        for column in LEGACY_AUDIT_COLUMNS:
            if column in columns:
                op.drop_column('template_items', column)
        if 'tenant_id' not in columns:
            # Added nullable, backfilled, then tightened: a NOT NULL column cannot be added to a
            # populated table, and a column DEFAULT would keep silently assigning a tenant to
            # future rows that forgot to set one — which is the leak, deferred.
            default_tenant = int(os.getenv('DEFAULT_TENANT_ID', '1'))
            op.execute('ALTER TABLE template_items ADD COLUMN tenant_id INTEGER')
            op.execute(f'UPDATE template_items SET tenant_id = {default_tenant}')
            op.execute('ALTER TABLE template_items ALTER COLUMN tenant_id SET NOT NULL')
        _create_item_indexes({i['name'] for i in inspector.get_indexes('template_items')})

    # --- audit trail (generated by SQLAlchemy-Continuum from __versioned__) ---------------------
    if 'transaction' not in existing:
        op.create_table(
            'transaction',
            sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column('remote_addr', sa.String(length=50), nullable=True),
            # timestamptz and NOT NULL: `timestamp without time zone` cannot express an instant and
            # the audit trail is read across timezones, and TimescaleDB requires the partition
            # column to be NOT NULL. The primary key widens to include it for the same reason —
            # every unique index on a hypertable must contain the partition column.
            sa.Column('issued_at', sa.TIMESTAMP(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id', 'issued_at'),
        )
    if 'transaction_meta' not in existing:
        op.create_table(
            'transaction_meta',
            sa.Column('transaction_id', sa.BigInteger(), nullable=False),
            sa.Column('key', sa.Unicode(length=255), nullable=False),
            sa.Column('value', sa.UnicodeText(), nullable=True),
            sa.PrimaryKeyConstraint('transaction_id', 'key'),
        )
    if 'template_items_version' not in existing:
        op.create_table(
            'template_items_version',
            sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
            # Continuum mirrors the entity's columns, so `tenant_id` arrives here for free — and
            # the history query filters on it, so a forgotten check upstream cannot expose another
            # tenant's history. Nullable, as every mirrored column is.
            sa.Column('tenant_id', sa.Integer(), autoincrement=False, nullable=True),
            sa.Column('name', sa.String(length=255), autoincrement=False, nullable=True),
            sa.Column('description', sa.Text(), autoincrement=False, nullable=True),
            sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
            sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
            sa.Column('operation_type', sa.SmallInteger(), nullable=False),
            # The version table has no time column of its own, only `transaction_id`, so the
            # transaction's instant is denormalised onto it to partition by.
            #
            # A column DEFAULT, and deliberately NOT a BEFORE INSERT trigger: Continuum's INSERT
            # omits the column, and TimescaleDB rejects a NULL partition value BEFORE a row-level
            # trigger runs ("Columns used for time partitioning cannot be NULL"), so the trigger
            # version made every write to a versioned entity return a 500.
            sa.Column('issued_at', sa.TIMESTAMP(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id', 'transaction_id', 'issued_at'),
        )
        op.create_index('ix_template_items_version_end_transaction_id',
                        'template_items_version', ['end_transaction_id'], unique=False)
        # `index=True` is redundant on the entity (its primary key indexes id) but Continuum
        # mirrors the flag here, where the primary key leads with (id, transaction_id) and the
        # history endpoint filters by `id` alone.
        op.create_index('ix_template_items_version_id',
                        'template_items_version', ['id'], unique=False)
        op.create_index('ix_template_items_version_operation_type',
                        'template_items_version', ['operation_type'], unique=False)
        op.create_index('ix_template_items_version_transaction_id',
                        'template_items_version', ['transaction_id'], unique=False)
        op.create_index('ix_template_items_version_tenant_id',
                        'template_items_version', ['tenant_id'], unique=False)

    # --- hypertables ----------------------------------------------------------------------------
    # Audit growth becomes bounded: chunks can be compressed and expired by policy. `if_not_exists`
    # makes this idempotent, and `migrate_data` covers the case where rows were written between the
    # CREATE TABLE above and this call (none, on a fresh install).
    for table in AUDIT_TABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', 'issued_at', "
            f"chunk_time_interval => INTERVAL '{CHUNK_INTERVAL}', migrate_data => true, "
            f"if_not_exists => true)"
        )

    # --- Row-Level Security ---------------------------------------------------------------------
    # The layer that survives a mistake: if a future query forgets its tenant filter, the database
    # still refuses the rows. Derived modules are written by different people at different times,
    # so the guarantee cannot rest on everyone remembering.
    #
    # Two settings are read, mirroring the two authorisations in auth.TenantScope, and the split is
    # the point: `app.tenant_ids` governs everything, `app.cross_tenant_read` only widens SELECT.
    # A cross-tenant reader therefore cannot write across tenants even at the database layer —
    # verified against the policies: `UPDATE 0`, `DELETE 0`, and an INSERT into another tenant
    # refused outright.
    for table in TENANT_SCOPED_TABLES:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        # FORCE, or the table owner is exempt even when it is not a superuser — and the whole layer
        # becomes decorative. (The application does not connect as the owner either: superusers
        # bypass RLS unconditionally. See the app role in docker-compose.yml.)
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')

        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
        # FOR ALL, so it governs SELECT, INSERT, UPDATE and DELETE. `current_setting(…, true)`
        # yields NULL when the setting is absent, and NULL matches no rows: a transaction that has
        # not said who is asking sees nothing and can write nothing. Fail closed.
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = ANY (
                    string_to_array(current_setting('app.tenant_ids', true), ',')::int[]
                )
            )
        """)

        op.execute(f'DROP POLICY IF EXISTS tenant_cross_read ON {table}')
        # FOR SELECT, and that is the whole security argument: permissive policies are OR-ed per
        # command, so this widens reads and touches no other command. It is set only for a caller
        # holding template.items:read_all_tenants (crud.apply_tenant_guc), which is a read
        # permission — granting visibility must not grant authority.
        op.execute(f"""
            CREATE POLICY tenant_cross_read ON {table}
            FOR SELECT
            USING (current_setting('app.cross_tenant_read', true) = 'on')
        """)

    _create_trigram_indexes()


def _create_item_indexes(existing_indexes: set) -> None:
    """B-tree indexes on the entity. `tenant_id` LEADS the composite ones.

    Isolation bolted on top of an index that does not lead with the tenant scans every tenant's
    rows and filters afterwards, which gives back the gains the query tuning measured.
    """
    wanted = (
        ('ix_template_items_id', ['id']),
        ('idx_template_items_name', ['name']),
        ('ix_template_items_tenant_id', ['tenant_id']),
        ('idx_template_items_tenant_id', ['tenant_id', 'id']),
        ('idx_template_items_tenant_name', ['tenant_id', 'name']),
    )
    for name, columns in wanted:
        if name not in existing_indexes:
            op.create_index(name, 'template_items', columns, unique=False)


def _create_trigram_indexes() -> None:
    """GIN trigram indexes for the `ILIKE '%term%'` filters.

    A LEADING wildcard is something no B-tree can serve, so every keystroke in a filter box was a
    sequential scan of the whole table — and one such scan saturates shared buffers for every other
    user at the same time. Measured on 1,000,000 rows: 543 ms parallel sequential scan → 2.6 ms
    bitmap index scan.

    Two things here that autogenerate cannot know:

    1. CREATE INDEX CONCURRENTLY, inside an autocommit block. A plain CREATE INDEX takes an ACCESS
       EXCLUSIVE lock and blocks every write for the duration, which on a large table is a write
       outage; CONCURRENTLY cannot run inside a transaction, which is what the block is for.
    2. A bounded `maintenance_work_mem`. Building these with the server default killed the database
       during development: the TimescaleDB image derives it from the HOST's memory (~980 MB) while
       the container is limited to 1 GB, so one index build exceeded the cgroup and Postgres was
       OOM-killed. 64 MB builds the same index on 1M rows in ~10 s and cannot take the database
       down — a migration that kills the database is worse than one that blocks it.
    """
    with op.get_context().autocommit_block():
        op.execute("SET maintenance_work_mem = '64MB'")
        # IF NOT EXISTS because a CONCURRENTLY build that fails leaves an INVALID index behind, and
        # re-running must not then fail on the name.
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_template_items_name_trgm '
            'ON template_items USING gin (name gin_trgm_ops)'
        )
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_template_items_description_trgm '
            'ON template_items USING gin (description gin_trgm_ops)'
        )


def downgrade() -> None:
    """Drop the ORM-owned tables.

    DESTRUCTIVE, and it reopens a cross-tenant read on the way: the policies go with the tables.
    Treat a rollback as a security incident rather than a routine revert, and back up first
    (scripts/runtime/config/backup.sh).

    The legacy `au_*` columns are deliberately NOT recreated: they held no data any code reads, and
    restoring them would reintroduce the schema the audit-trail spec forbids. The extensions are
    not dropped either — other objects may depend on them, and dropping an extension to undo a
    table is a far larger action than this migration took.
    """
    op.execute('DROP TABLE IF EXISTS template_items_version CASCADE')
    op.execute('DROP TABLE IF EXISTS transaction_meta CASCADE')
    op.execute('DROP TABLE IF EXISTS transaction CASCADE')
    op.execute('DROP TABLE IF EXISTS template_items CASCADE')
    op.execute('DROP TABLE IF EXISTS module_runtime_meta CASCADE')
    op.execute('DROP TABLE IF EXISTS module_bootstrap_execution CASCADE')
