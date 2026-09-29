"""sub_items sub_item_notes description trigram indexes

Revision ID: 06cf2414e715
Revises: 041b319b9b9d
Create Date: 2026-09-26 23:17:48.583347
"""
from typing import Sequence, Union

from alembic import op


revision: str = '06cf2414e715'
down_revision: Union[str, None] = '041b319b9b9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Trigram GIN indexes are expression indexes, which autogenerate cannot diff (see
    # `alembic/env.py`'s `_include_object` and `_rewrite_create_table`) — hand-written here, the
    # same way the tables' own baseline/creation migrations wrote their `name` trigram indexes.
    op.create_index(
        'idx_sub_items_description_trgm', 'sub_items', ['description'],
        unique=False, postgresql_using='gin', postgresql_ops={'description': 'gin_trgm_ops'},
    )
    op.create_index(
        'idx_sub_item_notes_description_trgm', 'sub_item_notes', ['description'],
        unique=False, postgresql_using='gin', postgresql_ops={'description': 'gin_trgm_ops'},
    )


def downgrade() -> None:
    op.drop_index('idx_sub_item_notes_description_trgm', table_name='sub_item_notes')
    op.drop_index('idx_sub_items_description_trgm', table_name='sub_items')
