"""
orchestrator/adapters/llm_adapter.py — LLM Integration Adapter.

Connects to OpenAI or Anthropic to generate AI responses for CommunityOS.
Used by the AI processor when a message is sent to an AI Twin.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings
from orchestrator.adapters.base import AdapterResult, BaseAdapter, register_adapter

logger = logging.getLogger(__name__)

# ── System prompts per CommunityOS intent ────────────────────────────────────

SYSTEM_PROMPTS: dict[str, str] = {
    "ai_chat": (
        "You are a helpful AI assistant for a residential community. "
        "You help members with questions about their property, amenities, events, "
        "and daily community life. Be friendly, concise, and helpful."
    ),
    "voice_navigation": (
        "You are a voice navigation assistant for a community app. "
        "The user gives voice commands to navigate the app. "
        "Respond with a JSON object: {\"action\": \"navigate\", \"screen\": \"<screen_path>\", \"message\": \"<confirmation>\"}. "
        "Valid screens: /home, /events, /chat, /tickets, /bookings, /payments, /profile, /settings, /community, /map, /polls, /notifications."
    ),
    "content_generation": (
        "You are a content writer for a residential community. "
        "Generate engaging community posts, announcements, or event descriptions. "
        "Respond with JSON: {\"title\": \"...\", \"body\": \"...\", \"tags\": [...]}."
    ),
    "ticket_triage": (
        "You are a support ticket triage system for a residential property. "
        "Analyze the ticket description and respond with JSON: "
        "{\"category\": \"...\", \"priority\": \"low|medium|high|urgent\", "
        "\"suggested_assignee\": \"...\", \"estimated_resolution_hours\": N, \"summary\": \"...\"}. "
        "Categories: maintenance, plumbing, electrical, security, cleaning, pest_control, elevator, parking, noise_complaint, other."
    ),
    "content_moderation": (
        "You are a content moderation system for a residential community platform. "
        "Analyze the content and respond with JSON: "
        "{\"approved\": true/false, \"flags\": [...], \"reason\": \"...\", \"confidence\": 0.0-1.0}. "
        "Flag categories: spam, offensive, harassment, misinformation, inappropriate, personal_info_leak."
    ),
    "insights": (
        "You are an analytics assistant for a property management admin. "
        "Based on the data provided, generate insights. "
        "Respond with JSON: {\"summary\": \"...\", \"key_metrics\": {...}, \"trends\": [...], \"recommendations\": [...]}."
    ),
    "ops_command": (
        "You are an operations assistant for a property admin. "
        "Help execute operational commands like sending announcements, managing schedules, etc. "
        "Respond with JSON: {\"action\": \"...\", \"result\": \"...\", \"message\": \"...\"}."
    ),
    "member_invite": (
        "You are an outreach assistant for a residential community. "
        "Draft a personalized, warm invitation message for a new resident. "
        "Respond with JSON: {\"invite_message\": \"...\", \"subject_line\": \"...\", \"suggested_channel\": \"whatsapp|email|sms\"}."
    ),
}

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant for a residential community management platform called CommunityOS. "
    "Help users with their requests. Be concise and helpful."
)


class LLMAdapter(BaseAdapter):
    """
    LLM adapter — sends prompts to OpenAI or Anthropic and returns AI responses.
    """
    name = "llm"

    async def execute(self, params: dict[str, Any]) -> AdapterResult:
        intent_name = params.get("intent_name", "ai_chat")
        user_message = params.get("message", "")
        context = params.get("context", {})
        memory = params.get("memory", [])

        system_prompt = SYSTEM_PROMPTS.get(intent_name, DEFAULT_SYSTEM_PROMPT)

        # Build context string from memory
        memory_context = ""
        if memory:
            recent = memory[:5]
            memory_context = "\n\nRecent interactions:\n" + "\n".join(
                f"- {m.get('event_type', '')}: {m.get('details', {})}" for m in recent
            )

        # Build context string from payload
        context_str = ""
        if context:
            context_str = "\n\nAdditional context:\n" + "\n".join(
                f"- {k}: {v}" for k, v in context.items()
                if k not in ("message", "intent_name", "memory", "context")
            )

        full_system = system_prompt + memory_context + context_str

        try:
            if settings.LLM_PROVIDER == "openai":
                response = await self._call_openai(full_system, user_message)
            elif settings.LLM_PROVIDER == "anthropic":
                response = await self._call_anthropic(full_system, user_message)
            else:
                return AdapterResult(
                    success=False, output={},
                    error=f"Unknown LLM provider: {settings.LLM_PROVIDER}",
                )

            return AdapterResult(
                success=True,
                output={
                    "response": response,
                    "model": settings.LLM_MODEL,
                    "intent_name": intent_name,
                },
            )

        except httpx.TimeoutException:
            return AdapterResult(success=False, output={}, error="LLM request timed out")
        except Exception as e:
            logger.exception("LLM adapter error: %s", e)
            return AdapterResult(success=False, output={}, error=str(e))

    async def _call_openai(self, system_prompt: str, user_message: str) -> str:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "max_tokens": settings.LLM_MAX_TOKENS,
                    "temperature": settings.LLM_TEMPERATURE,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _call_anthropic(self, system_prompt: str, user_message: str) -> str:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.LLM_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.LLM_MODEL,
                    "max_tokens": settings.LLM_MAX_TOKENS,
                    "system": system_prompt,
                    "messages": [
                        {"role": "user", "content": user_message},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]

    async def compensate(self, params: dict[str, Any]) -> AdapterResult:
        # LLM responses cannot be rolled back — nothing to compensate
        return AdapterResult(success=True, output={"status": "no_compensation_needed"})


# Auto-register on import
register_adapter(LLMAdapter())
