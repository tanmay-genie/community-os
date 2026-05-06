"""
aria/auth.py — Bearer token auth (HS256 JWT) + legacy API-key fallback.

Priority:
  1. Authorization: Bearer <jwt>  — verified against JWT_SECRET
  2. Legacy per-twin API keys in request body (deprecated, emits warning)

Production should always use the Bearer path.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import HTTPException, status

from aria.config import settings

logger = logging.getLogger("aria.auth")

TWIN_API_KEYS: dict[str, str] = {
    "tanmay_resident": os.getenv("TWIN_KEY_TANMAY", "tanmay-key-001"),
    "communityos_ops": os.getenv("TWIN_KEY_OPS", "ops-key-001"),
    "aria_assistant": os.getenv("TWIN_KEY_ARIA", "aria-key-001"),
}
ADMIN_TWIN_ID = "communityos_ops"
ADMIN_API_KEY = TWIN_API_KEYS[ADMIN_TWIN_ID]


@dataclass
class Principal:
    twin_id: str
    role: str  # "member" | "admin"
    org_id: str
    auth_method: str  # "bearer" | "api_key"


def issue_token(twin_id: str, role: str, org_id: str, expiry_hours: Optional[int] = None) -> str:
    """Issue an HS256 JWT for a twin. Used by the login endpoint."""
    now = int(time.time())
    exp = now + (expiry_hours or settings.JWT_EXPIRY_HOURS) * 3600
    payload = {
        "sub": twin_id,
        "role": role,
        "org_id": org_id,
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _verify_bearer(token: str) -> Principal:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER,
            options={"require": ["sub", "role", "org_id", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}")

    return Principal(
        twin_id=payload["sub"],
        role=payload["role"],
        org_id=payload["org_id"],
        auth_method="bearer",
    )


def _verify_api_key(twin_id: str, api_key: str, org_id: str) -> Principal:
    expected = TWIN_API_KEYS.get(twin_id)
    if not expected or expected != api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    role = "admin" if twin_id == ADMIN_TWIN_ID else "member"
    logger.warning("Legacy API-key auth used for twin=%s — migrate to Bearer tokens", twin_id)
    return Principal(twin_id=twin_id, role=role, org_id=org_id, auth_method="api_key")


def authenticate(
    authorization: Optional[str],
    twin_id: Optional[str] = None,
    api_key: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Principal:
    """
    Resolve a Principal from either Bearer header or legacy body-level api_key.
    Returns 401 if neither works.
    """
    if authorization and authorization.lower().startswith("bearer "):
        return _verify_bearer(authorization[7:].strip())

    is_prod = settings.APP_ENV.lower() in ("production", "prod", "staging")
    if is_prod:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")

    if twin_id and api_key and org_id:
        return _verify_api_key(twin_id, api_key, org_id)

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
