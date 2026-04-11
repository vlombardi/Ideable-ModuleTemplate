from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from . import models, schemas


def list_items(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    au_creation_timestamp: Optional[str] = None,
    au_last_update_timestamp: Optional[str] = None,
    au_created_by_user: Optional[str] = None,
    au_last_updated_by_user: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> tuple[list[models.TemplateItem], int]:
    query = db.query(models.TemplateItem)

    if id is not None:
        query = query.filter(models.TemplateItem.id == id)

    if name:
        query = query.filter(models.TemplateItem.name.ilike(f"%{name}%"))

    if description:
        query = query.filter(models.TemplateItem.description.ilike(f"%{description}%"))

    if au_creation_timestamp:
        query = query.filter(cast(models.TemplateItem.au_creation_timestamp, String).ilike(f"%{au_creation_timestamp}%"))

    if au_last_update_timestamp:
        query = query.filter(cast(models.TemplateItem.au_last_update_timestamp, String).ilike(f"%{au_last_update_timestamp}%"))

    if au_created_by_user:
        query = query.filter(models.TemplateItem.au_created_by_user.ilike(f"%{au_created_by_user}%"))

    if au_last_updated_by_user:
        query = query.filter(models.TemplateItem.au_last_updated_by_user.ilike(f"%{au_last_updated_by_user}%"))

    allowed_sort_fields = {
        "id",
        "name",
        "description",
        "au_creation_timestamp",
        "au_last_update_timestamp",
        "au_created_by_user",
        "au_last_updated_by_user",
    }
    if sort_by:
        if sort_by not in allowed_sort_fields:
            raise ValueError(f"Invalid sort_by: {sort_by}")
        if sort_order not in {"asc", "desc"}:
            raise ValueError(f"Invalid sort_order: {sort_order}")
        column = getattr(models.TemplateItem, sort_by)
        query = query.order_by(column.asc() if sort_order == "asc" else column.desc())
    else:
        query = query.order_by(models.TemplateItem.id.asc())

    total = query.count()
    items = query.offset(skip).limit(limit).all()
    return items, total


def get_item(db: Session, item_id: int) -> models.TemplateItem | None:
    return db.query(models.TemplateItem).filter(models.TemplateItem.id == item_id).first()


def create_item(db: Session, payload: schemas.TemplateItemCreate, username: str) -> models.TemplateItem:
    item = models.TemplateItem(
      name=payload.name,
      description=payload.description,
      au_created_by_user=username,
      au_last_updated_by_user=username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, existing: models.TemplateItem, payload: schemas.TemplateItemUpdate, username: str) -> models.TemplateItem:
    if payload.name is not None:
        existing.name = payload.name
    if payload.description is not None:
        existing.description = payload.description
    existing.au_last_updated_by_user = username
    db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


def delete_item(db: Session, existing: models.TemplateItem) -> None:
    db.delete(existing)
    db.commit()
