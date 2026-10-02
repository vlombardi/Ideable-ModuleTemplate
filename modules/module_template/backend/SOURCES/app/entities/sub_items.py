"""The `sub_item` entity: a row that belongs to one `items` row, declared for the framework to serve.

The plan's second entity (`an-entity-is-served-by-the-framework-unless-it-says-otherwise`,
sub-set 7) — added because a single flat entity cannot demonstrate a master/detail page, FK-ordered
create/delete, or the N+1 guard on a real relationship. See `models.SubItem`'s docstring for the
datamodel side.

`eager_load=(joinedload(SubItem.item),)` is what this entity is FOR: `SubItemRead.item_name` reads
`SubItem.item_name`, a property that reads `self.item` — and `item` is declared `lazy='raise'`, so
a descriptor that forgot this eager-load plan would fail every request instead of costing one query
per row. That is the N+1 guard doing its job at the one entity built to need it.
"""
from sqlalchemy.orm import joinedload

from .. import schemas
from ..models import SubItem
from . import EntityDescriptor, register_entity

SUB_ITEMS = register_entity(EntityDescriptor(
    key='sub_items',
    model=SubItem,
    create_schema=schemas.SubItemCreate,
    update_schema=schemas.SubItemUpdate,
    read_schema=schemas.SubItemRead,
    page_schema=schemas.SubItemsPage,
    version_schema=schemas.SubItemVersion,
    version_page_schema=schemas.SubItemVersionPage,
    permission_resource='sub_items',
    eager_load=(joinedload(SubItem.item),),
))
