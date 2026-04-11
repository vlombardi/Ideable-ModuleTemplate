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
    au_creation_timestamp: datetime
    au_last_update_timestamp: datetime
    au_created_by_user: str | None = None
    au_last_updated_by_user: str | None = None

    class Config:
        from_attributes = True


class TemplateItemsPage(BaseModel):
    items: list[TemplateItemRead]
    total: int
    page: int
    size: int
    pages: int
