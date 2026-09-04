"""Framework-owned tables.

These are not part of a module's datamodel — every Ideable module has them, and a module
developer neither designs nor edits them. They live apart from `models.py` for two reasons:

1. `models.py` is regenerated from the design database during the schema workflow (see
   `scripts/dev/schema.sh model`). Anything in it can be overwritten; anything here survives.
2. They must still be declared to SQLAlchemy, because Alembic owns all DDL now. A table that is
   absent from the metadata is a table autogenerate proposes to DROP.

The bootstrap job writes *rows* here (`script_key` ledger entries, the `system_epoch` instant);
it no longer creates the tables. Schema is Alembic's, data is the bootstrap's.
"""
from datetime import datetime

from sqlalchemy import TIMESTAMP, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ModuleBootstrapExecution(Base):
    """Ledger of one-shot bootstrap scripts, so re-running the job is a no-op."""

    # Not tenant data: one row per bootstrap script for the whole installation. Partitioning it by
    # tenant would make the ledger re-run scripts once per tenant.
    __tenant_scoped__ = False

    __tablename__ = 'module_bootstrap_execution'

    script_key: Mapped[str] = mapped_column(Text, primary_key=True)
    executed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class ModuleRuntimeMeta(Base):
    """Values that must be identical for every worker, replica and redeploy.

    `system_epoch` is the reference instant for synthetic audit-creation rows: derived per
    process it differs between workers and changes on restart, which makes the audit trail
    report different creation timestamps for the same record.
    """

    # Not tenant data, and deliberately so: `system_epoch` must be IDENTICAL for every worker,
    # replica and tenant. A per-tenant value is the bug this table was created to fix.
    __tenant_scoped__ = False

    __tablename__ = 'module_runtime_meta'

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
