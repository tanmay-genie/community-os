"""
aria.ai.sentiment — Detect frustration, urgency, and emotion in user messages.

Hybrid: lexical scoring + optional LLM refinement. Never blocks the reply.
Emits signals that downstream systems (escalation, routing) can use.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("aria.ai.sentiment")

FRUSTRATION_WORDS = {
    "angry", "frustrated", "annoyed", "fed up", "terrible", "horrible",
    "worst", "useless", "stupid", "waste", "pathetic", "disgusting",
    "pissed", "ridiculous", "unacceptable", "disappointed", "shameful",
    "नाराज", "गुस्सा", "परेशान", "बेकार",
}
URGENCY_WORDS = {
    "urgent", "emergency", "immediately", "asap", "right now", "quickly",
    "flooding", "fire", "gas leak", "stuck", "trapped", "help",
    "जल्दी", "तुरंत",
}
POSITIVE_WORDS = {
    "thanks", "thank you", "great", "awesome", "perfect", "love", "excellent",
    "धन्यवाद", "शुक्रिया",
}

REPEAT_PATTERN = re.compile(r"(.)\1{3,}")
ALL_CAPS_PATTERN = re.compile(r"\b[A-Z]{4,}\b")
MULTI_PUNCTUATION = re.compile(r"[!?]{2,}")


@dataclass
class SentimentSignal:
    label: str
    score: float
    urgency: bool
    frustration: bool
    reasons: list[str]


def analyze(message: str) -> SentimentSignal:
    """Lightweight sentiment classifier. Returns label + signals."""
    if not message:
        return SentimentSignal("neutral", 0.0, False, False, [])

    msg_lower = message.lower()
    reasons: list[str] = []
    score = 0.0

    frustration_hits = sum(1 for w in FRUSTRATION_WORDS if w in msg_lower)
    urgency_hits = sum(1 for w in URGENCY_WORDS if w in msg_lower)
    positive_hits = sum(1 for w in POSITIVE_WORDS if w in msg_lower)

    if frustration_hits:
        score -= frustration_hits * 0.4
        reasons.append(f"{frustration_hits} frustration word(s)")
    if urgency_hits:
        score -= urgency_hits * 0.2
        reasons.append(f"{urgency_hits} urgency word(s)")
    if positive_hits:
        score += positive_hits * 0.4
        reasons.append(f"{positive_hits} positive word(s)")

    if MULTI_PUNCTUATION.search(message):
        score -= 0.2
        reasons.append("multiple punctuation (!!!/???)")
    if len(ALL_CAPS_PATTERN.findall(message)) >= 2:
        score -= 0.3
        reasons.append("heavy caps lock")
    if REPEAT_PATTERN.search(message):
        score -= 0.2
        reasons.append("character repetition")

    score = max(-1.0, min(1.0, score))
    frustration = score <= -0.5 or frustration_hits >= 2
    urgency = urgency_hits >= 1

    if score <= -0.6:
        label = "angry"
    elif score <= -0.2:
        label = "frustrated"
    elif score >= 0.4:
        label = "happy"
    else:
        label = "neutral"

    return SentimentSignal(label=label, score=round(score, 2),
                           urgency=urgency, frustration=frustration, reasons=reasons)


def soften_tone_hint(signal: SentimentSignal) -> str:
    """Return a prompt hint so the LLM matches tone."""
    if signal.frustration:
        return ("The user sounds frustrated. Be empathetic, acknowledge the inconvenience, "
                "skip the small talk, and get to the solution fast.")
    if signal.urgency:
        return ("The user has an urgent request. Be direct and actionable. "
                "Don't ask clarifying questions unless absolutely necessary.")
    if signal.label == "happy":
        return "The user is in a good mood. Keep the reply warm and brief."
    return ""
