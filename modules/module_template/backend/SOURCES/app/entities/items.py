"""The `items` entity: `template_items`, declared for the framework to serve.

A worked example of the descriptor contract — see
`backend/SPECS/ideable-framework-specs/base-specs.md` § *Entities are declared, not written*. The
registry mounts its endpoints from this declaration; nothing else about `items` is written.

`eager_load` is empty because `TemplateItem` declares no relationships. The field is still stated
rather than omitted: an entity that gains one declares its plan here, and an omitted plan is how a
generic read falls into N+1.
"""
from .. import schemas
from ..models import TemplateItem
from . import EntityDescriptor, register_entity

ITEMS = register_entity(EntityDescriptor(
    key='items',
    model=TemplateItem,
    create_schema=schemas.TemplateItemCreate,
    update_schema=schemas.TemplateItemUpdate,
    read_schema=schemas.TemplateItemRead,
    page_schema=schemas.TemplateItemsPage,
    version_schema=schemas.TemplateItemVersion,
    version_page_schema=schemas.TemplateItemVersionPage,
    permission_resource='items',
    eager_load=(),
))
