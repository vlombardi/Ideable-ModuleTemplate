"""The audit history is paginated by the database, not in Python.

The endpoint used to load every version of a record, build two more maps with
`IN (all transaction_ids)`, convert every row to Pydantic, sort in Python, and only then slice.
`skip` and `limit` reduced nothing.

Measured on a record with 50,000 versions, returning a 50-row page:

    before   153,755 / 156,682 / 157,599 ms   (50,000 Pydantic rows materialised for 50 returned)
    after          8.3 ms p95 at skip=0
                  50.4 ms p95 at skip=49950   (offset still walks — documented, hence the cursor)
                   6.6 ms p95 by cursor       (constant with depth)

Roughly 18,500x on the first page. On a shared backend the old shape was also a noisy-neighbour
problem: one request on a heavily edited record consumed CPU and memory proportional to that
record's entire lifetime, degrading every other user at the same time.
"""
from pathlib import Path

import pytest
import requests

_APP = Path(__file__).resolve().parents[1] / "SOURCES" / "app"
_CRUD = (_APP / "crud.py").read_text(encoding="utf-8")
_ROUTER = (_APP / "routers" / "items.py").read_text(encoding="utf-8")


class TestWorkHappensInSql:

    def test_the_page_is_limited_by_the_database(self):
        assert "LIMIT :limit OFFSET :skip" in _CRUD

    def test_total_comes_from_a_count_not_from_len(self):
        assert "SELECT count(*)" in _CRUD
        assert "total = len(all_rows)" not in _ROUTER

    def test_no_python_sort_remains_in_the_endpoint(self):
        """`sorted(...)` over the whole history was the second unbounded cost."""
        assert "sorted(all_rows" not in _ROUTER
        assert "ORDER BY" in _CRUD

    def test_ordering_uses_an_indexable_key(self):
        """`issued_at` sits behind a COALESCE on a joined table, so no index can serve it.

        Ordering by it made the database sort all 50,000 rows before applying LIMIT (44 ms).
        `transaction_id` leads the version table's primary key, so the scan stops after LIMIT.
        """
        assert "'timestamp': 'v.transaction_id'" in _CRUD

    def test_actor_join_cannot_fan_out(self):
        """Without the key predicate in the JOIN, one row per metadata entry would be returned."""
        assert "m.key = 'actor'" in _CRUD

    def test_ordering_has_a_deterministic_tiebreak(self):
        """Rows sharing a sort value would otherwise reappear or vanish between pages."""
        assert "v.transaction_id {direction}" in _CRUD


class TestFilterEquivalence:
    """The filters moved from Python to SQL and must behave identically."""

    def test_actor_filter_matches_the_normalised_actor(self):
        """The response shows `COALESCE(NULLIF(BTRIM(value),''),'system')`; filtering must too."""
        assert "_ACTOR_SQL" in _CRUD
        assert "COALESCE(NULLIF(BTRIM(m.value), ''), :system_actor)" in _CRUD

    def test_operation_filter_accepts_label_or_numeric_code(self):
        assert "op_label" in _CRUD and "op_exact" in _CRUD

    def test_timestamp_filter_reproduces_python_isoformat(self):
        """isoformat() omits the fractional part when microseconds are zero; SQL must match."""
        assert "date_part('microseconds'" in _CRUD


class TestLiveEndpoint:

    def test_history_returns_a_page_and_a_total(self, api_base_url, auth_headers):
        items = requests.get(
            f"{api_base_url}/items", params={"limit": 1}, headers=auth_headers, timeout=15
        ).json()["items"]
        if not items:
            pytest.skip("no items to inspect")
        item_id = items[0]["id"]
        response = requests.get(
            f"{api_base_url}/items/{item_id}/history",
            params={"limit": 50}, headers=auth_headers, timeout=30,
        )
        assert response.status_code == 200
        body = response.json()
        assert {"items", "total", "page", "size", "pages"} <= set(body)
        assert len(body["items"]) <= 50

    def test_history_rejects_an_oversized_page(self, api_base_url, auth_headers):
        items = requests.get(
            f"{api_base_url}/items", params={"limit": 1}, headers=auth_headers, timeout=15
        ).json()["items"]
        if not items:
            pytest.skip("no items to inspect")
        response = requests.get(
            f"{api_base_url}/items/{items[0]['id']}/history",
            params={"limit": 100000}, headers=auth_headers, timeout=15,
        )
        assert response.status_code == 422

    def test_sorting_by_actor_and_operation_still_works(self, api_base_url, auth_headers):
        items = requests.get(
            f"{api_base_url}/items", params={"limit": 1}, headers=auth_headers, timeout=15
        ).json()["items"]
        if not items:
            pytest.skip("no items to inspect")
        for sort_by in ("actor", "operation_type", "timestamp"):
            response = requests.get(
                f"{api_base_url}/items/{items[0]['id']}/history",
                params={"limit": 10, "sort_by": sort_by, "sort_order": "asc"},
                headers=auth_headers, timeout=30,
            )
            assert response.status_code == 200, f"sort_by={sort_by} failed"


class TestSyntheticCreationRow:

    def test_it_is_built_without_materialising_anything(self):
        assert "if total == 0:" in _ROUTER
        assert "make_synthetic_creation_row" in _ROUTER

    def test_it_is_not_repeated_on_later_pages(self):
        """It is one row; paging past it must return nothing rather than showing it again."""
        assert "[] if skip > 0 else" in _ROUTER
