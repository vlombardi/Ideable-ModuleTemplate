from pathlib import Path


PAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "SOURCES"
    / "src"
    / "pages"
    / "TemplateItems.tsx"
)
SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "SOURCES"
    / "src"
    / "services"
    / "templateItems.ts"
)
TABLE_COMPONENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "SOURCES"
    / "src"
    / "components"
    / "ServerDataTable.tsx"
)


def test_template_items_page_contains_server_table_controls() -> None:
    page_content = PAGE_PATH.read_text(encoding="utf-8")
    table_content = TABLE_COMPONENT_PATH.read_text(encoding="utf-8")

    # Page must use ServerDataTable component
    assert "ServerDataTable" in page_content
    assert "showAuditData" in page_content
    assert "handleFilterChange" in page_content
    assert "handleSortChange" in page_content
    
    # Table component must contain required strings
    assert "Rows per page:" in table_content
    assert "ChevronsLeftIcon" in table_content
    assert "ChevronLeftIcon" in table_content
    assert "ChevronRightIcon" in table_content
    assert "ChevronsRightIcon" in table_content
    assert "Page {page} of {totalPages}" in table_content
    assert "Audit Data" in table_content  # Template literal: {showAuditColumns ? 'Hide' : 'Show'} Audit Data
    assert "SortNeutralIcon" in table_content
    
    # Page must have audit column headers
    assert "Created At" in page_content
    assert "Updated At" in page_content
    assert "Creator" in page_content
    assert "Updater" in page_content


def test_template_items_service_omits_empty_filter_params() -> None:
    content = SERVICE_PATH.read_text(encoding="utf-8")

    assert "new URLSearchParams()" in content
    assert "query.name && query.name.trim() !== ''" in content
    assert "query.description && query.description.trim() !== ''" in content
    assert "query.au_creation_timestamp && query.au_creation_timestamp.trim() !== ''" in content
    assert "query.au_last_update_timestamp && query.au_last_update_timestamp.trim() !== ''" in content
    assert "query.au_created_by_user && query.au_created_by_user.trim() !== ''" in content
    assert "query.au_last_updated_by_user && query.au_last_updated_by_user.trim() !== ''" in content
    assert "query.sort_by && query.sort_by.trim() !== '' && query.sort_order" in content
