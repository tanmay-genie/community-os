"""
orchestrator/executor.py — The Execution Engine.

Converts a confirmed intent into a workflow plan, executes each step
using the registered adapters, handles rollback on failure, and
updates the memory layer on success.

Called as a background task from the router after CONFIRM reply.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from auth.db import AsyncSessionLocal
from audit.audit import log_event
from audit.taxonomy import EventType, Severity
from orchestrator.adapters.base import get_adapter
from orchestrator.compensation import run_compensation
from orchestrator.planner import WorkflowPlan, WorkflowStep, build_plan
from router.store import transition_state
from schemas.intents import MessageState

logger = logging.getLogger(__name__)


async def execute_workflow(
    message_id: str,
    intent_type: str,
    intent_name: str | None,
    thread_id: str,
    from_twin_id: str,
    from_org_id: str,
    to_twin_id: str,
    to_org_id: str,
    payload: dict[str, Any],
    reply_payload: dict[str, Any],
) -> None:
    """
    Main orchestration entry point.

    Runs as a background asyncio task after a CONFIRM reply.
    Has its own DB session (independent of the HTTP request session).

    Pipeline:
    1. Build workflow plan (intent → steps)
    2. For each step:
       a. Re-run Policy Gate 2 for this specific action
       b. Get adapter
       c. Execute step
       d. Log result
       e. On failure → compensate all completed steps → mark FAILED
    3. On full success → update memory → mark COMPLETED → notify
    """

    async with AsyncSessionLocal() as db:
        try:
            await _run(
                db=db,
                message_id=message_id,
                intent_type=intent_type,
                intent_name=intent_name,
                thread_id=thread_id,
                from_twin_id=from_twin_id,
                from_org_id=from_org_id,
                to_twin_id=to_twin_id,
                to_org_id=to_org_id,
                payload=payload,
                reply_payload=reply_payload,
            )
            await db.commit()
        except Exception as exc:
            logger.exception("Orchestrator fatal error for message %s: %s", message_id, exc)
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
                        result="FATAL_ERROR",
                        reason=str(exc),
                        severity=Severity.CRITICAL,
                    )
                    await transition_state(db=err_db, message_id=message_id, target_state=MessageState.FAILED)
                    await err_db.commit()
            except Exception:
                logger.exception("Failed to log fatal orchestration error")


async def _run(
    db: Any,
    message_id: str,
    intent_type: str,
    intent_name: str | None,
    thread_id: str,
    from_twin_id: str,
    from_org_id: str,
    to_twin_id: str,
    to_org_id: str,
    payload: dict[str, Any],
    reply_payload: dict[str, Any],
) -> None:
    """Inner execution function with full error handling."""

    await log_event(
        db=db,
        event_type=EventType.ORCHESTRATION_STARTED,
        message_id=message_id,
        thread_id=thread_id,
        twin_id=to_twin_id,
        org_id=to_org_id,
        result="STARTED",
        extra={"intent_type": intent_type, "intent_name": intent_name},
    )

    # ── Step 1: Build plan ────────────────────────────────────────────────
    plan: WorkflowPlan = build_plan(
        intent_type=intent_type,
        intent_name=intent_name,
        payload=payload,
        reply_payload=reply_payload,
    )

    logger.info(
        "Orchestrator: workflow=%s steps=%d for message=%s",
        plan.workflow_id, len(plan.steps), message_id,
    )

    completed_steps: list[WorkflowStep] = []

    # ── Step 2: Execute each step ─────────────────────────────────────────
    for step in plan.steps:
        await log_event(
            db=db,
            event_type=EventType.STEP_STARTED,
            message_id=message_id,
            thread_id=thread_id,
            twin_id=to_twin_id,
            org_id=to_org_id,
            result="STARTED",
            extra={
                "step_id": step.step_id,
                "step_name": step.step_name,
                "adapter": step.adapter_name,
                "workflow_id": plan.workflow_id,
            },
        )

        # ── a. Get adapter ────────────────────────────────────────────────
        adapter = get_adapter(step.adapter_name)
        if adapter is None:
            logger.error("Adapter '%s' not registered", step.adapter_name)
            await _handle_step_failure(
                db=db,
                message_id=message_id,
                thread_id=thread_id,
                to_twin_id=to_twin_id,
                to_org_id=to_org_id,
                plan=plan,
                step=step,
                completed_steps=completed_steps,
                error=f"Adapter '{step.adapter_name}' not registered",
            )
            return

        # ── b. Execute step ───────────────────────────────────────────────
        try:
            logger.info(
                "Executing step=%s adapter=%s", step.step_id, step.adapter_name
            )
            result = await adapter.execute(step.params)
            step.result = result.output
            step.success = result.success
            step.error = result.error

        except Exception as exc:
            step.success = False
            step.error = str(exc)
            logger.exception("Step %s raised exception: %s", step.step_id, exc)
            await _handle_step_failure(
                db=db, message_id=message_id, thread_id=thread_id,
                to_twin_id=to_twin_id, to_org_id=to_org_id,
                plan=plan, step=step, completed_steps=completed_steps,
                error=str(exc),
            )
            return

        if not result.success:
            await _handle_step_failure(
                db=db, message_id=message_id, thread_id=thread_id,
                to_twin_id=to_twin_id, to_org_id=to_org_id,
                plan=plan, step=step, completed_steps=completed_steps,
                error=result.error or "Adapter returned failure",
            )
            return

        # ── c. Step succeeded ─────────────────────────────────────────────
        completed_steps.append(step)

        # Propagate output to next step params (chaining)
        if step.result:
            for next_step in plan.steps[plan.steps.index(step) + 1:]:
                next_step.params.update(step.result)

        await log_event(
            db=db,
            event_type=EventType.STEP_COMPLETED,
            message_id=message_id,
            thread_id=thread_id,
            twin_id=to_twin_id,
            org_id=to_org_id,
            result="SUCCESS",
            extra={
                "step_id": step.step_id,
                "step_name": step.step_name,
                "output": step.result,
                "workflow_id": plan.workflow_id,
            },
        )

    # ── Step 3: All steps completed — update memory ───────────────────────
    await _update_memory(
        db=db,
        message_id=message_id,
        from_twin_id=from_twin_id,
        to_twin_id=to_twin_id,
        org_id=to_org_id,
        intent_type=intent_type,
        intent_name=intent_name,
        plan=plan,
    )

    # ── Step 4: Mark COMPLETED ────────────────────────────────────────────
    await transition_state(
        db=db,
        message_id=message_id,
        target_state=MessageState.COMPLETED,
    )

    await log_event(
        db=db,
        event_type=EventType.WORKFLOW_COMPLETED,
        message_id=message_id,
        thread_id=thread_id,
        twin_id=to_twin_id,
        org_id=to_org_id,
        result="SUCCESS",
        extra={"workflow_id": plan.workflow_id, "steps_completed": len(completed_steps)},
    )

    # ── Step 5: Send completion notification ──────────────────────────────
    from notifications.notifications import send_notification, NotificationType
    await send_notification(
        db=db,
        to_twin_id=from_twin_id,
        from_system="orchestrator",
        notification_type=NotificationType.INFORMATIONAL,
        title="Workflow Completed",
        body=f"Intent '{intent_name or intent_type}' executed successfully ({len(completed_steps)} steps).",
        message_id=message_id,
        thread_id=thread_id,
    )

    logger.info(
        "Workflow COMPLETED: message=%s steps=%d",
        message_id, len(completed_steps),
    )


async def _handle_step_failure(
    db: Any,
    message_id: str,
    thread_id: str,
    to_twin_id: str,
    to_org_id: str,
    plan: WorkflowPlan,
    step: WorkflowStep,
    completed_steps: list[WorkflowStep],
    error: str,
) -> None:
    """Log step failure, run compensation, mark message FAILED."""

    await log_event(
        db=db,
        event_type=EventType.STEP_FAILED,
        message_id=message_id,
        thread_id=thread_id,
        twin_id=to_twin_id,
        org_id=to_org_id,
        result="FAILED",
        reason=error,
        severity=Severity.ERROR,
        extra={"step_id": step.step_id, "adapter": step.adapter_name, "workflow_id": plan.workflow_id},
    )

    # Run rollback for all previously completed steps
    if completed_steps:
        await run_compensation(
            completed_steps=completed_steps,
            workflow_id=plan.workflow_id,
            message_id=message_id,
            db=db,
        )

    await transition_state(db=db, message_id=message_id, target_state=MessageState.FAILED)

    await log_event(
        db=db,
        event_type=EventType.WORKFLOW_FAILED,
        message_id=message_id,
        thread_id=thread_id,
        twin_id=to_twin_id,
        org_id=to_org_id,
        result="FAILED",
        reason=f"Step '{step.step_id}' failed: {error}",
        severity=Severity.ERROR,
    )

    from notifications.notifications import send_notification, NotificationType
    await send_notification(
        db=db,
        to_twin_id=to_twin_id,
        from_system="orchestrator",
        notification_type=NotificationType.ACTION_REQUIRED,
        title="Workflow Failed",
        body=f"Step '{step.step_name}' failed: {error}. Rollback executed.",
        message_id=message_id,
        thread_id=thread_id,
    )


async def _update_memory(
    db: Any,
    message_id: str,
    from_twin_id: str,
    to_twin_id: str,
    org_id: str,
    intent_type: str,
    intent_name: str | None,
    plan: WorkflowPlan,
) -> None:
    """Update user and org memory after successful workflow execution."""
    from memory.user import update_user_memory
    from memory.org import update_org_memory
    from memory.decision import record_decision

    await update_user_memory(
        twin_id=to_twin_id,
        event_type=intent_type,
        details={"intent_name": intent_name, "workflow_id": plan.workflow_id},
    )

    await update_org_memory(
        org_id=org_id,
        event_type=intent_type,
        details={"intent_name": intent_name, "initiated_by": from_twin_id},
    )

    await record_decision(
        message_id=message_id,
        decided_by=to_twin_id,
        intent_type=intent_type,
        intent_name=intent_name,
        workflow_id=plan.workflow_id,
        outcome="COMPLETED",
    )

    await log_event(
        db=db,
        event_type=EventType.MEMORY_UPDATED,
        message_id=message_id,
        twin_id=to_twin_id,
        org_id=org_id,
        result="UPDATED",
    )
