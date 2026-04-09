"""
notifications/escalation.py — Escalation Task Service + SLA Timer.

When Policy Engine returns ESCALATE, this service:
1. Creates an EscalationTask with full context
2. Starts SLA countdown
3. Exposes approve/deny endpoints for human response
4. On approve → resumes the message flow (triggers orchestration)
5. On deny or SLA breach → logs and terminates
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from audit.audit import log_event
from audit.taxonomy import EventType, Severity
from auth.auth import TwinContext, verify_twin
from auth.db import Base, get_db
from config import settings

logger = logging.getLogger(__name__)


# ── ORM Model ─────────────────────────────────────────────────────────────────

class EscalationTaskModel(Base):
    __tablename__ = "escalation_tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requesting_twin_id: Mapped[str] = mapped_column(String(100), nullable=False)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    intent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    sla_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    sla_deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decision_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


# ── Core escalation functions ─────────────────────────────────────────────────

async def create_escalation_task(
    db: AsyncSession,
    message_id: str,
    thread_id: str,
    requesting_twin_id: str,
    org_id: str,
    intent_type: str,
    risk_level: str,
    rule_id: str,
    reason: str,
    sla_minutes: int | None = None,
) -> EscalationTaskModel:
    """Create and persist an escalation task. Starts SLA countdown."""
    effective_sla = sla_minutes or settings.DEFAULT_ESCALATION_SLA_MINUTES
    deadline = datetime.utcnow() + timedelta(minutes=effective_sla)

    task = EscalationTaskModel(
        task_id=str(uuid.uuid4()),
        message_id=message_id,
        thread_id=thread_id,
        requesting_twin_id=requesting_twin_id,
        org_id=org_id,
        intent_type=intent_type,
        risk_level=risk_level,
        rule_id=rule_id,
        reason=reason,
        sla_minutes=effective_sla,
        sla_deadline=deadline,
        status="PENDING",
    )
    db.add(task)
    await db.flush()

    await log_event(
        db=db,
        event_type=EventType.ESCALATION_CREATED,
        org_id=org_id,
        twin_id=requesting_twin_id,
        message_id=message_id,
        thread_id=thread_id,
        result="PENDING",
        reason=reason,
        severity=Severity.WARNING,
        extra={
            "task_id": task.task_id,
            "sla_minutes": effective_sla,
            "sla_deadline": deadline.isoformat(),
        },
    )

    logger.warning(
        "Escalation task created: task=%s message=%s rule=%s sla=%dmin",
        task.task_id, message_id, rule_id, effective_sla,
    )
    return task


async def approve_escalation(
    db: AsyncSession,
    task_id: str,
    approver_twin_id: str,
    reason: str = "Approved by human",
) -> dict[str, Any]:
    """Approve an escalation task — resume the workflow."""
    result = await db.execute(
        select(EscalationTaskModel).where(EscalationTaskModel.task_id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Escalation task not found")
    if task.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Task already {task.status}")

    # SLA check
    if datetime.utcnow() > task.sla_deadline:
        await _handle_sla_breach(db, task)
        raise HTTPException(status_code=410, detail="SLA deadline has passed")

    task.status = "APPROVED"
    task.decided_by = approver_twin_id
    task.decision_reason = reason
    task.decided_at = datetime.utcnow()
    await db.flush()

    await log_event(
        db=db,
        event_type=EventType.ESCALATION_APPROVED,
        org_id=task.org_id,
        twin_id=approver_twin_id,
        message_id=task.message_id,
        thread_id=task.thread_id,
        result="APPROVED",
        reason=reason,
        extra={"task_id": task_id},
    )

    # Resume orchestration
    from router.store import transition_state, get_message
    import json
    msg = await get_message(db=db, message_id=task.message_id)
    if msg:
        from schemas.intents import MessageState
        await transition_state(db=db, message_id=task.message_id, target_state=MessageState.DECIDED)
        # Trigger execution
        from orchestrator.executor import execute_workflow
        import asyncio
        asyncio.create_task(
            execute_workflow(
                message_id=task.message_id,
                intent_type=task.intent_type,
                intent_name=None,
                thread_id=task.thread_id,
                from_twin_id=task.requesting_twin_id,
                from_org_id=task.org_id,
                to_twin_id=approver_twin_id,
                to_org_id=task.org_id,
                payload=json.loads(msg.payload_json or "{}"),
                reply_payload={"approved_by": approver_twin_id, "reason": reason},
            )
        )

    logger.info("Escalation %s APPROVED by %s", task_id, approver_twin_id)
    return {"task_id": task_id, "status": "APPROVED", "message_id": task.message_id}


async def deny_escalation(
    db: AsyncSession,
    task_id: str,
    denier_twin_id: str,
    reason: str = "Denied by human",
) -> dict[str, Any]:
    """Deny an escalation task — terminate the message."""
    result = await db.execute(
        select(EscalationTaskModel).where(EscalationTaskModel.task_id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Escalation task not found")
    if task.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Task already {task.status}")

    task.status = "DENIED"
    task.decided_by = denier_twin_id
    task.decision_reason = reason
    task.decided_at = datetime.utcnow()
    await db.flush()

    from router.store import transition_state
    from schemas.intents import MessageState
    await transition_state(db=db, message_id=task.message_id, target_state=MessageState.FAILED)

    await log_event(
        db=db,
        event_type=EventType.ESCALATION_DENIED,
        org_id=task.org_id,
        twin_id=denier_twin_id,
        message_id=task.message_id,
        thread_id=task.thread_id,
        result="DENIED",
        reason=reason,
        extra={"task_id": task_id},
    )

    logger.warning("Escalation %s DENIED by %s", task_id, denier_twin_id)
    return {"task_id": task_id, "status": "DENIED", "message_id": task.message_id}


async def _handle_sla_breach(db: AsyncSession, task: EscalationTaskModel) -> None:
    task.status = "EXPIRED"
    await db.flush()
    await log_event(
        db=db,
        event_type=EventType.SLA_BREACHED,
        org_id=task.org_id,
        twin_id=task.requesting_twin_id,
        message_id=task.message_id,
        result="EXPIRED",
        reason=f"SLA of {task.sla_minutes} minutes breached",
        severity=Severity.ERROR,
    )


# ── Escalation API Router ─────────────────────────────────────────────────────

esc_router = APIRouter(prefix="/t2t/escalations", tags=["Escalations"])


@esc_router.get("/pending")
async def list_pending_escalations(
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List pending escalation tasks for the authenticated twin's org."""
    result = await db.execute(
        select(EscalationTaskModel)
        .where(
            EscalationTaskModel.org_id == twin.org_id,
            EscalationTaskModel.status == "PENDING",
        )
        .order_by(EscalationTaskModel.sla_deadline)
    )
    tasks = result.scalars().all()
    now = datetime.utcnow()
    return [
        {
            "task_id": t.task_id,
            "message_id": t.message_id,
            "requesting_twin": t.requesting_twin_id,
            "intent_type": t.intent_type,
            "risk_level": t.risk_level,
            "reason": t.reason,
            "sla_deadline": t.sla_deadline.isoformat(),
            "sla_remaining_minutes": max(0, int((t.sla_deadline - now).total_seconds() / 60)),
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]


@esc_router.post("/{task_id}/approve")
async def approve_task(
    task_id: str,
    reason: str = "Approved",
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await approve_escalation(db=db, task_id=task_id, approver_twin_id=twin.twin_id, reason=reason)


@esc_router.post("/{task_id}/deny")
async def deny_task(
    task_id: str,
    reason: str = "Denied",
    twin: TwinContext = Depends(verify_twin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await deny_escalation(db=db, task_id=task_id, denier_twin_id=twin.twin_id, reason=reason)
