"""
audit/audit.py — Immutable append-only event ledger.

log_event() is called at every pipeline stage.
Records are NEVER updated or deleted — only appended.
Supports replay, compliance exports, and anomaly detection.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from audit.taxonomy import EventType, Severity
from auth.db import Base

logger = logging.getLogger(__name__)


# ── ORM Model ────────────────────────────────────────────────────────────────

class EventModel(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default=Severity.INFO.value)

    # Identity context
    org_id: Mapped[str | None] = mapped_column(String(100), index=True)
    twin_id: Mapped[str | None] = mapped_column(String(100), index=True)

    # Message linkage
    message_id: Mapped[str | None] = mapped_column(String(36), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # Policy reference
    policy_decision_ref: Mapped[str | None] = mapped_column(String(36))
    rule_id: Mapped[str | None] = mapped_column(String(100))

    # Outcome
    result: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(Text)

    # Extra structured data (JSON string)
    metadata_json: Mapped[str | None] = mapped_column(Text)

    # Timestamp — immutable
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Event {self.event_type} twin={self.twin_id} result={self.result}>"


# ── Core log_event() function ─────────────────────────────────────────────────

async def log_event(
    db: AsyncSession,
    event_type: EventType,
    *,
    org_id: str | None = None,
    twin_id: str | None = None,
    message_id: str | None = None,
    thread_id: str | None = None,
    policy_decision_ref: str | None = None,
    rule_id: str | None = None,
    result: str | None = None,
    reason: str | None = None,
    severity: Severity = Severity.INFO,
    extra: dict[str, Any] | None = None,
) -> EventModel:
    """
    Append an immutable event to the audit ledger.

    Called at every stage of the T2T pipeline:
    - MESSAGE_RECEIVED → VALIDATED → POLICY_ALLOWED/DENIED → MESSAGE_ROUTED
    - MESSAGE_ACKNOWLEDGED → ORCHESTRATION_STARTED → STEP_* → WORKFLOW_*
    - ESCALATION_* → NOTIFICATION_SENT

    Never raises — logs a warning and returns a stub if DB write fails.
    """
    import json

    event = EventModel(
        event_id=str(uuid.uuid4()),
        event_type=event_type.value,
        severity=severity.value,
        org_id=org_id,
        twin_id=twin_id,
        message_id=message_id,
        thread_id=thread_id,
        policy_decision_ref=policy_decision_ref,
        rule_id=rule_id,
        result=result,
        reason=reason,
        metadata_json=json.dumps(extra) if extra else None,
        timestamp=datetime.utcnow(),
    )

    try:
        db.add(event)
        await db.flush()
        logger.debug(
            "Audit event: type=%s twin=%s result=%s",
            event_type.value, twin_id, result
        )
    except Exception as exc:
        logger.warning("Failed to write audit event %s: %s", event_type.value, exc)

    return event


# ── Query helpers (for admin / compliance endpoints) ─────────────────────────

from sqlalchemy import select, desc  # noqa: E402


async def get_events_for_message(
    db: AsyncSession, message_id: str
) -> list[EventModel]:
    result = await db.execute(
        select(EventModel)
        .where(EventModel.message_id == message_id)
        .order_by(EventModel.timestamp)
    )
    return result.scalars().all()


async def get_events_for_twin(
    db: AsyncSession,
    twin_id: str,
    limit: int = 100,
) -> list[EventModel]:
    result = await db.execute(
        select(EventModel)
        .where(EventModel.twin_id == twin_id)
        .order_by(desc(EventModel.timestamp))
        .limit(limit)
    )
    return result.scalars().all()


async def get_denied_events(
    db: AsyncSession,
    org_id: str,
    limit: int = 100,
) -> list[EventModel]:
    result = await db.execute(
        select(EventModel)
        .where(
            EventModel.org_id == org_id,
            EventModel.event_type == EventType.POLICY_DENIED.value,
        )
        .order_by(desc(EventModel.timestamp))
        .limit(limit)
    )
    return result.scalars().all()
