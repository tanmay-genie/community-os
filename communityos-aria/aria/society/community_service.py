"""aria.society.community_service — Events, Dues, Notices business logic.

Pure async functions — no FastAPI dependencies.

Moved from `t2t_backend/communityos/community_service.py` as part of the T2T
extraction.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aria.society.models import (
    CommunityEventModel,
    CommunityNoticeModel,
    DuesModel,
    RsvpModel,
)

logger = logging.getLogger(__name__)


async def get_events(db: AsyncSession, org_id: str, target_date: date) -> list[dict]:
    """Return active events for a given org and date."""
    result = await db.execute(
        select(CommunityEventModel).where(
            CommunityEventModel.org_id == org_id,
            CommunityEventModel.event_date == target_date,
            CommunityEventModel.active == True,  # noqa: E712
        )
    )
    return [
        {
            "event_id": e.event_id,
            "title": e.title,
            "description": e.description,
            "date": e.event_date.isoformat(),
            "time": e.event_time.strftime("%H:%M"),
            "location": e.location,
            "capacity": e.capacity,
            "rsvp_count": e.rsvp_count,
        }
        for e in result.scalars().all()
    ]


async def rsvp_event(
    db: AsyncSession, org_id: str, event_id: str, twin_id: str,
) -> dict:
    """Create an RSVP for an event. Prevents duplicates."""
    ev_result = await db.execute(
        select(CommunityEventModel).where(
            CommunityEventModel.event_id == event_id,
            CommunityEventModel.org_id == org_id,
            CommunityEventModel.active == True,  # noqa: E712
        )
    )
    event = ev_result.scalars().first()
    if not event:
        return {"success": False, "error": "Event not found"}

    existing = await db.execute(
        select(RsvpModel).where(
            RsvpModel.event_id == event_id,
            RsvpModel.twin_id == twin_id,
        )
    )
    if existing.scalars().first():
        return {"success": False, "error": "You have already RSVP'd to this event"}

    if event.rsvp_count >= event.capacity:
        return {"success": False, "error": "Event is at full capacity"}

    rsvp = RsvpModel(
        rsvp_id=str(uuid.uuid4()),
        event_id=event_id,
        twin_id=twin_id,
        org_id=org_id,
    )
    db.add(rsvp)
    event.rsvp_count += 1
    await db.flush()

    logger.info("RSVP created: %s -> event %s", twin_id, event.title)
    return {
        "success": True,
        "rsvp_id": rsvp.rsvp_id,
        "event": event.title,
        "rsvp_count": event.rsvp_count,
    }


async def get_dues(db: AsyncSession, twin_id: str, org_id: str) -> dict:
    """Return pending dues for a resident."""
    result = await db.execute(
        select(DuesModel).where(
            DuesModel.twin_id == twin_id,
            DuesModel.org_id == org_id,
            DuesModel.status == "PENDING",
        )
    )
    dues = result.scalars().all()
    total = sum(d.amount for d in dues)
    return {
        "dues": [
            {
                "due_id": d.due_id,
                "type": d.type,
                "amount": d.amount,
                "due_date": d.due_date.isoformat(),
                "status": d.status,
            }
            for d in dues
        ],
        "total": total,
    }


async def get_notices(db: AsyncSession, org_id: str) -> list[dict]:
    """Return latest 10 active notices for an org."""
    result = await db.execute(
        select(CommunityNoticeModel)
        .where(
            CommunityNoticeModel.org_id == org_id,
            CommunityNoticeModel.active == True,  # noqa: E712
        )
        .order_by(CommunityNoticeModel.created_at.desc())
        .limit(10)
    )
    return [
        {
            "notice_id": n.notice_id,
            "title": n.title,
            "body": n.body,
            "priority": n.priority,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in result.scalars().all()
    ]
