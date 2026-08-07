"""Items table + entity-page contract (post @ideable/ui migration).

The data table is the shared ``reusable.ui/widgets/ServerDataTable.tsx``
(package ``@ideable/ui``); entity pages wire it to server-side sort/filter and the
audit trail. The dev-only Widget Gallery also renders the table but against synthetic
in-file data, so it is excluded from the entity-wiring contract.
"""
import re
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[2]          # modules/<module>
PROJECT_ROOT = MODULE_ROOT.parents[1]                      # repo root
SOURCES_DIR = MODULE_ROOT / "frontend" / "SOURCES" / "src"
SHARED_TABLE = PROJECT_ROOT / "reusable.ui" / "widgets" / "ServerDataTable.tsx"


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
