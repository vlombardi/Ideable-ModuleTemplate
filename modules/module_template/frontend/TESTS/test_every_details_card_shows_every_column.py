"""A details card shows every column of its entity, or says why it does not.

The spec says the card shows *all entity attributes*; the widget cannot derive them (labels and
renderers are the page's), so a page lists its fields by hand — and a column left off the list
vanished without anyone noticing (the Users card omitted `first_name`, `last_name` and the tenant).
So completeness is enforced: every model column of a page that declares `detailFields` is either a
field of the card or listed, with a reason, in `detailExcluded`.

A foreign key `x_fk` is covered by a field named `x` (the card shows the entity it points to).
The same file runs in every module (it reads its own pages and its own `models.py`).
"""
import ast
import re
from pathlib import Path

import pytest

_MODULE = Path(__file__).resolve().parents[2]
_PAGES = _MODULE / "frontend" / "SOURCES" / "src" / "pages"
_MODELS = _MODULE / "backend" / "SOURCES" / "app" / "models.py"


def _columns_by_entity() -> dict[str, list[str]]:
    """entity key -> the model's COLUMNS (mapped_column, not relationships), via the descriptors."""
    classes: dict[str, list[str]] = {}
    for node in ast.parse(_MODELS.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.ClassDef):
            continue
        columns = []
        for item in node.body:
            if (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                    and isinstance(item.value, ast.Call) and ast.unparse(item.value.func).endswith("mapped_column")):
                columns.append(item.target.id)
        classes[node.name] = columns
    by_entity: dict[str, list[str]] = {}
    for descriptor in sorted((_MODULE / "backend" / "SOURCES" / "app" / "entities").glob("*.py")):
        text = descriptor.read_text(encoding="utf-8")
        key = re.search(r"\bkey=['\"]([a-z_]+)['\"]", text)
        model = re.search(r"\bmodel=([A-Za-z_]+)", text)
        if key and model and model.group(1) in classes:
            by_entity[key.group(1)] = classes[model.group(1)]
    return by_entity


def _block(text: str, start: str) -> str:
    """The bracketed/braced literal that follows `start` (after `=> ` for a memo), balanced."""
    at = text.index(start)
    arrow = re.compile(r"=>\s*([\[{])").search(text, at) if "useMemo" in start else None
    opener = arrow.start(1) if arrow else next(i for i in range(at, len(text)) if text[i] in "[{")
    pair = {"[": "]", "{": "}"}[text[opener]]
    depth = 0
    for i in range(opener, len(text)):
        if text[i] == text[opener]:
            depth += 1
        elif text[i] == pair:
            depth -= 1
            if depth == 0:
                return text[opener: i + 1]
    raise AssertionError(f"unbalanced literal after {start!r}")


def _pages() -> list[tuple[str, str, str]]:
    found = []
    for page in sorted(_PAGES.glob("*.tsx")):
        text = page.read_text(encoding="utf-8")
        if "detailFields=" not in text:
            continue
        entity = re.search(r"entityKey=[\"{']+([a-z_]+)", text)
        if entity:
            found.append((page.name, entity.group(1), text))
    return found


_TABLES = _columns_by_entity()
_CASES = _pages()


def test_there_is_at_least_one_page_to_check():
    if not _CASES:
        pytest.skip("this module declares no page with a details card")


@pytest.mark.parametrize("page,entity,text", _CASES, ids=[c[0] for c in _CASES])
def test_every_column_is_shown_or_excluded_with_a_reason(page, entity, text):
    assert entity in _TABLES, f"{page}: no entity descriptor declares the key {entity!r}"
    declared = _block(text, "detailFields = useMemo")
    shown = set(re.findall(r"name:\s*['\"]([A-Za-z_]+)['\"]", declared))
    excluded_src = _block(text, "const detailExcluded") if "const detailExcluded" in text else "{}"
    excluded = dict(re.findall(r"([A-Za-z_]+):\s*['\"`]([^'\"`]+)['\"`]", excluded_src))

    reasonless = sorted(c for c, why in excluded.items() if not why.strip())
    assert not reasonless, f"{page}: detailExcluded gives no reason for {reasonless}"

    missing = []
    for column in _TABLES[entity]:
        covered = column in shown or column in excluded
        if column.endswith("_fk") and column[: -len("_fk")] in shown:
            covered = True
        if not covered:
            missing.append(column)
    assert not missing, (
        f"{page}: the details card of {entity!r} neither shows nor excludes (with a reason) "
        f"{missing} — add a field to detailFields, or the column to detailExcluded with why"
    )
    stale = sorted(c for c in excluded if c not in _TABLES[entity])
    assert not stale, f"{page}: detailExcluded names columns {entity!r} does not have: {stale}"
