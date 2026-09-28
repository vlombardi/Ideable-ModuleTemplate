from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


class TemplateItem(Base):
    __versioned__: dict = {}

    # Mandatory on every model, and checked at build time by
    # scripts/dev/common/check_tenancy_markers.py: True means the rows are partitioned by tenant, and
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


class SubItem(Base):
    """A row that belongs to one `TemplateItem` — the plan's worked example of a related entity.

    Exists to make the framework's example a real one rather than a single flat table: a master
    page needs an associated table under it (`StandardEntityPage`'s `detail(row)`), FK-ordered
    create/delete needs a real foreign key, and the N+1 guard
    (`test_every_entity_declares_an_eager_load_plan_for_its_relationships`) needs a read schema
    that actually exposes a relationship — `item_name`, below, via `item`.
    """

    __versioned__: dict = {}

    __tenant_scoped__ = True

    # `item_fk` is an exact-match lookup ("which item's sub-items"), never a text search — the
    # generic query core picks the operator from the column's SQL type
    # (`ideable_api.query._is_exact_match_column`), so declaring it filterable does not put an
    # `ILIKE` behind an integer column the way `name` needs one.
    __filterable__ = ('name', 'description', 'item_fk')
    __sortable__ = ('id', 'name', 'item_fk')

    __tablename__ = 'sub_items'

    __table_args__ = (
        Index('idx_sub_items_name', 'name'),
        Index('idx_sub_items_tenant_id', 'tenant_id', 'id'),
        Index('idx_sub_items_item_fk', 'item_fk'),
        Index('idx_sub_items_name_trgm', 'name',
              postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_sub_items_description_trgm', 'description',
              postgresql_using='gin', postgresql_ops={'description': 'gin_trgm_ops'}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # RESTRICT (the default): a `sub_item` outlives no `item` it points at, which is exactly why
    # FK-ordered tests create the item first and delete the sub_item first — an item with
    # sub_items still attached must refuse deletion, not cascade it silently away.
    item_fk: Mapped[int] = mapped_column(Integer, ForeignKey('template_items.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    item: Mapped['TemplateItem'] = relationship('TemplateItem', lazy='raise')

    @property
    def item_name(self) -> str | None:
        """The parent item's name, for `SubItemRead` — requires `item` to already be loaded.

        `lazy='raise'` on the relationship makes that requirement a loud failure rather than a
        silent N+1: reading `self.item` without the descriptor's eager-load plan raises instead of
        issuing one query per row.
        """
        return self.item.name if self.item is not None else None


class SubItemNote(Base):
    """A row that belongs to one `SubItem` — the third level of the chain.

    WHY A THIRD LEVEL. `items → sub_items` demonstrates Depth and nothing else: a one-level
    association has nothing reachable beyond itself, so the standard page's Depth visit / Full
    perspective toggle has no second reading to offer, and the Widget Examples gallery — the place a
    module maintainer reads what the framework gives them — could show the master table and not the
    half of the entry that is hardest to get right. With a level under `sub_items`, Depth reads the
    selected sub-item's notes and Full reads every note reachable from the selected ITEM, so the
    toggle visibly changes the table.

    Same shape as its two parents, deliberately: `name` + `description`, `tenant_id` non-null, the
    FK RESTRICT so a sub-item with notes refuses deletion rather than cascading them away, and the
    trigram index `name` needs for its `ILIKE '%term%'` filter.
    """

    __versioned__: dict = {}

    __tenant_scoped__ = True

    # `sub_item_fk` is an exact-match lookup, not a text search — the generic query core picks the
    # operator from the column's SQL type, so declaring it filterable puts no `ILIKE` behind it.
    __filterable__ = ('name', 'description', 'sub_item_fk')
    __sortable__ = ('id', 'name', 'sub_item_fk')

    __tablename__ = 'sub_item_notes'

    __table_args__ = (
        Index('idx_sub_item_notes_name', 'name'),
        Index('idx_sub_item_notes_tenant_id', 'tenant_id', 'id'),
        Index('idx_sub_item_notes_sub_item_fk', 'sub_item_fk'),
        Index('idx_sub_item_notes_name_trgm', 'name',
              postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_sub_item_notes_description_trgm', 'description',
              postgresql_using='gin', postgresql_ops={'description': 'gin_trgm_ops'}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sub_item_fk: Mapped[int] = mapped_column(Integer, ForeignKey('sub_items.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sub_item: Mapped['SubItem'] = relationship('SubItem', lazy='raise')

    @property
    def sub_item_name(self) -> str | None:
        """The parent sub-item's name, for `SubItemNoteRead` — the same eager-load contract
        `SubItem.item_name` states, and for the same reason."""
        return self.sub_item.name if self.sub_item is not None else None
