from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
HOSTAPP_TABLE_PATH = PROJECT_ROOT / "modules" / "HostApp" / "frontend" / "SOURCES" / "src" / "components" / "ServerDataTable.tsx"
TEMPLATE_TABLE_PATH = PROJECT_ROOT / "modules" / "ModuleTemplate" / "frontend" / "SOURCES" / "src" / "components" / "ServerDataTable.tsx"
HOSTAPP_USERS_PAGE_PATH = PROJECT_ROOT / "modules" / "HostApp" / "frontend" / "SOURCES" / "src" / "pages" / "Users.tsx"
TEMPLATE_ITEMS_PAGE_PATH = PROJECT_ROOT / "modules" / "ModuleTemplate" / "frontend" / "SOURCES" / "src" / "pages" / "TemplateItems.tsx"


TABLE_CLASS_FRAGMENTS = [
    "template-relative template-overflow-auto template-rounded-md template-border",
    "template-sticky template-top-0 template-z-10 template-border-b template-bg-background",
    "template-h-12 template-px-4 template-text-left template-align-middle template-font-medium template-text-muted-foreground",
    "template-flex template-items-center template-justify-between template-border-t template-bg-background template-py-2",
]

TEMPLATE_ONLY_CLASS_FRAGMENTS = [
    "template-h-8 template-p-0 template-font-medium",
    "template-h-8 template-w-full template-rounded-md template-border template-bg-background",
]


PAGE_CLASS_FRAGMENTS = [
    "template-flex template-items-center template-justify-between",
    "template-text-3xl template-font-bold",
]

TEMPLATE_ONLY_PAGE_FRAGMENTS = [
    "template-inline-flex template-items-center template-justify-center template-whitespace-nowrap template-rounded-md template-text-sm template-font-medium",
]


ICON_CONTRACT = [
    "SortNeutralIcon",
    "SortAscIcon",
    "SortDescIcon",
    "ChevronLeftIcon",
    "ChevronRightIcon",
    "ChevronsLeftIcon",
    "ChevronsRightIcon",
    "EyeIcon",
    "EyeOffIcon",
]


def _normalize_host_classes(source: str) -> str:
    return source.replace("hostapp-", "template-")


def _compact(source: str) -> str:
    return " ".join(source.split())


def test_serverdatatable_lf_class_parity_contract() -> None:
    host_content = _normalize_host_classes(HOSTAPP_TABLE_PATH.read_text(encoding="utf-8"))
    template_content = TEMPLATE_TABLE_PATH.read_text(encoding="utf-8")

    host_compact = _compact(host_content)
    template_compact = _compact(template_content)

    for fragment in TABLE_CLASS_FRAGMENTS:
        assert fragment in host_compact
        assert fragment in template_compact

    for fragment in TEMPLATE_ONLY_CLASS_FRAGMENTS:
        assert fragment in template_compact

    assert "Rows per page:" in template_content
    assert "Page {page} of {totalPages}" in template_content
    assert "Audit Data" in template_content

    for icon_name in ICON_CONTRACT:
        assert icon_name in template_content


def test_templateitems_page_lf_contract() -> None:
    host_content = _normalize_host_classes(HOSTAPP_USERS_PAGE_PATH.read_text(encoding="utf-8"))
    template_content = TEMPLATE_ITEMS_PAGE_PATH.read_text(encoding="utf-8")

    host_compact = _compact(host_content)
    template_compact = _compact(template_content)

    for fragment in PAGE_CLASS_FRAGMENTS:
        assert fragment in host_compact
        assert fragment in template_compact

    for fragment in TEMPLATE_ONLY_PAGE_FRAGMENTS:
        assert fragment in template_compact

    assert "Create Item" in template_content
    assert "template-bg-primary template-text-primary-foreground" in template_content
