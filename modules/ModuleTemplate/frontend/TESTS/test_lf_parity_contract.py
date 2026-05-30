import re
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = MODULE_ROOT.parents[1]
SOURCES_DIR = MODULE_ROOT / "frontend" / "SOURCES" / "src"


def _read_env(key: str) -> str:
    env_path = MODULE_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise KeyError(f"{key} not found in .env")


def _get_slug() -> str:
    return _read_env("APP_SLUG")


def _get_main_entities() -> list[str]:
    datamodel_path = MODULE_ROOT / "database" / "SPECS" / "datamodel.sql"
    if not datamodel_path.exists():
        datamodel_path = MODULE_ROOT / "database" / "SOURCES" / "initdb" / "datamodel.sql"
    content = datamodel_path.read_text(encoding="utf-8")
    return re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", content)


def _normalize_host_classes(source: str, slug: str) -> str:
    return source.replace("hostapp-", f"{slug}-")


def _compact(source: str) -> str:
    return " ".join(source.split())


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


def test_serverdatatable_lf_class_parity_contract() -> None:
    slug = _get_slug()
    hostapp_table = PROJECT_ROOT / "modules" / "HostApp" / "frontend" / "SOURCES" / "src" / "components" / "ServerDataTable.tsx"
    module_table = SOURCES_DIR / "components" / "ServerDataTable.tsx"

    host_content = _normalize_host_classes(hostapp_table.read_text(encoding="utf-8"), slug)
    module_content = module_table.read_text(encoding="utf-8")

    host_compact = _compact(host_content)
    module_compact = _compact(module_content)

    table_class_fragments = [
        f"{slug}-relative {slug}-overflow-auto {slug}-rounded-md {slug}-border",
        f"{slug}-sticky {slug}-top-0 {slug}-z-10 {slug}-border-b {slug}-bg-background",
        f"{slug}-h-12 {slug}-px-4 {slug}-text-left {slug}-align-middle {slug}-font-medium {slug}-text-muted-foreground",
        f"{slug}-flex {slug}-items-center {slug}-justify-between {slug}-border-t {slug}-bg-background {slug}-py-2",
    ]
    for fragment in table_class_fragments:
        assert fragment in host_compact, f"HostApp ServerDataTable missing: {fragment}"
        assert fragment in module_compact, f"Module ServerDataTable missing: {fragment}"

    assert "Rows per page:" in module_content
    assert "Page {page} of {totalPages}" in module_content
    assert "Audit Data" in module_content

    for icon_name in ICON_CONTRACT:
        assert icon_name in module_content, f"ServerDataTable missing icon: {icon_name}"


def test_entity_pages_lf_contract() -> None:
    slug = _get_slug()
    entities = _get_main_entities()
    assert entities, "No main entities found in datamodel.sql"

    hostapp_page = PROJECT_ROOT / "modules" / "HostApp" / "frontend" / "SOURCES" / "src" / "pages" / "Users.tsx"
    host_content = _normalize_host_classes(hostapp_page.read_text(encoding="utf-8"), slug)
    host_compact = _compact(host_content)

    page_class_fragments = [
        f"{slug}-flex {slug}-items-center {slug}-justify-between",
        f"{slug}-text-3xl {slug}-font-bold",
    ]

    pages_dir = SOURCES_DIR / "pages"
    page_files = list(pages_dir.glob("*.tsx"))
    assert page_files, "No page files found in SOURCES/src/pages/"

    for page_path in page_files:
        module_content = page_path.read_text(encoding="utf-8")
        if "ServerDataTable" not in module_content:
            continue
        module_compact = _compact(module_content)
        for fragment in page_class_fragments:
            assert fragment in host_compact, f"HostApp Users.tsx missing: {fragment}"
            assert fragment in module_compact, f"{page_path.name} missing: {fragment}"
        assert f"{slug}-bg-primary {slug}-text-primary-foreground" in module_content, \
            f"{page_path.name} missing primary button classes"
