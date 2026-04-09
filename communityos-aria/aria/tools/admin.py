"""
aria/tools/admin.py — MCP tools for ADMIN side.

Admin tools give the property manager AI-powered control:
  - Society insights and trend detection
  - Escalation queue management
  - Content moderation decisions
  - Auto-generate announcements
"""

import httpx
from aria.t2t_client import t2t
from aria.config import settings


def register(mcp):

    # ── INSIGHTS ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_society_insights(org_id: str, days: int = 7) -> str:
        """
        Generate AI-powered insights from society activity data.
        Call when admin says: 'Give me a summary', 'What's happening in the society?',
        'Any patterns in complaints?', 'Society health report'.
        Pulls from audit logs and surfaces trends, risks, recommendations.
        """
        try:
            audit_data = await t2t.get_audit_summary(org_id=org_id, days=days)
            events = audit_data if isinstance(audit_data, list) else []

            if not events:
                return (
                    f"No significant activity found in the last {days} days. "
                    f"Society seems quiet."
                )

            # Summarise event types
            type_counts: dict = {}
            for ev in events:
                t = ev.get("event_type", "UNKNOWN")
                type_counts[t] = type_counts.get(t, 0) + 1

            top = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            lines = [f"Society snapshot — last {days} days:"]
            for event_type, count in top:
                lines.append(f"• {event_type}: {count} times")

            lines.append(
                "\nRecommendation: Review denied events and escalations for action items."
            )
            return "\n".join(lines)
        except Exception:
            return "Insights unavailable right now. T2T audit service may be down."

    @mcp.tool()
    async def get_ticket_trends(org_id: str) -> str:
        """
        Detect complaint patterns across the society.
        Call when admin says: 'Which issues keep coming up?', 'Any recurring problems?',
        'Ticket trends', 'What are residents complaining about most?'
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{settings.T2T_BASE_URL}/communityos/tickets/trends",
                    params={"org_id": org_id},
                    headers={"X-Admin-Secret": settings.T2T_ADMIN_SECRET},
                )
                resp.raise_for_status()
                data = resp.json()

            trends = data.get("trends", [])
            if not trends:
                return "No significant complaint patterns detected right now."

            lines = ["Ticket trends:"]
            for tr in trends[:5]:
                lines.append(
                    f"• {tr['category']}: {tr['count']} tickets "
                    f"({tr.get('location', 'various areas')})"
                )
            if trends:
                top = trends[0]
                lines.append(
                    f"\nTop concern: {top['category']} — consider proactive action."
                )
            return "\n".join(lines)
        except Exception:
            return "Ticket trend analysis unavailable right now."

    # ── ESCALATIONS ───────────────────────────────────────────────────────

    @mcp.tool()
    async def get_pending_escalations(org_id: str) -> str:
        """
        Fetch all pending escalations waiting for admin decision.
        Call when admin says: 'Any pending approvals?', 'What needs my attention?',
        'Show escalations', 'What's in the queue?'
        """
        try:
            data = await t2t.get_pending_escalations(org_id=org_id)
            tasks = data if isinstance(data, list) else data.get("tasks", [])

            if not tasks:
                return "No pending escalations. Queue is clear."

            lines = [f"{len(tasks)} escalation(s) waiting:"]
            for task in tasks[:5]:
                sla = task.get("sla_remaining_minutes", "?")
                lines.append(
                    f"• [{task.get('risk_level','?')}] {task.get('reason','?')} "
                    f"— {sla} min SLA remaining (ID: {task.get('task_id','')})"
                )
            return "\n".join(lines)
        except Exception:
            return "Couldn't fetch escalations right now."

    @mcp.tool()
    async def approve_escalation(task_id: str, reason: str = "Approved by admin") -> str:
        """
        Approve a pending escalation — resumes the workflow.
        Call when admin says: 'Approve that', 'Green light it', 'Approve task <id>'.
        task_id: the escalation task ID from get_pending_escalations.
        """
        try:
            await t2t.approve_escalation(task_id=task_id, reason=reason)
            return f"Escalation approved. Workflow resumed. Task ID: {task_id}"
        except Exception:
            return f"Couldn't approve escalation {task_id}. Please try again."

    @mcp.tool()
    async def deny_escalation(task_id: str, reason: str = "Denied by admin") -> str:
        """
        Deny a pending escalation — terminates the workflow.
        Call when admin says: 'Deny that', 'Reject it', 'Deny task <id>'.
        task_id: the escalation task ID from get_pending_escalations.
        """
        try:
            await t2t.deny_escalation(task_id=task_id, reason=reason)
            return f"Escalation denied. Workflow terminated. Task ID: {task_id}"
        except Exception:
            return f"Couldn't deny escalation {task_id}. Please try again."

    # ── CONTENT GENERATION ────────────────────────────────────────────────

    @mcp.tool()
    async def generate_announcement(
        raw_text: str,
        tone: str = "formal",
    ) -> str:
        """
        Convert admin's rough note into a polished society announcement.
        Call when admin says: 'Write an announcement about water cut',
        'Draft a notice for the AGM', 'Help me write this notice'.
        raw_text: admin's rough note
        tone: formal | friendly | urgent
        """
        tone_guide = {
            "formal": "professional and formal",
            "friendly": "warm and conversational",
            "urgent": "clear, urgent, and action-oriented",
        }.get(tone, "professional")

        return (
            f"[Draft — {tone.title()} Tone]\n\n"
            f"Dear Residents,\n\n"
            f"This is to inform you that {raw_text.strip()}.\n\n"
            f"We appreciate your cooperation and understanding.\n\n"
            f"Regards,\nSociety Management\n\n"
            f"[Note: Review and edit before publishing]"
        )

    @mcp.tool()
    async def generate_event_description(
        event_title: str,
        date: str,
        location: str,
        extra_details: str = "",
    ) -> str:
        """
        Auto-generate a friendly event description for the community feed.
        Call when admin says: 'Write description for Holi event',
        'Create an event post for cricket match'.
        """
        details = f" {extra_details}" if extra_details else ""
        return (
            f"Join us for {event_title}!\n\n"
            f"Date: {date}\n"
            f"Location: {location}\n\n"
            f"Come together with your neighbours for a wonderful time.{details} "
            f"All residents are welcome. We look forward to seeing you there!\n\n"
            f"[Edit as needed before publishing]"
        )

    # ── MODERATION ────────────────────────────────────────────────────────

    @mcp.tool()
    async def moderate_content(
        content: str,
        content_id: str,
        org_id: str,
    ) -> str:
        """
        Analyse a post or message for policy violations.
        Call when admin says: 'Check this post', 'Is this okay to publish?',
        'Review this message', or when moderation queue has items.
        Returns: severity level and recommended action.
        """
        content_lower = content.lower()

        # Simple rule-based checks — replace with LLM call in production
        abusive_words = ["cheat", "fraud", "steal", "liar", "chor"]
        spam_patterns = ["buy now", "click here", "whatsapp", "discount"]

        severity = "CLEAN"
        reason = "No issues detected."
        action = "ALLOW"

        if any(w in content_lower for w in abusive_words):
            severity = "HIGH"
            reason = "Potentially defamatory or abusive language detected."
            action = "HIDE and escalate to admin review"
        elif any(p in content_lower for p in spam_patterns):
            severity = "MEDIUM"
            reason = "Possible spam or promotional content."
            action = "Flag for admin review"
        elif len(content.split()) < 3:
            severity = "LOW"
            reason = "Very short content — may be incomplete."
            action = "ALLOW with note"

        return (
            f"Content ID: {content_id}\n"
            f"Severity: {severity}\n"
            f"Reason: {reason}\n"
            f"Recommended action: {action}"
        )
