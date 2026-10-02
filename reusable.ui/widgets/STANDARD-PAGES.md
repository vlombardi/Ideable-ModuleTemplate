# Standard pages

`@ideable/ui` ships **widgets** (a table, a popup, a chart) and **pages** — whole screens a module
mounts instead of writing. A page in this catalogue is parametrized: it takes its subject as an
input, so one implementation serves every module and every entity.

| Page | What it serves | Source |
|---|---|---|
| `StandardEntityPage` | one declared entity: its master table, selection, an optional detail region, and the audit trail | `widgets/StandardEntityPage.tsx` |

Its parts are exported separately and are usable on their own:

| Part | Use |
|---|---|
| `EntityTable` | the entity's table, wherever a page wants one |
| `EntityForm` | a create/edit form from a field list — a `formFields` entry may supply its own `render(value, setValue, values)` instead of the default text input, for a value the PAGE derives rather than one the viewer types (a fixed foreign key from the selected parent row, a select over another entity). `setValue`'s identity is stable across renders for the lifetime of that field, so a `render` field is safe to depend on it from its own effect — the worked example is `HiddenParentId` in `modules/module_template/frontend/SOURCES/src/pages/TemplateItems.tsx`, a hidden field that sets a related entity's foreign key from the selected master row. `values` is every field's current value, for a field derived from others — the Users form's read-only composed full name previews `<first> <last>` from it |
| `ImageField`, `EntityImage` | an entity's image (a tenant's logo): `type: "image"` on a form field is a file input with a preview and a remove action, and `image: true` on a `DetailField` draws it in a box of at most 200 x 200 px, proportions kept. The file never travels in the entity's JSON: after the create or update the page sends it to `PUT /<entityKey>/<id>/<field>` as multipart (`transport.putFile`) and a removal to `DELETE`; the card loads it from `GET` (`transport.getBlob`) when the row's `has_<field>` is true. The server judges the bytes and a refusal's message is shown in the form |
| `EntitySelector` | the named implementation of "a select over another entity" above — the Entity Selector Pattern (`shared-ui-widgets-specs.md` § *Form FK association selection (normative)*): current value shown as `<Name> (<ID>)`, a "Select" button opens a modal `EntityTable` (server paging/sorting/filtering) to pick from, never a plain dropdown or a typed id. Plug it into a `formFields` entry's `render`, one per FK field — `modules/module_template/frontend/SOURCES/src/pages/TemplateSubItems.tsx`'s `item_fk` and `TemplateSubItemNotes.tsx`'s `sub_item_fk` are the worked examples |
| `useEntityQuery` | the descriptor, a page of rows, and the paging/sort/filter state |
| `useHostEditMode` | whether the host shell is in edit mode |

### Where to read a working example

The **Widget Examples gallery** in `module_template` demonstrates this page live, including the half
of it that is hardest to get right: it declares the association chain
`items -> sub_items -> sub_item_notes`, so the `Depth visit` / `Full perspective` toggle visibly
changes the table. Depth is the selected sub-item's notes (a filter on one table); Full is every
note reachable from the selected ITEM (`/items/{id}/sub_item_notes`, a join across three). A
one-level chain would show the same table under both readings, which is why the sample datamodel
carries a third level at all.

It is a ROOT menu item (`UI Examples`, beside `Template`) and not a child of it: the gallery shows
what the framework gives you rather than an entity of the module, and its `authorization_claim` is
the module's for the same reason. Source:
`modules/module_template/frontend/SOURCES/src/pages/WidgetGallery.tsx`.

### What `StandardEntityPage` serves

| | |
|---|---|
| table | server-side paging, sorting and filtering, from the entity's own whitelists |
| details card | the selected row's attributes, one field marked `isName` rendered as the highlighted header — `detailFields`, the caller's list on the page's 12-column grid |
| association view | the visit-mode toggle (`Depth visit` / `Full perspective`), the breadcrumb tabs strip (a tab may name the tab that enables it with `dependsOn`), one association table mounted at a time with eager counters, selection pruning, and each level's write affordances — `associations`, the caller's levels on the page's mechanics |
| row actions | history, edit, delete — in that order, gated on edit mode **and** the write permission; a module's own action comes after them via `rowActions` |
| create | a form built from `formFields`, offered under the same gate; create and edit forms sit in `data-detail-region`, and `onFormDirtyChange` reports whether an open form is dirty |
| audit trail | when the entity is versioned and a `fetchHistoryPage` is supplied |
| refusal | `renderError` is shown WITH the empty grid, never instead of it |
| detail | `detail(row)` renders under the table with the selected row — the caller's own region for content that is neither the details card nor an association level. Wrapped in `<div data-detail-region>`, which `ServerDataTable`'s click-outside-deselects handler exempts (the details card and the association view are wrapped the same way, so a click inside any of them never deselects the master row that produced it) |

The layout order is the spec's (`shared-ui-widgets-specs.md` § *The standard entity page*): table → details
card → association view → `detail(row)` → audit trail.

**The row-action order is part of the contract.** They are icon-only buttons, so position is the
only thing identifying them — to a test, and to a user who has learned where the destructive one
sits. Delete stays last.

**A refusal is shown alongside an empty grid, not instead of it.** A message over populated rows
would mean the data had already been fetched and the guard was decoration; shown above an empty
grid, the two together say the rows were never returned.

## What makes something a catalogue entry

Three properties. A page missing any of them belongs in the module that needs it, not here.

1. **It takes its subject as a parameter.** `entityKey` is an input, valorized at the point of use —
   never a binding baked in at build time. A page that only works for the entity it was written for
   is a module's page.
2. **It does not own its placement.** No router import, no route registration, no assumption about
   being full-screen. The caller decides: a menu-bound route, a popup, a drawer, a tab. *"Open this
   entity's table in a popup"* is an ordinary requirement, and a page that could only be a route
   cannot answer it.
3. **It is decomposed.** The parts are exported and usable separately, so a module writing its own
   page reuses them instead of copying the whole. A sealed page makes the escape hatch a fork,
   which is the failure this catalogue exists to avoid.

The widget catalogue arrived at these by accretion. The page catalogue states them from its first
entry, because that entry sets the contract the second one inherits.

## Using one

```tsx
import { StandardEntityPage } from '@ideable/ui'

<StandardEntityPage
  entityKey="items"
  transport={entityTransport}   // how to reach YOUR module's API
  title={t('items.title')}      // already translated
  labelFor={labelFor}           // field name -> column header
/>
```

The module supplies one thing the library cannot know: an `EntityTransport` — `get`, and `post`,
`put`, `delete` for a page that writes — which holds the base URL, authentication and error
mapping. `@ideable/ui` must not know how a module authenticates or
where its API lives. `modules/module_template/frontend/SOURCES/src/services/entityTransport.ts` is
the worked example.

**Labels and column order are the caller's.** The backend descriptor
(`GET <api>/entities/{key}`) declares what is *queryable* — the filterable and sortable whitelists,
the fields, the page ceiling — because that is the side that enforces it. What a column is called
needs translating, and a cell may need arbitrary React, so neither is in the payload.

## Replacing one

Point the menu item at your own component. The endpoints stay mounted and the standard page stays
importable, so the choice is reversible and costs nothing in either direction — and the parts above
are still available to the page you write.

Moving the OTHER direction — an existing hand-written page onto `StandardEntityPage` — is a guided
process, not a rewrite from scratch: `modules/module_template/SPECS/ideable-framework-specs/
adopting-the-entity-standard.md` covers what the standard serves out of the box, the order that keeps
the old and new paths both working while you compare them, and which regions of the old page are
genuine exceptions to keep rather than duplication to delete.

## Adding one

Same route as a widget (`../README.md` § *Extending the widget library*): implement it here, add a
demonstrating section to `module_template`'s `WidgetGallery.tsx`, add a row to the table above, and
extend the spec it implements. A page that fails any of the three properties is not added.
