"""Look-and-feel parity contract (post @ideable/ui migration).

Parity between host_app and every module's data tables is now guaranteed
*structurally*: they all render the SAME shared widget,
``reusable.ui/widgets/ServerDataTable.tsx`` (package ``@ideable/ui``). So instead of
comparing per-module class strings (the old ``{slug}-`` vs ``hostapp-`` approach,
obsolete now that the shared widget uses the neutral ``ideable:`` prefix), these
checks enforce the shared-consumption contract:

* the shared widget exists and carries the table controls, and
* host_app and the module both consume it (rather than shipping their own copy).
"""
import re
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parents[2]          # modules/<module>
PROJECT_ROOT = MODULE_ROOT.parents[1]                      # repo root
SOURCES_DIR = MODULE_ROOT / "frontend" / "SOURCES" / "src"

SHARED_TABLE = PROJECT_ROOT / "reusable.ui" / "widgets" / "ServerDataTable.tsx"
HOSTAPP_TABLE = (
    PROJECT_ROOT / "modules" / "host_app" / "frontend" / "SOURCES" / "src"
    / "components" / "ServerDataTable.tsx"
)
LOCAL_TABLE = SOURCES_DIR / "components" / "ServerDataTable.tsx"

# Control markers the shared table must render: i18n keys for the rows-per-page
# selector + page indicator, and the lucide pagination / sort icons.
SHARED_TABLE_CONTRACT = [
    "table.rowsPerPage",
    "table.page",
    "ChevronsLeft",
    "ChevronLeft",
    "ChevronRight",
    "ChevronsRight",
    "ArrowUpDown",  # sort-neutral
    "ArrowUp",      # sort-asc
    "ArrowDown",    # sort-desc
]


def test_shared_serverdatatable_defines_lf_contract() -> None:
    assert SHARED_TABLE.exists(), f"shared widget missing: {SHARED_TABLE}"
    content = SHARED_TABLE.read_text(encoding="utf-8")
    for marker in SHARED_TABLE_CONTRACT:
        assert marker in content, f"shared ServerDataTable missing control marker: {marker}"


def test_hostapp_consumes_shared_serverdatatable() -> None:
    # Module-only projects may not vendor host_app; the parity anchor is still the
    # shared widget, so skip rather than fail when host_app is absent.
    if not HOSTAPP_TABLE.exists():
        pytest.skip("host_app not present in this project")
    content = HOSTAPP_TABLE.read_text(encoding="utf-8")
    assert "@ideable/ui" in content and "ServerDataTable" in content, (
        "host_app ServerDataTable must re-export the shared @ideable/ui widget "
        "(look-and-feel parity comes from consuming the same code)"
    )


def test_module_pages_consume_shared_serverdatatable() -> None:
    # A module must not ship its own ServerDataTable copy; parity comes from @ideable/ui.
    assert not LOCAL_TABLE.exists(), (
        "module must consume @ideable/ui's ServerDataTable, not a local "
        f"copy at {LOCAL_TABLE.relative_to(MODULE_ROOT)}"
    )

    pages_dir = SOURCES_DIR / "pages"
    page_files = list(pages_dir.glob("*.tsx"))
    assert page_files, "No page files found in SOURCES/src/pages/"

    table_pages = [p for p in page_files if "ServerDataTable" in p.read_text(encoding="utf-8")]
    assert table_pages, "No pages using ServerDataTable found"
    for page in table_pages:
        content = page.read_text(encoding="utf-8")
        assert re.search(r"from ['\"]@ideable/ui", content), (
            f"{page.name}: ServerDataTable must be imported from @ideable/ui"
        )
