"""
aria.ai.quota — Per-twin Gemini spend + call-count quota enforcement.

Two windows checked before every LLM call:
  - Daily cost budget   (ARIA_QUOTA_DAILY_USD, default $1.00/twin)
  - Daily call count    (ARIA_QUOTA_DAILY_CALLS, default 500/twin)
  - Burst call limit    (ARIA_QUOTA_BURST_CALLS_PER_MIN, default 60/twin)

Source of truth:
  - Daily spend/count    — llm_calls table (Postgres), 24h window
  - Burst count          — Redis sliding counter (1-min TTL)

If any limit exceeded, raises QuotaExceededError — chat_api returns 429.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("aria.ai.quota")

DAILY_USD = float(os.getenv("ARIA_QUOTA_DAILY_USD", "1.00"))
DAILY_CALLS = int(os.getenv("ARIA_QUOTA_DAILY_CALLS", "500"))
BURST_PER_MIN = int(os.getenv("ARIA_QUOTA_BURST_CALLS_PER_MIN", "60"))
ADMIN_EXEMPT = os.getenv("ARIA_QUOTA_ADMIN_EXEMPT", "true").lower() == "true"


class QuotaExceededError(Exception):
    def __init__(self, kind: str, current: float, limit: float, retry_after_s: int = 60):
        self.kind = kind
        self.current = current
        self.limit = limit
        self.retry_after_s = retry_after_s
        super().__init__(f"quota {kind} exceeded: {current:.4f}/{limit}")


@dataclass
class QuotaUsage:
    twin_id: str
    daily_cost_usd: float
    daily_calls: int
    burst_calls: int
    daily_cost_limit: float = DAILY_USD
    daily_calls_limit: int = DAILY_CALLS
    burst_limit: int = BURST_PER_MIN


def _get_db_engine():
    from aria.ai.metrics import _get_db_engine  # reuse
    return _get_db_engine()


async def _get_redis():
    """Reuse memory store's redis client (same ARIA-local Redis)."""
    try:
        from aria.ai.conversation_memory import memory
        backend = getattr(memory, "_backend", None)
        if backend is not None and hasattr(backend, "_redis"):
            return backend._redis
    except Exception:
        pass
    return None


def _fetch_daily(twin_id: str) -> tuple[float, int]:
    """Return (cost_usd_24h, calls_24h) from llm_calls. (0,0) if DB unavailable."""
    engine = _get_db_engine()
    if engine is None:
        return 0.0, 0
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd),0), COUNT(*) "
                    "FROM llm_calls "
                    "WHERE twin_id = :tid AND created_at >= NOW() - INTERVAL '24 hours'"
                ),
                {"tid": twin_id},
            ).fetchone()
            return float(row[0] or 0), int(row[1] or 0)
    except Exception as e:
        logger.debug("Daily-quota DB check failed: %s", e)
        return 0.0, 0


async def _incr_burst(twin_id: str) -> int:
    """Atomic INCR on a 60s-window key. Returns current count (post-incr)."""
    redis = await _get_redis()
    if redis is None:
        return 0
    try:
        import time
        minute = int(time.time()) // 60
        key = f"aria:quota:burst:{twin_id}:{minute}"
        val = await redis.incr(key)
        if val == 1:
            await redis.expire(key, 90)
        return int(val)
    except Exception as e:
        logger.debug("Burst-quota Redis check failed: %s", e)
        return 0


async def check_quota(twin_id: str, role: str = "member") -> QuotaUsage:
    """
    Raise QuotaExceededError if any limit hit. Returns current usage.
    Admin twins are exempt when ARIA_QUOTA_ADMIN_EXEMPT=true.
    """
    if ADMIN_EXEMPT and role == "admin":
        return QuotaUsage(twin_id=twin_id, daily_cost_usd=0, daily_calls=0, burst_calls=0)

    cost, calls = _fetch_daily(twin_id)
    if cost >= DAILY_USD:
        raise QuotaExceededError("daily_cost_usd", cost, DAILY_USD, retry_after_s=3600)
    if calls >= DAILY_CALLS:
        raise QuotaExceededError("daily_calls", calls, DAILY_CALLS, retry_after_s=3600)

    burst = await _incr_burst(twin_id)
    if burst > BURST_PER_MIN:
        raise QuotaExceededError("burst_calls_per_min", burst, BURST_PER_MIN, retry_after_s=60)

    return QuotaUsage(
        twin_id=twin_id,
        daily_cost_usd=cost,
        daily_calls=calls,
        burst_calls=burst,
    )
