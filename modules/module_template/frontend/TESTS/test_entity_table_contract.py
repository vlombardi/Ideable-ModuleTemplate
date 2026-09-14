"""Items table + entity-page contract (post @ideable/ui migration).

The data table is the shared ``reusable.ui/widgets/ServerDataTable.tsx``
(package ``@ideable/ui``); entity pages wire it to server-side sort/filter and the
audit trail. The dev-only Widget Gallery also renders the table but against synthetic
in-file data, so it is excluded from the entity-wiring contract.
"""
import re
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parents[2]          # modules/<module>
PROJECT_ROOT = MODULE_ROOT.parents[1]                      # repo root
SOURCES_DIR = MODULE_ROOT / "frontend" / "SOURCES" / "src"
SHARED_TABLE = PROJECT_ROOT / "reusable.ui" / "widgets" / "ServerDataTable.tsx"
SHARED_POPUP = PROJECT_ROOT / "reusable.ui" / "widgets" / "DraggableResizablePopup.tsx"
SHARED_DIALOG = PROJECT_ROOT / "reusable.ui" / "primitives" / "dialog.tsx"
SHARED_AUDIT = PROJECT_ROOT / "reusable.ui" / "widgets" / "AuditTrailPopup.tsx"


def test_audit_trail_table_uses_serverdatatable() -> None:
    """The audit-trail popup's table must be the shared ServerDataTable (so it inherits
    column resize, sort, pagination and dark-mode), not a hand-rolled <table>. See
    shared-ui-widgets-specs § Audit Trail Popup."""
    content = SHARED_AUDIT.read_text(encoding="utf-8")
    assert "ServerDataTable" in content, "audit-trail table must render via the shared ServerDataTable"
    assert "<table" not in content, "audit-trail popup must not hand-roll a <table> (use ServerDataTable)"


def test_audit_trail_table_supports_column_filtering() -> None:
    """The audit table must expose column filtering (When/Who/Op) wired to the history
    endpoint, not disable the filter row."""
    content = SHARED_AUDIT.read_text(encoding="utf-8")
    assert "onFilterChange" in content, "audit table must wire onFilterChange for column filtering"
    assert "showFilters={false}" not in content, "audit table must not disable the filter row"
    # filters must be forwarded to the history fetch
    assert "filters" in content and "AuditPageParams" in content


def test_serverdatatable_columns_are_user_resizable() -> None:
    """Columns must be user-resizable: a draggable divider per column boundary + double-click
    auto-fit to content, applied to header/filter/body cells (see shared-ui-widgets-specs)."""
    content = SHARED_TABLE.read_text(encoding="utf-8")
    assert "startColumnResize" in content, "missing column drag-resize handler"
    assert "autofitColumn" in content, "missing double-click auto-fit handler"
    assert "onDoubleClick" in content and "onMouseDown" in content, "resize handle must drag + double-click"
    assert "cursor-col-resize" in content, "resize divider must show a col-resize cursor"
    assert 'data-col=' in content, "cells must be tagged data-col so a column resizes together"


def test_popups_dismiss_only_via_close_icon() -> None:
    """Popup windows must not dismiss on an outside/backdrop click — only the close (X) icon.
    See shared-ui-widgets-specs § Popup styling (Dismissal)."""
    popup = SHARED_POPUP.read_text(encoding="utf-8")
    assert re.search(r"closeOnBackdrop\s*=\s*false", popup), \
        "DraggableResizablePopup must default closeOnBackdrop=false (no outside-click dismiss)"
    dialog = SHARED_DIALOG.read_text(encoding="utf-8")
    assert "onPointerDownOutside" in dialog and "onInteractOutside" in dialog and "preventDefault" in dialog, \
        "shared DialogContent must prevent outside-interaction dismissal by default"


def test_popup_surfaces_use_theme_tokens_not_hardcoded_white() -> None:
    """Popup/dialog surfaces must use theme tokens (bg-popover/bg-background +
    *-foreground) so they render correctly in dark mode. A hardcoded `bg-white` gives
    white-on-white text under `.dark`."""
    for path in (SHARED_POPUP, SHARED_DIALOG):
        content = path.read_text(encoding="utf-8")
        assert "ideable:bg-white" not in content, \
            f"{path.name}: hardcoded bg-white breaks dark mode — use ideable:bg-popover/bg-background"
        assert ("ideable:bg-popover" in content or "ideable:bg-background" in content), \
            f"{path.name}: popup surface must use a theme background token"
        assert "foreground" in content, \
            f"{path.name}: popup surface must set a matching *-foreground text token"
SHARED_ROW_ACTION = PROJECT_ROOT / "reusable.ui" / "widgets" / "RowActionButton.tsx"


def test_row_action_button_is_canonical() -> None:
    """The shared RowActionButton/RowActions widget is the single source of truth for
    entity-table row-action icons (rounded-square, bordered, hover-accent; danger for
    destructive actions). Every module renders its `actions` column with it, so all
    tables look identical — see shared-ui-widgets-specs.md and shared-frontend-bug-avoider.md.
    """
    assert SHARED_ROW_ACTION.exists(), \
        "shared reusable.ui/widgets/RowActionButton.tsx is missing"
    content = SHARED_ROW_ACTION.read_text(encoding="utf-8")
    assert "export const RowActionButton" in content or "export function RowActionButton" in content
    assert "export function RowActions" in content or "export const RowActions" in content
    # Canonical look: bordered rounded square with a hover-accent fill…
    assert "ideable:rounded-md" in content and "ideable:border" in content
    assert "ideable:hover:bg-accent" in content
    # …and a destructive `danger` variant for delete/unlink.
    assert 'variant === "danger"' in content or "variant==='danger'" in content
    assert "destructive" in content
    # Icon prop is a structural element type (dedupe-proof across lucide installs), not
    # a nominal lucide type that would force consumers to cast.
    assert "React.ElementType" in content


def _entity_pages() -> list[Path]:
    """Every page in THIS module that renders the shared table with an actions column.

    Discovered by what the page renders, never by its filename. Naming the template's
    `TemplateItems.tsx` made this assertion a permanent no-op in every remote module project:
    `module-init.sh` renames that file after the new module's slug, so the check skipped forever
    and a remote's own entity pages were never held to the pattern — the opposite of what a
    force-synced contract is for.

    The Widget Gallery renders `ServerDataTable` too, against synthetic in-file data and with no
    actions column, so requiring an actions column is also what excludes it.
    """
    pages_dir = SOURCES_DIR / "pages"
    if not pages_dir.is_dir():
        return []
    found = []
    for page in sorted(pages_dir.glob("*.tsx")):
        body = page.read_text(encoding="utf-8")
        if "ServerDataTable" in body and re.search(r"""id:\s*['"]actions['"]""", body):
            found.append(page)
    return found


def _entity_page_params():
    """An EXPLAINED skip when the module has no such page — never pytest's bare empty-set skip."""
    pages = _entity_pages()
    if pages:
        return [pytest.param(p, id=p.name) for p in pages]
    return [pytest.param(None, id="none", marks=pytest.mark.skip(reason=(
        "this module has no page rendering ServerDataTable with an `id: 'actions'` column, so it "
        "has no entity table for the actions-column contract to apply to"
    )))]


@pytest.mark.parametrize("page", _entity_page_params())
def test_entity_pages_use_row_action_button(page) -> None:
    """An entity page's actions column must use the shared widgets, not a hand-rolled button.

    This runs against whatever entities the module defines — the template's Items, or a real
    module's companies and assets — which is what makes the rule hold from day zero rather than
    only in the reference module.
    """
    content = page.read_text(encoding="utf-8")
    assert "RowActionButton" in content and "RowActions" in content, \
        f"{page.name} must render its actions column with RowActions/RowActionButton"
    # The actions cell must NOT hand-roll a raw <button> (the pre-widget divergence).
    actions_cell = content[re.search(r"""id:\s*['"]actions['"]""", content).start():]
    actions_cell = actions_cell[:actions_cell.find("meta:")] if "meta:" in actions_cell else actions_cell
    assert "<button" not in actions_cell, \
        f"{page.name}: the actions cell must use RowActionButton, not a hand-rolled <button>"


def test_serverdatatable_contains_required_controls() -> None:
    table_content = SHARED_TABLE.read_text(encoding="utf-8")

    # The rows-per-page selector and page indicator are rendered via i18n
    # (t('table.rowsPerPage') / t('table.page', { page, total })) rather than
    # hardcoded English, per the shared UI i18n contract.
    assert "table.rowsPerPage" in table_content
    assert "table.page" in table_content
    # Pagination + sort controls use lucide icons.
    for icon in ("ChevronsLeft", "ChevronLeft", "ChevronRight", "ChevronsRight", "ArrowUpDown"):
        assert icon in table_content, f"shared ServerDataTable missing icon: {icon}"


def test_fk_label_columns_are_not_force_narrowed() -> None:
    """Regression: an FK column that renders a *resolved label* via a custom ``cell``
    (e.g. "Cluster 1 (1)") must size to content, not the raw-id 90px narrow default —
    which clipped the label and truncated header/filter placeholders. The shared table
    must therefore gate the ``_fk`` narrowing on the *absence* of a custom cell renderer.
    """
    content = SHARED_TABLE.read_text(encoding="utf-8")
    # Still keys off FK columns…
    assert re.search(r"""endsWith\(["']_fk["']\)""", content), \
        "FK narrowing must still key off columns whose id ends in _fk"
    # …but conjoined with a negation guard (…endsWith('_fk') && !<custom cell>), so a
    # labelled FK column (one that supplies its own `cell`) is NOT force-narrowed.
    assert re.search(r"""endsWith\(["']_fk["']\)\s*&&\s*!""", content), \
        ("FK narrowing must be gated on the absence of a custom `cell` "
         "(…endsWith('_fk') && !<custom cell>), else resolved-label FK columns get clipped")


def _entity_pages() -> list[Path]:
    """Pages that render ServerDataTable against a real data service.

    Entity pages import from a `services/` module; the dev-only Widget Gallery uses
    synthetic in-file data (no service import) and is therefore excluded.
    """
    pages_dir = SOURCES_DIR / "pages"
    page_files = list(pages_dir.glob("*.tsx"))
    assert page_files, "No page files found in SOURCES/src/pages/"

    entity = []
    for page_path in page_files:
        content = page_path.read_text(encoding="utf-8")
        if "ServerDataTable" not in content:
            continue
        if not re.search(r"from ['\"][^'\"]*services/", content):
            continue
        entity.append(page_path)
    return entity


#: An import of the module's OWN sources: a relative path, or the `@/` alias every module's
#: tsconfig points at `src/`. A package import (`@ideable/ui`, `react`) is deliberately not one —
#: following those would search the whole dependency tree for two strings.
_LOCAL_IMPORT = re.compile(r"""from\s+['"](\.{1,2}/[^'"]+|@/[^'"]+)['"]""")

#: Either the shared widget itself or the framework's standard key for the control that opens it.
_AUDIT_MARKERS = ("AuditTrailPopup", "viewAuditTrail")


def _resolve_local_import(page_path: Path, spec: str) -> Path | None:
    """The file a page's own import names, or None when it resolves outside this module's sources.

    Every path is RESOLVED before it is compared. `pages/../components/X` and
    `pages/../../../elsewhere` both start with the sources directory as text, so a containment check
    on the unresolved path accepts a file from outside the module and reports the followed file
    under a name nobody would recognise.
    """
    base = (SOURCES_DIR / spec[2:]) if spec.startswith("@/") else (page_path.parent / spec)
    root = SOURCES_DIR.resolve()
    for candidate in (base, *(base.with_suffix(ext) for ext in (".tsx", ".ts")),
                      base / "index.tsx", base / "index.ts"):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        return resolved if resolved.is_relative_to(root) else None
    return None


def _audit_trail_wiring(page_path: Path) -> tuple[bool, list[str]]:
    """Whether a page wires the audit trail, directly or through a component of its own.

    ONE LEVEL, and that is the whole change. The assertion used to be a substring match on the page
    file, so a module that shares one column set across three call sites — by putting the shared
    widget behind its own component, which is what the shared-widget rule asks for — was reported
    as not having wired the audit trail at all. Two framework rules then pulled in opposite
    directions: reuse the widget behind a wrapper, and also name it literally in every page.

    One level is enough for that shape and stops the search from becoming a graph walk: a wrapper
    around a shared widget is a wrapper, not a hierarchy. Package imports are not followed at all
    — `@ideable/ui` is where the widget legitimately comes from, and searching a dependency tree
    for two strings would find them somewhere and prove nothing.

    Returns the verdict and every file it read, so a failure says where it looked.
    """
    content = page_path.read_text(encoding="utf-8")
    searched = [page_path.name]
    if any(marker in content for marker in _AUDIT_MARKERS):
        return True, searched
    for spec in _LOCAL_IMPORT.findall(content):
        imported = _resolve_local_import(page_path, spec)
        if imported is None:
            continue
        searched.append(imported.relative_to(SOURCES_DIR.resolve()).as_posix())
        if any(marker in imported.read_text(encoding="utf-8") for marker in _AUDIT_MARKERS):
            return True, searched
    return False, searched


def test_entity_pages_use_server_table_and_audit_columns() -> None:
    entity_pages = _entity_pages()
    assert entity_pages, "No entity pages (ServerDataTable + data service) found"

    for page_path in entity_pages:
        content = page_path.read_text(encoding="utf-8")
        # Assert the wiring via the ServerDataTable @ideable/ui props — NOT specific
        # handler names, which a real module may name differently.
        assert "onFilterChange" in content, \
            f"{page_path.name}: ServerDataTable must be wired with onFilterChange (server-side filter)"
        assert "onSortChange" in content, \
            f"{page_path.name}: ServerDataTable must be wired with onSortChange (server-side sort)"
        # Audit trail wired via the shared widget or the standard i18n key. Audit
        # metadata (when/who) is surfaced via the Audit Trail popup, not inline au_*
        # columns (audit-trail-specs §3.3).
        wired, searched = _audit_trail_wiring(page_path)
        assert wired, (
            f"{page_path.name}: audit trail must be wired (AuditTrailPopup / table.viewAuditTrail), "
            f"in the page or in a component it imports. Searched: {', '.join(searched)}"
        )


def test_services_omit_empty_filter_params() -> None:
    services_dir = SOURCES_DIR / "services"
    service_files = list(services_dir.glob("*.ts"))
    assert service_files, "No service files found in SOURCES/src/services/"

    entity_services = [s for s in service_files if "URLSearchParams" in s.read_text(encoding="utf-8")]
    assert entity_services, "No services using URLSearchParams found"

    for service_path in entity_services:
        content = service_path.read_text(encoding="utf-8")
        assert "new URLSearchParams()" in content, f"{service_path.name}: missing URLSearchParams construction"
        assert "sort_by" in content and "sort_order" in content, \
            f"{service_path.name}: missing sort_by/sort_order params"
        assert "query.sort_by && query.sort_by.trim() !== '' && query.sort_order" in content, \
            f"{service_path.name}: sort params must be omitted when empty"
