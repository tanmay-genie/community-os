"""
policy/contracts.py — Cross-Organization Contracts.

Twins from different organizations can only communicate when an active
contract exists. Each contract defines:
  - Which orgs are party to it
  - Allowed scope grants (intents, risk levels)
  - Redaction profile to apply
  - Expiration date
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from auth.db import Base

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrgContractModel(Base):
    __tablename__ = "org_contracts"

    contract_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_a_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    org_b_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    scope_grants: Mapped[str | None] = mapped_column(Text)  # JSON list of allowed intents
    redaction_profile: Mapped[str] = mapped_column(String(50), default="CROSS_ORG_SAFE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Contract {self.contract_id} {self.org_a_id}↔{self.org_b_id} status={self.status}>"


async def validate_cross_org_contract(
    db: AsyncSession,
    sender_org: str,
    recipient_org: str,
    contract_id: str | None = None,
) -> OrgContractModel | None:
    """
    Validate that an active, non-expired contract exists between two orgs.

    Args:
        db: Database session.
        sender_org: Sender's org_id.
        recipient_org: Recipient's org_id.
        contract_id: Optional specific contract to check.

    Returns:
        The valid contract, or None if no valid contract exists.
    """
    now = _utcnow()
    query = select(OrgContractModel).where(
        OrgContractModel.status == "ACTIVE",
        # Check both directions (contract is bidirectional)
        (
            (OrgContractModel.org_a_id == sender_org) & (OrgContractModel.org_b_id == recipient_org)
        ) | (
            (OrgContractModel.org_a_id == recipient_org) & (OrgContractModel.org_b_id == sender_org)
        ),
    )

    if contract_id:
        query = query.where(OrgContractModel.contract_id == contract_id)

    result = await db.execute(query)
    contracts = result.scalars().all()

    for contract in contracts:
        # Check expiration
        if contract.expires_at and contract.expires_at < now:
            logger.warning(
                "Contract %s expired at %s", contract.contract_id, contract.expires_at
            )
            continue
        return contract

    return None


async def create_contract(
    db: AsyncSession,
    org_a_id: str,
    org_b_id: str,
    redaction_profile: str = "CROSS_ORG_SAFE",
    scope_grants: str | None = None,
    expires_at: datetime | None = None,
) -> OrgContractModel:
    """Create a new cross-org contract."""
    contract = OrgContractModel(
        contract_id=str(uuid.uuid4()),
        org_a_id=org_a_id,
        org_b_id=org_b_id,
        redaction_profile=redaction_profile,
        scope_grants=scope_grants,
        expires_at=expires_at,
    )
    db.add(contract)
    await db.flush()
    logger.info("Contract created: %s (%s ↔ %s)", contract.contract_id, org_a_id, org_b_id)
    return contract


async def get_active_contracts(
    db: AsyncSession,
    org_id: str,
) -> list[OrgContractModel]:
    """Get all active contracts for an org."""
    result = await db.execute(
        select(OrgContractModel).where(
            OrgContractModel.status == "ACTIVE",
            (OrgContractModel.org_a_id == org_id) | (OrgContractModel.org_b_id == org_id),
        )
    )
    return result.scalars().all()
