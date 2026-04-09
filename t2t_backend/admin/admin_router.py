"""
admin/admin_router.py — Admin endpoints.
Twin registration, audit queries, system health.
Protect these with an admin-only secret header in production.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from audit.audit import get_denied_events, get_events_for_message, get_events_for_twin
from auth.auth import register_twin
from auth.db import get_db
from config import settings

logger = logging.getLogger(__name__)
admin_router = APIRouter(prefix="/admin", tags=["Admin"])


def _require_admin(x_admin_secret: str = Header(...)) -> None:
    if x_admin_secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access denied")


# ── Twin Registration ─────────────────────────────────────────────────────────

class RegisterTwinRequest(BaseModel):
    twin_id: str
    org_id: str
    role: str
    clearance: str = "INTERNAL"
    human_name: str | None = None
    raw_api_key: str
    autonomy_level: str = "SEMI_AUTONOMOUS"
    budget_threshold_usd: float | None = None
    max_risk_level: str = "MEDIUM"
    signing_public_key: str | None = None


@admin_router.post("/twins/register")
async def admin_register_twin(
    req: RegisterTwinRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
) -> dict:
    from sqlalchemy import select
    from auth.models import TwinModel

    existing = await db.execute(
        select(TwinModel).where(TwinModel.twin_id == req.twin_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Twin '{req.twin_id}' already registered")

    twin = await register_twin(
        db=db,
        twin_id=req.twin_id,
        org_id=req.org_id,
        role=req.role,
        clearance=req.clearance,
        raw_api_key=req.raw_api_key,
        human_name=req.human_name,
        autonomy_level=req.autonomy_level,
        budget_threshold_usd=req.budget_threshold_usd,
        max_risk_level=req.max_risk_level,
        signing_public_key=req.signing_public_key,
    )
    return {
        "status": "registered",
        "twin_id": twin.twin_id,
        "org_id": twin.org_id,
        "role": twin.role,
    }


# ── Audit Queries ─────────────────────────────────────────────────────────────

@admin_router.get("/audit/message/{message_id}")
async def audit_by_message(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
) -> list[dict]:
    events = await get_events_for_message(db=db, message_id=message_id)
    return [
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "severity": e.severity,
            "twin_id": e.twin_id,
            "result": e.result,
            "reason": e.reason,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]


@admin_router.get("/audit/twin/{twin_id}")
async def audit_by_twin(
    twin_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
) -> list[dict]:
    events = await get_events_for_twin(db=db, twin_id=twin_id)
    return [
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "message_id": e.message_id,
            "result": e.result,
            "reason": e.reason,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]


@admin_router.get("/audit/denied/{org_id}")
async def audit_denied(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
) -> list[dict]:
    events = await get_denied_events(db=db, org_id=org_id)
    return [
        {
            "event_id": e.event_id,
            "twin_id": e.twin_id,
            "rule_id": e.rule_id,
            "reason": e.reason,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in events
    ]


# ── Contract Management ───────────────────────────────────────────────────────

class CreateContractRequest(BaseModel):
    org_a_id: str
    org_b_id: str
    redaction_profile: str = "CROSS_ORG_SAFE"
    scope_grants: str | None = None
    expires_at: str | None = None  # ISO format datetime


@admin_router.post("/contracts")
async def create_contract_endpoint(
    req: CreateContractRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
) -> dict:
    from policy.contracts import create_contract
    from datetime import datetime

    expires = None
    if req.expires_at:
        expires = datetime.fromisoformat(req.expires_at)

    contract = await create_contract(
        db=db,
        org_a_id=req.org_a_id,
        org_b_id=req.org_b_id,
        redaction_profile=req.redaction_profile,
        scope_grants=req.scope_grants,
        expires_at=expires,
    )
    await db.commit()
    return {
        "status": "created",
        "contract_id": contract.contract_id,
        "org_a_id": contract.org_a_id,
        "org_b_id": contract.org_b_id,
        "redaction_profile": contract.redaction_profile,
    }


@admin_router.get("/contracts/{org_id}")
async def list_contracts(
    org_id: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
) -> list[dict]:
    from policy.contracts import get_active_contracts

    contracts = await get_active_contracts(db=db, org_id=org_id)
    return [
        {
            "contract_id": c.contract_id,
            "org_a_id": c.org_a_id,
            "org_b_id": c.org_b_id,
            "status": c.status,
            "redaction_profile": c.redaction_profile,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        }
        for c in contracts
    ]
