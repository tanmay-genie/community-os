"""
schemas/envelope.py — The canonical T2T message envelope.
Every message exchanged between twins must conform to this schema.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from schemas.intents import ClearanceLevel, IntentType, RiskLevel


# ── Sub-objects ─────────────────────────────────────────────────────────────

class Party(BaseModel):
    """Identifies one end of a T2T conversation (sender or recipient)."""
    org_id: str = Field(..., min_length=1, max_length=100)
    twin_id: str = Field(..., min_length=1, max_length=100)
    role: str | None = None
    clearance: ClearanceLevel | None = None


class IntentBlock(BaseModel):
    """Describes the intent of the message — what the sender wants to achieve."""
    type: IntentType
    name: str | None = Field(default=None, max_length=200)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_confirmation: bool = False
    sla_minutes: int = Field(default=1440, ge=1, le=43200)


class ScopeBlock(BaseModel):
    """Restricts what artifacts and actions are allowed for this message."""
    contract_id: str | None = None
    allowed_artifacts: list[str] = Field(default_factory=list)
    redaction_profile: str = "INTERNAL_FULL"
    data_residency: str | None = None


class SecurityBlock(BaseModel):
    """Cryptographic and replay-prevention fields."""
    signature: str | None = None          # ed25519 base64 signature
    signature_alg: str = "ed25519"        # "ed25519" for non-repudiation
    nonce: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, v: str) -> str:
        # Must be a valid UUID
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("idempotency_key must be a valid UUID v4")
        return v


class TelemetryBlock(BaseModel):
    """Distributed tracing fields for observability."""
    priority: str = "NORMAL"
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ── Main Envelope ────────────────────────────────────────────────────────────

class MessageEnvelope(BaseModel):
    """
    The canonical T2T message envelope.
    Every twin-to-twin message must use this exact structure.
    """
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    protocol_version: str = "1.0"
    thread_id: str = Field(..., description="Groups related messages into a conversation")
    sequence_no: int = Field(..., ge=1, description="Ordering within a thread")

    sender: Party = Field(..., alias="from")
    recipient: Party = Field(..., alias="to")

    intent: IntentBlock
    scope: ScopeBlock = Field(default_factory=ScopeBlock)
    payload: dict[str, Any] = Field(default_factory=dict)
    security: SecurityBlock = Field(default_factory=SecurityBlock)
    telemetry: TelemetryBlock = Field(default_factory=TelemetryBlock)

    model_config = {"populate_by_name": True}

    def get_signable_bytes(self) -> bytes:
        """
        Returns canonical bytes for Ed25519 signing.
        Excludes the signature field itself to avoid circular dependency.
        """
        signable = {
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "sequence_no": self.sequence_no,
            "from": {"org_id": self.sender.org_id, "twin_id": self.sender.twin_id},
            "to": {"org_id": self.recipient.org_id, "twin_id": self.recipient.twin_id},
            "intent": {"type": self.intent.type.value, "name": self.intent.name},
            "payload": self.payload,
            "nonce": self.security.nonce,
            "idempotency_key": self.security.idempotency_key,
        }
        return json.dumps(signable, sort_keys=True, separators=(',', ':')).encode("utf-8")

    @field_validator("sequence_no")
    @classmethod
    def validate_sequence(cls, v: int) -> int:
        if v < 1:
            raise ValueError("sequence_no must be >= 1")
        return v


# ── Response models ───────────────────────────────────────────────────────────

class SendResponse(BaseModel):
    status: str
    message_id: str
    decision: str
    reason: str | None = None
    escalation_task_id: str | None = None


class InboxMessage(BaseModel):
    message_id: str
    thread_id: str
    sequence_no: int
    from_twin_id: str
    from_org_id: str
    intent_type: str
    intent_name: str | None
    payload: dict[str, Any]
    state: str
    created_at: datetime


class ReplyEnvelope(BaseModel):
    thread_id: str
    original_message_id: str
    from_twin_id: str
    intent_type: IntentType
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
