"""
aria.ai.triage — Auto-categorize and prioritize tickets with LLM.

Given a free-text complaint, returns:
  category: plumbing, electrical, lift, security, parking, cleaning, other
  priority: urgent, high, normal, low
  sla_minutes: suggested response SLA
  assigned_team: best team to handle it
  tags: keywords for search

Runs locally via heuristics if LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("aria.ai.triage")

CATEGORY_KEYWORDS = {
    "plumbing": ["water", "leak", "pipe", "tap", "flush", "drain", "flood", "bathroom", "sink"],
    "electrical": ["light", "power", "electric", "switch", "wiring", "bulb", "fan", "ac", "outlet"],
    "lift": ["lift", "elevator"],
    "security": ["gate", "guard", "intruder", "cctv", "camera", "intercom"],
    "parking": ["parking", "car", "bike", "vehicle", "slot"],
    "cleaning": ["clean", "garbage", "trash", "dust", "sweep", "pest"],
    "gas": ["gas", "cylinder", "lpg"],
    "fire_safety": ["fire", "smoke", "extinguisher", "alarm"],
}
URGENT_WORDS = {"fire", "gas leak", "flooding", "trapped", "stuck", "no water", "electrocut", "smoke"}
HIGH_WORDS = {"urgent", "asap", "immediately", "emergency", "not working", "broken"}

TEAM_MAP = {
    "plumbing": "Plumbing Team",
    "electrical": "Electrical Team",
    "lift": "Lift AMC Team",
    "security": "Security Team",
    "parking": "Security Team",
    "cleaning": "Housekeeping Team",
    "gas": "Gas Safety Team",
    "fire_safety": "Fire Safety Team",
    "other": "Maintenance Team",
}
SLA_MAP = {"urgent": 15, "high": 60, "normal": 120, "low": 480}

TRIAGE_PROMPT = """Triage this society maintenance complaint. Return ONLY JSON:
{"category": "plumbing|electrical|lift|security|parking|cleaning|gas|fire_safety|other", "priority": "urgent|high|normal|low", "sla_minutes": <int>, "assigned_team": "<team name>", "tags": ["<kw1>","<kw2>"], "reasoning": "<one sentence>"}

Priority rules:
- urgent = safety risk (fire, gas leak, flooding, trapped in lift)
- high = essential service down (no water, no electricity, AC broken in summer)
- normal = routine fix
- low = cosmetic / non-urgent

Complaint:
"""


def _heuristic_triage(text: str) -> dict:
    lower = text.lower()
    category = "other"
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            category = cat
            break

    priority = "normal"
    if any(w in lower for w in URGENT_WORDS) or category in ("fire_safety", "gas"):
        priority = "urgent"
    elif any(w in lower for w in HIGH_WORDS):
        priority = "high"

    tags = [kw for cat_kws in CATEGORY_KEYWORDS.values() for kw in cat_kws if kw in lower][:5]

    return {
        "category": category,
        "priority": priority,
        "sla_minutes": SLA_MAP[priority],
        "assigned_team": TEAM_MAP[category],
        "tags": tags,
        "reasoning": f"Heuristic match on category={category}, priority={priority}",
        "source": "heuristic",
    }


async def triage_ticket(description: str, *, use_llm: bool = True) -> dict:
    """Categorize and prioritize a ticket. Returns structured triage result."""
    if not description or not description.strip():
        return {**_heuristic_triage(""), "category": "other"}

    heuristic = _heuristic_triage(description)
    if not use_llm or heuristic["priority"] == "urgent":
        return heuristic

    try:
        import google.generativeai as genai
        from aria.config import settings
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp = model.generate_content(
            TRIAGE_PROMPT + description[:1500],
            generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
        )
        data = json.loads((resp.text or "").strip())
        if all(k in data for k in ("category", "priority", "assigned_team")):
            data["source"] = "llm"
            data.setdefault("sla_minutes", SLA_MAP.get(data["priority"], 120))
            data.setdefault("tags", heuristic["tags"])
            return data
    except Exception as e:
        logger.info("LLM triage failed, using heuristic: %s", e)

    return heuristic
