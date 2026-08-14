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


def test_reference_page_uses_row_action_button() -> None:
    """The module_template reference entity page must model the canonical pattern (so
    every remote copies it correctly). Skipped in modules that don't ship TemplateItems.
    """
    ref = SOURCES_DIR / "pages" / "TemplateItems.tsx"
    if not ref.exists():
        pytest.skip("no TemplateItems reference page in this module")
    content = ref.read_text(encoding="utf-8")
    assert "RowActionButton" in content and "RowActions" in content, \
        "reference page must render its actions column with RowActions/RowActionButton"
    # The actions cell must NOT hand-roll a raw <button> (the pre-widget divergence).
    actions_cell = content[content.find("id: 'actions'"):]
    actions_cell = actions_cell[:actions_cell.find("meta:")] if "meta:" in actions_cell else actions_cell
    assert "<button" not in actions_cell, \
        "reference actions cell must use RowActionButton, not a hand-rolled <button>"


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
        assert ("AuditTrailPopup" in content) or ("viewAuditTrail" in content), \
            f"{page_path.name}: audit trail must be wired (AuditTrailPopup / table.viewAuditTrail)"


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
