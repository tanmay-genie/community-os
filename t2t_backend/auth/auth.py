"""
auth/auth.py — FastAPI dependency for API key authentication.

Every endpoint that handles T2T messages must use `verify_twin` as a dependency.
It validates the Bearer token, looks up the twin, checks status, and returns a
TwinContext object used by Policy, Router, and Orchestrator.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import bcrypt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from audit.audit import log_event
from audit.taxonomy import EventType
from auth.db import get_db
from auth.models import TwinModel
from schemas.intents import ClearanceLevel, TwinStatus

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()

CLEARANCE_RANK: dict[str, int] = {
    ClearanceLevel.PUBLIC.value: 0,
    ClearanceLevel.INTERNAL.value: 1,
    ClearanceLevel.CONFIDENTIAL.value: 2,
    ClearanceLevel.SECRET.value: 3,
}


@dataclass(frozen=True)
class TwinContext:
    """
    Verified identity context returned after successful authentication.
    Passed through Policy, Router, and Orchestrator.
    """
    twin_id: str
    org_id: str
    role: str
    clearance: str
    autonomy_level: str
    status: str
    budget_threshold_usd: float | None
    max_risk_level: str
    signing_public_key: str | None

    @property
    def clearance_rank(self) -> int:
        return CLEARANCE_RANK.get(self.clearance, 0)

    def meets_clearance(self, required: str) -> bool:
        return self.clearance_rank >= CLEARANCE_RANK.get(required, 0)


def _hash_key(raw_key: str) -> str:
    """SHA-256 fast hash for indexed lookup."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def verify_twin(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> TwinContext:
    """
    FastAPI dependency.
    1. Extracts Bearer token from Authorization header.
    2. Computes SHA-256 lookup hash for O(1) indexed DB query.
    3. Verifies with bcrypt (timing-safe) against the single matched twin.
    4. Validates status (active / suspended / revoked).
    5. Returns TwinContext consumed by all downstream modules.
    """
    raw_key = credentials.credentials
    lookup_hash = _hash_key(raw_key)

    # ── O(1) indexed lookup via SHA-256 hash ──────────────────────────────
    result = await db.execute(
        select(TwinModel).where(TwinModel.api_key_lookup_hash == lookup_hash)
    )
    twin = result.scalar_one_or_none()

    # ── Fallback: legacy twins without lookup hash (scan + upgrade) ───────
    if twin is None:
        result = await db.execute(select(TwinModel))
        all_twins = result.scalars().all()
        for t in all_twins:
            try:
                if bcrypt.checkpw(raw_key.encode(), t.api_key_hash.encode()):
                    twin = t
                    # Backfill the lookup hash for future fast lookups
                    t.api_key_lookup_hash = lookup_hash
                    await db.flush()
                    break
            except Exception:
                continue

    if twin is None:
        logger.warning("Authentication failed — API key not found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Bcrypt verification for indexed path ──────────────────────────────
    if twin.api_key_lookup_hash == lookup_hash:
        try:
            if not bcrypt.checkpw(raw_key.encode(), twin.api_key_hash.encode()):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # ── Status check ──────────────────────────────────────────────────────
    if twin.status == TwinStatus.REVOKED.value:
        await log_event(
            db=db,
            event_type=EventType.SID_REVOKED,
            twin_id=twin.twin_id,
            org_id=twin.org_id,
            result="BLOCKED",
            reason="Twin API key is revoked",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Twin identity has been revoked",
        )

    if twin.status == TwinStatus.SUSPENDED.value:
        await log_event(
            db=db,
            event_type=EventType.TWIN_SUSPENDED,
            twin_id=twin.twin_id,
            org_id=twin.org_id,
            result="BLOCKED",
            reason="Twin is suspended",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Twin account is suspended",
        )

    logger.info("Twin authenticated: %s (org=%s, role=%s)", twin.twin_id, twin.org_id, twin.role)

    return TwinContext(
        twin_id=twin.twin_id,
        org_id=twin.org_id,
        role=twin.role,
        clearance=twin.clearance,
        autonomy_level=twin.autonomy_level,
        status=twin.status,
        budget_threshold_usd=twin.budget_threshold_usd,
        max_risk_level=twin.max_risk_level,
        signing_public_key=twin.signing_public_key,
    )


# ── Twin registration helper (admin use) ──────────────────────────────────────

async def register_twin(
    db: AsyncSession,
    twin_id: str,
    org_id: str,
    role: str,
    clearance: str,
    raw_api_key: str,
    human_name: str | None = None,
    autonomy_level: str = "SEMI_AUTONOMOUS",
    budget_threshold_usd: float | None = None,
    max_risk_level: str = "MEDIUM",
    signing_public_key: str | None = None,
) -> TwinModel:
    """Creates and persists a new twin with a hashed API key."""
    hashed = bcrypt.hashpw(raw_api_key.encode(), bcrypt.gensalt()).decode()
    lookup_hash = _hash_key(raw_api_key)
    twin = TwinModel(
        twin_id=twin_id,
        org_id=org_id,
        role=role,
        clearance=clearance,
        api_key_hash=hashed,
        api_key_lookup_hash=lookup_hash,
        human_name=human_name,
        autonomy_level=autonomy_level,
        budget_threshold_usd=budget_threshold_usd,
        max_risk_level=max_risk_level,
        signing_public_key=signing_public_key,
    )
    db.add(twin)
    await db.flush()
    logger.info("Twin registered: %s", twin_id)
    return twin
