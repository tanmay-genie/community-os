"""
orchestrator/adapters/dummy.py — DummyAdapter for testing and dev.
Simulates successful execution and compensation without side effects.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from orchestrator.adapters.base import AdapterResult, BaseAdapter, register_adapter

logger = logging.getLogger(__name__)


class DummyAdapter(BaseAdapter):
    """
    No-op adapter — logs the call and returns success.
    Use this to test the orchestration pipeline without real integrations.
    """
    name = "dummy"

    async def execute(self, params: dict[str, Any]) -> AdapterResult:
        await asyncio.sleep(0.05)  # simulate async I/O
        logger.info("[DummyAdapter] execute called with params=%s", params)
        return AdapterResult(
            success=True,
            output={"status": "ok", "adapter": "dummy", "params_received": params},
        )

    async def compensate(self, params: dict[str, Any]) -> AdapterResult:
        await asyncio.sleep(0.05)
        logger.info("[DummyAdapter] compensate called with params=%s", params)
        return AdapterResult(
            success=True,
            output={"status": "compensated", "adapter": "dummy"},
        )


# Auto-register on import
register_adapter(DummyAdapter())
