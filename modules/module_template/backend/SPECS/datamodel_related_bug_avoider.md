# module_template backend — datamodel-related bug avoider

Bugs tied to a specific table or view, rather than to the generic query core or entity registry
(those live in `general_bug_avoider.md`). Read this before changing `SubItem`, `SubItemNote`, or
adding a new entity that follows their pattern.

## 2026-09-27 — A filterable text column needs BOTH `__filterable__` and its trigram index

**Bug**: `SubItem.__filterable__` and `SubItemNote.__filterable__` declared `name` and their parent
FK, but not `description` — unlike `TemplateItem`, which declares both `name` and `description`.
The Description column's filter box existed in the UI (every `StandardEntityPage` column offers
one) but silently did nothing: the generic query core only turns a column into an `ILIKE`/exact
filter when the entity declares it in `__filterable__`, so a request filtering on `description`
was accepted and its filter parameter was simply not applied against the query. Found by hand,
months after `sub_items`/`sub_item_notes` were first added — no test asserted the Description
filter actually narrowed anything, only that the Name filter did.

**Fix**: `description` added to both `__filterable__` tuples, plus the matching trigram GIN index
on each table's `description` column (`idx_sub_items_description_trgm`,
`idx_sub_item_notes_description_trgm`) — a filterable text column without its trigram index works
but scans sequentially, which is the same class of gap this file exists to catch before it reaches
production data volumes.

**Rule**: every text column declared in `__filterable__` must have a matching trigram GIN index in
the same migration, and every text column NOT declared in `__filterable__` must not have a filter
box that claims to search it — when a new entity or column joins this pattern, add both together,
the way `TemplateItem`'s own `name`/`description` pair already does. A column added to
`__filterable__` produces no migration diff from `alembic revision --autogenerate` (expression
indexes are excluded from the diff — see `alembic/env.py`'s `_include_object`), so the index must
be hand-written into the migration, not assumed to appear automatically.
