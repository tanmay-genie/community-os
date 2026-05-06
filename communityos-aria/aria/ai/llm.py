"""
aria.ai.llm — Unified Gemini wrapper: streaming, caching, metrics, retries.

Provides:
  - call_gemini(): async non-streaming call with full telemetry
  - stream_gemini(): async generator yielding text chunks
  - uses prompt_cache, model_router, metrics transparently
"""
from __future__ import annotations

import asyncio
import logging
import time

from aria.ai.metrics import CallRecord, estimate_tokens, metrics

logger = logging.getLogger("aria.ai.llm")

RETRYABLE_ERRORS = (
    "ResourceExhausted", "ServiceUnavailable", "DeadlineExceeded",
    "InternalError", "429", "503", "500",
)


def _is_retryable(err: Exception) -> bool:
    s = str(err)
    return any(code in s for code in RETRYABLE_ERRORS)


async def call_gemini(
    system_prompt: str,
    user_message: str,
    model: str = "gemini-2.5-flash",
    history: list | None = None,
    conversation_id: str = "",
    max_attempts: int = 3,
    temperature: float = 0.7,
    twin_id: str | None = None,
) -> tuple[str, dict]:
    """
    Non-streaming Gemini call with retries + telemetry.
    Returns (reply_text, telemetry_dict). Empty reply on total failure.
    """
    import google.generativeai as genai
    from aria.config import settings
    from aria.ai.prompt_cache import get_cached_content

    genai.configure(api_key=settings.GOOGLE_API_KEY)

    cache_handle = get_cached_content(system_prompt, model) if len(system_prompt) > 2000 else None
    cached = cache_handle is not None

    start = time.monotonic()
    telemetry = {"model": model, "cached": cached, "attempts": 0, "error": None}
    text = ""

    for attempt in range(max_attempts):
        telemetry["attempts"] = attempt + 1
        try:
            if cache_handle is not None:
                gm = genai.GenerativeModel.from_cached_content(cached_content=cache_handle)
            else:
                gm = genai.GenerativeModel(model_name=model, system_instruction=system_prompt)

            chat = gm.start_chat(history=history or [])
            resp = await asyncio.to_thread(
                chat.send_message, user_message,
                generation_config={"temperature": temperature},
            )

            try:
                text = resp.text or ""
            except (ValueError, AttributeError):
                for cand in (resp.candidates or []):
                    for part in (cand.content.parts or []):
                        if getattr(part, "text", None):
                            text = part.text
                            break
                    if text:
                        break

            if text and text.strip():
                telemetry["history"] = list(chat.history)
                break
        except Exception as e:
            telemetry["error"] = str(e)[:200]
            logger.warning("Gemini attempt %d failed: %s", attempt + 1, e)
            if not _is_retryable(e):
                break
            await asyncio.sleep(0.5 * (attempt + 1))

    latency_ms = (time.monotonic() - start) * 1000
    in_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_message)
    out_tokens = estimate_tokens(text)

    metrics.record(CallRecord(
        conversation_id=conversation_id, model=model,
        input_tokens=in_tokens, output_tokens=out_tokens,
        latency_ms=latency_ms, cached=cached, error=telemetry["error"],
    ), twin_id=twin_id)

    telemetry["latency_ms"] = round(latency_ms, 1)
    telemetry["input_tokens"] = in_tokens
    telemetry["output_tokens"] = out_tokens
    return text.strip(), telemetry


async def stream_gemini(
    system_prompt: str,
    user_message: str,
    model: str = "gemini-2.5-flash",
    history: list | None = None,
    conversation_id: str = "",
    temperature: float = 0.7,
    twin_id: str | None = None,
):
    """
    Async generator — yields text chunks as they arrive from Gemini.
    Falls back to single chunk on error.
    """
    import google.generativeai as genai
    from aria.config import settings

    genai.configure(api_key=settings.GOOGLE_API_KEY)

    start = time.monotonic()
    full_text = ""
    error: str | None = None

    try:
        gm = genai.GenerativeModel(model_name=model, system_instruction=system_prompt)
        chat = gm.start_chat(history=history or [])

        def _iter():
            return chat.send_message(
                user_message, stream=True,
                generation_config={"temperature": temperature},
            )

        response = await asyncio.to_thread(_iter)

        for chunk in response:
            piece = ""
            try:
                piece = chunk.text or ""
            except (ValueError, AttributeError):
                for cand in (chunk.candidates or []):
                    for part in (cand.content.parts or []):
                        if getattr(part, "text", None):
                            piece += part.text
            if piece:
                full_text += piece
                yield piece
    except Exception as e:
        error = str(e)[:200]
        logger.warning("Stream failed: %s", e)
        if not full_text:
            yield ""

    latency_ms = (time.monotonic() - start) * 1000
    metrics.record(CallRecord(
        conversation_id=conversation_id, model=model,
        input_tokens=estimate_tokens(system_prompt) + estimate_tokens(user_message),
        output_tokens=estimate_tokens(full_text),
        latency_ms=latency_ms, cached=False, error=error,
    ), twin_id=twin_id)
