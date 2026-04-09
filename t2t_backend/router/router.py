"""
router/router.py — T2T Agent Router API endpoints.

Three core endpoints:
  POST /t2t/send      — Twin A sends a message
  GET  /t2t/inbox/{twin_id} — Twin B fetches pending messages
  POST /t2t/reply     — Twin B replies (CONFIRM / DECLINE / COMPLETE / FAIL)

Every request is:
  1. Authenticated (verify_twin)
  2. Schema validated (Pydantic)
  3. Signature verified (Ed25519)
  4. Loop detection checked
  5. Idempotency checked (Redis)
  6. Policy checked (Gate 1 or Gate 2)
  7. Cross-org redaction applied
  8. Stored in DB
  9. Audit logged
  10. WebSocket push attempted
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from audit.audit import log_event
from audit.taxonomy import EventType, Severity
from auth.auth import TwinContext, verify_twin
from auth.crypto import verify_signature
from auth.db import get_db
from notifications.escalation import create_escalation_task
from policy.policy import PolicyResult, policy_check
from router.messages import MessageModel
from router.store import (
    check_and_set_idempotency,
    check_loop_detection,
    fetch_inbox,
    get_idempotency_response,
    get_message,
    save_message,
    store_idempotency_response,
    transition_state,
    validate_sequence_no,
)
from schemas.envelope import (
    InboxMessage,
    MessageEnvelope,
    ReplyEnvelope,
    SendResponse,
)
from schemas.intents import MessageState, PolicyDecision

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/t2t", tags=["T2T Router"])


# ── POST /t2t/send ────────────────────────────────────────────────────────────

@router.post("/send", response_model=SendResponse)
async def send_message(
    envelope: MessageEnvelope,
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> SendResponse:
    """
    Primary entry point for all T2T messages.

    Pipeline:
    auth → validate sender → idempotency check → sequence check →
    Policy Gate 1 → save to DB → deliver to inbox → audit log
    """

    # ── 1. Sender identity match ──────────────────────────────────────────
    if envelope.sender.twin_id != twin.twin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sender twin_id '{envelope.sender.twin_id}' does not match authenticated twin '{twin.twin_id}'",
        )

    await log_event(
        db=db,
        event_type=EventType.MESSAGE_RECEIVED,
        org_id=twin.org_id,
        twin_id=twin.twin_id,
        message_id=envelope.message_id,
        thread_id=envelope.thread_id,
        result="RECEIVED",
    )

    # ── 1b. Ed25519 signature verification ─────────────────────────────
    if envelope.security.signature_alg == "ed25519" and envelope.security.signature:
        if not twin.signing_public_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sender has no signing public key — cannot verify ed25519 signature",
            )
        signable_bytes = envelope.get_signable_bytes()
        if not verify_signature(twin.signing_public_key, signable_bytes, envelope.security.signature):
            await log_event(
                db=db,
                event_type=EventType.MESSAGE_SCHEMA_ERROR,
                org_id=twin.org_id,
                twin_id=twin.twin_id,
                message_id=envelope.message_id,
                result="SIGNATURE_INVALID",
                reason="Ed25519 signature verification failed",
                severity=Severity.WARNING,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Ed25519 signature verification failed",
            )

    # ── 1c. Loop detection ──────────────────────────────────────────────
    is_loop = await check_loop_detection(
        thread_id=envelope.thread_id,
        from_twin_id=twin.twin_id,
        to_twin_id=envelope.recipient.twin_id,
    )
    if is_loop:
        await log_event(
            db=db,
            event_type=EventType.LOOP_DETECTED,
            org_id=twin.org_id,
            twin_id=twin.twin_id,
            message_id=envelope.message_id,
            thread_id=envelope.thread_id,
            result="BLOCKED",
            reason="Message loop detected",
            severity=Severity.WARNING,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Message loop detected — too many exchanges in this thread",
        )

    # ── 2. Idempotency check ──────────────────────────────────────────────
    is_new = await check_and_set_idempotency(envelope.security.idempotency_key)
    if not is_new:
        cached = await get_idempotency_response(envelope.security.idempotency_key)
        if cached:
            await log_event(
                db=db,
                event_type=EventType.DUPLICATE_DETECTED,
                org_id=twin.org_id,
                twin_id=twin.twin_id,
                message_id=envelope.message_id,
                result="DUPLICATE",
                reason="Idempotency key already processed",
            )
            return SendResponse(**json.loads(cached))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate message — idempotency key already processed",
        )

    # ── 3. Sequence / thread order check ─────────────────────────────────
    in_order = await validate_sequence_no(
        thread_id=envelope.thread_id,
        sequence_no=envelope.sequence_no,
        to_twin_id=envelope.recipient.twin_id,
    )
    if not in_order:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Out-of-order message: sequence_no={envelope.sequence_no} in thread {envelope.thread_id}",
        )

    # ── 4. Policy Gate 1 ──────────────────────────────────────────────────
    policy_result: PolicyResult = await policy_check(
        envelope=envelope,
        sender=twin,
        db=db,
        gate="GATE_1",
    )

    await log_event(
        db=db,
        event_type=EventType.MESSAGE_VALIDATED,
        org_id=twin.org_id,
        twin_id=twin.twin_id,
        message_id=envelope.message_id,
        thread_id=envelope.thread_id,
        policy_decision_ref=policy_result.decision_id,
        rule_id=policy_result.rule_id,
        result=policy_result.decision.value,
        reason=policy_result.reason,
    )

    # ── 5. Handle DENY ────────────────────────────────────────────────────
    if policy_result.denied:
        await save_message(
            db=db,
            envelope=envelope,
            state=MessageState.FAILED,
            policy_decision=policy_result.decision.value,
            policy_rule_id=policy_result.rule_id,
            policy_reason=policy_result.reason,
            policy_decision_id=policy_result.decision_id,
        )
        response = SendResponse(
            status="denied",
            message_id=envelope.message_id,
            decision="DENY",
            reason=policy_result.reason,
        )
        await store_idempotency_response(
            envelope.security.idempotency_key, response.model_dump_json()
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"decision": "DENY", "reason": policy_result.reason, "rule_id": policy_result.rule_id},
        )

    # ── 6. Handle ESCALATE ────────────────────────────────────────────────
    if policy_result.needs_escalation:
        msg = await save_message(
            db=db,
            envelope=envelope,
            state=MessageState.ESCALATED,
            policy_decision=policy_result.decision.value,
            policy_rule_id=policy_result.rule_id,
            policy_reason=policy_result.reason,
            policy_decision_id=policy_result.decision_id,
        )
        task = await create_escalation_task(
            db=db,
            message_id=envelope.message_id,
            thread_id=envelope.thread_id,
            requesting_twin_id=twin.twin_id,
            org_id=twin.org_id,
            intent_type=envelope.intent.type.value,
            risk_level=envelope.intent.risk_level.value,
            rule_id=policy_result.rule_id,
            reason=policy_result.reason,
            sla_minutes=envelope.intent.sla_minutes,
        )
        response = SendResponse(
            status="escalated",
            message_id=envelope.message_id,
            decision="ESCALATE",
            reason=policy_result.reason,
            escalation_task_id=task.task_id,
        )
        await store_idempotency_response(
            envelope.security.idempotency_key, response.model_dump_json()
        )
        return response

    # ── 7. ALLOW — save and route ─────────────────────────────────────────
    # Apply cross-org redaction if orgs differ
    redacted_payload = envelope.payload
    if envelope.sender.org_id != envelope.recipient.org_id:
        from policy.redaction import apply_redaction
        redacted_payload = apply_redaction(envelope.payload, envelope.scope.redaction_profile)

    await save_message(
        db=db,
        envelope=envelope,
        state=MessageState.ROUTED,
        policy_decision=policy_result.decision.value,
        policy_rule_id=policy_result.rule_id,
        policy_reason=policy_result.reason,
        policy_decision_id=policy_result.decision_id,
        redacted_payload=redacted_payload,
    )

    await log_event(
        db=db,
        event_type=EventType.MESSAGE_ROUTED,
        org_id=twin.org_id,
        twin_id=twin.twin_id,
        message_id=envelope.message_id,
        thread_id=envelope.thread_id,
        result="ROUTED",
        extra={"to_twin": envelope.recipient.twin_id},
    )

    response = SendResponse(
        status="routed",
        message_id=envelope.message_id,
        decision="ALLOW",
        reason=policy_result.reason,
    )
    await store_idempotency_response(
        envelope.security.idempotency_key, response.model_dump_json()
    )

    # WebSocket push (best-effort — falls back to polling inbox)
    try:
        from router.websocket import ws_manager
        await ws_manager.push_message(
            twin_id=envelope.recipient.twin_id,
            data={
                "type": "new_message",
                "message_id": envelope.message_id,
                "thread_id": envelope.thread_id,
                "from_twin_id": twin.twin_id,
                "intent_type": envelope.intent.type.value,
            },
        )
    except Exception:
        pass

    # ── AI Auto-Processing ───────────────────────────────────────────────
    # If recipient is an AI Twin, automatically process the message
    await _maybe_trigger_ai(
        db=db,
        envelope=envelope,
        sender_twin=twin,
    )

    return response


# ── GET /t2t/inbox/{twin_id} ──────────────────────────────────────────────────

@router.get("/inbox/{twin_id}", response_model=list[InboxMessage])
async def get_inbox(
    twin_id: str,
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> list[InboxMessage]:
    """
    Fetch all pending (ROUTED) messages for the authenticated twin.
    Marks each as ACKNOWLEDGED on fetch.
    """
    if twin.twin_id != twin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only read your own inbox",
        )

    messages: list[MessageModel] = await fetch_inbox(db=db, twin_id=twin_id)

    result: list[InboxMessage] = []
    for msg in messages:
        # Transition to ACKNOWLEDGED
        await transition_state(db=db, message_id=msg.message_id, target_state=MessageState.ACKNOWLEDGED)
        await log_event(
            db=db,
            event_type=EventType.MESSAGE_ACKNOWLEDGED,
            org_id=twin.org_id,
            twin_id=twin.twin_id,
            message_id=msg.message_id,
            thread_id=msg.thread_id,
            result="ACKNOWLEDGED",
        )
        payload = json.loads(msg.payload_json) if msg.payload_json else {}
        result.append(
            InboxMessage(
                message_id=msg.message_id,
                thread_id=msg.thread_id,
                sequence_no=msg.sequence_no,
                from_twin_id=msg.from_twin_id,
                from_org_id=msg.from_org_id,
                intent_type=msg.intent_type,
                intent_name=msg.intent_name,
                payload=payload,
                state=MessageState.ACKNOWLEDGED.value,
                created_at=msg.created_at,
            )
        )

    logger.info("Inbox fetched: twin=%s count=%d", twin_id, len(result))
    return result


# ── POST /t2t/reply ───────────────────────────────────────────────────────────

@router.post("/reply", response_model=SendResponse)
async def reply_to_message(
    reply: ReplyEnvelope,
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> SendResponse:
    """
    Target twin sends a reply: CONFIRM, DECLINE, COMPLETE, or FAIL.
    CONFIRM triggers orchestration. DECLINE terminates the thread.
    """
    from schemas.intents import IntentType

    # Verify sender
    if reply.from_twin_id != twin.twin_id:
        raise HTTPException(status_code=403, detail="Reply from_twin_id mismatch")

    # Idempotency
    is_new = await check_and_set_idempotency(reply.idempotency_key)
    if not is_new:
        cached = await get_idempotency_response(reply.idempotency_key)
        if cached:
            return SendResponse(**json.loads(cached))

    # Find original message
    original = await get_message(db=db, message_id=reply.original_message_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Original message not found")

    # Validate reply is directed at correct twin
    if original.to_twin_id != twin.twin_id:
        raise HTTPException(status_code=403, detail="You are not the intended recipient")

    # Determine new state
    reply_intent = reply.intent_type
    if reply_intent == IntentType.CONFIRM:
        new_state = MessageState.DECIDED
        # Trigger orchestration asynchronously
        await _trigger_orchestration(
            db=db,
            original=original,
            twin=twin,
            reply_payload=reply.payload,
        )
    elif reply_intent in (IntentType.DECLINE, IntentType.CANCEL):
        new_state = MessageState.FAILED
    elif reply_intent == IntentType.COMPLETE:
        new_state = MessageState.COMPLETED
    elif reply_intent == IntentType.FAIL:
        new_state = MessageState.FAILED
    else:
        new_state = MessageState.ACKNOWLEDGED

    await transition_state(db=db, message_id=original.message_id, target_state=new_state)

    await log_event(
        db=db,
        event_type=EventType.MESSAGE_ACKNOWLEDGED,
        org_id=twin.org_id,
        twin_id=twin.twin_id,
        message_id=original.message_id,
        thread_id=original.thread_id,
        result=reply_intent.value,
        reason=f"Reply from {twin.twin_id}",
    )

    response = SendResponse(
        status=reply_intent.value.lower(),
        message_id=original.message_id,
        decision=reply_intent.value,
    )
    await store_idempotency_response(reply.idempotency_key, response.model_dump_json())
    return response


async def _trigger_orchestration(
    db: AsyncSession,
    original: MessageModel,
    twin: TwinContext,
    reply_payload: dict,
) -> None:
    """Kick off the orchestrator for a CONFIRM reply."""
    from orchestrator.executor import execute_workflow
    import asyncio

    await transition_state(
        db=db,
        message_id=original.message_id,
        target_state=MessageState.EXECUTING,
    )

    # Run orchestration as background task (non-blocking)
    asyncio.create_task(
        execute_workflow(
            message_id=original.message_id,
            intent_type=original.intent_type,
            intent_name=original.intent_name,
            thread_id=original.thread_id,
            from_twin_id=original.from_twin_id,
            from_org_id=original.from_org_id,
            to_twin_id=twin.twin_id,
            to_org_id=twin.org_id,
            payload=json.loads(original.payload_json or "{}"),
            reply_payload=reply_payload,
        )
    )


async def _maybe_trigger_ai(
    db: AsyncSession,
    envelope: MessageEnvelope,
    sender_twin: TwinContext,
) -> None:
    """
    Check if the recipient is an AI Twin. If so, auto-process the message.
    No manual CONFIRM needed — AI responds automatically.
    """
    import asyncio
    from sqlalchemy import select
    from auth.models import TwinModel

    result = await db.execute(
        select(TwinModel).where(TwinModel.twin_id == envelope.recipient.twin_id)
    )
    recipient_twin = result.scalar_one_or_none()

    if recipient_twin is None or recipient_twin.role != "AI":
        return  # Not an AI twin — normal flow (wait for manual reply)

    logger.info(
        "AI Twin detected: %s — auto-processing message %s",
        envelope.recipient.twin_id, envelope.message_id,
    )

    from orchestrator.ai_processor import process_ai_message

    asyncio.create_task(
        process_ai_message(
            message_id=envelope.message_id,
            thread_id=envelope.thread_id,
            sequence_no=envelope.sequence_no,
            from_twin_id=sender_twin.twin_id,
            from_org_id=sender_twin.org_id,
            to_twin_id=envelope.recipient.twin_id,
            to_org_id=envelope.recipient.org_id,
            intent_type=envelope.intent.type.value,
            intent_name=envelope.intent.name,
            payload=envelope.payload,
        )
    )
