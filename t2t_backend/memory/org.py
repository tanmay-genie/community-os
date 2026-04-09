"""memory/org.py — Org-level shared memory."""
from __future__ import annotations
import json, logging
from datetime import datetime
from typing import Any
logger = logging.getLogger(__name__)

async def update_org_memory(org_id: str, event_type: str, details: dict[str, Any]) -> None:
    from redis_client import get_redis
    redis = await get_redis()
    key = f"memory:org:{org_id}"
    entry = {"event_type": event_type, "details": details, "timestamp": datetime.utcnow().isoformat()}
    await redis.lpush(key, json.dumps(entry))
    await redis.ltrim(key, 0, 999)
    await redis.expire(key, 86400 * 180)
    logger.debug("Org memory updated org=%s event=%s", org_id, event_type)

async def get_org_memory(org_id: str, limit: int = 50) -> list[dict]:
    from redis_client import get_redis
    redis = await get_redis()
    entries = await redis.lrange(f"memory:org:{org_id}", 0, limit - 1)
    return [json.loads(e) for e in entries]
