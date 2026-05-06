"""
aria.ai.prompt_cache — System prompt + society context caching.

Gemini 2.5 supports context caching (CachedContent API) for repeated system
prompts. We cache per-role system prompts so every conversation reuses the
same cached content block instead of re-sending 1-2K tokens each call.

Falls back to no-op if caching API is unavailable.
"""
from __future__ import annotations

import hashlib
import logging
import time
from threading import Lock

logger = logging.getLogger("aria.ai.prompt_cache")

CACHE_TTL_SECONDS = 3600
_cache: dict[str, dict] = {}
_lock = Lock()


def _key(content: str, model: str) -> str:
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"{model}:{h}"


def get_cached_content(content: str, model: str, display_name: str = "aria-system-prompt"):
    """
    Returns a Gemini CachedContent handle for the system prompt, or None if
    caching is unsupported. Creates the cache entry on first call.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        return None

    cache_key = _key(content, model)
    now = time.time()

    with _lock:
        entry = _cache.get(cache_key)
        if entry and (now - entry["created_at"]) < CACHE_TTL_SECONDS:
            return entry["handle"]

    try:
        caching = getattr(genai, "caching", None)
        if caching is None:
            return None
        handle = caching.CachedContent.create(
            model=model,
            display_name=display_name,
            system_instruction=content,
            ttl=f"{CACHE_TTL_SECONDS}s",
        )
        with _lock:
            _cache[cache_key] = {"handle": handle, "created_at": now}
        logger.info("Gemini cached_content created: %s (%d chars)", cache_key, len(content))
        return handle
    except Exception as e:
        logger.info("Prompt caching unavailable (%s) — continuing without cache", e)
        return None
