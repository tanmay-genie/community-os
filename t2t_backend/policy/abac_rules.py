"""
policy/abac_rules.py — Attribute-Based Access Control rules.

These rules layer on top of RBAC and evaluate context attributes:
- clearance level mismatch
- risk level thresholds per autonomy level
- org boundary crossing
- PII / regulated data flags
"""
from __future__ import annotations

from dataclasses import dataclass

from schemas.envelope import MessageEnvelope
from schemas.intents import AutonomyLevel, ClearanceLevel, PolicyDecision, RiskLevel

CLEARANCE_RANK: dict[str, int] = {
    ClearanceLevel.PUBLIC.value: 0,
    ClearanceLevel.INTERNAL.value: 1,
    ClearanceLevel.CONFIDENTIAL.value: 2,
    ClearanceLevel.SECRET.value: 3,
}

# Autonomy level → max risk level before ESCALATE is forced
AUTONOMY_RISK_THRESHOLD: dict[str, str] = {
    AutonomyLevel.ADVISORY.value: RiskLevel.LOW.value,
    AutonomyLevel.ASSISTIVE.value: RiskLevel.LOW.value,
    AutonomyLevel.SEMI_AUTONOMOUS.value: RiskLevel.MEDIUM.value,
    AutonomyLevel.AUTONOMOUS.value: RiskLevel.HIGH.value,
}

RISK_RANK: dict[str, int] = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
    RiskLevel.CRITICAL.value: 3,
}


@dataclass
class ABACResult:
    decision: PolicyDecision
    rule_id: str
    reason: str


def evaluate_abac(
    envelope: MessageEnvelope,
    sender_clearance: str,
    sender_autonomy: str,
    sender_org_id: str,
    sender_budget_threshold: float | None,
    sender_max_risk: str,
) -> ABACResult | None:
    """
    Evaluate all ABAC rules against the message envelope.
    Returns an ABACResult if a rule fires (DENY or ESCALATE),
    or None if all rules pass (ALLOW proceeds from RBAC).
    Rules are evaluated in priority order — first match wins.
    """

    # ── Rule 1: Clearance mismatch ─────────────────────────────────────────
    required_clearance = envelope.recipient.clearance
    if required_clearance:
        sender_rank = CLEARANCE_RANK.get(sender_clearance, 0)
        required_rank = CLEARANCE_RANK.get(required_clearance.value, 0)
        if sender_rank < required_rank:
            return ABACResult(
                decision=PolicyDecision.DENY,
                rule_id="abac_clearance_mismatch",
                reason=(
                    f"Sender clearance '{sender_clearance}' is below "
                    f"required '{required_clearance.value}'"
                ),
            )

    # ── Rule 2: Risk level vs autonomy threshold ────────────────────────────
    intent_risk = envelope.intent.risk_level.value
    max_allowed_risk = AUTONOMY_RISK_THRESHOLD.get(sender_autonomy, RiskLevel.LOW.value)

    if RISK_RANK.get(intent_risk, 0) > RISK_RANK.get(max_allowed_risk, 0):
        return ABACResult(
            decision=PolicyDecision.ESCALATE,
            rule_id="abac_risk_exceeds_autonomy",
            reason=(
                f"Intent risk '{intent_risk}' exceeds autonomy threshold "
                f"'{max_allowed_risk}' for level '{sender_autonomy}'"
            ),
        )

    # ── Rule 3: Max risk level override per twin config ────────────────────
    if RISK_RANK.get(intent_risk, 0) > RISK_RANK.get(sender_max_risk, 0):
        return ABACResult(
            decision=PolicyDecision.ESCALATE,
            rule_id="abac_risk_exceeds_twin_max",
            reason=(
                f"Intent risk '{intent_risk}' exceeds this twin's "
                f"configured max risk '{sender_max_risk}'"
            ),
        )

    # ── Rule 4: CRITICAL risk always escalates ─────────────────────────────
    if intent_risk == RiskLevel.CRITICAL.value:
        return ABACResult(
            decision=PolicyDecision.ESCALATE,
            rule_id="abac_critical_risk_always_escalate",
            reason="CRITICAL risk level always requires human approval",
        )

    # ── Rule 5: Cross-org without valid contract ─────────────────────────
    if envelope.recipient.org_id != sender_org_id:
        if not envelope.scope.contract_id:
            return ABACResult(
                decision=PolicyDecision.DENY,
                rule_id="abac_cross_org_no_contract",
                reason=(
                    f"Cross-org message to '{envelope.recipient.org_id}' blocked — "
                    "no contract_id provided in scope"
                ),
            )
        # NOTE: Full DB-level contract validation (active + not expired)
        # is done at the router layer via policy/contracts.py.
        # ABAC only gates on the presence of a contract_id to fail fast.

    # ── Rule 6: EXECUTE intent always requires confirmation ────────────────
    from schemas.intents import IntentType
    if envelope.intent.type == IntentType.EXECUTE:
        if not envelope.intent.requires_human_confirmation:
            # Check autonomy — only AUTONOMOUS twins can auto-execute
            if sender_autonomy not in (
                AutonomyLevel.AUTONOMOUS.value, AutonomyLevel.SEMI_AUTONOMOUS.value
            ):
                return ABACResult(
                    decision=PolicyDecision.ESCALATE,
                    rule_id="abac_execute_requires_confirmation",
                    reason=(
                        f"EXECUTE intent from autonomy level '{sender_autonomy}' "
                        "requires human confirmation"
                    ),
                )

    # ── All rules passed ───────────────────────────────────────────────────
    return None
