from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy_continuum import version_class

from .. import crud, schemas
from ..audit import (
    get_system_startup_at,
    build_transaction_map,
    build_transaction_actor_map,
    make_synthetic_creation_row,
    version_row_to_schema,
    merge_and_sort_history,
)
from ..auth import require_permission
from ..database import get_db
from ..models import TemplateItem

router = APIRouter(tags=['Template Items'])


@router.get('/items', response_model=schemas.TemplateItemsPage)
def get_items(
    skip: int = 0,
    limit: int = 100,
    id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('items:view')),
):
    try:
        items, total = crud.list_items(
            db,
            skip=skip,
            limit=limit,
            id=id,
            name=name,
            description=description,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        'items': items,
        'total': total,
        'page': (skip // limit) + 1 if limit > 0 else 1,
        'size': limit,
        'pages': (total + limit - 1) // limit if limit > 0 else 1,
    }


@router.post('/items', response_model=schemas.TemplateItemRead, status_code=status.HTTP_201_CREATED)
def post_item(
    payload: schemas.TemplateItemCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('items:edit')),
):
    return crud.create_item(db, payload)


@router.put('/items/{item_id}', response_model=schemas.TemplateItemRead)
def put_item(
    item_id: int,
    payload: schemas.TemplateItemUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('items:edit')),
):
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    return crud.update_item(db, item, payload)


@router.delete('/items/{item_id}', status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('items:edit')),
):
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    crud.delete_item(db, item)
    return None


@router.get('/items/{item_id}/history', response_model=list[schemas.TemplateItemVersion])
def get_item_history(
    item_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('audit_trail:view')),
):
    """Return the full version history for a template item.

    Returns both field-change rows (INSERT/UPDATE/DELETE) and, when the item
    has versioned association tables, association-change rows (ASSOCIATE/
    DISASSOCIATE) merged and sorted chronologically.
    """
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')

    startup_at = get_system_startup_at()

    try:
        VersionClass = version_class(TemplateItem)
        versions = db.query(VersionClass).filter_by(id=item_id).order_by(
            VersionClass.transaction_id.asc()
        ).all()
    except SQLAlchemyError:
        db.rollback()
        versions = []

    tx_map = build_transaction_map(db, versions)
    actor_map = build_transaction_actor_map(db, versions)

    if not versions:
        return [make_synthetic_creation_row(
            schemas.TemplateItemVersion, item, startup_at,
            name=item.name,
            description=item.description,
        )]

    field_versions = [version_row_to_schema(
        v, schemas.TemplateItemVersion, tx_map, startup_at, actor_map,
        name=v.name,
        description=v.description,
    ) for v in versions]

    # When association tables are versioned, association_rows would be built here.
    association_rows: list[schemas.TemplateItemVersion] = []

    return merge_and_sort_history(field_versions, association_rows, startup_at)
