"""Deleting a row another row still points at is `409 Conflict` naming the blocker — never a 500.

Measured: the generated `DELETE` answered a foreign-key violation with an unhandled 500, so a legitimate
refusal (a parent with children) was indistinguishable from a crash, and the "refuses deletion" browser
specs could only assert "not 204" — which a crash also satisfies. The core now converts exactly the
foreign-key violation (SQLSTATE 23503) and leaves every other database failure what it was.

The behaviour is exercised, not read: the session is a stub whose commit raises the error PostgreSQL
raised in the measured case (`pgcode 23503`, `diag.table_name` the REFERENCING table). The core raises a
plain `StillReferenced` (only the router imports fastapi); the generated route answers it as 409.
"""
import dataclasses

import pytest
from sqlalchemy.exc import IntegrityError


class _Diag:
    def __init__(self, table_name=None, message_detail=None):
        self.table_name = table_name
        self.message_detail = message_detail


class _Original(Exception):
    def __init__(self, pgcode, diag):
        super().__init__("database error text that must not reach the caller: constraint sub_items_item_fk_fkey")
        self.pgcode = pgcode
        self.diag = diag


def _integrity_error(pgcode, table_name=None, message_detail=None):
    return IntegrityError("DELETE ...", {}, _Original(pgcode, _Diag(table_name, message_detail)))


class _Session:
    def __init__(self, error):
        self.error = error
        self.rolled_back = False

    def delete(self, row):
        pass

    def commit(self):
        raise self.error

    def rollback(self):
        self.rolled_back = True


@pytest.fixture(scope="module")
def core(app_module):
    import ideable_api.entities as core
    return core


@pytest.fixture
def descriptor(core, app_module):
    """Whichever entity registers first, with its own delete hooks neutralised.

    This suite measures the foreign-key -> 409 conversion in `delete_entity_row`, not a hook — and
    runs it against a bare `object()` standing in for a row (see module docstring). An entity whose
    own `before_delete`/`after_delete` reads the row it is given (the common "refuse while still
    referenced" shape) would fail every test here with an unrelated `UnmappedInstanceError`, for a
    reason that has nothing to do with the 409 this file exists to prove
    (`module-specs.md` § "`test_a_restricted_delete_is_a_409.py` is a third FRAMEWORK contract").
    """
    return dataclasses.replace(
        next(iter(core.all_entity_descriptors().values())),
        before_delete=None, after_delete=None,
    )


def test_a_foreign_key_violation_is_a_409_naming_the_referencing_table(core, descriptor):
    session = _Session(_integrity_error("23503", table_name="sub_items"))
    with pytest.raises(core.StillReferenced) as refusal:
        core.delete_entity_row(session, descriptor, object(), None)
    assert str(refusal.value) == f"{descriptor.key} is still referenced by sub_items and cannot be deleted"
    assert session.rolled_back, "the failed transaction must be rolled back before the answer"


def test_the_answer_leaks_nothing_else_of_the_database(core, descriptor):
    session = _Session(_integrity_error("23503", table_name="sub_items"))
    with pytest.raises(core.StillReferenced) as refusal:
        core.delete_entity_row(session, descriptor, object(), None)
    assert "constraint" not in str(refusal.value) and "fkey" not in str(refusal.value)
    assert refusal.value.__cause__ is None, "the driver's error text must not travel with the answer"


def test_the_table_is_read_from_the_detail_when_the_driver_gives_no_diagnostic_table(core, descriptor):
    session = _Session(_integrity_error("23503", message_detail='Key (id)=(5) is still referenced from table "sub_item_notes".'))
    with pytest.raises(core.StillReferenced) as refusal:
        core.delete_entity_row(session, descriptor, object(), None)
    assert "sub_item_notes" in str(refusal.value)


def test_with_no_table_known_it_still_refuses_with_a_409(core, descriptor):
    session = _Session(_integrity_error("23503"))
    with pytest.raises(core.StillReferenced) as refusal:
        core.delete_entity_row(session, descriptor, object(), None)
    assert "other rows" in str(refusal.value)


@pytest.mark.parametrize("pgcode", ["23502", "23505", "23514", None])
def test_any_other_integrity_failure_stays_the_server_error_it_was(core, descriptor, pgcode):
    session = _Session(_integrity_error(pgcode))
    with pytest.raises(IntegrityError):
        core.delete_entity_row(session, descriptor, object(), None)
    assert session.rolled_back


def test_the_exception_is_plain_because_only_the_router_imports_fastapi(core):
    assert core.StillReferenced.__mro__[1] is Exception


def test_the_generated_delete_turns_it_into_a_409():
    from pathlib import Path
    router = (Path(__file__).resolve().parents[1] / "SOURCES" / ".ideable-api" / "ideable_api" / "router.py").read_text(encoding="utf-8")
    start = router.index("def delete_row(\n        row_id: int")
    body = router[start: router.index("\n    if not descriptor.read_only", start)]
    assert "except StillReferenced as refusal" in body
    assert "status.HTTP_409_CONFLICT" in body and "detail=str(refusal)" in body
