"""
aria.ai.proactive — Suggest actions based on user patterns + context.

Examples:
  - User asks "any events?" → also suggest RSVP if pending interest
  - User has pending dues > 10 days → proactively remind
  - User repeatedly books gym at same time → offer "book your usual slot"
  - User raised 2+ tickets in a week → offer "see all my tickets"
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass

from aria.ai.conversation_memory import memory

logger = logging.getLogger("aria.ai.proactive")


@dataclass
class Suggestion:
    intent: str
    display: str
    reason: str
    priority: int


def suggest_followups(twin_id: str, last_intent: str | None, tool_result: dict | None) -> list[Suggestion]:
    """Generate 0-3 proactive suggestions to show alongside the reply."""
    suggestions: list[Suggestion] = []
    user = memory.get_or_create_user(twin_id)
    recent_actions = [a["intent"] for a in user.recent_actions]

    if last_intent == "book_amenity" and tool_result and tool_result.get("status") == "booked":
        suggestions.append(Suggestion(
            intent="check_dues", display="Check pending dues",
            reason="After booking, remind user about dues if any exist",
            priority=3,
        ))

    if last_intent == "check_dues" and tool_result:
        total = tool_result.get("total", 0)
        if total > 0:
            suggestions.append(Suggestion(
                intent="pay_dues", display=f"Pay Rs.{total:,.0f} now",
                reason="User just checked dues and has pending balance",
                priority=1,
            ))

    if last_intent == "create_ticket":
        ticket_count = sum(1 for a in recent_actions if a == "create_ticket")
        if ticket_count >= 2:
            suggestions.append(Suggestion(
                intent="get_society_insights", display="See all my tickets",
                reason="User raised multiple tickets recently",
                priority=2,
            ))

    counter = Counter(recent_actions)
    if counter.get("book_amenity", 0) >= 3 and last_intent != "book_amenity":
        suggestions.append(Suggestion(
            intent="book_amenity", display="Book your usual slot",
            reason="User has a booking pattern",
            priority=3,
        ))

    if last_intent == "get_society_events" and tool_result:
        events = tool_result.get("events", [])
        if events:
            suggestions.append(Suggestion(
                intent="rsvp_to_event", display=f"RSVP to {events[0].get('title', 'next event')}",
                reason="User just asked about events",
                priority=2,
            ))

    suggestions.sort(key=lambda s: s.priority)
    return suggestions[:3]
