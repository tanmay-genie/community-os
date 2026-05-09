"""aria.ai.conversation_state — Multi-turn pending-action state machine.

When ARIA needs more info from the user before completing an action (which
gym? what time? confirm?), it parks the partial intent in this store. The
next user message is then evaluated against the parked state FIRST so we
can resume the original intent instead of re-classifying.

Concrete flows this fixes:
  - "book gym at 7" → 3 gyms exist → set pending(intent=book_amenity,
    awaiting=amenity_choice, options=[T1, T2, T3], args={time:"19:00"})
    → user replies "Tower 1" → resume book_amenity with the chosen id
  - ARIA: "I can show notices instead, want me to?" → set pending(
    intent=get_notices, awaiting=yes_no) → user "yes" → run get_notices
  - "pay rent" → no amount given → set pending(intent=pay_dues,
    awaiting=amount) → user "$480" → resume

State expires after PENDING_TTL_SECONDS so abandoned conversations don't
leak. Stored per conversation_id (not twin) so two windows of the same
twin don't trample each other.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger("aria.ai.conversation_state")

PENDING_TTL_SECONDS = 5 * 60   # 5 minutes


@dataclass
class PendingAction:
    intent: str                              # e.g. "book_amenity"
    args: dict                               # slot values already collected
    awaiting: str                            # "yes_no" | "amenity_choice" | "time_slot" | "amount" | "free_text"
    options: list[dict] = field(default_factory=list)  # for choice flows
    prompt_text: str = ""                    # what ARIA asked the user
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > PENDING_TTL_SECONDS


# ── Affirmative / negative detection ───────────────────────────────────


_AFFIRMATIVE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|please|do it|go ahead|"
    r"absolutely|of course|please do|sounds good|that works|fine|alright|"
    r"i want to|i'd like to|i would like|i want|please show|show me)\b",
    flags=re.IGNORECASE,
)
_NEGATIVE = re.compile(
    r"^\s*(?:no|nope|nah|not now|not really|cancel|skip|never mind|nevermind|"
    r"don't|do not|leave it|forget it)\b",
    flags=re.IGNORECASE,
)


def is_affirmative(message: str) -> bool:
    return bool(_AFFIRMATIVE.match(message or ""))


def is_negative(message: str) -> bool:
    return bool(_NEGATIVE.match(message or ""))


# ── Amenity-choice matcher ─────────────────────────────────────────────


_ORDINAL_RE = re.compile(
    r"^\s*(?:the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|"
    r"option\s*(\d)|number\s*(\d)|#\s*(\d)|(\d))\b",
    flags=re.IGNORECASE,
)
_ORDINAL_MAP = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
}


def match_choice_from_message(message: str, options: list[dict]) -> dict | None:
    """Try to identify which option the user picked.

    Match priority:
      1. Display name substring ("Tower 1 gym" → matches the option whose
         display_name contains that)
      2. Block / floor substring ("Tower 1" or "Block C")
      3. Ordinal ("first", "second", "1", "#2", "option 3")
    """
    if not options:
        return None
    msg = (message or "").strip().lower()
    if not msg:
        return None

    # 1. Display name substring (longest match wins)
    best = None
    best_len = 0
    for opt in options:
        dn = (opt.get("display_name") or "").lower()
        if dn and dn in msg:
            if len(dn) > best_len:
                best = opt
                best_len = len(dn)
    if best:
        return best

    # 2. Block (or floor) substring — pick the option whose block/floor
    #    appears in the message AND no other option's does (avoid ambiguity)
    block_hits: list[dict] = []
    for opt in options:
        block = (opt.get("block") or "").lower()
        if block and block in msg:
            block_hits.append(opt)
    if len(block_hits) == 1:
        return block_hits[0]

    # 3. Ordinal — "first" / "1st" / "1" / "option 1"
    m = _ORDINAL_RE.match(msg)
    if m:
        for grp in (1, 2, 3, 4, 5):
            try:
                token = m.group(grp)
            except IndexError:
                token = None
            if not token:
                continue
            if token in _ORDINAL_MAP:
                idx = _ORDINAL_MAP[token]
            else:
                try:
                    idx = int(token) - 1
                except ValueError:
                    continue
            if 0 <= idx < len(options):
                return options[idx]
    return None


# ── Store ──────────────────────────────────────────────────────────────


class PendingActionStore:
    """In-process pending-action store keyed by conversation_id."""

    def __init__(self):
        self._store: dict[str, PendingAction] = {}
        self._lock = Lock()

    def set(self, conv_id: str, action: PendingAction) -> None:
        if not conv_id:
            return
        with self._lock:
            self._store[conv_id] = action
        logger.debug(
            "pending_action set: conv=%s intent=%s awaiting=%s opts=%d",
            conv_id, action.intent, action.awaiting, len(action.options),
        )

    def get(self, conv_id: str) -> PendingAction | None:
        if not conv_id:
            return None
        with self._lock:
            pa = self._store.get(conv_id)
            if pa and pa.is_expired():
                del self._store[conv_id]
                return None
            return pa

    def clear(self, conv_id: str) -> None:
        if not conv_id:
            return
        with self._lock:
            self._store.pop(conv_id, None)

    def __contains__(self, conv_id: str) -> bool:
        return self.get(conv_id) is not None


# Module-level singleton (chat_api wires this into the request flow).
PENDING = PendingActionStore()


# ── Resume API used by chat_api ────────────────────────────────────────


@dataclass
class ResumeResult:
    """What to do with the current message based on parked state."""
    resumed_intent: str | None = None
    resumed_args: dict = field(default_factory=dict)
    cleared: bool = False
    reason: str = ""


def try_resume(conv_id: str, message: str) -> ResumeResult | None:
    """Inspect the message against the parked action.

    Returns a ResumeResult with a concrete intent/args to execute, OR
    a "cleared" result if the user declined / aborted, OR None if there
    is nothing parked / the message doesn't fit the parked state.
    """
    pa = PENDING.get(conv_id)
    if not pa:
        return None

    if is_negative(message):
        PENDING.clear(conv_id)
        return ResumeResult(cleared=True, reason="user_declined")

    if pa.awaiting == "yes_no":
        if is_affirmative(message):
            PENDING.clear(conv_id)
            return ResumeResult(
                resumed_intent=pa.intent,
                resumed_args=dict(pa.args),
                reason="yes_no_affirmed",
            )
        return None  # let normal classifier handle it

    if pa.awaiting == "amenity_choice":
        chosen = match_choice_from_message(message, pa.options)
        if chosen:
            args = dict(pa.args)
            if chosen.get("amenity_id"):
                args["amenity_id"] = chosen["amenity_id"]
            args["amenity_name"] = chosen.get("display_name", args.get("amenity_name", ""))
            PENDING.clear(conv_id)
            return ResumeResult(
                resumed_intent=pa.intent,
                resumed_args=args,
                reason="amenity_chosen",
            )
        return None

    if pa.awaiting == "amount":
        m = re.search(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", message)
        if m:
            try:
                amount = float(m.group(1).replace(",", ""))
                args = dict(pa.args)
                args["amount"] = amount
                PENDING.clear(conv_id)
                return ResumeResult(
                    resumed_intent=pa.intent,
                    resumed_args=args,
                    reason="amount_filled",
                )
            except ValueError:
                pass
        return None

    if pa.awaiting == "time_slot":
        # Match "7pm", "19:00", "8 am" etc.
        m = re.search(r"\b(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)?\b", message, flags=re.IGNORECASE)
        if m:
            args = dict(pa.args)
            args["time_slot"] = m.group(0)
            PENDING.clear(conv_id)
            return ResumeResult(
                resumed_intent=pa.intent,
                resumed_args=args,
                reason="time_filled",
            )
        return None

    return None


def park_disambiguation(conv_id: str, intent: str, args: dict, options: list[dict], prompt: str = "") -> None:
    """Helper used by tool dispatchers when a tool returns disambiguation."""
    PENDING.set(conv_id, PendingAction(
        intent=intent,
        args=args,
        awaiting="amenity_choice",
        options=options,
        prompt_text=prompt,
    ))


def park_yes_no(conv_id: str, intent: str, args: dict, prompt: str = "") -> None:
    """Helper used when ARIA offers an alternative action."""
    PENDING.set(conv_id, PendingAction(
        intent=intent,
        args=args,
        awaiting="yes_no",
        prompt_text=prompt,
    ))


def park_amount(conv_id: str, intent: str, args: dict, prompt: str = "") -> None:
    PENDING.set(conv_id, PendingAction(
        intent=intent,
        args=args,
        awaiting="amount",
        prompt_text=prompt,
    ))
