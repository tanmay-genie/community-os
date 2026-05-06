"""
aria.ai.conversation_memory — Long-term multi-turn memory with summarization.

Persistence:
  - Redis when REDIS_URL is reachable (survives restarts + works horizontally).
  - In-process fallback when Redis is unavailable (single-worker dev only).

The MemoryStore interface is unchanged: chat_api.py never needs to know which
backend is in use.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Optional

logger = logging.getLogger("aria.ai.conversation_memory")

MAX_TURNS_BEFORE_SUMMARIZE = 12
RECENT_TURNS_TO_KEEP = 6
CONV_TTL_SECONDS = 7 * 24 * 3600     # 7 days
USER_TTL_SECONDS = 90 * 24 * 3600    # 90 days
_REDIS_PREFIX = "aria:mem"


@dataclass
class Turn:
    role: str
    message: str
    intent: Optional[str] = None
    action_taken: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationState:
    conversation_id: str
    twin_id: str
    turns: deque = field(default_factory=lambda: deque(maxlen=50))
    summary: str = ""
    pending_booking: Optional[dict] = None
    last_intent: Optional[str] = None
    last_action: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "twin_id": self.twin_id,
            "turns": [asdict(t) for t in self.turns],
            "summary": self.summary,
            "pending_booking": self.pending_booking,
            "last_intent": self.last_intent,
            "last_action": self.last_action,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationState":
        turns = deque((Turn(**t) for t in data.get("turns", [])), maxlen=50)
        return cls(
            conversation_id=data["conversation_id"],
            twin_id=data["twin_id"],
            turns=turns,
            summary=data.get("summary", ""),
            pending_booking=data.get("pending_booking"),
            last_intent=data.get("last_intent"),
            last_action=data.get("last_action"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class UserProfile:
    twin_id: str
    facts: list[str] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    recent_actions: deque = field(default_factory=lambda: deque(maxlen=20))
    frustration_count: int = 0
    last_seen: float = field(default_factory=time.time)

    def record_action(self, intent: str, args: dict) -> None:
        self.recent_actions.append({"intent": intent, "args": args, "ts": time.time()})
        self.last_seen = time.time()

    def to_dict(self) -> dict:
        return {
            "twin_id": self.twin_id,
            "facts": list(self.facts),
            "preferences": dict(self.preferences),
            "recent_actions": list(self.recent_actions),
            "frustration_count": self.frustration_count,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        p = cls(twin_id=data["twin_id"])
        p.facts = list(data.get("facts", []))
        p.preferences = dict(data.get("preferences", {}))
        p.recent_actions = deque(data.get("recent_actions", []), maxlen=20)
        p.frustration_count = int(data.get("frustration_count", 0))
        p.last_seen = float(data.get("last_seen", time.time()))
        return p


class _RedisBackend:
    """Best-effort Redis persistence. Any failure degrades to in-memory."""

    def __init__(self, url: str):
        import redis  # noqa: F401  (sync client; operations are fast)
        from redis import Redis
        self._client = Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)
        self._client.ping()  # fail fast if unreachable

    def load_conv(self, conv_id: str) -> Optional[dict]:
        try:
            raw = self._client.get(f"{_REDIS_PREFIX}:conv:{conv_id}")
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug("redis load_conv miss: %s", e)
            return None

    def save_conv(self, conv_id: str, data: dict) -> None:
        try:
            self._client.set(f"{_REDIS_PREFIX}:conv:{conv_id}", json.dumps(data), ex=CONV_TTL_SECONDS)
        except Exception as e:
            logger.debug("redis save_conv failed: %s", e)

    def load_user(self, twin_id: str) -> Optional[dict]:
        try:
            raw = self._client.get(f"{_REDIS_PREFIX}:user:{twin_id}")
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug("redis load_user miss: %s", e)
            return None

    def save_user(self, twin_id: str, data: dict) -> None:
        try:
            self._client.set(f"{_REDIS_PREFIX}:user:{twin_id}", json.dumps(data), ex=USER_TTL_SECONDS)
        except Exception as e:
            logger.debug("redis save_user failed: %s", e)


class MemoryStore:
    def __init__(self):
        self._convs: dict[str, ConversationState] = {}
        self._users: dict[str, UserProfile] = {}
        self._lock = Lock()
        self._redis: Optional[_RedisBackend] = None
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            self._redis = _RedisBackend(url)
            logger.info("Conversation memory: Redis backend active (%s)", url)
        except Exception as e:
            logger.warning("Conversation memory: Redis unavailable, using in-memory (%s)", e)

    def get_or_create_conversation(self, conv_id: str, twin_id: str) -> ConversationState:
        with self._lock:
            if conv_id in self._convs:
                return self._convs[conv_id]
        if self._redis:
            data = self._redis.load_conv(conv_id)
            if data:
                conv = ConversationState.from_dict(data)
                with self._lock:
                    self._convs[conv_id] = conv
                return conv
        conv = ConversationState(conversation_id=conv_id, twin_id=twin_id)
        with self._lock:
            self._convs[conv_id] = conv
        return conv

    def get_or_create_user(self, twin_id: str) -> UserProfile:
        with self._lock:
            if twin_id in self._users:
                return self._users[twin_id]
        if self._redis:
            data = self._redis.load_user(twin_id)
            if data:
                user = UserProfile.from_dict(data)
                with self._lock:
                    self._users[twin_id] = user
                return user
        user = UserProfile(twin_id=twin_id)
        with self._lock:
            self._users[twin_id] = user
        return user

    def add_turn(self, conv_id: str, twin_id: str, role: str, message: str,
                 intent: Optional[str] = None, action: Optional[str] = None) -> ConversationState:
        conv = self.get_or_create_conversation(conv_id, twin_id)
        with self._lock:
            conv.turns.append(Turn(role=role, message=message, intent=intent, action_taken=action))
            if intent:
                conv.last_intent = intent
            if action:
                conv.last_action = action
        if self._redis:
            self._redis.save_conv(conv_id, conv.to_dict())
        return conv

    def persist_user(self, twin_id: str) -> None:
        """Call after mutating a UserProfile so Redis sees the change."""
        user = self._users.get(twin_id)
        if user and self._redis:
            self._redis.save_user(twin_id, user.to_dict())

    def needs_summarization(self, conv_id: str) -> bool:
        conv = self._convs.get(conv_id)
        return bool(conv and len(conv.turns) > MAX_TURNS_BEFORE_SUMMARIZE)

    def compress(self, conv_id: str, summary_text: str) -> None:
        conv = self._convs.get(conv_id)
        if not conv:
            return
        with self._lock:
            kept = list(conv.turns)[-RECENT_TURNS_TO_KEEP:]
            conv.turns = deque(kept, maxlen=50)
            prefix = f"{conv.summary}\n\n" if conv.summary else ""
            conv.summary = f"{prefix}{summary_text}".strip()
        if self._redis:
            self._redis.save_conv(conv_id, conv.to_dict())

    def context_snapshot(self, conv_id: str, twin_id: str) -> str:
        conv = self._convs.get(conv_id)
        user = self._users.get(twin_id)
        parts: list[str] = []
        if user:
            if user.facts:
                parts.append("User facts: " + "; ".join(user.facts[-5:]))
            if user.preferences:
                pref_str = ", ".join(f"{k}={v}" for k, v in list(user.preferences.items())[:5])
                parts.append(f"User preferences: {pref_str}")
            if user.recent_actions:
                recents = list(user.recent_actions)[-3:]
                parts.append("Recent actions: " + ", ".join(a["intent"] for a in recents))
            if user.frustration_count >= 2:
                parts.append(
                    f"NOTE: User shown frustration {user.frustration_count} times this session. "
                    "Be extra empathetic."
                )
        if conv and conv.summary:
            parts.append(f"Earlier conversation summary: {conv.summary}")
        if conv and conv.last_intent:
            parts.append(f"Last action: {conv.last_action or conv.last_intent}")
        return "\n".join(parts)


memory = MemoryStore()


def build_summarization_prompt(turns: list[Turn]) -> str:
    lines = [
        "Summarize this conversation in 2-3 sentences, preserving: user preferences, "
        "any pending tasks, and key decisions. Be concise.",
        "",
    ]
    for t in turns[:MAX_TURNS_BEFORE_SUMMARIZE]:
        lines.append(f"{t.role}: {t.message[:200]}")
    return "\n".join(lines)
