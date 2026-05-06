"""
aria.ai.safety — Prompt injection protection + input sanitization.

Detects common injection patterns before they reach the LLM.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("aria.ai.safety")

INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|messages?)",
    r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?)",
    r"you\s+are\s+(?:now|actually)\s+(?:a|an)\s+",
    r"forget\s+(?:everything|all|your\s+(?:instructions|rules|prompt))",
    r"new\s+(?:instructions?|prompt|role|persona)\s*[:=]",
    r"system\s*[:=]\s*",
    r"</?\s*(?:system|user|assistant|instruction)\s*>",
    r"(?:act|behave|pretend|roleplay)\s+as\s+(?:a|an|if)\s+",
    r"reveal\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|rules)",
    r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions?|rules)",
    r"print\s+(?:the\s+)?(?:above|previous|system)\s+(?:prompt|text|instructions?)",
    r"```\s*system",
    r"\[INST\]|\[/INST\]",
    r"<\|im_start\|>|<\|im_end\|>",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

MAX_MESSAGE_LENGTH = 4000


def detect_injection(message: str) -> tuple[bool, str | None]:
    """Return (is_suspicious, reason). Never blocks — just flags."""
    if not message:
        return False, None

    if len(message) > MAX_MESSAGE_LENGTH:
        return True, f"Message exceeds max length ({MAX_MESSAGE_LENGTH} chars)"

    for pattern in COMPILED_PATTERNS:
        m = pattern.search(message)
        if m:
            return True, f"Suspicious pattern: '{m.group(0)[:60]}'"

    repeats = re.findall(r"(.)\1{50,}", message)
    if repeats:
        return True, "Excessive character repetition (possible prompt flood)"

    return False, None


def sanitize_user_input(message: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate and neutralize obvious injection syntax."""
    if not message:
        return ""
    msg = message[:max_length]
    msg = re.sub(r"<\|(?:im_start|im_end|system|user|assistant)\|>", "", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\[/?INST\]", "", msg, flags=re.IGNORECASE)
    return msg.strip()


def wrap_user_input(message: str) -> str:
    """Wrap user input in clear delimiters so the LLM knows where it starts/ends."""
    safe = sanitize_user_input(message)
    return f"<user_message>\n{safe}\n</user_message>"
