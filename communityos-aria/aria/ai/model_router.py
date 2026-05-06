"""
aria.ai.model_router — Smart model routing: simple → Flash, complex → Pro.

Heuristics:
  - Simple/transactional intents (booking, dues, notices) → gemini-2.5-flash
  - Generation tasks (announcements, summaries, insights) → gemini-2.5-pro
  - Moderation/classification → gemini-2.5-flash (fast + cheap)
  - Unknown/chat (no intent) → gemini-2.5-flash with upgrade if message long
"""
from __future__ import annotations

import logging

logger = logging.getLogger("aria.ai.model_router")

FLASH = "gemini-2.5-flash"
PRO = "gemini-2.5-pro"

SIMPLE_INTENTS = {
    "book_amenity", "cancel_booking", "check_dues", "pay_dues",
    "get_notices", "get_society_events", "rsvp_to_event",
    "get_pending_escalations", "approve_escalation", "deny_escalation",
    "create_ticket", "moderate_content",
}
COMPLEX_INTENTS = {
    "generate_announcement", "get_society_insights",
}

COMPLEX_KEYWORDS = (
    "summarize", "summarise", "explain", "why", "recommend",
    "analyze", "analyse", "draft", "compose", "strategy",
)

LONG_MESSAGE_TOKENS = 300


def choose_model(intent: str | None, message: str, role: str = "member") -> str:
    """Return the best Gemini model for this request."""
    if intent in COMPLEX_INTENTS:
        return PRO

    msg_lower = (message or "").lower()
    if any(kw in msg_lower for kw in COMPLEX_KEYWORDS):
        return PRO

    if intent in SIMPLE_INTENTS:
        return FLASH

    est_tokens = len(message) // 4
    if est_tokens > LONG_MESSAGE_TOKENS and role == "admin":
        return PRO

    return FLASH
