"""aria.society.seed_community — Seed events, dues, and notices for greenfield_society.

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


ORG_ID = "greenfield_society"
TWIN_ID = "tanmay_resident"

EVENTS = [
    {
        "title": "Morning Yoga",
        "description": "Daily morning yoga session in the garden area. All residents welcome.",
        "event_date": date(2026, 4, 18),
        "event_time": time(6, 30),
        "location": "Garden Area, Block A",
        "capacity": 30,
        "rsvp_count": 12,
    },
    {
        "title": "Kids Cricket",
        "description": "Weekend cricket match for kids aged 8-14. Bring your own kit.",
        "event_date": date(2026, 4, 19),
        "event_time": time(16, 0),
        "location": "Cricket Ground, East Wing",
        "capacity": 22,
        "rsvp_count": 8,
    },
    {
        "title": "Society AGM",
        "description": "Annual General Meeting of Greenfield Society. Attendance mandatory for all flat owners.",
        "event_date": date(2026, 4, 20),
        "event_time": time(18, 0),
        "location": "Community Hall, Block A, 2nd Floor",
        "capacity": 100,
        "rsvp_count": 45,
    },
]

DUES = [
    {
        "type": "Maintenance",
        "amount": 4500.0,
        "due_date": date(2026, 4, 30),
        "status": "PENDING",
    },
    {
        "type": "Parking",
        "amount": 1500.0,
        "due_date": date(2026, 4, 30),
        "status": "PENDING",
    },
]

NOTICES = [
    {
        "title": "Water Supply Maintenance",
        "body": "Water supply will be shut off on 19 Apr from 10 AM to 2 PM for tank cleaning and pipeline maintenance. Please store water accordingly.",
        "priority": "urgent",
    },
    {
        "title": "Holi Celebration",
        "body": "Society Holi celebration on 20 Apr at the garden area. Organic colours will be provided. DJ from 3 PM to 6 PM. All families welcome!",
        "priority": "normal",
    },
    {
        "title": "Parking Update",
        "body": "Visitor parking in Block C basement is now reserved for residents on weekends. Visitors may use the open lot near the east gate.",
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
            print(f"  + due: {due_data['type']} Rs {due_data['amount']}")

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
