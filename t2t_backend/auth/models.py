"""
auth/models.py — SQLAlchemy ORM model for the twins table.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from auth.db import Base
from schemas.intents import AutonomyLevel, ClearanceLevel, TwinStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TwinModel(Base):
    __tablename__ = "twins"

    twin_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    human_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    clearance: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ClearanceLevel.INTERNAL.value
    )
    autonomy_level: Mapped[str] = mapped_column(
        String(50), nullable=False, default=AutonomyLevel.SEMI_AUTONOMOUS.value
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TwinStatus.ACTIVE.value, index=True
    )
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # Fast O(1) lookup hash (SHA-256 of raw key) — indexed for quick auth
    api_key_lookup_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True
    )

    # Ed25519 public key (base64 encoded) — for message signature verification
    signing_public_key: Mapped[str | None] = mapped_column(String(64))

    # Budget / threshold controls
    budget_threshold_usd: Mapped[float | None] = mapped_column()
    max_risk_level: Mapped[str] = mapped_column(String(20), default="MEDIUM")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Twin {self.twin_id} org={self.org_id} role={self.role}>"
