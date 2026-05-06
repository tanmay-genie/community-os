"""
aria.ai.moderation — LLM-based content moderation for admin flows.

Replaces the keyword-based rule with a Gemini Flash call that classifies
content into categories: safe, harassment, hate, defamation, spam, pii_leak,
incitement, legal_risk.

Returns structured JSON with severity, category, and reason.
Has deterministic keyword fallback for the rare LLM failure.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("aria.ai.moderation")

SEVERITY_KEYWORDS = {
    "harassment": ["cheat", "fraud", "liar", "thief", "scam", "crook", "idiot", "stupid"],
    "hate": ["caste", "religion", "race"],
    "defamation": ["fraud", "corrupt", "embezzle", "steal", "kickback"],
    "spam": ["click here", "buy now", "limited offer", "http://", "https://"],
    "pii_leak": [r"\d{12}", r"\d{4}\s?\d{4}\s?\d{4}"],
}

MODERATION_PROMPT = """Classify this community-society message for moderation.
Return ONLY valid JSON in this exact shape, no markdown fences, no explanation:
{"severity": "LOW|MEDIUM|HIGH", "category": "safe|harassment|hate|defamation|spam|pii_leak|incitement|legal_risk", "reason": "<one short sentence>", "action": "allow|flag|block"}

Rules:
- Defamation against named residents/committee = HIGH
- Hate speech or casteist/religious slur = HIGH
- Harassment, threats = HIGH
- Spam (links, promos) = MEDIUM
- PII exposure (Aadhaar, phone, account) = MEDIUM
- Mild rudeness = LOW
- Benign content = LOW + safe + allow

Message to classify:
"""


def _fallback_classify(content: str) -> dict:
    lower = content.lower()
    for category, keywords in SEVERITY_KEYWORDS.items():
        for kw in keywords:
            if kw.startswith(r"\\") or any(c in kw for c in ".*+?()[]{}"):
                if re.search(kw, content):
                    return {"severity": "MEDIUM" if category in ("spam", "pii_leak") else "HIGH",
                            "category": category, "reason": f"Matched pattern for {category}",
                            "action": "flag" if category == "spam" else "block"}
            elif kw in lower:
                return {"severity": "HIGH" if category in ("harassment", "defamation", "hate") else "MEDIUM",
                        "category": category, "reason": f"Contains word(s) associated with {category}",
                        "action": "flag"}
    return {"severity": "LOW", "category": "safe", "reason": "No issues detected", "action": "allow"}


async def moderate(content: str, *, use_llm: bool = True) -> dict:
    """Classify content. Tries LLM first, falls back to keyword rules."""
    if not content or not content.strip():
        return {"severity": "LOW", "category": "safe", "reason": "Empty", "action": "allow"}

    if not use_llm:
        return _fallback_classify(content)

    try:
        import google.generativeai as genai
        from aria.config import settings
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        resp = model.generate_content(
            MODERATION_PROMPT + content[:2000],
            generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
        )
        text = (resp.text or "").strip()
        data = json.loads(text)
        if all(k in data for k in ("severity", "category", "reason", "action")):
            return data
    except Exception as e:
        logger.info("LLM moderation failed, using fallback: %s", e)

    return _fallback_classify(content)
