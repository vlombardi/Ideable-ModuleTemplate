"""Unit tests for the reusable audit history filter helper (app.audit.apply_history_filters).

Pure in-memory filtering used by every entity history endpoint to power the audit-table
column filters. Skipped when the backend deps aren't importable in the test env.
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy_continuum")
pytest.importorskip("sqlalchemy")

AUDIT = Path(__file__).resolve().parents[1] / "SOURCES" / "app" / "audit.py"


def _load():
    spec = importlib.util.spec_from_file_location("template_audit_under_test", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load()


def _row(op, actor, ts):
    return SimpleNamespace(operation_type=op, actor=actor, timestamp=ts)


ROWS = [
    _row(0, "alice(1)", datetime(2026, 8, 1, tzinfo=timezone.utc)),   # INSERT
    _row(1, "bob(2)", datetime(2026, 8, 2, tzinfo=timezone.utc)),     # UPDATE
    _row(2, "alice(1)", datetime(2025, 1, 5, tzinfo=timezone.utc)),   # DELETE
]


def test_no_filters_returns_all() -> None:
    assert audit.apply_history_filters(ROWS) == ROWS


def test_actor_substring_case_insensitive() -> None:
    result = audit.apply_history_filters(ROWS, actor="ALICE")
    assert [r.actor for r in result] == ["alice(1)", "alice(1)"]


def test_operation_type_by_label_and_by_int() -> None:
    assert [r.operation_type for r in audit.apply_history_filters(ROWS, operation_type="update")] == [1]
    assert [r.operation_type for r in audit.apply_history_filters(ROWS, operation_type="del")] == [2]
    assert [r.operation_type for r in audit.apply_history_filters(ROWS, operation_type="2")] == [2]


def test_timestamp_substring_matches_month() -> None:
    result = audit.apply_history_filters(ROWS, timestamp="2026-08")
    assert len(result) == 2


def test_blank_filters_ignored() -> None:
    assert audit.apply_history_filters(ROWS, actor="   ", operation_type="") == ROWS


def test_filters_combine_as_and() -> None:
    result = audit.apply_history_filters(ROWS, actor="alice", operation_type="insert")
    assert [r.operation_type for r in result] == [0]
