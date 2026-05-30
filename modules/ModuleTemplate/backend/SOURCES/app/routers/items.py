from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..auth import require_permission
from ..database import get_db

router = APIRouter(tags=['Template Items'])


@router.get('/items', response_model=schemas.TemplateItemsPage)
def get_items(
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
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('template.items:view')),
):
    try:
        items, total = crud.list_items(
            db,
            skip=skip,
            limit=limit,
            id=id,
            name=name,
            description=description,
            au_creation_timestamp=au_creation_timestamp,
            au_last_update_timestamp=au_last_update_timestamp,
            au_created_by_user=au_created_by_user,
            au_last_updated_by_user=au_last_updated_by_user,
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
    username: str = Depends(require_permission('template.items:edit')),
):
    return crud.create_item(db, payload, username)


@router.put('/items/{item_id}', response_model=schemas.TemplateItemRead)
def put_item(
    item_id: int,
    payload: schemas.TemplateItemUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('template.items:edit')),
):
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    return crud.update_item(db, item, payload, username)


@router.delete('/items/{item_id}', status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('template.items:edit')),
):
    item = crud.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    crud.delete_item(db, item)
    return None
