"""aria.society.models — SQLAlchemy models for society persistence.

Tables: amenities, bookings, community_events, dues, community_notices, rsvps.

Moved from `t2t_backend/communityos/models.py` as part of the T2T extraction —
T2T no longer carries society-specific schema.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import (
    Boolean, Date, DateTime, Float, Integer, String, Text, Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from aria.society.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AmenityModel(Base):
    __tablename__ = "amenities"

    amenity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # ``name`` is the short type-like key used by the legacy chat flow
    # ("gym", "pool", "badminton") — kept for back-compat. Multiple instances
    # can share the same ``name`` (e.g. three gyms across blocks).
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # ``display_name`` is the human-facing label and SHOULD be unique per org
    # (e.g. "Greenfield Gym - Block A"). We do not enforce a DB constraint to
    # avoid breaking older rows, but the seed and admin flows treat it that way.
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Canonical type used by the new discovery API. Indexed because the
    # `find_amenities_by_type` flow filters on it on every call.
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="other", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # JSON-encoded list of feature strings. We use Text + json.loads/dumps in
    # the service layer so the schema works on both SQLite and Postgres
    # without depending on a JSONB column type.
    features: Mapped[str] = mapped_column(Text, default="[]")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    block: Mapped[str] = mapped_column(String(50), default="")
    floor: Mapped[str] = mapped_column(String(50), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    capacity_per_slot: Mapped[int] = mapped_column(Integer, default=10)
    slot_duration_mins: Mapped[int] = mapped_column(Integer, default=60)
    open_time: Mapped[time] = mapped_column(Time, default=time(6, 0))
    close_time: Mapped[time] = mapped_column(Time, default=time(22, 0))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<Amenity {self.display_name} type={self.type} org={self.org_id}>"


class BookingModel(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("amenity_id", "slot_date", "slot_start", "twin_id",
                         name="uq_booking_per_slot_per_twin"),
    )

    booking_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    amenity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False)
    twin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    slot_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    slot_start: Mapped[time] = mapped_column(Time, nullable=False)
    slot_end: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="CONFIRMED")
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Booking {self.booking_id[:8]} {self.amenity_id} {self.slot_date} {self.slot_start}>"


class CommunityEventModel(Base):
    __tablename__ = "community_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="")
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_time: Mapped[time] = mapped_column(Time, nullable=False)
    location: Mapped[str] = mapped_column(String(300), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=50)
    rsvp_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<CommunityEvent {self.title} org={self.org_id}>"


class DuesModel(Base):
    __tablename__ = "dues"

    due_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    twin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<Dues {self.type} {self.amount} twin={self.twin_id}>"


class CommunityNoticeModel(Base):
    __tablename__ = "community_notices"

    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), default="")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<CommunityNotice {self.title} org={self.org_id}>"


class RsvpModel(Base):
    __tablename__ = "rsvps"
    __table_args__ = (
        UniqueConstraint("event_id", "twin_id",
                         name="uq_rsvp_per_event_per_twin"),
    )

    rsvp_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    twin_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<Rsvp {self.rsvp_id[:8]} event={self.event_id[:8]}>"
