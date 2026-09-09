"""Time-partitioning metadata for the audit tables.

The versioning-table retention work converts `transaction` and the Continuum version tables into TimescaleDB hypertables so
audit growth is bounded and old chunks can be compressed and expired. Two schema facts have to be
true before TimescaleDB will accept the conversion, and both must also be true in the ORM
metadata, or `alembic check` proposes undoing them on the next autogenerate:

1. **The partition column must be NOT NULL.** `transaction.issued_at` was nullable.
2. **Every unique index must contain the partition column.** So the primary keys become
   `(id, issued_at)` and `(id, transaction_id, issued_at)`.

The version tables have no time column at all — only `transaction_id` — so `issued_at` is
denormalised onto them. It is filled by a column default rather than by
application code: Continuum writes these rows inside its own flush without mentioning the column,
and the default applies to every writer — this application, migrations, shells alike.

Continuum builds these tables during `configure_mappers()`, so this runs after that — in the app
and in alembic/env.py alike, which is why it lives in a function rather than at import.
"""
from sqlalchemy import Column, DateTime, Index, PrimaryKeyConstraint, text

# Denormalised onto every version table; also the partition column of `transaction`.
PARTITION_COLUMN = 'issued_at'


def apply_audit_partitioning_metadata(metadata) -> None:
    """Add `issued_at` and widen the primary keys, in metadata, for the audit tables."""
    for name, table in metadata.tables.items():
        is_version = name.endswith('_version')
        if not (is_version or name == 'transaction'):
            continue

        if PARTITION_COLUMN not in table.c:
            # Version tables gain the column; `transaction` already has it.
            # server_default rather than a trigger: Continuum's INSERT does not mention the
            # column at all, and TimescaleDB rejects a NULL partition value before a row-level
            # BEFORE INSERT trigger can fill it ("Columns used for time partitioning cannot be
            # NULL"). The default is applied by the database itself, so it cannot lose that race
            # — and the version row is written inside the same transaction whose `issued_at` it
            # mirrors, so now() and that instant differ by microseconds. Display still reads the
            # transaction's own value; this column exists to partition by.
            table.append_column(Column(
                PARTITION_COLUMN, DateTime(timezone=True),
                nullable=False, server_default=text('now()'),
            ))
        else:
            # A hypertable's partition column cannot be nullable, and Continuum declares
            # `issued_at` without a timezone — which cannot express an instant, and the audit
            # trail is read across timezones.
            table.c[PARTITION_COLUMN].nullable = False
            table.c[PARTITION_COLUMN].type = DateTime(timezone=True)

        # create_hypertable() builds an index on the partition column itself. Undeclared, it is
        # an index autogenerate would propose dropping — which would un-optimise the partitioning
        # on the next migration anyone generates.
        # DESC, because that is how create_hypertable() builds it — newest chunk first, which is
        # also the order every audit query wants.
        index_name = f'{name}_{PARTITION_COLUMN}_idx'
        if not any(i.name == index_name for i in table.indexes):
            Index(index_name, table.c[PARTITION_COLUMN].desc())

        key_columns = [c.name for c in table.primary_key.columns]
        if PARTITION_COLUMN not in key_columns:
            # `table.primary_key.columns` is read-only, so the constraint is replaced rather than
            # mutated: drop the existing one and append a wider one.
            table.constraints = {
                c for c in table.constraints if not isinstance(c, PrimaryKeyConstraint)
            }
            table.append_constraint(
                PrimaryKeyConstraint(*key_columns, PARTITION_COLUMN)
            )
