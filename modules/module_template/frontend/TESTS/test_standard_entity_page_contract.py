"""How a module's pages relate to the framework's standard entity page.

MODULE-AGNOSTIC, and force-synced into every module: it names no entity, no page file and no slug.
It discovers the module's own pages and holds each to the contract for the shape it chose — a page
that ADOPTED `StandardEntityPage`/`EntityTable`, or one that hand-wrote its own table.

The catalogue-entry contract for the standard page itself — that it takes its subject as a
parameter, owns no placement and is decomposed — lives in the framework repository
(`scripts/TESTS/test_the_standard_page_is_a_catalogue_entry.py`), because it reads `reusable.ui/`,
which a remote module does not have: it consumes the same code as `@ideable/ui` from its
dependencies.

WHAT THIS IS FOR. A module chooses, per entity, whether to adopt the standard implementation. These
tests do not make that choice — they hold each page to what it chose. A page that adopted the
standard one must not also carry the fetching and table wiring it just delegated (that is the copy
the adoption was meant to remove); a page that hand-wrote its own is held to the full wiring by
`test_entity_table_contract.py`, as before.
"""
import re
from pathlib import Path

import pytest

_SOURCES = Path(__file__).resolve().parents[1] / "SOURCES" / "src"
_PAGES = _SOURCES / "pages"

#: The dev-only widget gallery demonstrates widgets with synthetic data. Every module ships one,
#: and it is not an entity page however it imports.
_NOT_AN_ENTITY_PAGE = ("WidgetGallery.tsx",)


def _pages() -> list[Path]:
    found = [p for p in sorted(_PAGES.glob("*.tsx")) if p.name not in _NOT_AN_ENTITY_PAGE]
    assert found, "no pages found in SOURCES/src/pages/"
    return found


def _adopting_pages() -> list[Path]:
    """Pages that render the framework's standard entity page or its table."""
    return [p for p in _pages()
            if re.search(r"\b(StandardEntityPage|EntityTable)\b", p.read_text(encoding="utf-8"))]


def test_the_module_presents_its_entities_somehow() -> None:
    """Either shape counts. Presenting none at all is the gap worth failing on."""
    presenting = [
        p for p in _pages()
        if re.search(r"\b(StandardEntityPage|EntityTable|ServerDataTable)\b",
                     p.read_text(encoding="utf-8"))
    ]
    assert presenting, (
        "no page presents an entity: none renders StandardEntityPage or EntityTable, and none "
        "builds a ServerDataTable of its own"
    )


class TestAPageThatAdoptedTheStandardOneKeptNothingItDelegated:
    """Adoption that leaves the old code behind is the worst of both: two implementations of one
    entity, and the hand-written one still the thing that has to be maintained."""

    @pytest.mark.parametrize("page", _adopting_pages(), ids=lambda p: p.name)
    def test_it_does_not_also_build_a_table(self, page: Path) -> None:
        content = page.read_text(encoding="utf-8")
        if "EntityTable" in content and "StandardEntityPage" not in content:
            # A page composing EntityTable beside its own content is a legitimate custom page; it
            # simply must not hand-roll the table it is already reusing.
            pass
        for hand_rolled in ("ServerDataTable", "useServerTableState"):
            assert hand_rolled not in content, (
                f"{page.name} adopts the framework table and ALSO builds one with {hand_rolled} — "
                f"one of the two is dead code, and the dead one is the one nobody updates"
            )

    @pytest.mark.parametrize("page", _adopting_pages(), ids=lambda p: p.name)
    def test_it_localizes_what_it_renders(self, page: Path) -> None:
        """Its own strings — headings, labels — are still the page's to translate. The widget
        resolves its own chrome from the library bundle."""
        content = page.read_text(encoding="utf-8")
        assert "useTranslation" in content, (
            f"{page.name} renders user-facing strings without useTranslation"
        )


def test_an_adopting_page_does_not_fetch_the_entity_itself() -> None:
    """The point of adopting: the ENTITY's rows are fetched by the widget, not by the page.

    Narrowly scoped, and the narrowing matters. A page that forwards still legitimately fetches
    other things — permissions above all, which host_app resolves and the access token deliberately
    does not carry. Forbidding every effect would forbid that, and the first version of this test
    did exactly that: it failed the page for checking whether the user may edit.

    What must not come back is a per-entity data layer: a direct `fetch` of the entity's own path,
    or a typed list/create/update/delete service beside the transport.
    """
    for page in _adopting_pages():
        content = page.read_text(encoding="utf-8")
        if "StandardEntityPage" not in content:
            continue
        assert "fetch(" not in content, (
            f"{page.name} forwards to the standard page and still calls fetch() — the transport "
            f"owns the requests"
        )
        for listing in ("getItems", "listItems", "fetchRows", "loadRows"):
            assert listing not in content, (
                f"{page.name} still calls {listing}() — a per-entity fetching layer survived the "
                f"adoption, so there are now two ways this entity is read"
            )


def test_no_page_returns_before_its_hooks() -> None:
    """An early return above a hook takes the whole remote down, not just the page.

    React throws "Rendered fewer hooks than expected" on the render where the condition flips, and
    a module federation host reports that as the REMOTE having failed — the boundary message says
    the module is unavailable and names no line. Measured 2026-09-18: a permission guard placed one
    line above a `useMemo` failed six specs, and the symptom pointed at module loading, at chunk
    paths and at the manifest before it pointed at the page.

    Scanned rather than rendered because it is a source-level property, and because the failure it
    prevents is silent until the exact render that flips the condition — which a test that mounted
    the component once could easily miss.
    """
    hook = re.compile(r"\buse(State|Effect|Memo|Callback|Ref|Context|Reducer|[A-Z]\w+)\s*\(")
    # EXACTLY the component's own indentation. `\s{2,}` also matched `if (cancelled) return`
    # inside an effect's callback, which is an ordinary guard in a nested function and says nothing
    # about hook order — the first version of this check failed on one.
    early_return = re.compile(r"^  (if\s*\(.*\)\s*return\b|return\b)")

    for page in _pages():
        lines = page.read_text(encoding="utf-8").splitlines()
        body = None
        for index, line in enumerate(lines):
            if re.match(r"export default function \w+\(", line):
                body = index
                break
        if body is None:
            continue

        first_early_return = None
        for index in range(body + 1, len(lines)):
            line = lines[index]
            is_hook = bool(hook.search(line))
            # The hook check must come BEFORE the "left the component" break. A `const x = useMemo(…)`
            # is both a hook and a `const \w+ = ` line; the old order matched the latter first and
            # stopped scanning AT the hook's own declaration, so a hook after an early return passed
            # this test. Measured 2026-09-21: `TemplateItems` declared two `useMemo` hooks below its
            # permissions early return and every suite still went green.
            if first_early_return is not None and is_hook:
                raise AssertionError(
                    f"{page.name}: a hook on line {index + 1} sits below the early return on line "
                    f"{first_early_return + 1}, so it is called conditionally. React throws on the "
                    f"render where that condition flips, and the host reports the whole remote as "
                    f"crashed.\n    return: {lines[first_early_return].strip()}\n    hook:   "
                    f"{line.strip()}"
                )
            if re.match(r"^(export |function |const \w+ = )", line) and not is_hook:
                break  # left the component
            if first_early_return is None and early_return.match(line) and "=>" not in line:
                if line.strip().startswith("return ("):
                    break  # the component's final JSX return: everything before it was checked
                first_early_return = index
                continue


def test_the_shared_query_hook_sends_the_filters() -> None:
    """A filter row that narrows nothing is worse than no filter row.

    `useServerTableState.queryParams` carries paging and sort only; filters live beside it and have
    always been merged in by whatever builds the request. Measured 2026-09-18: the standard page
    rendered a filter row, accepted typing, and returned every row — the values never left the
    browser, and the spec that caught it was an end-to-end one, because every unit-level contract
    was satisfied.

    Read from `@ideable/ui` when it is present as source (the framework repository). A remote module
    consumes the built package and skips: the hook is not its to hold.
    """
    hook = (
        Path(__file__).resolve().parents[4] / "reusable.ui" / "hooks" / "useEntityQuery.ts"
    )
    if not hook.exists():
        pytest.skip("@ideable/ui is consumed as a package here, so its source is not readable")
    source = hook.read_text(encoding="utf-8")
    assert "debouncedFilters" in source, (
        "the entity query does not merge the table's filters into the request, so a filter row "
        "renders and narrows nothing"
    )
    assert "...debouncedFilters" in source or "...table.debouncedFilters" in source, (
        "the filters are read but not spread into the query parameters"
    )
