"""Pagination and query-cost contracts for the items list endpoint.

Three costs were paid on every page request before the query-performance work, and each is now optional or bounded:
an unconditional `COUNT(*)` (a second full pass with the same filters), `OFFSET` deep-paging that
degrades linearly and can duplicate or skip rows under concurrent writes, and an unbounded
`limit` that let one request ask for the whole table.

Measured on a 1,000,000-row dataset while implementing this:

    filter (leading wildcard)   543 ms Seq Scan   ->   2.6 ms Bitmap Index Scan
    filtered COUNT(*)           556 ms           ->   2.6 ms
    page at offset 900000        89 ms           ->   0.115 ms via cursor

The live assertions below run against the deployed stack; the rest are contract checks on the
source, because the behaviour they pin down (a cap expressed in OpenAPI, a cursor refused against
an unstable sort) is structural.
"""
import re
from pathlib import Path

import pytest
import requests

_APP = Path(__file__).resolve().parents[1] / "SOURCES" / "app"
_CRUD = (_APP / "crud.py").read_text(encoding="utf-8")
_ROUTER = (_APP / "routers" / "items.py").read_text(encoding="utf-8")


class TestPageSizeIsBounded:

    def test_cap_is_declared_in_the_api_signature(self):
        """`le=` puts the bound in OpenAPI, so a client sees it before sending the request."""
        assert "le=crud.MAX_PAGE_SIZE" in _ROUTER

    def test_crud_refuses_an_oversized_limit_independently(self):
        """The cap must not live only at the edge: crud is called directly by tests and jobs."""
        assert "if limit > MAX_PAGE_SIZE:" in _CRUD

    def test_oversized_limit_is_rejected(self, api_base_url, auth_headers):
        response = requests.get(
            f"{api_base_url}/items", params={"limit": 100000}, headers=auth_headers, timeout=15
        )
        assert response.status_code == 422, (
            f"expected 422 for limit=100000, got {response.status_code} — an unbounded page is a "
            f"denial-of-service vector and unbounded server memory per request"
        )


class TestTotalIsOptional:

    def test_include_total_false_omits_the_count(self, api_base_url, auth_headers):
        response = requests.get(
            f"{api_base_url}/items",
            params={"limit": 5, "include_total": "false"},
            headers=auth_headers,
            timeout=15,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0, "total must not be computed when not requested"

    def test_response_declares_whether_the_total_is_exact(self, api_base_url, auth_headers):
        """A view rendering "of N" must know whether N was counted or estimated."""
        response = requests.get(
            f"{api_base_url}/items", params={"limit": 5}, headers=auth_headers, timeout=15
        )
        assert response.status_code == 200
        assert "total_is_exact" in response.json()

    def test_estimate_is_used_above_the_threshold(self):
        assert "EXACT_COUNT_THRESHOLD" in _CRUD
        assert "_estimated_total" in _CRUD
        # The estimate must come from the planner, not from a count with a limit.
        assert "EXPLAIN (FORMAT JSON)" in _CRUD


def _max_page_size(api_base_url, auth_headers):
    """The API's declared maximum page size, read from OpenAPI.

    `le=crud.MAX_PAGE_SIZE` puts the bound in the schema precisely so a client can discover it
    instead of guessing — which is what a test is. Falls back to the code's default only if the
    schema does not carry it, and says so rather than passing quietly.
    """
    spec = requests.get(f"{api_base_url}/openapi.json", headers=auth_headers, timeout=15)
    assert spec.status_code == 200, f"cannot read OpenAPI: {spec.status_code}"
    for param in spec.json()["paths"]["/api/items"]["get"]["parameters"]:
        if param["name"] == "limit":
            maximum = param["schema"].get("maximum")
            assert maximum, f"the `limit` parameter declares no maximum: {param['schema']}"
            return int(maximum)
    raise AssertionError("GET /api/items declares no `limit` parameter")


class TestCursorPagination:

    # These read the SOURCE because the property is cheap to guard there and expensive to provoke
    # at runtime. They assert the PROPERTY, not its spelling: crud.py was factored into
    # model-parameterised helpers, so the same predicate is now written `model.id > after_id`
    # rather than `models.TemplateItem.id > after_id`. A test pinned to one entity's name would
    # have failed on a refactor that changed nothing it exists to protect — which is what happened.

    def test_cursor_seeks_instead_of_skipping(self):
        assert re.search(r"\.filter\(\s*\w+\.id\s*>\s*after_id", _CRUD), (
            "the cursor no longer seeks on id — deep pages would go back to scanning and "
            "discarding every row before the page"
        )
        assert ".offset(skip)" in _CRUD, "offset must remain for arbitrary page jumps"

    def test_cursor_is_refused_against_an_unstable_sort(self):
        """A cursor on a non-unique column silently skips rows; refusing is the safe failure."""
        assert re.search(r"if\s+keyset\s+and\s+sort_by\s*!=\s*['\"]id['\"]", _CRUD), (
            "a cursor combined with a non-id sort is no longer refused — the paginator would "
            "silently return the wrong window"
        )

    def test_next_cursor_is_returned_and_is_null_on_the_last_page(self, api_base_url, auth_headers):
        """A page shorter than the requested limit is the last page, so the cursor must be null.

        This asked for `limit=1000` and expected 200. The API caps pages at `MAX_PAGE_SIZE` (200) and
        returns 422 above it — which the sibling `test_oversized_limit_is_rejected` in this same file
        asserts deliberately. So the two tests contradicted each other, and the contradiction
        survived because neither had ever run: both were skipped for want of `TEST_AUTH_TOKEN`.

        The limit is now read from the API's own OpenAPI document rather than hardcoded, so a change
        to MAX_PAGE_SIZE cannot silently reintroduce the same disagreement.
        """
        limit = _max_page_size(api_base_url, auth_headers)
        response = requests.get(
            f"{api_base_url}/items", params={"limit": limit}, headers=auth_headers, timeout=15
        )
        assert response.status_code == 200, (
            f"limit={limit} is the documented maximum but was refused: "
            f"{response.status_code} {response.text[:200]}"
        )
        body = response.json()
        assert "next_after_id" in body
        if len(body["items"]) < limit:
            assert body["next_after_id"] is None, "a short page is the last page"

    def test_cursor_walk_visits_every_row_exactly_once(self, api_base_url, auth_headers):
        """The anomaly offset paging has: under concurrent writes rows shift between pages.

        Walking by cursor cannot duplicate or skip, because each page is defined by the last id
        seen rather than by a count of rows to discard.
        """
        seen, after_id, pages = [], None, 0
        while pages < 25:
            params = {"limit": 2, "include_total": "false"}
            if after_id is not None:
                params["after_id"] = after_id
            response = requests.get(
                f"{api_base_url}/items", params=params, headers=auth_headers, timeout=15
            )
            assert response.status_code == 200
            body = response.json()
            seen.extend(item["id"] for item in body["items"])
            after_id = body.get("next_after_id")
            pages += 1
            if after_id is None:
                break
        assert len(seen) == len(set(seen)), f"cursor walk returned duplicates: {seen}"
        assert seen == sorted(seen), "cursor walk must be monotonic in id"


class TestTrigramIndexes:

    def test_indexes_are_declared_on_the_model(self):
        """Declared in the model, so the schema workflow owns them like any other index."""
        models = (_APP / "models.py").read_text(encoding="utf-8")
        assert "gin_trgm_ops" in models
        assert "idx_template_items_name_trgm" in models

    def test_migration_creates_them_without_blocking_writes(self):
        """Read across every migration, not one named file.

        The trigram revision was squashed into the baseline; the operational properties it carried
        are what matter and they must survive the squash, so this asserts on them wherever they
        live.
        """
        versions = _APP.parent / "alembic" / "versions"
        migration = "".join(p.read_text(encoding="utf-8") for p in sorted(versions.glob("*.py")))
        assert "gin_trgm_ops" in migration, "no migration creates the trigram indexes"
        assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in migration
        assert "CONCURRENTLY" in migration, (
            "a plain CREATE INDEX takes ACCESS EXCLUSIVE and blocks every write for the duration"
        )
        assert "autocommit_block" in migration, "CONCURRENTLY cannot run inside a transaction"
        assert "maintenance_work_mem" in migration, (
            "the TimescaleDB image sizes maintenance_work_mem from HOST memory (~980MB) while the "
            "container is capped at 1GB; an unbounded index build OOM-killed the database"
        )


class TestCursorPredicateReachesTheQuery:
    """`before_transaction_id` must actually narrow the row query.

    Found by the first `ruff` run of the runtime-correctness work, as `F841 local variable 'paged_joins' is assigned to
    but never used`. The cursor clause was built, its parameter was bound, `paged_joins` was
    assembled — and the row query interpolated `joins`, without it. At the same time the offset was
    forced to `0` **because** a cursor was present.

    So a client paging with `?before_transaction_id=N` got the first page back, every time: the
    cursor was ignored and the offset was zeroed. It failed silently — SQLAlchemy's `text()` accepts
    a bound parameter the SQL never references — and no test covered the cursor path.
    """

    def test_the_row_query_uses_the_cursor_and_the_count_does_not(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "SOURCES" / "app" / "crud.py"
        ).read_text(encoding="utf-8")
        body = src.split("def list_item_history")[1].split("\ndef ")[0]

        assert "AS actor {paged_joins} " in body, (
            "the row query must interpolate `paged_joins`; with plain `joins` the cursor predicate "
            "is dropped while the offset is still zeroed, so every page is the first page"
        )
        assert "SELECT count(*) {joins}" in body, (
            "the total must count the whole history, not the page — otherwise a client cannot know "
            "how many rows remain"
        )

    def test_the_cursor_is_only_applied_to_the_default_ordering(self):
        """Against an `actor` or `operation_type` sort a transaction-id cursor would skip rows."""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1] / "SOURCES" / "app" / "crud.py"
        ).read_text(encoding="utf-8")
        body = src.split("def list_item_history")[1].split("\ndef ")[0]
        assert "(sort_by or 'timestamp') == 'timestamp'" in body
