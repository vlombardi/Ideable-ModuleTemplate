from pathlib import Path


SOURCES_DIR = Path(__file__).resolve().parents[1] / "SOURCES" / "src"
TABLE_COMPONENT_PATH = SOURCES_DIR / "components" / "ServerDataTable.tsx"


def test_serverdatatable_contains_required_controls() -> None:
    table_content = TABLE_COMPONENT_PATH.read_text(encoding="utf-8")

    assert "Rows per page:" in table_content
    assert "ChevronsLeftIcon" in table_content
    assert "ChevronLeftIcon" in table_content
    assert "ChevronRightIcon" in table_content
    assert "ChevronsRightIcon" in table_content
    assert "Page {page} of {totalPages}" in table_content
    assert "Audit Data" in table_content
    assert "SortNeutralIcon" in table_content


def test_entity_pages_use_server_table_and_audit_columns() -> None:
    pages_dir = SOURCES_DIR / "pages"
    page_files = list(pages_dir.glob("*.tsx"))
    assert page_files, "No page files found in SOURCES/src/pages/"

    entity_pages = [p for p in page_files if "ServerDataTable" in p.read_text(encoding="utf-8")]
    assert entity_pages, "No pages using ServerDataTable found"

    for page_path in entity_pages:
        content = page_path.read_text(encoding="utf-8")
        assert "showAuditData" in content, f"{page_path.name}: missing showAuditData"
        assert "handleFilterChange" in content, f"{page_path.name}: missing handleFilterChange"
        assert "handleSortChange" in content, f"{page_path.name}: missing handleSortChange"
        assert "Created At" in content, f"{page_path.name}: missing audit column header 'Created At'"
        assert "Updated At" in content, f"{page_path.name}: missing audit column header 'Updated At'"
        assert "Creator" in content, f"{page_path.name}: missing audit column header 'Creator'"
        assert "Updater" in content, f"{page_path.name}: missing audit column header 'Updater'"


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
