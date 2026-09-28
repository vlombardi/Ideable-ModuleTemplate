"""The `items → sub_item_notes` full-perspective view: every note reachable from one item.

WHY THIS EXISTS. The standard page's association view offers two readings of a level — Depth (the
rows associated with the level above) and Full (everything reachable from the selected main row).
For the `sub_item_notes` level the two are genuinely different: Depth is "the selected sub-item's
notes", a filter on one table, while Full is "every note reachable from the selected ITEM", a join
across three. With no endpoint for the second, the Full half has nothing to read that Depth does not
already show — which is what made the Widget Examples gallery's toggle decorative.

WHY IT IS HAND-WRITTEN. A traversal view's rows are a join across tables whose shape is the view's,
not any one entity's, so the generic query core cannot serve them. What it CAN do, and what this
uses, is the two halves that are framework matters: the tenant scoping (`scoped_to_readable_tenants`
plus the GUC the RLS policy reads) and the envelope `ideable_api.router` builds, so the association
view pages and sorts this response with no special case.

The published keys are dotted where a column comes from a related entity — the contract the
association endpoints state (`frontend/SPECS/ideable-framework-specs/shared-ui-specs.md` § *Speaking
columns*) — and a key this view does not publish is refused rather than answered with rows in an
arbitrary order.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ideable_api import query as query_core
from ideable_api.tenancy import TenantScope

from .. import auth, database, models, schemas

router = APIRouter(prefix='/items', tags=['items'])

#: Published name -> the field the row carries it in. Both spellings resolve, because a caller may
#: name the column the way the UI does (`sub_item_name`) or the way the row does.
PUBLISHED = ('name', 'sub_item_name', 'item_name')


@router.get('/{item_id}/sub_item_notes', response_model=schemas.ItemSubItemNotesPage)
def read_item_sub_item_notes(
    item_id: int,
    skip: int = 0,
    limit: int = 100,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    db: Session = Depends(database.get_db),
    current_user: str = Depends(auth.require_permission('sub_item_notes:view')),
    scope: TenantScope = Depends(auth.require_tenant_scope()),
):
    """Every note reachable from one item, through its sub-items, with its provenance."""
    if sort_by and sort_by not in PUBLISHED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown sort field: {sort_by}. This view publishes: {', '.join(PUBLISHED)}.",
        )

    # The GUC first: the RLS policy reads it, so the query below is already confined to the tenants
    # this caller may read before the ORM adds its own predicate.
    query_core.apply_tenant_guc(db, scope)
    rows = query_core.scoped_to_readable_tenants(
        db.query(models.SubItemNote, models.SubItem, models.TemplateItem)
        .join(models.SubItem, models.SubItemNote.sub_item_fk == models.SubItem.id)
        .join(models.TemplateItem, models.SubItem.item_fk == models.TemplateItem.id)
        .filter(models.TemplateItem.id == item_id),
        models.SubItemNote,
        scope,
    ).all()

    items = [
        schemas.ItemSubItemNotePath(
            id=note.id,
            sub_item_fk=note.sub_item_fk,
            sub_item_name=sub_item.name,
            item_fk=item.id,
            item_name=item.name,
            name=note.name,
            description=note.description,
        )
        for note, sub_item, item in rows
    ]

    if sort_by:
        items.sort(key=lambda row: getattr(row, sort_by) or "",
                   reverse=(sort_order or "").lower() == "desc")

    total = len(items)
    page_items = items[skip : skip + limit] if limit > 0 else items[skip:]
    return {
        'items': page_items,
        'total': total,
        'total_is_exact': True,
        'next_after_id': page_items[-1].id if page_items and len(page_items) == limit else None,
        'page': (skip // limit) + 1 if limit > 0 else 1,
        'size': limit,
        'pages': (total + limit - 1) // limit if limit > 0 else 1,
    }
