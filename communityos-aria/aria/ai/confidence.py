"""
aria.ai.confidence — Confidence scoring for every AI decision.

Combines multiple signals into a single 0..1 confidence:
  - Intent classifier confidence
  - Tool result success/failure
  - Sentiment signal (frustrated user lowers confidence)
  - Hallucination guard status
  - Language detection alignment
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceReport:
    score: float
    label: str
    factors: dict
    should_confirm: bool


def score_decision(
    intent_confidence: float,
    tool_success: bool,
    hallucination_ok: bool,
    sentiment_score: float = 0.0,
    has_required_args: bool = True,
    used_fallback: bool = False,
) -> ConfidenceReport:
    """Fuse signals into a single confidence number."""
    factors = {
        "intent": round(intent_confidence, 3),
        "tool_success": tool_success,
        "hallucination_ok": hallucination_ok,
        "sentiment_score": sentiment_score,
        "has_required_args": has_required_args,
        "used_fallback": used_fallback,
    }

    score = 0.0
    score += min(1.0, max(0.0, intent_confidence)) * 0.35
    score += (0.25 if tool_success else 0.0)
    score += (0.20 if hallucination_ok else 0.0)
    score += (0.10 if has_required_args else 0.0)
    score += (0.10 if not used_fallback else 0.0)
    if sentiment_score < -0.4:
        score -= 0.05
    score = max(0.0, min(1.0, score))

    if score >= 0.8:
        label = "HIGH"
    elif score >= 0.55:
        label = "MEDIUM"
    else:
        label = "LOW"

    should_confirm = (label != "HIGH") and (not tool_success or not hallucination_ok or not has_required_args)
    return ConfidenceReport(score=round(score, 3), label=label, factors=factors, should_confirm=should_confirm)
