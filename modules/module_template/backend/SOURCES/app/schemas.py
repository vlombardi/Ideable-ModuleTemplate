from datetime import datetime
from pydantic import BaseModel


class TemplateItemBase(BaseModel):
    name: str
    description: str | None = None


class TemplateItemCreate(TemplateItemBase):
    # Optional: omit it when the token authorises exactly one tenant — requiring clients to echo
    # back their own tenant mostly invites them to send the wrong one. Naming a tenant outside the
    # caller's scope is a 403.
    tenant_id: int | None = None


class TemplateItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class TemplateItemRead(TemplateItemBase):
    id: int
    tenant_id: int

    class Config:
        from_attributes = True


class TemplateItemsPage(BaseModel):
    items: list[TemplateItemRead]
    total: int
    # A client that renders "1–50 of 12,431" must know whether that number can be trusted. Above
    # EXACT_COUNT_THRESHOLD the total is the planner's estimate, and saying so is the difference
    # between an approximation and a wrong number.
    total_is_exact: bool = True
    # Cursor for the next page: pass back as `after_id` for constant-time sequential navigation.
    # None when this is the last page.
    next_after_id: int | None = None
    page: int
    size: int
    pages: int


class BaseVersion(BaseModel):
    """Common fields for every SQLAlchemy-Continuum version schema.

    All entity-specific *Version schemas must inherit from this base so that
    history endpoints and the frontend ``AuditTrailPopup`` receive a uniform
    shape for audit metadata and association-change fields.
    """
    transaction_id: int
    operation_type: int
    end_transaction_id: int | None = None
    id: int | None = None
    # Association-change fields (populated when operation_type is 3=ASSOCIATE or 4=DISASSOCIATE)
    association_name: str | None = None
    peer_entity_type: str | None = None
    peer_entity_id: str | None = None
    peer_entity_label: str | None = None
    timestamp: datetime | None = None
    actor: str | None = None
    actor_id: int | None = None

    class Config:
        from_attributes = True


class TemplateItemVersion(BaseVersion):
    """One row from the template_items_version table produced by SQLAlchemy-Continuum."""
    name: str | None = None
    description: str | None = None


class TemplateItemVersionPage(BaseModel):
    items: list[TemplateItemVersion]
    total: int
    page: int
    size: int
    pages: int


class SubItemBase(BaseModel):
    name: str
    description: str | None = None
    item_fk: int


class SubItemCreate(SubItemBase):
    tenant_id: int | None = None


class SubItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    item_fk: int | None = None


class SubItemRead(SubItemBase):
    id: int
    tenant_id: int
    # From `SubItem.item_name` (a property, not a column) — requires the descriptor's eager-load
    # plan to have populated `item` first, or reading it raises (`lazy='raise'` on the model).
    item_name: str | None = None

    class Config:
        from_attributes = True


class SubItemsPage(BaseModel):
    items: list[SubItemRead]
    total: int
    total_is_exact: bool = True
    next_after_id: int | None = None
    page: int
    size: int
    pages: int


class SubItemVersion(BaseVersion):
    """One row from the sub_items_version table produced by SQLAlchemy-Continuum.

    `description` is deliberately absent: the generated history route populates a version
    schema's extra fields from `descriptor.model.__filterable__`
    (`ideable_api.router._add_history_route`), and `description` is not declared filterable here
    (see `models.py` — it has no trigram index, unlike `template_items.description`). A field the
    route can never populate is worse than one this schema does not carry at all.
    """
    name: str | None = None
    item_fk: int | None = None


class SubItemVersionPage(BaseModel):
    items: list[SubItemVersion]
    total: int
    page: int
    size: int
    pages: int


class SubItemNoteBase(BaseModel):
    name: str
    description: str | None = None
    sub_item_fk: int


class SubItemNoteCreate(SubItemNoteBase):
    tenant_id: int | None = None


class SubItemNoteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sub_item_fk: int | None = None


class SubItemNoteRead(SubItemNoteBase):
    id: int
    tenant_id: int
    # From `SubItemNote.sub_item_name` (a property, not a column) — requires the descriptor's
    # eager-load plan to have populated `sub_item` first, or reading it raises (`lazy='raise'`).
    sub_item_name: str | None = None

    class Config:
        from_attributes = True


class SubItemNotesPage(BaseModel):
    items: list[SubItemNoteRead]
    total: int
    total_is_exact: bool = True
    next_after_id: int | None = None
    page: int
    size: int
    pages: int


class SubItemNoteVersion(BaseVersion):
    """One row from the sub_item_notes_version table produced by SQLAlchemy-Continuum.

    `name` and `sub_item_fk` only, for the reason `SubItemVersion` states: the generated history
    route populates a version schema's extra fields from `descriptor.model.__filterable__`, and
    `description` is not declared filterable on this entity.
    """
    name: str | None = None
    sub_item_fk: int | None = None


class SubItemNoteVersionPage(BaseModel):
    items: list[SubItemNoteVersion]
    total: int
    page: int
    size: int
    pages: int


class ItemSubItemNotePath(BaseModel):
    """One note as the full-perspective view returns it: the note, its sub-item and its item.

    The PROVENANCE is the point. The depth half of the `sub_item_notes` level is "the selected
    sub-item's notes", where the parent is already known from the selection; the full perspective is
    "every note reachable from the selected ITEM", where a row's own parent is the only thing that
    says which branch it came from — so the row carries both names.
    """
    id: int
    sub_item_fk: int
    sub_item_name: str | None = None
    item_fk: int
    item_name: str | None = None
    name: str
    description: str | None = None

    class Config:
        from_attributes = True


class ItemSubItemNotesPage(BaseModel):
    items: list[ItemSubItemNotePath]
    total: int
    total_is_exact: bool = True
    next_after_id: int | None = None
    page: int
    size: int
    pages: int
