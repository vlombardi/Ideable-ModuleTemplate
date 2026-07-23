import logging
from typing import Optional
from sqlalchemy.orm import Session
from . import models, schemas

logger = logging.getLogger(__name__)


def list_items(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
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

    allowed_sort_fields = {"id", "name", "description"}
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


def create_item(db: Session, payload: schemas.TemplateItemCreate) -> models.TemplateItem:
    item = models.TemplateItem(
        name=payload.name,
        description=payload.description,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, existing: models.TemplateItem, payload: schemas.TemplateItemUpdate) -> models.TemplateItem:
    if payload.name is not None:
        existing.name = payload.name
    if payload.description is not None:
        existing.description = payload.description
    db.add(existing)
    logger.info("update_item committing item_id=%s name=%s", existing.id, existing.name)
    db.commit()
    db.refresh(existing)
    return existing


def delete_item(db: Session, existing: models.TemplateItem) -> None:
    db.delete(existing)
    db.commit()
