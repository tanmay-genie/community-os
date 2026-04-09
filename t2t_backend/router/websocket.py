"""
router/websocket.py — WebSocket push for real-time message delivery.

Twins can connect via WebSocket to receive instant push notifications
instead of polling /inbox. The polling endpoint is kept as a fallback.

Authentication: The first message on the WebSocket must be a JSON object
containing {"token": "<api_key>"}. The connection is closed if auth fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

ws_router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages active WebSocket connections keyed by twin_id."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, twin_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            # Close any previous connection for this twin
            existing = self._connections.get(twin_id)
            if existing and existing.client_state == WebSocketState.CONNECTED:
                try:
                    await existing.close(code=1000, reason="Replaced by new connection")
                except Exception:
                    pass
            self._connections[twin_id] = websocket
        logger.info("WebSocket connected: twin=%s", twin_id)

    async def disconnect(self, twin_id: str) -> None:
        async with self._lock:
            self._connections.pop(twin_id, None)
        logger.info("WebSocket disconnected: twin=%s", twin_id)

    async def push_message(self, twin_id: str, data: dict[str, Any]) -> bool:
        """
        Push a JSON message to a connected twin.
        Returns True if push succeeded, False if twin is not connected.
        """
        async with self._lock:
            ws = self._connections.get(twin_id)
        if ws is None or ws.client_state != WebSocketState.CONNECTED:
            return False
        try:
            await ws.send_json(data)
            logger.debug("WebSocket push to twin=%s data=%s", twin_id, data)
            return True
        except Exception as exc:
            logger.warning("WebSocket push failed for twin=%s: %s", twin_id, exc)
            await self.disconnect(twin_id)
            return False

    @property
    def active_connections(self) -> int:
        return len(self._connections)


# Singleton
ws_manager = ConnectionManager()


@ws_router.websocket("/t2t/ws/{twin_id}")
async def websocket_endpoint(websocket: WebSocket, twin_id: str) -> None:
    """
    WebSocket endpoint for real-time message push.

    Protocol:
    1. Client connects to /t2t/ws/{twin_id}
    2. Client sends auth message: {"token": "<api_key>"}
    3. Server verifies token and twin_id match
    4. Server pushes messages as JSON objects
    5. Client can send heartbeats: {"ping": true}
    """
    await websocket.accept()

    from config import settings

    # ── Auth phase ────────────────────────────────────────────────────────
    try:
        auth_msg = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=settings.WS_AUTH_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, Exception):
        await websocket.close(code=4001, reason="Auth timeout")
        return

    token = auth_msg.get("token") if isinstance(auth_msg, dict) else None
    if not token:
        await websocket.close(code=4002, reason="Missing token")
        return

    # Verify the token
    from auth.auth import _hash_key
    from auth.db import AsyncSessionLocal
    from auth.models import TwinModel
    from sqlalchemy import select
    import bcrypt

    try:
        async with AsyncSessionLocal() as db:
            lookup_hash = _hash_key(token)
            result = await db.execute(
                select(TwinModel).where(TwinModel.api_key_lookup_hash == lookup_hash)
            )
            twin = result.scalar_one_or_none()

            if twin is None:
                # Fallback scan for legacy twins
                result = await db.execute(select(TwinModel))
                for t in result.scalars().all():
                    try:
                        if bcrypt.checkpw(token.encode(), t.api_key_hash.encode()):
                            twin = t
                            break
                    except Exception:
                        continue

            if twin is None or twin.twin_id != twin_id:
                await websocket.close(code=4003, reason="Invalid credentials")
                return
            if twin.status != "ACTIVE":
                await websocket.close(code=4004, reason="Twin not active")
                return
    except Exception as exc:
        logger.error("WebSocket auth DB error: %s", exc)
        await websocket.close(code=4005, reason="Auth error")
        return

    # ── Connected phase ───────────────────────────────────────────────────
    await ws_manager.connect(twin_id, websocket)
    await websocket.send_json({"type": "auth_ok", "twin_id": twin_id})

    try:
        while True:
            data = await websocket.receive_json()
            # Handle heartbeat
            if isinstance(data, dict) and data.get("ping"):
                await websocket.send_json({"pong": True})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error for twin=%s: %s", twin_id, exc)
    finally:
        await ws_manager.disconnect(twin_id)
