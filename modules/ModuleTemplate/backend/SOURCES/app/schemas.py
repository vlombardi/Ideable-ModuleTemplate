from datetime import datetime
from pydantic import BaseModel


class TemplateItemBase(BaseModel):
    name: str
    description: str | None = None


class TemplateItemCreate(TemplateItemBase):
    pass


class TemplateItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class TemplateItemRead(TemplateItemBase):
    id: int

    class Config:
        from_attributes = True


class TemplateItemsPage(BaseModel):
    items: list[TemplateItemRead]
    total: int
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
    au_creation_timestamp: datetime | None = None
    au_last_update_timestamp: datetime | None = None
    au_created_by_user: str | None = None
    au_last_updated_by_user: str | None = None

    class Config:
        from_attributes = True


class TemplateItemVersion(BaseVersion):
    """One row from the template_items_version table produced by SQLAlchemy-Continuum."""
    name: str | None = None
    description: str | None = None
