"""The `sub_item_notes` entity: a row that belongs to one `sub_items` row.

The chain's third level (`template_items → sub_items → sub_item_notes`), added so the standard
page's association view has a Full perspective to offer: with one level, Depth is the only reading
there is, and the Widget Examples gallery — where a module maintainer reads what the framework
gives them — could not show the toggle doing anything. See `models.SubItemNote` for the datamodel
side and `frontend/SPECS/ideable-framework-specs/base_specs.md` § *The gallery's
`StandardEntityPage` section demonstrates a real association chain* for what it is for.

`eager_load=(joinedload(SubItemNote.sub_item),)` is the same N+1 contract `sub_items` states:
`SubItemNoteRead.sub_item_name` reads a property that reads `self.sub_item`, which is `lazy='raise'`,
so a descriptor that forgot this plan would fail every request rather than cost one query per row.
"""
from sqlalchemy.orm import joinedload

from .. import schemas
from ..models import SubItemNote
from . import EntityDescriptor, register_entity

SUB_ITEM_NOTES = register_entity(EntityDescriptor(
    key='sub_item_notes',
    model=SubItemNote,
    create_schema=schemas.SubItemNoteCreate,
    update_schema=schemas.SubItemNoteUpdate,
    read_schema=schemas.SubItemNoteRead,
    page_schema=schemas.SubItemNotesPage,
    version_schema=schemas.SubItemNoteVersion,
    version_page_schema=schemas.SubItemNoteVersionPage,
    permission_resource='sub_item_notes',
    eager_load=(joinedload(SubItemNote.sub_item),),
))
