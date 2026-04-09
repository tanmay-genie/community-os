"""
orchestrator/compensation.py — Rollback / Compensation Engine.

When a workflow step fails, this engine executes compensation actions
for all previously completed steps in reverse order.

Each step must define compensation_params before execution begins.
"""
from __future__ import annotations

import logging
from typing import Any

from orchestrator.adapters.base import get_adapter
from orchestrator.planner import WorkflowStep

logger = logging.getLogger(__name__)


async def run_compensation(
    completed_steps: list[WorkflowStep],
    workflow_id: str,
    message_id: str,
    db: Any,  # AsyncSession — avoid circular import
) -> dict[str, Any]:
    """
    Execute compensation (rollback) for all completed steps in reverse order.

    Args:
        completed_steps: Steps that were successfully executed before the failure.
        workflow_id:     ID of the workflow being rolled back.
        message_id:      Original message ID for audit logging.
        db:              DB session for audit events.

    Returns:
        Summary dict with rollback results.
    """
    from audit.audit import log_event
    from audit.taxonomy import EventType, Severity

    if not completed_steps:
        logger.info("[Compensation] No completed steps to compensate for workflow=%s", workflow_id)
        return {"workflow_id": workflow_id, "compensated_steps": 0}

    logger.warning(
        "[Compensation] Starting rollback for workflow=%s, steps_to_compensate=%d",
        workflow_id, len(completed_steps),
    )

    await log_event(
        db=db,
        event_type=EventType.ROLLBACK_EXECUTED,
        message_id=message_id,
        result="STARTED",
        reason=f"Compensating {len(completed_steps)} steps for workflow {workflow_id}",
        extra={"workflow_id": workflow_id},
    )

    rollback_results = []
    # Reverse order
    for step in reversed(completed_steps):
        adapter = get_adapter(step.adapter_name)
        if adapter is None:
            logger.error(
                "[Compensation] Adapter '%s' not found for step %s — skipping",
                step.adapter_name, step.step_id,
            )
            rollback_results.append({
                "step_id": step.step_id,
                "success": False,
                "error": f"Adapter '{step.adapter_name}' not registered",
            })
            continue

        # Merge original step output into compensation params
        comp_params = {
            **step.compensation_params,
            **(step.result or {}),
        }

        try:
            logger.info(
                "[Compensation] Compensating step=%s adapter=%s",
                step.step_id, step.adapter_name,
            )
            comp_result = await adapter.compensate(comp_params)
            rollback_results.append({
                "step_id": step.step_id,
                "success": comp_result.success,
                "output": comp_result.output,
                "error": comp_result.error,
            })

            await log_event(
                db=db,
                event_type=EventType.STEP_COMPLETED if comp_result.success else EventType.STEP_FAILED,
                message_id=message_id,
                result="COMPENSATED" if comp_result.success else "COMPENSATION_FAILED",
                reason=f"Compensation for step {step.step_id}",
                extra={"step_id": step.step_id, "adapter": step.adapter_name},
            )

        except Exception as exc:
            logger.exception(
                "[Compensation] Exception compensating step=%s: %s",
                step.step_id, exc,
            )
            rollback_results.append({
                "step_id": step.step_id,
                "success": False,
                "error": str(exc),
            })

    await log_event(
        db=db,
        event_type=EventType.ROLLBACK_COMPLETED,
        message_id=message_id,
        result="COMPLETED",
        reason=f"Rollback completed for {len(completed_steps)} steps",
        extra={"workflow_id": workflow_id, "results": rollback_results},
    )

    logger.info("[Compensation] Rollback complete for workflow=%s", workflow_id)
    return {
        "workflow_id": workflow_id,
        "compensated_steps": len(completed_steps),
        "results": rollback_results,
    }
