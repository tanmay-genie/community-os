"""
aria.ai.metrics — LLM observability: latency, tokens, cost per conversation.

Two-tier: in-memory ring buffer (fast) + optional async Postgres persistence
(survives restarts, scrapable by SQL). DB writes are fire-and-forget so they
never block the chat path.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

logger = logging.getLogger("aria.ai.metrics")

_DB_ENABLED = os.getenv("ARIA_PERSIST_METRICS", "true").lower() == "true"
_db_engine = None
_db_lock = Lock()

GEMINI_PRICING = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
}


@dataclass
class CallRecord:
    conversation_id: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cached: bool = False
    error: str | None = None
    timestamp: float = field(default_factory=time.time)

    @property
    def cost_usd(self) -> float:
        pricing = GEMINI_PRICING.get(self.model, {"input": 0.1, "output": 0.3})
        return (self.input_tokens * pricing["input"] + self.output_tokens * pricing["output"]) / 1_000_000


def _get_db_engine():
    """Lazily create a sync SQLAlchemy engine. Returns None if unavailable."""
    global _db_engine
    if not _DB_ENABLED:
        return None
    with _db_lock:
        if _db_engine is not None:
            return _db_engine
        dsn = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        if not dsn:
            return None
        try:
            from sqlalchemy import create_engine
            _db_engine = create_engine(dsn, pool_pre_ping=True, pool_size=2, max_overflow=5)
            with _db_engine.connect() as c:
                c.exec_driver_sql("SELECT 1 FROM llm_calls LIMIT 1")
            logger.info("Metrics DB persistence active")
            return _db_engine
        except Exception as e:
            logger.warning("Metrics DB disabled: %s", e)
            _db_engine = None
            return None


def _persist_record(rec: "CallRecord", twin_id: Optional[str] = None) -> None:
    engine = _get_db_engine()
    if engine is None:
        return
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO llm_calls "
                    "(conversation_id, twin_id, model, input_tokens, output_tokens, "
                    "latency_ms, cost_usd, cached, error) "
                    "VALUES (:cid, :tid, :m, :it, :ot, :lat, :cost, :cached, :err)"
                ),
                {
                    "cid": rec.conversation_id,
                    "tid": twin_id,
                    "m": rec.model,
                    "it": rec.input_tokens,
                    "ot": rec.output_tokens,
                    "lat": rec.latency_ms,
                    "cost": rec.cost_usd,
                    "cached": rec.cached,
                    "err": rec.error,
                },
            )
    except Exception as e:
        logger.debug("Metrics DB write failed: %s", e)


class MetricsCollector:
    def __init__(self, max_records: int = 5000):
        self._records: deque[CallRecord] = deque(maxlen=max_records)
        self._by_conv: dict[str, list[CallRecord]] = defaultdict(list)
        self._lock = Lock()

    def record(self, rec: CallRecord, twin_id: Optional[str] = None) -> None:
        with self._lock:
            self._records.append(rec)
            self._by_conv[rec.conversation_id].append(rec)
            if len(self._by_conv[rec.conversation_id]) > 50:
                self._by_conv[rec.conversation_id] = self._by_conv[rec.conversation_id][-50:]
        logger.info(
            "llm_call conv=%s model=%s in=%d out=%d latency=%.0fms cached=%s cost=$%.6f err=%s",
            rec.conversation_id[:8], rec.model, rec.input_tokens, rec.output_tokens,
            rec.latency_ms, rec.cached, rec.cost_usd, rec.error or "-",
        )
        # Fire-and-forget DB persistence. Runs in the event loop's default executor
        # so it never blocks the calling coroutine.
        try:
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, _persist_record, rec, twin_id)
        except RuntimeError:
            # Not inside an event loop (e.g. tests, scripts) — persist synchronously
            _persist_record(rec, twin_id)
        try:
            from aria.obs.prom import update_llm_metric
            update_llm_metric(rec.model, rec.cached, rec.error, rec.latency_ms, rec.cost_usd)
        except Exception:
            pass

    def snapshot(self) -> dict:
        with self._lock:
            records = list(self._records)
        if not records:
            return {"total_calls": 0, "total_cost_usd": 0.0, "models": {}, "recent": []}

        by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "errors": 0, "cached_hits": 0})
        total_latency = 0.0
        total_cost = 0.0
        errors = 0

        for r in records:
            m = by_model[r.model]
            m["calls"] += 1
            m["input_tokens"] += r.input_tokens
            m["output_tokens"] += r.output_tokens
            m["cost_usd"] += r.cost_usd
            if r.error:
                m["errors"] += 1
                errors += 1
            if r.cached:
                m["cached_hits"] += 1
            total_latency += r.latency_ms
            total_cost += r.cost_usd

        return {
            "total_calls": len(records),
            "total_cost_usd": round(total_cost, 6),
            "avg_latency_ms": round(total_latency / len(records), 1),
            "error_rate": round(errors / len(records), 4),
            "models": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in by_model.items()},
            "recent": [
                {
                    "conv": r.conversation_id[:8], "model": r.model,
                    "tokens_in": r.input_tokens, "tokens_out": r.output_tokens,
                    "latency_ms": round(r.latency_ms, 1), "cached": r.cached,
                    "cost_usd": round(r.cost_usd, 6), "error": r.error,
                }
                for r in list(records)[-20:]
            ],
        }

    def conversation_summary(self, conv_id: str) -> dict:
        with self._lock:
            recs = list(self._by_conv.get(conv_id, []))
        if not recs:
            return {"conversation_id": conv_id, "calls": 0}
        return {
            "conversation_id": conv_id,
            "calls": len(recs),
            "total_tokens": sum(r.input_tokens + r.output_tokens for r in recs),
            "total_cost_usd": round(sum(r.cost_usd for r in recs), 6),
            "avg_latency_ms": round(sum(r.latency_ms for r in recs) / len(recs), 1),
            "models_used": list({r.model for r in recs}),
        }


metrics = MetricsCollector()


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars ≈ 1 token)."""
    return max(1, len(text) // 4)
