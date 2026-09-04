from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class TemplateItem(Base):
    __versioned__: dict = {}

    # Mandatory on every model, and checked at build time by
    # scripts/common/check_tenancy_markers.py: True means the rows are partitioned by tenant, and
    # the gate then insists `tenant_id` exists. A new table added without either is a build
    # failure, because the alternative is a table that silently holds every customer's rows and
    # whose queries look correct.
    __tenant_scoped__ = True

    # What a client may filter and sort by. Declared, never inferred: exposing every column to
    # `ILIKE '%…%'` puts a sequential scan behind any field without a trigram index, and accepting an
    # arbitrary `sort_by` lets a caller order by a column the planner has no index for. The generic
    # CRUD in `crud.py` reads these; adding an entity means declaring them, not editing crud.
    #
    # A filterable column SHOULD have the matching index — `name` and `description` have trigram GIN
    # indexes below for exactly this reason.
    __filterable__ = ('name', 'description')
    __sortable__ = ('id', 'name', 'description')

    __tablename__ = 'template_items'

    # The model is the schema's source of truth now that Alembic owns migrations, so it must
    # describe what the database actually has — including the index the migration creates, under
    # its existing name. Any difference here shows up as drift in `alembic check`.
    __table_args__ = (
        Index('idx_template_items_name', 'name'),
        # tenant_id LEADS every index. A trigram index on `name` alone would be searched across
        # every tenant's rows and then filtered, so isolation would cost back the query-performance work gains;
        # leading with the tenant makes a query touch one tenant's data.
        Index('idx_template_items_tenant_id', 'tenant_id', 'id'),
        Index('idx_template_items_tenant_name', 'tenant_id', 'name'),
        # Trigram GIN indexes. The table filters use `ILIKE '%term%'` — a LEADING wildcard, which
        # no B-tree can serve, so every keystroke was a sequential scan over the whole table.
        # Measured on 1,000,000 rows: 543 ms sequential scan → 2.6 ms bitmap index scan.
        Index('idx_template_items_name_trgm', 'name',
              postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_template_items_description_trgm', 'description',
              postgresql_using='gin', postgresql_ops={'description': 'gin_trgm_ops'}),
    )

    # `index=True` is redundant on the base table (the PK already indexes it) but Continuum
    # mirrors the flag onto `template_items_version`, whose primary key is (id, transaction_id) —
    # and the history endpoint filters that table by `id` alone. Dropping the flag would remove
    # the index the audit-trail query depends on.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Non-nullable by design: a row with no tenant is a row no filter excludes, which is exactly
    # the leak this column exists to prevent.
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
