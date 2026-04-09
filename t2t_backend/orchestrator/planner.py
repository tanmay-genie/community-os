"""
orchestrator/planner.py — Intent → Workflow Plan.

Converts a confirmed intent into an ordered list of executable steps.
Each step specifies: adapter_name, params, and compensation_params.

Add new workflows here as the product grows.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """A single executable step in a workflow plan."""
    step_id: str
    step_name: str
    adapter_name: str
    params: dict[str, Any]
    compensation_params: dict[str, Any] = field(default_factory=dict)
    # Populated after execution
    result: dict[str, Any] | None = None
    success: bool | None = None
    error: str | None = None


@dataclass
class WorkflowPlan:
    """An ordered list of steps to execute for a given intent."""
    intent_type: str
    intent_name: str | None
    steps: list[WorkflowStep]
    workflow_id: str = ""

    def __post_init__(self) -> None:
        import uuid
        if not self.workflow_id:
            self.workflow_id = str(uuid.uuid4())


# ── Workflow Definitions ──────────────────────────────────────────────────────

def build_plan(
    intent_type: str,
    intent_name: str | None,
    payload: dict[str, Any],
    reply_payload: dict[str, Any],
) -> WorkflowPlan:
    """
    Build a WorkflowPlan for the given intent.
    Merges original payload with reply payload for context.
    """
    context = {**payload, **reply_payload}

    # ── CommunityOS AI Workflows ────────────────────────────────────────

    if intent_name == "ai_chat":
        return _plan_ai_chat(context)

    elif intent_name == "voice_navigation":
        return _plan_voice_navigation(context)

    elif intent_name == "content_generation":
        return _plan_content_generation(context)

    elif intent_name == "ticket_triage":
        return _plan_ticket_triage(context)

    elif intent_name == "content_moderation":
        return _plan_content_moderation(context)

    elif intent_name == "insights":
        return _plan_insights(context)

    elif intent_name == "ops_command":
        return _plan_ops_command(context)

    elif intent_name == "member_invite":
        return _plan_member_invite(context)

    # ── Genie AI Internal Workflows ──────────────────────────────────────

    elif intent_name == "PROPOSE_LAUNCH" or intent_type == "PROPOSE":
        return _plan_product_launch(context)

    elif intent_name == "REQUEST_SPRINT_CREATE" or (
        intent_type == "EXECUTE" and "sprint" in str(intent_name or "").lower()
    ):
        return _plan_sprint_create(context)

    elif intent_name == "REQUEST_CAPACITY_ESTIMATE":
        return _plan_capacity_estimate(context)

    elif intent_name == "REQUEST_SECURITY_REVIEW":
        return _plan_security_review(context)

    elif intent_name == "REQUEST_STATUS":
        return _plan_status_report(context)

    elif intent_name == "MEETING_SUMMARIZE" or intent_type == "MEETING_SUMMARIZE":
        return _plan_meeting_summary(context)

    else:
        # Generic fallback — single LLM step
        return _plan_generic(intent_type, intent_name, context)


# ── CommunityOS Plan Builders ─────────────────────────────────────────────────

def _plan_ai_chat(ctx: dict) -> WorkflowPlan:
    """Member talks to AI — general conversation."""
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="ai_chat",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Generate AI chat response",
                adapter_name="llm",
                params={
                    "intent_name": "ai_chat",
                    "message": ctx.get("message", ""),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_voice_navigation(ctx: dict) -> WorkflowPlan:
    """User gives voice command to navigate app."""
    return WorkflowPlan(
        intent_type="EXECUTE",
        intent_name="voice_navigation",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Parse voice navigation command",
                adapter_name="llm",
                params={
                    "intent_name": "voice_navigation",
                    "message": ctx.get("command", ctx.get("message", "")),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_content_generation(ctx: dict) -> WorkflowPlan:
    """Admin requests AI to generate community content."""
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="content_generation",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Generate community content",
                adapter_name="llm",
                params={
                    "intent_name": "content_generation",
                    "message": (
                        f"Type: {ctx.get('type', 'announcement')}\n"
                        f"Topic: {ctx.get('topic', '')}\n"
                        f"Tone: {ctx.get('tone', 'friendly')}\n"
                        f"Additional context: {ctx.get('details', '')}"
                    ),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_ticket_triage(ctx: dict) -> WorkflowPlan:
    """AI triages a service request ticket."""
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="ticket_triage",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Triage service ticket",
                adapter_name="llm",
                params={
                    "intent_name": "ticket_triage",
                    "message": (
                        f"Ticket ID: {ctx.get('ticket_id', 'N/A')}\n"
                        f"Description: {ctx.get('description', '')}\n"
                        f"Unit: {ctx.get('unit', 'N/A')}\n"
                        f"Reported by: {ctx.get('reported_by', 'N/A')}"
                    ),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_content_moderation(ctx: dict) -> WorkflowPlan:
    """AI moderates community content."""
    return WorkflowPlan(
        intent_type="POLICY_CHECK",
        intent_name="content_moderation",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Moderate content",
                adapter_name="llm",
                params={
                    "intent_name": "content_moderation",
                    "message": (
                        f"Content type: {ctx.get('content_type', 'community_post')}\n"
                        f"Content: {ctx.get('content', '')}\n"
                        f"Author: {ctx.get('author', 'N/A')}"
                    ),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_insights(ctx: dict) -> WorkflowPlan:
    """Admin requests AI insights and analytics."""
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="insights",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Generate AI insights",
                adapter_name="llm",
                params={
                    "intent_name": "insights",
                    "message": (
                        f"Report type: {ctx.get('type', 'weekly_summary')}\n"
                        f"Property: {ctx.get('property', 'N/A')}\n"
                        f"Period: {ctx.get('period', 'last_7_days')}\n"
                        f"Data: {ctx.get('data', '{}')}"
                    ),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_ops_command(ctx: dict) -> WorkflowPlan:
    """Admin issues an operational command via AI."""
    return WorkflowPlan(
        intent_type="EXECUTE",
        intent_name="ops_command",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Process ops command",
                adapter_name="llm",
                params={
                    "intent_name": "ops_command",
                    "message": (
                        f"Command: {ctx.get('command', '')}\n"
                        f"Target: {ctx.get('target', 'all_residents')}\n"
                        f"Details: {ctx.get('message', ctx.get('details', ''))}"
                    ),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


def _plan_member_invite(ctx: dict) -> WorkflowPlan:
    """AI drafts a member invitation."""
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="member_invite",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Draft member invitation",
                adapter_name="llm",
                params={
                    "intent_name": "member_invite",
                    "message": (
                        f"Resident name: {ctx.get('resident_name', '')}\n"
                        f"Unit: {ctx.get('unit', '')}\n"
                        f"Property: {ctx.get('property_name', '')}\n"
                        f"Channel: {ctx.get('channel', 'whatsapp')}"
                    ),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )


# ── Genie AI Internal Plan Builders ──────────────────────────────────────────

def _plan_product_launch(ctx: dict) -> WorkflowPlan:
    return WorkflowPlan(
        intent_type="PROPOSE",
        intent_name="PROPOSE_LAUNCH",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Create launch epic in Jira",
                adapter_name="jira",
                params={
                    "action": "create_issue",
                    "summary": f"[T2T] Product Launch: {ctx.get('product', 'New Module')}",
                    "description": ctx.get("description", "Auto-generated by T2T"),
                    "issue_type": "Epic",
                },
                compensation_params={"action": "close_issue"},
            ),
            WorkflowStep(
                step_id="step_2",
                step_name="Add launch timeline comment",
                adapter_name="jira",
                params={
                    "action": "add_comment",
                    "comment": f"Launch timeline: {ctx.get('timeline', 'Q2')}. Initiated via T2T.",
                },
                compensation_params={},
            ),
            WorkflowStep(
                step_id="step_3",
                step_name="Log confirmation artifact",
                adapter_name="dummy",
                params={"action": "log_artifact", "artifact": "launch_plan", **ctx},
                compensation_params={},
            ),
        ],
    )


def _plan_sprint_create(ctx: dict) -> WorkflowPlan:
    return WorkflowPlan(
        intent_type="EXECUTE",
        intent_name="REQUEST_SPRINT_CREATE",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Create sprint in Jira",
                adapter_name="jira",
                params={
                    "action": "create_issue",
                    "summary": f"[T2T Sprint] {ctx.get('sprint_name', 'New Sprint')}",
                    "description": ctx.get("goal", "Sprint created via T2T"),
                    "issue_type": "Story",
                },
                compensation_params={"action": "close_issue"},
            ),
            WorkflowStep(
                step_id="step_2",
                step_name="Assign team members",
                adapter_name="dummy",
                params={"action": "assign_members", "members": ctx.get("members", [])},
                compensation_params={"action": "unassign_members"},
            ),
        ],
    )


def _plan_capacity_estimate(ctx: dict) -> WorkflowPlan:
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="REQUEST_CAPACITY_ESTIMATE",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Generate capacity report",
                adapter_name="dummy",
                params={"action": "generate_capacity_report", **ctx},
                compensation_params={},
            ),
        ],
    )


def _plan_security_review(ctx: dict) -> WorkflowPlan:
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="REQUEST_SECURITY_REVIEW",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Create security review task",
                adapter_name="jira",
                params={
                    "action": "create_issue",
                    "summary": f"[T2T Security Review] {ctx.get('feature', 'Feature')}",
                    "description": "Security review requested via T2T protocol.",
                    "issue_type": "Task",
                },
                compensation_params={"action": "close_issue"},
            ),
        ],
    )


def _plan_status_report(ctx: dict) -> WorkflowPlan:
    return WorkflowPlan(
        intent_type="REQUEST",
        intent_name="REQUEST_STATUS",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Compile status report",
                adapter_name="dummy",
                params={"action": "compile_status", **ctx},
                compensation_params={},
            ),
        ],
    )


def _plan_meeting_summary(ctx: dict) -> WorkflowPlan:
    return WorkflowPlan(
        intent_type="MEETING_SUMMARIZE",
        intent_name="MEETING_SUMMARIZE",
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name="Generate meeting summary",
                adapter_name="dummy",
                params={"action": "summarize_meeting", "transcript": ctx.get("transcript", "")},
                compensation_params={},
            ),
            WorkflowStep(
                step_id="step_2",
                step_name="Extract action items",
                adapter_name="dummy",
                params={"action": "extract_action_items", **ctx},
                compensation_params={},
            ),
        ],
    )


def _plan_generic(
    intent_type: str, intent_name: str | None, ctx: dict
) -> WorkflowPlan:
    logger.warning("Using generic workflow plan for intent=%s name=%s", intent_type, intent_name)
    return WorkflowPlan(
        intent_type=intent_type,
        intent_name=intent_name,
        steps=[
            WorkflowStep(
                step_id="step_1",
                step_name=f"Execute {intent_name or intent_type}",
                adapter_name="llm",
                params={
                    "intent_name": intent_name or "ai_chat",
                    "message": ctx.get("message", str(ctx)),
                    "context": ctx,
                },
                compensation_params={},
            ),
        ],
    )
