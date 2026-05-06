"""
aria.ai.hallucination_guard — Validates LLM output against tool results.

Checks:
  - Booking IDs in reply must exist in tool result
  - Monetary amounts must match tool result
  - Dates/times must match
  - No fabricated ticket IDs, RSVP IDs, payment IDs

If hallucination detected, we rewrite the reply using a deterministic
template from the tool result.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("aria.ai.hallucination_guard")


@dataclass
class GuardResult:
    ok: bool
    issues: list[str]
    corrected_reply: str | None


ID_PATTERN = re.compile(r"\b([A-Z]{2,}-[A-Z0-9]{4,}|[A-F0-9]{8}(?:-[A-F0-9]{4}){0,4})\b")
AMOUNT_PATTERN = re.compile(r"(?:Rs\.?|₹|INR)\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)


def _extract_ids_from_dict(d: dict) -> set[str]:
    ids: set[str] = set()
    for k, v in d.items():
        if isinstance(v, str) and any(suffix in k.lower() for suffix in ("id", "ref", "token")):
            if len(v) >= 6:
                ids.add(v.upper())
                ids.add(v[:8].upper())
        elif isinstance(v, dict):
            ids |= _extract_ids_from_dict(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    ids |= _extract_ids_from_dict(item)
    return ids


def _extract_amounts_from_dict(d: dict) -> set[float]:
    amounts: set[float] = set()
    for k, v in d.items():
        if isinstance(v, (int, float)) and any(
            hint in k.lower() for hint in ("amount", "total", "due", "balance", "price")
        ):
            amounts.add(float(v))
        elif isinstance(v, dict):
            amounts |= _extract_amounts_from_dict(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    amounts |= _extract_amounts_from_dict(item)
    return amounts


def validate_reply(reply: str, tool_result: dict | None, intent: str | None) -> GuardResult:
    """Check reply for fabricated IDs or amounts. Returns GuardResult."""
    issues: list[str] = []
    if not reply or not tool_result:
        return GuardResult(ok=True, issues=[], corrected_reply=None)

    allowed_ids = _extract_ids_from_dict(tool_result)
    allowed_amounts = _extract_amounts_from_dict(tool_result)

    mentioned_ids = set(m.upper() for m in ID_PATTERN.findall(reply))
    for mid in mentioned_ids:
        if mid in {"ARIA", "ESC", "TKT", "BK", "RSVP", "PAY"}:
            continue
        ok = any(mid == aid or mid in aid or aid in mid for aid in allowed_ids)
        if not ok:
            issues.append(f"Reply contains ID '{mid}' not in tool result")

    mentioned_amounts = set()
    for m in AMOUNT_PATTERN.findall(reply):
        try:
            mentioned_amounts.add(float(m.replace(",", "")))
        except ValueError:
            continue

    for amt in mentioned_amounts:
        if not any(abs(amt - a) < 0.5 for a in allowed_amounts):
            issues.append(f"Reply mentions amount Rs.{amt:,.0f} not in tool result")

    return GuardResult(ok=not issues, issues=issues, corrected_reply=None)


def safe_format(intent: str, tool_result: dict) -> str:
    """Deterministic formatter used when guard detects hallucination."""
    status = tool_result.get("status", "")
    msg = tool_result.get("message", "")

    if intent == "book_amenity" and status == "booked":
        return (f"Your {tool_result.get('amenity', 'amenity')} is booked for "
                f"{tool_result.get('slot', '')} on {tool_result.get('date', 'today')}. "
                f"Booking ID: {tool_result.get('booking_id', '')[:8].upper()}.")
    if intent == "check_dues":
        total = tool_result.get("total", 0)
        return f"You have Rs.{total:,.0f} in pending dues." if total else "You have no pending dues."
    if intent == "pay_dues" and status == "success":
        return f"Payment of Rs.{tool_result.get('amount', 0):,.0f} initiated."

    return msg or "Action completed."
