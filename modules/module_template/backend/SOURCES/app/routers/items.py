from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy_continuum import version_class

from .. import crud, schemas
from ..audit import (
    get_system_startup_at,
    AuditUnavailableError,
    make_synthetic_creation_row,
    ensure_utc,
    SYSTEM_ACTOR_USERNAME,
)
from ..auth import TenantScope, require_permission, require_tenant_scope
from ..database import get_db
from ..models import TemplateItem

logger = logging.getLogger(__name__)

router = APIRouter(tags=['Template Items'])


@router.get('/items', response_model=schemas.TemplateItemsPage)
def get_items(
    skip: int = 0,
    # Capped at the API boundary so an oversized page is a 422 with a reason, not a giant
    # response. `le` puts the bound in the OpenAPI schema, so a client sees it before sending.
    limit: int = Query(100, ge=1, le=crud.MAX_PAGE_SIZE),
    id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    # Additive and optional, so every existing caller keeps working unchanged: `after_id` seeks
    # instead of skipping, and `include_total` drops the second full pass when a caller does not
    # need a total (infinite scroll, or a page that already knows it).
    after_id: Optional[int] = None,
    include_total: bool = True,
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('template.items:view')),
    scope: TenantScope = Depends(require_tenant_scope()),
):
    try:
        items, total, total_is_exact = crud.list_items(
            db,
            scope=scope,
            skip=skip,
            limit=limit,
            id=id,
            name=name,
            description=description,
            sort_by=sort_by,
            sort_order=sort_order,
            after_id=after_id,
            include_total=include_total,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # A full page implies there may be another; a short page is the end. This costs nothing,
    # where asking the database "is there more?" would be another query.
    next_after_id = items[-1].id if items and len(items) == limit else None

    return {
        'items': items,
        'total': total,
        'total_is_exact': total_is_exact,
        'next_after_id': next_after_id,
        'page': (skip // limit) + 1 if limit > 0 else 1,
        'size': limit,
        'pages': (total + limit - 1) // limit if limit > 0 else 1,
    }


@router.get('/items/{item_id}', response_model=schemas.TemplateItemRead)
def get_single_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('template.items:view')),
    scope: TenantScope = Depends(require_tenant_scope()),
):
    """One item by id, or 404.

    Added because the tenancy contract is written in terms of it: auth-specs.md's checklist requires
    "another tenant's id → 404 on GET, PUT, DELETE and history", and `crud.get_item` carries the
    404-not-403 reasoning — while the router had no GET-by-id route at all, so the documented
    behaviour was unreachable and the acceptance test could not be written against it. A 405 is not
    a safe answer to "can A read B's row?"; it is no answer.

    A read, so a caller holding template.items:read_all_tenants sees other tenants here. PUT and
    DELETE load the same row through `for_write=True` and do not.
    """
    item = crud.get_item(db, item_id, scope)
    if item is None:
        # 404 rather than 403: a 403 would confirm the id exists in some other tenant, which lets a
        # caller map the shape of data it cannot read.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    return item


@router.post('/items', response_model=schemas.TemplateItemRead, status_code=status.HTTP_201_CREATED)
def post_item(
    payload: schemas.TemplateItemCreate,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('template.items:edit')),
    scope: TenantScope = Depends(require_tenant_scope()),
):
    try:
        return crud.create_item(db, payload, scope)
    except crud.TenantScopeError as exc:
        # 403 rather than 404: the caller named a tenant explicitly, so telling them they may not
        # write there reveals nothing they did not already assert.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.put('/items/{item_id}', response_model=schemas.TemplateItemRead)
def put_item(
    item_id: int,
    payload: schemas.TemplateItemUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('template.items:edit')),
    scope: TenantScope = Depends(require_tenant_scope()),
):
    # for_write: a caller holding template.items:read_all_tenants may SEE every tenant's items
    # and must still get a 404 when it aims a PUT at one. The row-level policy would refuse the
    # UPDATE anyway (verified: `UPDATE 0` against another tenant's row), but a 404 is the honest
    # answer rather than a write that silently affects nothing.
    item = crud.get_item(db, item_id, scope, for_write=True)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    return crud.update_item(db, item, payload, scope)


@router.delete('/items/{item_id}', status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    item_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(require_permission('template.items:edit')),
    scope: TenantScope = Depends(require_tenant_scope()),
):
    item = crud.get_item(db, item_id, scope, for_write=True)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')
    crud.delete_item(db, item)
    return None


@router.get('/items/{item_id}/history', response_model=schemas.TemplateItemVersionPage)
def get_item_history(
    item_id: int,
    skip: int = 0,
    limit: int = Query(50, ge=1, le=crud.MAX_PAGE_SIZE),
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    actor: Optional[str] = None,
    operation_type: Optional[str] = None,
    timestamp: Optional[str] = None,
    # Cursor for the next (older) page: the oldest transaction_id already shown. Measured on a
    # 50,000-version record, the page at offset 49950 took 68 ms and the same page by cursor
    # 0.061 ms. Additive and optional, so existing callers are unchanged.
    before_transaction_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: str = Depends(require_permission('template.audit_trail:view')),
    scope: TenantScope = Depends(require_tenant_scope()),
):
    """Return the paginated version history for a template item.

    Returns both field-change rows (INSERT/UPDATE/DELETE) and, when the item
    has versioned association tables, association-change rows (ASSOCIATE/
    DISASSOCIATE) merged and sorted chronologically.
    """
    item = crud.get_item(db, item_id, scope)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Item not found')

    startup_at = get_system_startup_at()

    try:
        VersionClass = version_class(TemplateItem)
        # The table name comes from the ORM, never from the request: list_item_history
        # interpolates it into SQL.
        page_rows, total = crud.list_item_history(
            db,
            version_table=VersionClass.__table__.name,
            item_id=item_id,
            scope=scope,
            startup_at=startup_at,
            system_actor=SYSTEM_ACTOR_USERNAME,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
            actor=actor,
            operation_type=operation_type,
            timestamp=timestamp,
            before_transaction_id=before_transaction_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SQLAlchemyError as exc:
        # Degrading to an empty history here rendered a synthetic "created" row: a record with a
        # real history became one that looked like it had never changed.
        db.rollback()
        logger.error('Audit trail: version rows unreadable for item %s', item_id, exc_info=True)
        raise AuditUnavailableError('version rows unreadable') from exc

    if total == 0:
        # A record whose versioning began after it was created has no version rows at all. The
        # synthetic row is built directly rather than materialising anything — and only on the
        # first page, so paging past it returns nothing rather than repeating it.
        synthetic = [] if skip > 0 else [make_synthetic_creation_row(
            schemas.TemplateItemVersion, item, startup_at,
            name=item.name,
            description=item.description,
        )]
        return {
            'items': synthetic,
            'total': len(synthetic) if skip == 0 else 1,
            'page': (skip // limit) + 1 if limit > 0 else 1,
            'size': limit,
            'pages': 1,
        }

    items = [schemas.TemplateItemVersion(
        transaction_id=row['transaction_id'],
        operation_type=int(row['operation_type']),
        end_transaction_id=row['end_transaction_id'],
        id=row['id'],
        timestamp=ensure_utc(row['ts']),
        actor=row['actor'],
        actor_id=None,
        name=row['name'],
        description=row['description'],
    ) for row in page_rows]

    pages = (total + limit - 1) // limit if limit > 0 else 1

    return {
        'items': items,
        'total': total,
        'page': (skip // limit) + 1 if limit > 0 else 1,
        'size': limit,
        'pages': pages,
    }
