# Ideable Framework — Adopting the entity standard

This file is the authoritative cross-cutting guide for two questions a module maintainer asks at
different points in a module's life: *what does declaring an entity get me for free*, and *how do I
move an existing hand-written entity onto that standard*. It names nothing new — every capability
and rule here is already specified in the files it links to — and exists because those files are
scattered across sub-modules (backend, frontend, database) while the maintainer's question is not.

Read this after the sub-module `base-specs.md` chain, when the question is "is this worth doing for
my entity" or "how do I actually do it", not while implementing a single declared field or endpoint
— those are the linked files' job.

---

## 1. What a declared entity gets, out of the box

Declaring an entity — a model with `EntityDescriptor(...)` registered in `app/entities/` — mounts
and wires all of the following. Nothing here is opt-in per capability; the only per-entity switches
are the descriptor fields named in the right-hand column.

| Capability | What it means | Governed by | Opt out with |
|---|---|---|---|
| CRUD endpoints | `GET`/`POST`/`PUT`/`DELETE` on `/<key>` and `/<key>/{id}`, permission-gated per route | `backend/SPECS/ideable-framework-specs/base-specs.md` § *What is served, per entity* | `EntityDescriptor.read_only=True` mounts the three read routes only |
| Server-side paging, sorting, filtering | from the model's own `__filterable__`/`__sortable__` whitelists; the operator follows the column's type (substring for text, exact match for an integer/FK) | same file, § *What keeps it as fast as a hand-written query* | narrow the whitelist on the model — there is no per-request override |
| Tenant scoping | every query is scoped before any other filter, and can only be narrowed further, never widened | `backend/SPECS/ideable-framework-specs/base-specs.md` § *Entities are declared, not written*; `rules/general-guidelines.md` § tenancy | `__tenant_scoped__ = False` on a genuinely shared entity — checked at build time |
| Audit trail | full version history, paginated in SQL, with a synthetic creation row when history predates versioning | `audit-trail-specs.md` | `__versioned__ = {'exclude': True}`, with a reason |
| The standard page | `StandardEntityPage` — master table, details card for the selected row, visit-mode toggle with the association tabs strip and one association table at a time, create/edit forms, row actions, the audit trail popup, and `detail(row)` as the caller's own region | `shared-ui-widgets-specs.md` § *The standard entity page*; `reusable.ui/widgets/STANDARD-PAGES.md` | write your own page against the same descriptor; the endpoints stay mounted either way |
| N+1 safety | a relationship exposed in a read schema must have an eager-load plan, checked mechanically | `backend/SPECS/ideable-framework-specs/base-specs.md` § *What keeps it as fast…* | not optional — an omitted plan fails the suite |
| Permissions | `<slug>.<resource>:view` / `:edit`, one pair per entity, declared in `config/authorization.yaml` | `module-integration-specs.md` | none — every mounted route is gated |

**Reuse hooks**, for the case where the standard behaviour is right everywhere except one step —
`scope_query`, `before_create`, `after_create`, `before_update`, `after_update`, `after_delete`, or
replacing a single generated endpoint while the rest stay mounted (`backend/SPECS/…/base-specs.md`
§ *Changing one step without writing a router*). An escape hatch that costs the whole descriptor to
use is not an escape hatch — reach for a hook before reaching for a bespoke router.

---

## 2. Refactoring an existing entity onto the standard

An entity that predates the registry, or was hand-written for a reason that no longer applies, moves
onto the standard in this order. Each step is independently testable — do not batch them, and do not
delete anything until its replacement is proven.

1. **Write the descriptor** (`app/entities/<entity>.py`): model, the four CRUD schemas, `version_schema`
   / `version_page_schema` (both or neither), `permission_resource`, `eager_load` for every
   relationship the read schema exposes. Register it; the registry rejects a malformed descriptor at
   import, not at request time.
2. **Mount it and verify against the bespoke path.** The generated router and the hand-written one can
   coexist under different prefixes while you compare responses — the registry does not require the
   old router's removal to work.
3. **Point the page at `StandardEntityPage`** (or its parts, `EntityTable`/`EntityForm`, if the layout
   needs bespoke composition) instead of the hand-written page component. Verify every row action,
   every filter, and the audit trail popup against the page it replaces.
4. **Delete what the standard now serves**: the hand-written router, its entity-bound CRUD functions,
   the frontend service module, and the old page component — except the regions named in § 3 below.
   Deleting is not optional once the standard covers a capability: a generic layer added *beside* the
   code it generalizes leaves the duplication intact and adds to it, which is the failure this guide
   exists to prevent.
5. **Run the module's full suite**, not only the entity's own tests — a bespoke page frequently carries
   behaviour (a shared filter component, a menu entry, a permission check elsewhere) that a generic
   page does not automatically reproduce, and the earlier steps only proved the entity's own contract.

## 3. What must NOT be deleted

Some of a hand-written page's code is not duplication — it is a genuine feature the standard does not
serve, and deleting it because *most* of the page was standard loses working behaviour for no reason.
The unit of this decision is the **region**, not the page: a page can be the standard one everywhere
except a named, surviving exception.

A region is a legitimate exception when it does something no descriptor hook can express — a
multi-step wizard, a write that spans more than one entity in one transaction, a view built from data
the entity's own table does not carry. It is **not** an exception merely because rewriting it takes
effort, or because nobody has checked whether a hook would serve it.

**Declare every exception explicitly** where the page is otherwise standard — name the region, and
say why it stays, in the module's own `SPECS/base-specs.md` or in a comment at the region itself. An
undeclared survivor reads as an oversight the next maintainer "fixes" by deleting it; a declared one
reads as a decision. `host_app`'s own `Users.tsx` is the worked example: password change, tenant
assignment and the full-perspective role/permission views survive as named exceptions on a page that
is otherwise `StandardEntityPage`, recorded in the plan that adopted the standard for that page
(`rules/implementation-plan.md`-format decisions record, § *Decisions and answers*, 2026-09-17 17:03).

---

## 4. Finding candidates automatically

`scripts/dev/common/check_standard_adoption.py` names, on every `validate_modules.sh` run, any
hand-written full-CRUD router with no declared entity — a candidate for § 2 above. It never fails a
build: this is information, not a contract. An entity kept custom on purpose is recorded, not
silently skipped, as a bullet in that module's own `backend/SPECS/custom-entities.md`
(`modules/host_app/backend/SPECS/custom-entities.md` is the worked example) — the check stops
naming it, and the next maintainer reads a decision instead of rediscovering the same question.

## 5. Reachability

This file is read from `module_template`'s own `SPECS/base-specs.md` (module-level, step 3 in that
file's own mandatory reading order) and from `reusable.ui/widgets/STANDARD-PAGES.md` § *Replacing
one*, so a maintainer reaches it whether they start from the module's specs or from the page they are
about to replace. It is force-synced to every remote module the same way every other file in this
directory is — see `infrastructure-file-list.md` § *Shared framework-spec files*.
