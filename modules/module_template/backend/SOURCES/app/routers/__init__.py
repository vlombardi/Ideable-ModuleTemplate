"""Hand-written routers — the views the entity descriptors cannot express.

A module declares its ENTITIES (`app/entities/`) and the framework generates their CRUD, list,
history and association routes. What lands here is the other kind of route: a view whose rows are a
join across tables whose shape is the view's rather than any one entity's, so no descriptor can
serve it. `item_traversal.py` is the worked example — the standard page's *Full perspective* for the
`sub_item_notes` level.

It is small on purpose, and it stays small by using the framework for everything that is a framework
matter: `ideable_api.query` for tenant scoping and `ideable_api.router`'s envelope shape for the
page, so a hand-written view pages and sorts exactly like a generated one.
"""
