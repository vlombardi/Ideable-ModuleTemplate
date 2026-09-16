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
