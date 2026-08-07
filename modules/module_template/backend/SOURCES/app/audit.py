"""Audit trail actor injection and reusable history helpers.

Provides a context variable that stores the currently authenticated username,
a SQLAlchemy before-commit listener that injects the actor into each
SQLAlchemy-Continuum TransactionMeta record, and factory utilities for building
history responses from SQLAlchemy-Continuum version tables.
"""
import logging
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy_continuum import versioning_manager
from sqlalchemy_continuum.plugins import Plugin

logger = logging.getLogger(__name__)

_current_user: ContextVar[str | None] = ContextVar('_current_user', default=None)
_system_startup_at: datetime = datetime.now(timezone.utc)
SYSTEM_ACTOR_USERNAME = "system"


def set_current_user(username: str | None) -> None:
    """Set the actor for the current async context (call once per request before commit)."""
    _current_user.set(username)


def clear_current_user() -> None:
    """Clear the actor for the current async context."""
    _current_user.set(None)


def get_current_user() -> str | None:
    """Return the actor for the current async context."""
    return _current_user.get()


def set_system_startup_at(startup_at: datetime | None) -> None:
    """Record the process startup timestamp used for synthetic creation events."""
    global _system_startup_at
    if startup_at is None:
        _system_startup_at = datetime.now(timezone.utc)
        return
    if startup_at.tzinfo is None:
        _system_startup_at = startup_at.replace(tzinfo=timezone.utc)
    else:
        _system_startup_at = startup_at.astimezone(timezone.utc)


def get_system_startup_at() -> datetime:
    """Return the process startup timestamp used for synthetic creation events."""
    return _system_startup_at


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime, adding UTC if naive."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_actor_username(username: str | None) -> str:
    """Return a stable username for audit rows, defaulting to the system actor."""
    cleaned = (username or "").strip()
    return cleaned or SYSTEM_ACTOR_USERNAME


# ---------------------------------------------------------------------------
# Reusable history-response factories
# ---------------------------------------------------------------------------

TSchema = TypeVar("TSchema")


def build_transaction_map(db: Session, version_rows: list[Any]) -> dict[int, datetime]:
    """Build a transaction_id -> issued_at mapping from Continuum's transaction table.

    Returns an empty dict when there are no version rows or when the query fails.
    Rolls back the session on SQLAlchemyError to keep the session usable.
    """
    if not version_rows:
        return {}
    tx_ids = [v.transaction_id for v in version_rows]
    try:
        TransactionModel = versioning_manager.transaction_cls
        tx_rows = db.query(TransactionModel).filter(TransactionModel.id.in_(tx_ids)).all()
        return {t.id: t.issued_at for t in tx_rows}
    except SQLAlchemyError:
        db.rollback()
        return {}


def build_transaction_actor_map(db: Session, version_rows: list[Any]) -> dict[int, str]:
    """Build a transaction_id -> actor mapping from Continuum transaction meta.

    Returns an empty dict when there are no version rows, when the query fails,
    or when the TransactionMetaPlugin is not enabled.
    """
    if not version_rows:
        return {}
    tx_ids = [v.transaction_id for v in version_rows]
    TransactionMetaModel = getattr(versioning_manager, 'transaction_meta_cls', None)
    if TransactionMetaModel is None:
        return {}
    try:
        rows = (
            db.query(TransactionMetaModel)
            .filter(TransactionMetaModel.transaction_id.in_(tx_ids))
            .filter(TransactionMetaModel.key == 'actor')
            .all()
        )
        return {r.transaction_id: r.value for r in rows if r.value}
    except SQLAlchemyError:
        db.rollback()
        return {}


def make_synthetic_creation_row(
    schema_cls: type[TSchema],
    entity: Any,
    startup_at: datetime | None = None,
    **field_overrides: Any,
) -> TSchema:
    """Return a synthetic INSERT version row for an entity with no history.

    Uses ``startup_at`` (or ``get_system_startup_at()``) for timestamps and
    ``SYSTEM_ACTOR_USERNAME`` for actor fields.  Business fields are taken from
    ``entity`` unless overridden via ``field_overrides``.
    """
    ts = ensure_utc(startup_at or get_system_startup_at())
    base = {
        "transaction_id": getattr(entity, "id", 0),
        "operation_type": 0,
        "end_transaction_id": None,
        "id": getattr(entity, "id", None),
        "timestamp": ts,
        "actor": SYSTEM_ACTOR_USERNAME,
        "actor_id": None,
    }
    for attr in dir(entity):
        if attr.startswith("_"):
            continue
        val = getattr(entity, attr, None)
        if not callable(val) and attr not in base:
            base[attr] = val
    base.update(field_overrides)
    return schema_cls(**base)


def version_row_to_schema(
    version_row: Any,
    schema_cls: type[TSchema],
    tx_map: dict[int, datetime],
    startup_at: datetime | None = None,
    actor_map: dict[int, str] | None = None,
    **extra_fields: Any,
) -> TSchema:
    """Convert a single Continuum version ORM row into a Pydantic schema instance.

    Timestamps are resolved from ``tx_map`` (falling back to ``startup_at``) and
    forced to UTC via ``ensure_utc``.  Actor fields are normalised with
    ``normalize_actor_username``.  Any ``extra_fields`` override values that
    would otherwise be copied from the ORM row.
    """
    ts = ensure_utc(tx_map.get(version_row.transaction_id, startup_at or get_system_startup_at()))
    actor = normalize_actor_username(
        (actor_map or {}).get(version_row.transaction_id)
    )
    data = {
        "transaction_id": version_row.transaction_id,
        "operation_type": int(version_row.operation_type),
        "end_transaction_id": getattr(version_row, "end_transaction_id", None),
        "id": getattr(version_row, "id", None),
        "timestamp": ts,
        "actor": actor,
        "actor_id": None,
    }
    for attr in dir(version_row):
        if attr.startswith("_") or attr in data:
            continue
        val = getattr(version_row, attr, None)
        if not callable(val):
            data[attr] = val
    data.update(extra_fields)
    return schema_cls(**data)


def merge_and_sort_history(
    field_versions: list[Any],
    association_rows: list[Any],
    startup_at: datetime | None = None,
) -> list[Any]:
    """Merge field-change and association-change rows and sort by timestamp descending.

    The returned list is a new list sorted so that the most recent event is first.
    When two rows have the same timestamp, the one with the higher transaction_id
    (newer) is placed first.
    """
    merged = list(field_versions) + list(association_rows)
    fallback = startup_at or get_system_startup_at()
    merged.sort(
        key=lambda r: (r.timestamp or fallback, r.transaction_id),
        reverse=True,
    )
    return merged


class ActorPlugin(Plugin):
    """Inject the authenticated actor into each Continuum transaction during flush."""

    def before_flush(self, uow, session):
        tx = uow.current_transaction
        if tx is not None:
            actor = _current_user.get()
            if actor:
                logger.debug("ActorPlugin.before_flush: actor=%s tx_id=%s", actor, tx.id)
                tx.meta['actor'] = actor


def _before_commit(session):
    """Inject the current actor into the Continuum transaction meta before each commit."""
    uow = versioning_manager.unit_of_work(session)
    if uow is not None:
        tx = uow.current_transaction
        if tx is not None:
            actor = _current_user.get()
            if actor:
                logger.debug("_before_commit: actor=%s tx_id=%s", actor, tx.id)
                tx.meta['actor'] = actor


def register_audit_listener(engine):
    """Attach the before-commit listener to the given SQLAlchemy engine's session factory.

    Call this once after the engine is created (e.g., in database.py or main.py).
    """
    from sqlalchemy import event as sa_event
    from sqlalchemy.orm import Session

    sa_event.listen(Session, 'before_commit', _before_commit)
