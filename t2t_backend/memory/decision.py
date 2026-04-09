"""memory/decision.py — Decision graph — records what was decided, by whom, and why."""
from __future__ import annotations
import json, logging, uuid
from datetime import datetime
from typing import Any
logger = logging.getLogger(__name__)

async def record_decision(
    message_id: str,
    decided_by: str,
    intent_type: str,
    intent_name: str | None,
    workflow_id: str,
    outcome: str,
    extra: dict[str, Any] | None = None,
) -> None:
    from redis_client import get_redis
    redis = await get_redis()
    decision = {
        "decision_id": str(uuid.uuid4()),
        "message_id": message_id,
        "decided_by": decided_by,
        "intent_type": intent_type,
        "intent_name": intent_name,
        "workflow_id": workflow_id,
        "outcome": outcome,
        "extra": extra or {},
        "timestamp": datetime.utcnow().isoformat(),
    }
    key = f"memory:decisions:{decided_by}"
    await redis.lpush(key, json.dumps(decision))
    await redis.ltrim(key, 0, 999)
    await redis.expire(key, 86400 * 365)
    logger.debug("Decision recorded by=%s outcome=%s", decided_by, outcome)

async def get_decisions(twin_id: str, limit: int = 50) -> list[dict]:
    from redis_client import get_redis
    redis = await get_redis()
    entries = await redis.lrange(f"memory:decisions:{twin_id}", 0, limit - 1)
    return [json.loads(e) for e in entries]
