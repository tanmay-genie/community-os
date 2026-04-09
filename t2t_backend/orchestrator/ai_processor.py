"""
orchestrator/ai_processor.py — AI Auto-Processor.

When a message is sent TO an AI Twin, this module automatically:
1. Picks up the message
2. Builds a workflow plan based on intent
3. Runs the LLM adapter to generate a response
4. Sends the AI response back to the sender via T2T protocol
5. Logs everything to audit trail
6. Updates memory

This removes the need for manual CONFIRM/DECLINE for AI chat interactions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from auth.db import AsyncSessionLocal
from audit.audit import log_event
from audit.taxonomy import EventType, Severity
from memory.user import get_user_memory, update_user_memory
from memory.org import update_org_memory
from memory.decision import record_decision
from notifications.notifications import NotificationType, send_notification
from orchestrator.adapters.base import get_adapter
from orchestrator.planner import build_plan
from router.store import transition_state
from schemas.intents import MessageState

logger = logging.getLogger(__name__)


async def process_ai_message(
    message_id: str,
    thread_id: str,
    sequence_no: int,
    from_twin_id: str,
    from_org_id: str,
    to_twin_id: str,
    to_org_id: str,
    intent_type: str,
    intent_name: str | None,
    payload: dict[str, Any],
) -> None:
    """
    Auto-process a message sent to an AI Twin.

    Runs as a background asyncio task after the message is routed.
    Has its own DB session (independent of the HTTP request).
    """
    async with AsyncSessionLocal() as db:
        try:
            await _process(
                db=db,
                message_id=message_id,
                thread_id=thread_id,
                sequence_no=sequence_no,
                from_twin_id=from_twin_id,
                from_org_id=from_org_id,
                to_twin_id=to_twin_id,
                to_org_id=to_org_id,
                intent_type=intent_type,
                intent_name=intent_name,
                payload=payload,
            )
            await db.commit()
        except Exception as exc:
            logger.exception(
                "AI processor fatal error for message %s: %s", message_id, exc
            )
            await db.rollback()
            try:
                async with AsyncSessionLocal() as err_db:
                    await log_event(
                        db=err_db,
                        event_type=EventType.WORKFLOW_FAILED,
                        message_id=message_id,
                        thread_id=thread_id,
                        twin_id=to_twin_id,
                        org_id=to_org_id,
                        result="AI_PROCESSOR_ERROR",
                        reason=str(exc),
                        severity=Severity.ERROR,
                    )
                    await transition_state(
                        db=err_db, message_id=message_id,
                        target_state=MessageState.FAILED,
                    )
                    await err_db.commit()
            except Exception:
                logger.exception("Failed to log AI processor error")


async def _process(
    db: Any,
    message_id: str,
    thread_id: str,
    sequence_no: int,
    from_twin_id: str,
    from_org_id: str,
    to_twin_id: str,
    to_org_id: str,
    intent_type: str,
    intent_name: str | None,
    payload: dict[str, Any],
) -> None:
    """Inner processing function."""

    await log_event(
        db=db,
        event_type=EventType.ORCHESTRATION_STARTED,
        message_id=message_id,
        thread_id=thread_id,
        twin_id=to_twin_id,
        org_id=to_org_id,
        result="AI_PROCESSING",
        extra={"intent_type": intent_type, "intent_name": intent_name},
    )

    # ── 1. Fetch user memory for context ─────────────────────────────────
    user_memory = []
    try:
        user_memory = await get_user_memory(from_twin_id, limit=10)
    except Exception as e:
        logger.warning("Could not fetch user memory: %s", e)

    # ── 2. Get LLM adapter ───────────────────────────────────────────────
    llm = get_adapter("llm")
    if llm is None:
        logger.error("LLM adapter not registered — cannot process AI message")
        await transition_state(
            db=db, message_id=message_id, target_state=MessageState.FAILED,
        )
        return

    # ── 3. Build LLM params ──────────────────────────────────────────────
    user_message = payload.get("message", "")
    if not user_message:
        # For non-chat intents, serialize the payload as context
        user_message = json.dumps(payload, indent=2, default=str)

    llm_params = {
        "intent_name": intent_name or "ai_chat",
        "message": user_message,
        "context": payload,
        "memory": user_memory,
    }

    # ── 4. Call LLM ──────────────────────────────────────────────────────
    result = await llm.execute(llm_params)

    if not result.success:
        logger.error("LLM failed: %s", result.error)
        await log_event(
            db=db,
            event_type=EventType.WORKFLOW_FAILED,
            message_id=message_id,
            thread_id=thread_id,
            twin_id=to_twin_id,
            org_id=to_org_id,
            result="LLM_FAILED",
            reason=result.error,
            severity=Severity.ERROR,
        )
        await transition_state(
            db=db, message_id=message_id, target_state=MessageState.FAILED,
        )
        # Notify sender of failure
        await send_notification(
            db=db,
            to_twin_id=from_twin_id,
            from_system="ai_processor",
            notification_type=NotificationType.INFORMATIONAL,
            title="AI could not process your request",
            body=f"Error: {result.error}",
            message_id=message_id,
            thread_id=thread_id,
        )
        return

    # ── 5. Send AI response back to sender ───────────────────────────────
    ai_response = result.output.get("response", "")

    response_message_id = str(uuid.uuid4())
    response_payload = {
        "response": ai_response,
        "original_message_id": message_id,
        "intent_name": intent_name,
        "model": result.output.get("model", ""),
    }

    # Save AI response as a new message in sender's inbox
    from router.messages import MessageModel
    response_msg = MessageModel(
        message_id=response_message_id,
        thread_id=thread_id,
        protocol_version="1.0",
        sequence_no=sequence_no + 1,
        from_twin_id=to_twin_id,      # AI Twin is the sender
        from_org_id=to_org_id,
        to_twin_id=from_twin_id,       # Original sender is the recipient
        to_org_id=from_org_id,
        intent_type="UPDATE",
        intent_name=f"ai_response_{intent_name or 'chat'}",
        risk_level="LOW",
        payload_json=json.dumps(response_payload),
        idempotency_key=str(uuid.uuid4()),
        state=MessageState.ROUTED.value,
        created_at=datetime.utcnow(),
    )
    db.add(response_msg)
    await db.flush()

    # ── 6. Mark original message as COMPLETED ────────────────────────────
    await transition_state(
        db=db, message_id=message_id, target_state=MessageState.COMPLETED,
    )

    # ── 7. WebSocket push to sender ──────────────────────────────────────
    try:
        from router.websocket import ws_manager
        await ws_manager.push_message(
            twin_id=from_twin_id,
            data={
                "type": "ai_response",
                "message_id": response_message_id,
                "thread_id": thread_id,
                "from_twin_id": to_twin_id,
                "intent_type": "UPDATE",
                "payload": response_payload,
            },
        )
    except Exception:
        pass  # Fallback to polling inbox

    # ── 8. Update memory ─────────────────────────────────────────────────
    await update_user_memory(
        twin_id=from_twin_id,
        event_type=intent_type,
        details={
            "intent_name": intent_name,
            "message": user_message[:200],
            "ai_response": ai_response[:200],
        },
    )

    await update_org_memory(
        org_id=from_org_id,
        event_type="AI_INTERACTION",
        details={
            "intent_name": intent_name,
            "twin_id": from_twin_id,
        },
    )

    await record_decision(
        message_id=message_id,
        decided_by=to_twin_id,
        intent_type=intent_type,
        intent_name=intent_name,
        workflow_id=response_message_id,
        outcome="AI_RESPONDED",
    )

    # ── 9. Audit log ─────────────────────────────────────────────────────
    await log_event(
        db=db,
        event_type=EventType.WORKFLOW_COMPLETED,
        message_id=message_id,
        thread_id=thread_id,
        twin_id=to_twin_id,
        org_id=to_org_id,
        result="AI_RESPONDED",
        extra={
            "response_message_id": response_message_id,
            "intent_name": intent_name,
            "model": result.output.get("model", ""),
        },
    )

    logger.info(
        "AI processed: message=%s → response=%s intent=%s",
        message_id, response_message_id, intent_name,
    )
