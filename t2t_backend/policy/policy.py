"""
policy/policy.py — The Policy Engine.

The central permission brain of the T2T system.
Called at TWO points in every message pipeline:
  Gate 1 — before routing (sender side)
  Gate 2 — before execution (target/orchestrator side)

Returns a structured PolicyResult with decision, rule_id, and reason.
This result is:
  - attached to the message state
  - stored in the audit log
  - used by the router and orchestrator to proceed or halt
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from audit.audit import log_event
from audit.taxonomy import EventType, Severity
from auth.auth import TwinContext
from policy.abac_rules import evaluate_abac
from policy.rbac_rules import role_can_send
from schemas.envelope import MessageEnvelope
from schemas.intents import PolicyDecision

logger = logging.getLogger(__name__)


@dataclass
class PolicyResult:
    """Structured output of every policy evaluation."""
    decision: PolicyDecision
    rule_id: str
    reason: str
    decision_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == PolicyDecision.DENY

    @property
    def needs_escalation(self) -> bool:
        return self.decision == PolicyDecision.ESCALATE

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "decision": self.decision.value,
            "rule_id": self.rule_id,
            "reason": self.reason,
        }


async def policy_check(
    envelope: MessageEnvelope,
    sender: TwinContext,
    db: AsyncSession,
    gate: str = "GATE_1",
) -> PolicyResult:
    """
    Run the full policy evaluation pipeline for a message.

    Order of evaluation:
    1. RBAC — does the sender's role allow this intent type?
    2. ABAC — do clearance, risk, org boundary, autonomy rules pass?
    3. Human confirmation flag — does the intent explicitly require it?

    Args:
        envelope: The full T2T message envelope.
        sender:   Verified TwinContext from auth.
        db:       DB session for audit logging.
        gate:     "GATE_1" (pre-routing) or "GATE_2" (pre-execution).

    Returns:
        PolicyResult with decision ALLOW | DENY | ESCALATE.
    """

    # ── Step 1: RBAC check ────────────────────────────────────────────────
    if not role_can_send(sender.role, envelope.intent.type):
        result = PolicyResult(
            decision=PolicyDecision.DENY,
            rule_id="rbac_role_not_permitted",
            reason=(
                f"Role '{sender.role}' is not permitted to send "
                f"intent '{envelope.intent.type.value}'"
            ),
        )
        await _log_policy_event(db, result, sender, envelope, gate)
        return result

    # ── Step 2: ABAC check ────────────────────────────────────────────────
    abac_result = evaluate_abac(
        envelope=envelope,
        sender_clearance=sender.clearance,
        sender_autonomy=sender.autonomy_level,
        sender_org_id=sender.org_id,
        sender_budget_threshold=sender.budget_threshold_usd,
        sender_max_risk=sender.max_risk_level,
    )

    if abac_result is not None:
        result = PolicyResult(
            decision=abac_result.decision,
            rule_id=abac_result.rule_id,
            reason=abac_result.reason,
        )
        await _log_policy_event(db, result, sender, envelope, gate)
        return result

    # ── Step 3: Explicit human confirmation required ───────────────────────
    if envelope.intent.requires_human_confirmation:
        result = PolicyResult(
            decision=PolicyDecision.ESCALATE,
            rule_id="policy_human_confirmation_required",
            reason="Intent is flagged as requiring explicit human confirmation",
        )
        await _log_policy_event(db, result, sender, envelope, gate)
        return result

    # ── All checks passed: ALLOW ──────────────────────────────────────────
    result = PolicyResult(
        decision=PolicyDecision.ALLOW,
        rule_id="policy_all_checks_passed",
        reason=f"All RBAC and ABAC checks passed at {gate}",
    )
    await _log_policy_event(db, result, sender, envelope, gate)
    return result


async def _log_policy_event(
    db: AsyncSession,
    result: PolicyResult,
    sender: TwinContext,
    envelope: MessageEnvelope,
    gate: str,
) -> None:
    """Map a PolicyResult to the appropriate audit event type and log it."""
    if result.allowed:
        event_type = EventType.POLICY_ALLOWED
        severity = Severity.INFO
    elif result.denied:
        event_type = EventType.POLICY_DENIED
        severity = Severity.WARNING
    else:
        event_type = EventType.POLICY_ESCALATED
        severity = Severity.WARNING

    await log_event(
        db=db,
        event_type=event_type,
        severity=severity,
        org_id=sender.org_id,
        twin_id=sender.twin_id,
        message_id=envelope.message_id,
        thread_id=envelope.thread_id,
        policy_decision_ref=result.decision_id,
        rule_id=result.rule_id,
        result=result.decision.value,
        reason=result.reason,
        extra={"gate": gate, "intent": envelope.intent.type.value},
    )

    logger.info(
        "Policy %s [%s] twin=%s intent=%s rule=%s reason=%s",
        result.decision.value, gate,
        sender.twin_id, envelope.intent.type.value,
        result.rule_id, result.reason,
    )
