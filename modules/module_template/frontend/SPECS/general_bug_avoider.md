# Frontend Bug Avoider

This file tracks bugs found during testing/execution and the corresponding rules added to prevent them from recurring.

> **Framework-level frontend rules** (AuditTrailPopup raw dump, edit/view mode action icons, au_* columns, computeDiffs synthetic rows) are defined in:
> `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md`
> Read that file before this one. Only module-specific rules are listed here.

---

## `TemplateItems.tsx`'s association view stopped one level short of the datamodel's actual chain

**Bug.** `template_items → sub_items → sub_item_notes` is a real three-entity chain (see
`module-specs.md` § *Minimum expected result for current datamodel*), but `TemplateItems.tsx`'s
`associations` prop carried only the first hop (`sub_items`). The Items page's Depth visit strip
never showed a Sub-Item Notes tab, and selecting Item → Sub-Item never surfaced that sub-item's own
notes — a maintainer had to leave Items and open the standalone Sub-Items page to reach them. The
backend's `GET /items/{id}/sub_item_notes` traversal endpoint (`app/routers/item_traversal.py`) and
the `WidgetGallery.tsx` demo chain already existed for exactly this depth; only the real Items page
had never been wired to use them.

**Fix.** `TemplateItems.tsx`'s `associations` prop is the concatenation of two `AssociationTab`
entries: `sub_items` (`chain[0]` scoped, unchanged) and `sub_item_notes` (`chain[1]` scoped) —
Depth reads `sub_item_fk` off the selected sub-item, Full reads the traversal endpoint and carries
the `sub_item_name` provenance column, the same shape `TemplateSubItems.tsx` and
`WidgetGallery.tsx`'s `galleryAssociations` already use one level up. **How to avoid the
regression:** when a module's datamodel chain is N entities deep, its topmost page's
`associations` array must carry N-1 `AssociationTab` entries, one per hop — check the chain depth
against `associations.length` whenever an entity is added below an existing association level,
not only when the leaf's own standalone page is created.
