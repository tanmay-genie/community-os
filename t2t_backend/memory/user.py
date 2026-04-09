"""
memory/user.py — User (personal twin) memory updates.
memory/org.py  — Org-level shared memory updates.
memory/decision.py — Decision graph recording.

Phase 1: simple JSON file / Redis store.
Phase 2: upgrade to vector DB + graph DB.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ── User Memory ───────────────────────────────────────────────────────────────

async def update_user_memory(
    twin_id: str,
    event_type: str,
    details: dict[str, Any],
) -> None:
    """
    Update the personal memory for a twin.
    Stores what actions they've taken, preferences learned, etc.

    Phase 1: Redis hash.
    Phase 2: Vector store (semantic retrieval).
    """
    from redis_client import get_redis
    redis = await get_redis()
    key = f"memory:user:{twin_id}"
    entry = {
        "event_type": event_type,
        "details": details,
        "timestamp": datetime.utcnow().isoformat(),
    }
    # Append to a list (keep last 500 entries)
    await redis.lpush(key, json.dumps(entry))
    await redis.ltrim(key, 0, 499)
    await redis.expire(key, 86400 * 90)  # 90 day TTL
    logger.debug("User memory updated for twin=%s event=%s", twin_id, event_type)


async def get_user_memory(twin_id: str, limit: int = 20) -> list[dict]:
    from redis_client import get_redis
    redis = await get_redis()
    key = f"memory:user:{twin_id}"
    entries = await redis.lrange(key, 0, limit - 1)
    return [json.loads(e) for e in entries]
