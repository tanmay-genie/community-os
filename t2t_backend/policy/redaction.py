"""
policy/redaction.py — Payload redaction for cross-organization messages.

When twins from different orgs communicate, the message payload is
redacted according to the contract's redaction profile before delivery.

Profiles:
  INTERNAL_FULL     — No redaction (same org)
  CROSS_ORG_SAFE    — Strip PII fields, keep business data
  REGULATED_MINIMAL — Strip everything except intent and metadata
"""
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fields to strip in CROSS_ORG_SAFE mode
PII_FIELDS = {
    "email", "phone", "address", "ssn", "social_security",
    "date_of_birth", "dob", "passport", "national_id",
    "credit_card", "bank_account", "salary", "compensation",
    "ip_address", "device_id", "location", "coordinates",
    "personal_notes", "health_data", "biometric",
}

# Fields to keep in REGULATED_MINIMAL mode
MINIMAL_ALLOWED_FIELDS = {
    "intent_type", "intent_name", "status", "action",
    "type", "name", "result", "timestamp", "version",
}


def apply_redaction(
    payload: dict[str, Any],
    redaction_profile: str,
) -> dict[str, Any]:
    """
    Apply a redaction profile to a message payload.

    Args:
        payload: The original payload dict.
        redaction_profile: One of INTERNAL_FULL, CROSS_ORG_SAFE, REGULATED_MINIMAL.

    Returns:
        A new dict with redacted content. Never mutates the original.
    """
    if redaction_profile == "INTERNAL_FULL":
        return payload  # No redaction needed

    if redaction_profile == "CROSS_ORG_SAFE":
        return _redact_pii(payload)

    if redaction_profile == "REGULATED_MINIMAL":
        return _redact_minimal(payload)

    # Unknown profile — default to safe
    logger.warning("Unknown redaction profile '%s', defaulting to CROSS_ORG_SAFE", redaction_profile)
    return _redact_pii(payload)


def _redact_pii(payload: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively strip PII fields from payload."""
    if depth > 10:
        return {"__redacted__": "max_depth_exceeded"}

    result = {}
    for key, value in payload.items():
        key_lower = key.lower()
        if key_lower in PII_FIELDS:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = _redact_pii(value, depth + 1)
        elif isinstance(value, list):
            result[key] = [
                _redact_pii(item, depth + 1) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _redact_minimal(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip everything except whitelisted metadata fields."""
    result = {}
    for key, value in payload.items():
        if key.lower() in MINIMAL_ALLOWED_FIELDS:
            result[key] = value
        else:
            result[key] = "[REDACTED]"
    result["__redaction_profile__"] = "REGULATED_MINIMAL"
    return result
