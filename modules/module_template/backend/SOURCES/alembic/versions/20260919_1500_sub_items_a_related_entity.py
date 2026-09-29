"""sub_items — the second, related entity the plan's example needed

`template_items` alone cannot demonstrate a master/detail page, FK-ordered create/delete, or the
N+1 guard on a real relationship (`an-entity-is-served-by-the-framework-unless-it-says-otherwise`,
sub-set 7). This migration is UNCONDITIONAL, per the baseline migration's own rule — every
migration after it describes one known-empty starting state, not a database that might already
carry the table in some other shape.

Mirrors `template_items`'s shape exactly: tenant-scoped, Continuum-versioned, RLS, a trigram index
on the one ILIKE-filterable text column. What's new is `item_fk`, a plain (RESTRICT) foreign key
to `template_items` — an item cannot be deleted while a sub_item still points at it, which is
exactly why the FK-ordered Playwright spec creates the item first and deletes the sub_item first.

Revision ID: 2611b5d150a7
Revises: a1c0de5f1e2b
Create Date: 2026-09-19 15:00:00
"""
from typing import Sequence, Union

import os

from alembic import op
import sqlalchemy as sa

revision: str = '2611b5d150a7'
down_revision: Union[str, None] = 'a1c0de5f1e2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHUNK_INTERVAL = os.getenv('AUDIT_CHUNK_INTERVAL', '7 days')


def upgrade() -> None:
    op.create_table(
        'sub_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('item_fk', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['item_fk'], ['template_items.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sub_items_id', 'sub_items', ['id'], unique=False)
    op.create_index('ix_sub_items_tenant_id', 'sub_items', ['tenant_id'], unique=False)
    op.create_index('idx_sub_items_tenant_id', 'sub_items', ['tenant_id', 'id'], unique=False)
    op.create_index('idx_sub_items_name', 'sub_items', ['name'], unique=False)
    op.create_index('idx_sub_items_item_fk', 'sub_items', ['item_fk'], unique=False)

    op.create_table(
        'sub_items_version',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('tenant_id', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('item_fk', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('name', sa.String(length=255), autoincrement=False, nullable=True),
        sa.Column('description', sa.Text(), autoincrement=False, nullable=True),
        sa.Column('transaction_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('end_transaction_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_type', sa.SmallInteger(), nullable=False),
        sa.Column('issued_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', 'transaction_id', 'issued_at'),
    )
    op.create_index('ix_sub_items_version_end_transaction_id',
                     'sub_items_version', ['end_transaction_id'], unique=False)
    op.create_index('ix_sub_items_version_id', 'sub_items_version', ['id'], unique=False)
    op.create_index('ix_sub_items_version_operation_type',
                     'sub_items_version', ['operation_type'], unique=False)
    op.create_index('ix_sub_items_version_transaction_id',
                     'sub_items_version', ['transaction_id'], unique=False)
    op.create_index('ix_sub_items_version_tenant_id',
                     'sub_items_version', ['tenant_id'], unique=False)

    op.execute(
        f"SELECT create_hypertable('sub_items_version', 'issued_at', "
        f"chunk_time_interval => INTERVAL '{CHUNK_INTERVAL}', migrate_data => true, "
        f"if_not_exists => true)"
    )

    for table in ('sub_items', 'sub_items_version'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')

        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                tenant_id = ANY (
                    string_to_array(current_setting('app.tenant_ids', true), ',')::int[]
                )
            )
        """)

        op.execute(f'DROP POLICY IF EXISTS tenant_cross_read ON {table}')
        op.execute(f"""
            CREATE POLICY tenant_cross_read ON {table}
            FOR SELECT
            USING (current_setting('app.cross_tenant_read', true) = 'on')
        """)

    # CONCURRENTLY, autocommit, bounded maintenance_work_mem — see the baseline migration's
    # `_create_trigram_indexes` for the measured reasons behind all three.
    with op.get_context().autocommit_block():
        op.execute("SET maintenance_work_mem = '64MB'")
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sub_items_name_trgm '
            'ON sub_items USING gin (name gin_trgm_ops)'
        )


def downgrade() -> None:
    """DESTRUCTIVE — see the baseline migration's downgrade for the same warning."""
    op.execute('DROP TABLE IF EXISTS sub_items_version CASCADE')
    op.execute('DROP TABLE IF EXISTS sub_items CASCADE')
