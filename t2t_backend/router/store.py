"""
router/store.py — DB operations for messages + Redis idempotency.

All database reads/writes for the routing layer go through this module.
Idempotency checks use Redis to prevent double-execution from retries.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from redis_client import get_redis
from router.messages import MessageModel, can_transition
from schemas.envelope import MessageEnvelope
from schemas.intents import MessageState, PolicyDecision

logger = logging.getLogger(__name__)

IDEMPOTENCY_PREFIX = "t2t:idem:"
INBOX_SEQUENCE_PREFIX = "t2t:seq:"
LOOP_DETECTION_PREFIX = "t2t:loop:"


# ── Idempotency ───────────────────────────────────────────────────────────────

async def check_and_set_idempotency(idempotency_key: str) -> bool:
    """
    Atomically check and set idempotency key in Redis.
    Returns True if key is new (proceed), False if already seen (duplicate).
    """
    redis = await get_redis()
    redis_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}"
    # SET NX (only if not exists) with TTL
    result = await redis.set(
        redis_key,
        "1",
        nx=True,
        ex=settings.IDEMPOTENCY_TTL_SECONDS,
    )
    return result is not None  # True = new key, False = duplicate


async def get_idempotency_response(idempotency_key: str) -> str | None:
    """Get stored response for an already-processed idempotency key."""
    redis = await get_redis()
    resp_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}:resp"
    return await redis.get(resp_key)


async def store_idempotency_response(idempotency_key: str, response_json: str) -> None:
    """Store the response associated with an idempotency key for future duplicates."""
    redis = await get_redis()
    resp_key = f"{IDEMPOTENCY_PREFIX}{idempotency_key}:resp"
    await redis.set(resp_key, response_json, ex=settings.IDEMPOTENCY_TTL_SECONDS)


# ── Sequence / Thread Ordering ────────────────────────────────────────────────

async def validate_sequence_no(
    thread_id: str,
    sequence_no: int,
    to_twin_id: str,
) -> bool:
    """
    Check that this message is the next expected sequence_no for the thread.
    Returns True if in order, False if out of order.
    Stores the last seen sequence_no in Redis per thread.
    """
    redis = await get_redis()
    seq_key = f"{INBOX_SEQUENCE_PREFIX}{thread_id}:{to_twin_id}"
    last_seq = await redis.get(seq_key)

    if last_seq is None:
        # First message in thread — sequence_no=1 is expected
        if sequence_no != 1:
            logger.warning(
                "Thread %s: first message has sequence_no=%d (expected 1)",
                thread_id, sequence_no,
            )
            return False
    else:
        expected = int(last_seq) + 1
        if sequence_no != expected:
            logger.warning(
                "Thread %s: out-of-order message seq=%d (expected %d)",
                thread_id, sequence_no, expected,
            )
            return False

    await redis.set(seq_key, str(sequence_no), ex=86400 * 7)
    return True


# ── Loop Detection ────────────────────────────────────────────────────────────

async def check_loop_detection(
    thread_id: str,
    from_twin_id: str,
    to_twin_id: str,
) -> bool:
    """
    Check for message loops within a thread.
    Tracks the number of messages from→to within a thread.
    Returns True if loop detected (exceeded max hops), False otherwise.
    """
    redis = await get_redis()
    loop_key = f"{LOOP_DETECTION_PREFIX}{thread_id}:{from_twin_id}:{to_twin_id}"
    count = await redis.incr(loop_key)
    if count == 1:
        await redis.expire(loop_key, 86400)  # 24h TTL
    if count > settings.LOOP_DETECTION_MAX_HOPS:
        logger.warning(
            "Loop detected: thread=%s from=%s to=%s count=%d",
            thread_id, from_twin_id, to_twin_id, count,
        )
        return True
    return False

# ── Save / Update message ────────────────────────────────────────────────────

async def save_message(
    db: AsyncSession,
    envelope: MessageEnvelope,
    state: MessageState,
    policy_decision: str | None = None,
    policy_rule_id: str | None = None,
    policy_reason: str | None = None,
    policy_decision_id: str | None = None,
    in_reply_to_message_id: str | None = None,
    redacted_payload: dict | None = None,
) -> MessageModel:
    """Persist a new message to the DB. Uses redacted_payload if provided."""
    # Use redacted payload for cross-org messages, else original
    effective_payload = redacted_payload if redacted_payload is not None else envelope.payload
    msg = MessageModel(
        message_id=envelope.message_id,
        protocol_version=envelope.protocol_version,
        thread_id=envelope.thread_id,
        sequence_no=envelope.sequence_no,

        from_twin_id=envelope.sender.twin_id,
        from_org_id=envelope.sender.org_id,
        from_role=envelope.sender.role,
        from_clearance=envelope.sender.clearance.value if envelope.sender.clearance else None,

        to_twin_id=envelope.recipient.twin_id,
        to_org_id=envelope.recipient.org_id,

        intent_type=envelope.intent.type.value,
        intent_name=envelope.intent.name,
        risk_level=envelope.intent.risk_level.value,
        requires_human_confirmation=envelope.intent.requires_human_confirmation,
        sla_minutes=envelope.intent.sla_minutes,

        contract_id=envelope.scope.contract_id,
        redaction_profile=envelope.scope.redaction_profile,

        payload_json=json.dumps(effective_payload),
        idempotency_key=envelope.security.idempotency_key,
        nonce=envelope.security.nonce,
        signature=envelope.security.signature,
        trace_id=envelope.telemetry.trace_id,
        span_id=envelope.telemetry.span_id,

        state=state.value,
        policy_decision=policy_decision,
        policy_rule_id=policy_rule_id,
        policy_reason=policy_reason,
        policy_decision_id=policy_decision_id,
        in_reply_to_message_id=in_reply_to_message_id,
    )
    db.add(msg)
    await db.flush()
    return msg


async def transition_state(
    db: AsyncSession,
    message_id: str,
    target_state: MessageState,
    **kwargs,
) -> MessageModel | None:
    """
    Transition a message to a new state (validates the transition is legal).
    Optionally update additional fields via kwargs.
    Returns the updated model or None if transition is invalid.
    """
    result = await db.execute(
        select(MessageModel).where(MessageModel.message_id == message_id)
    )
    msg = result.scalar_one_or_none()
    if msg is None:
        logger.error("transition_state: message %s not found", message_id)
        return None

    current = MessageState(msg.state)
    if not can_transition(current, target_state):
        logger.warning(
            "Invalid transition %s → %s for message %s",
            current.value, target_state.value, message_id,
        )
        return None

    msg.state = target_state.value
    msg.updated_at = datetime.utcnow()

    if target_state == MessageState.ACKNOWLEDGED:
        msg.acknowledged_at = datetime.utcnow()
    if target_state in (MessageState.COMPLETED, MessageState.FAILED):
        msg.completed_at = datetime.utcnow()

    for key, value in kwargs.items():
        if hasattr(msg, key):
            setattr(msg, key, value)

    await db.flush()
    return msg


# ── Fetch inbox ───────────────────────────────────────────────────────────────

async def fetch_inbox(
    db: AsyncSession,
    twin_id: str,
    limit: int = 50,
) -> list[MessageModel]:
    """Fetch all ROUTED (unread) messages for a twin."""
    result = await db.execute(
        select(MessageModel)
        .where(
            MessageModel.to_twin_id == twin_id,
            MessageModel.state == MessageState.ROUTED.value,
        )
        .order_by(MessageModel.thread_id, MessageModel.sequence_no)
        .limit(limit)
    )
    return result.scalars().all()


async def get_message(db: AsyncSession, message_id: str) -> MessageModel | None:
    result = await db.execute(
        select(MessageModel).where(MessageModel.message_id == message_id)
    )
    return result.scalar_one_or_none()


async def get_thread_messages(
    db: AsyncSession, thread_id: str
) -> list[MessageModel]:
    result = await db.execute(
        select(MessageModel)
        .where(MessageModel.thread_id == thread_id)
        .order_by(MessageModel.sequence_no)
    )
    return result.scalars().all()
