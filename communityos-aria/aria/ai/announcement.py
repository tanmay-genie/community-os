"""
aria.ai.announcement — Polish admin raw notes into resident-friendly announcements.

Takes a rough note + optional tone + topic and produces a clean, warm,
community-appropriate announcement. Preserves all factual details.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("aria.ai.announcement")

TONE_INSTRUCTIONS = {
    "formal": "Use a formal tone. Proper salutation, clear structure, respectful sign-off.",
    "friendly": "Use a warm, neighborly tone. Keep it light but professional.",
    "urgent": "Use direct, action-oriented language. Put the most important info first. Call out the deadline or action required.",
    "celebratory": "Use a festive, inclusive tone. Be welcoming and emphasize community spirit.",
    "empathetic": "Acknowledge the inconvenience. Apologize where appropriate. Explain the reason and the mitigation steps.",
}

ANNOUNCEMENT_PROMPT = """You are writing a society announcement for residents.

Tone: {tone}
Topic: {topic}
Raw notes from the committee/admin:
{notes}

Rules:
- Keep it under 150 words.
- Start with a warm salutation (Dear Residents,).
- Make all facts, dates, times, and actions crystal clear.
- End with a respectful sign-off (Regards, Society Management).
- Do not invent details that aren't in the notes.
- Preserve language style if notes are Hinglish - write the announcement in the same style.

Output only the announcement text. No preamble, no explanation, no markdown fences.
"""


async def draft_announcement(notes: str, topic: str = "", tone: str = "friendly") -> dict:
    """Generate a polished announcement from raw notes."""
    tone = tone if tone in TONE_INSTRUCTIONS else "friendly"
    tone_desc = TONE_INSTRUCTIONS[tone]

    prompt = ANNOUNCEMENT_PROMPT.format(
        tone=tone_desc,
        topic=topic or "General update",
        notes=notes[:2000],
    )

    try:
        import google.generativeai as genai
        from aria.config import settings
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-pro")
        resp = model.generate_content(prompt, generation_config={"temperature": 0.4})
        draft = (resp.text or "").strip()
        if draft:
            return {"status": "success", "draft": draft, "tone": tone, "topic": topic, "source": "llm"}
    except Exception as e:
        logger.warning("Announcement draft failed: %s", e)

    fallback = (
        f"Dear Residents,\n\nThis is regarding {topic or 'an update from the society'}.\n\n"
        f"{notes}\n\nWe appreciate your cooperation.\n\nRegards,\nSociety Management"
    )
    return {"status": "fallback", "draft": fallback, "tone": tone, "topic": topic, "source": "template"}
