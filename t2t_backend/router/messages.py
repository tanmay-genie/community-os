"""
router/messages.py — Message ORM model + state machine transitions.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from auth.db import Base
from schemas.intents import MessageState


class MessageModel(Base):
    __tablename__ = "t2t_messages"

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    protocol_version: Mapped[str] = mapped_column(String(10), default="1.0")

    # Thread linkage
    thread_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # Parties
    from_twin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    from_org_id: Mapped[str] = mapped_column(String(100), nullable=False)
    from_role: Mapped[str | None] = mapped_column(String(100))
    from_clearance: Mapped[str | None] = mapped_column(String(50))

    to_twin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    to_org_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # Intent
    intent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    intent_name: Mapped[str | None] = mapped_column(String(200))
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    requires_human_confirmation: Mapped[bool] = mapped_column(default=False)
    sla_minutes: Mapped[int] = mapped_column(default=1440)

    # Scope
    contract_id: Mapped[str | None] = mapped_column(String(100))
    redaction_profile: Mapped[str] = mapped_column(String(50), default="INTERNAL_FULL")

    # Payload (stored as JSON string)
    payload_json: Mapped[str | None] = mapped_column(Text)

    # Security
    idempotency_key: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    nonce: Mapped[str | None] = mapped_column(String(36))
    signature: Mapped[str | None] = mapped_column(Text)

    # Telemetry
    trace_id: Mapped[str | None] = mapped_column(String(36))
    span_id: Mapped[str | None] = mapped_column(String(36))

    # State machine
    state: Mapped[str] = mapped_column(
        String(30), nullable=False,
        default=MessageState.DRAFT.value,
        index=True,
    )
    policy_decision: Mapped[str | None] = mapped_column(String(20))
    policy_rule_id: Mapped[str | None] = mapped_column(String(100))
    policy_reason: Mapped[str | None] = mapped_column(Text)
    policy_decision_id: Mapped[str | None] = mapped_column(String(36))

    # For reply messages — links back to original
    in_reply_to_message_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    def __repr__(self) -> str:
        return (
            f"<Message {self.message_id[:8]} "
            f"{self.from_twin_id}→{self.to_twin_id} "
            f"intent={self.intent_type} state={self.state}>"
        )


# ── Valid state transitions ────────────────────────────────────────────────────

VALID_TRANSITIONS: dict[MessageState, set[MessageState]] = {
    MessageState.DRAFT:        {MessageState.VALIDATED, MessageState.FAILED},
    MessageState.VALIDATED:    {MessageState.SCOPED, MessageState.FAILED},
    MessageState.SCOPED:       {MessageState.ROUTED, MessageState.ESCALATED, MessageState.FAILED},
    MessageState.ROUTED:       {MessageState.ACKNOWLEDGED, MessageState.COMPLETED, MessageState.FAILED},
    MessageState.ACKNOWLEDGED: {MessageState.DECIDED, MessageState.ESCALATED, MessageState.FAILED},
    MessageState.DECIDED:      {MessageState.EXECUTING, MessageState.FAILED, MessageState.CANCELLED},
    MessageState.EXECUTING:    {MessageState.COMPLETED, MessageState.FAILED},
    MessageState.COMPLETED:    set(),
    MessageState.FAILED:       set(),
    MessageState.ESCALATED:    {MessageState.DECIDED, MessageState.FAILED, MessageState.CANCELLED},
    MessageState.CANCELLED:    set(),
}


def can_transition(current: MessageState, target: MessageState) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())
