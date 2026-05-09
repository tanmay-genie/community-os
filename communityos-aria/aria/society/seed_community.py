"""aria.society.seed_community — Seed events, dues, and notices for maple_heights.

Run: python -m aria.society.seed_community

Moved from `t2t_backend/communityos/seed_community.py` as part of the T2T
extraction.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, time

from sqlalchemy import select

from aria.society.db import AsyncSessionLocal, create_all_tables
from aria.society.models import (
    CommunityEventModel,
    CommunityNoticeModel,
    DuesModel,
)


ORG_ID = "maple_heights"
TWIN_ID = "tanmay_resident"

EVENTS = [
    {
        "title": "Morning Yoga",
        "description": "Daily morning yoga session in the courtyard. All residents welcome.",
        "event_date": date(2026, 5, 12),
        "event_time": time(6, 30),
        "location": "Courtyard, Tower 1",
        "capacity": 30,
        "rsvp_count": 12,
    },
    {
        "title": "Rooftop Social",
        "description": "Saturday evening rooftop social with light snacks. Meet your neighbours.",
        "event_date": date(2026, 5, 14),
        "event_time": time(18, 0),
        "location": "Tower 4 Rooftop",
        "capacity": 60,
        "rsvp_count": 22,
    },
    {
        "title": "Annual General Meeting",
        "description": "Annual General Meeting for all unit owners. Attendance encouraged; proxies accepted.",
        "event_date": date(2026, 5, 20),
        "event_time": time(18, 0),
        "location": "Party Room, Tower 5 Lobby Level",
        "capacity": 200,
        "rsvp_count": 78,
    },
]

DUES = [
    {
        "type": "Strata Fee",
        "amount": 480.0,  # CAD
        "due_date": date(2026, 5, 31),
        "status": "PENDING",
    },
    {
        "type": "Parking",
        "amount": 75.0,  # CAD
        "due_date": date(2026, 5, 31),
        "status": "PENDING",
    },
]

NOTICES = [
    {
        "title": "Water Shutoff Notice",
        "body": "Water will be shut off on May 14 from 10 AM to 2 PM for routine maintenance of risers in Tower 2. Please store water in advance.",
        "priority": "urgent",
    },
    {
        "title": "Spring Maintenance Walkthrough",
        "body": "Property manager will conduct spring inspection of common areas on May 16. No unit access required.",
        "priority": "normal",
    },
    {
        "title": "Visitor Parking Reminder",
        "body": "Visitor parking is limited to 24 hours. Please use the visitor permit system. Vehicles without a valid permit may be towed at owner's expense.",
        "priority": "normal",
    },
]


async def seed() -> None:
    await create_all_tables()
    async with AsyncSessionLocal() as db:
        # Seed events
        for event_data in EVENTS:
            existing = await db.execute(
                select(CommunityEventModel).where(
                    CommunityEventModel.org_id == ORG_ID,
                    CommunityEventModel.title == event_data["title"],
                    CommunityEventModel.event_date == event_data["event_date"],
                )
            )
            if existing.scalars().first():
                print(f"  skip event '{event_data['title']}' (exists)")
                continue

            event = CommunityEventModel(
                event_id=str(uuid.uuid4()),
                org_id=ORG_ID,
                **event_data,
            )
            db.add(event)
            print(f"  + event: {event_data['title']} ({event_data['event_date']})")

        # Seed dues
        for due_data in DUES:
            existing = await db.execute(
                select(DuesModel).where(
                    DuesModel.org_id == ORG_ID,
                    DuesModel.twin_id == TWIN_ID,
                    DuesModel.type == due_data["type"],
                    DuesModel.due_date == due_data["due_date"],
                )
            )
            if existing.scalars().first():
                print(f"  skip due '{due_data['type']}' (exists)")
                continue

            due = DuesModel(
                due_id=str(uuid.uuid4()),
                org_id=ORG_ID,
                twin_id=TWIN_ID,
                **due_data,
            )
            db.add(due)
            print(f"  + due: {due_data['type']} CAD ${due_data['amount']:.2f}")

        # Seed notices
        for notice_data in NOTICES:
            existing = await db.execute(
                select(CommunityNoticeModel).where(
                    CommunityNoticeModel.org_id == ORG_ID,
                    CommunityNoticeModel.title == notice_data["title"],
                )
            )
            if existing.scalars().first():
                print(f"  skip notice '{notice_data['title']}' (exists)")
                continue

            notice = CommunityNoticeModel(
                notice_id=str(uuid.uuid4()),
                org_id=ORG_ID,
                **notice_data,
            )
            db.add(notice)
            print(f"  + notice: {notice_data['title']} [{notice_data['priority']}]")

        await db.commit()

    print(f"\nSeeded events, dues, and notices for {ORG_ID}")


if __name__ == "__main__":
    asyncio.run(seed())
