"""aria.society.seed_amenities — Seed amenities for greenfield_society.

This is the canonical fixture that ARIA's discovery flow renders. Each
amenity has the rich fields the new amenity-cards UI relies on (type,
description, features, block, floor) so the chat can answer:

  "what amenities are here?"           -> list_society_amenities
  "show me all gyms"                   -> find_amenities_by_type(type=gym)
  "tell me about Block A gym"          -> get_amenity_info
  "book Block A gym at 7am"            -> book_amenity(amenity_id=...)

# Re-seed instructions
# --------------------
# Fresh install (SQLite or Postgres):
#   python -m aria.society.seed_amenities
#
# Existing dev SQLite DB (file-backed) that was seeded with the older,
# 6-amenity layout:
#   1. Stop chat_api
#   2. Delete the SQLite file (or run `DROP TABLE amenities; DROP TABLE bookings`)
#   3. python -m aria.society.seed_amenities
#   4. Start chat_api
#
# Existing Postgres DB:
#   alembic upgrade head        # adds the new columns + backfills
#   python -m aria.society.seed_amenities   # idempotent (skips existing display_names)

This script is idempotent: if a row with the same ``display_name`` already
exists for the org, it is left untouched and the seed reports a skip. We
key on ``display_name`` (not ``name``) because there are now multiple
amenities sharing the same short name (three gyms, two pools, etc.).

Moved from `t2t_backend/communityos/seed.py` as part of the T2T extraction.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import time

from sqlalchemy import select

from aria.society.db import AsyncSessionLocal, create_all_tables
from aria.society.models import AmenityModel


ORG_ID = "greenfield_society"


# Each entry is a complete amenity spec. ``features`` is stored JSON-encoded
# in the DB; we accept Python lists here for readability.
AMENITIES: list[dict] = [
    # ── Gyms (3) ──────────────────────────────────────────────────────
    {
        "name": "gym",
        "display_name": "Greenfield Gym - Block A",
        "type": "gym",
        "block": "Block A",
        "floor": "Ground Floor",
        "location": "Block A, Ground Floor",
        "description": "Main residents gym with full strength + cardio equipment, towel service and free parking.",
        "features": ["Full equipment", "Cardio machines", "Strength rack", "Towels provided", "Locker room"],
        "image_url": "",
        "capacity_per_slot": 15,
        "slot_duration_mins": 60,
        "open_time": time(5, 0),
        "close_time": time(22, 0),
    },
    {
        "name": "gym",
        "display_name": "Greenfield Gym - Block C",
        "type": "gym",
        "block": "Block C",
        "floor": "1st Floor",
        "location": "Block C, 1st Floor",
        "description": "Premium air-conditioned gym with on-call personal trainer (book in advance) and recovery lounge.",
        "features": ["AC", "Personal trainer on call", "Recovery lounge", "Cold towels", "Smoothie bar"],
        "image_url": "",
        "capacity_per_slot": 10,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(22, 0),
    },
    {
        "name": "gym",
        "display_name": "Greenfield Gym - Block D",
        "type": "gym",
        "block": "Block D",
        "floor": "Basement",
        "location": "Block D, Basement",
        "description": "24x7 cardio-focused gym for shift workers and night owls. Treadmills, bikes, ellipticals.",
        "features": ["24x7 access", "Cardio focus", "Treadmills", "Stationary bikes", "Quiet zone"],
        "image_url": "",
        "capacity_per_slot": 12,
        "slot_duration_mins": 60,
        "open_time": time(0, 0),
        "close_time": time(23, 59),
    },

    # ── Pools (2) ─────────────────────────────────────────────────────
    {
        "name": "pool",
        "display_name": "Main Swimming Pool",
        "type": "pool",
        "block": "Block C",
        "floor": "Ground Floor",
        "location": "Block C, Backside",
        "description": "25-meter heated lap pool with poolside loungers. Ideal for serious swimmers.",
        "features": ["25m lap pool", "Heated", "Lounge chairs", "Lifeguard on duty", "Changing rooms"],
        "image_url": "",
        "capacity_per_slot": 20,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(20, 0),
    },
    {
        "name": "pool",
        "display_name": "Kids Splash Pool",
        "type": "pool",
        "block": "Block A",
        "floor": "Ground Floor",
        "location": "Block A, Garden Side",
        "description": "Kids-only shallow splash pool with full-time lifeguard. Parents must accompany under-6s.",
        "features": ["Shallow (3 ft)", "Kids only", "Full-time lifeguard", "Splash toys", "Garden seating"],
        "image_url": "",
        "capacity_per_slot": 15,
        "slot_duration_mins": 60,
        "open_time": time(7, 0),
        "close_time": time(19, 0),
    },

    # ── Badminton Courts (2) ──────────────────────────────────────────
    {
        "name": "badminton",
        "display_name": "Badminton Court 1",
        "type": "court_badminton",
        "block": "Block B",
        "floor": "Terrace",
        "location": "Block B, Terrace Level",
        "description": "Wooden-floor badminton court with new LED lighting. Rackets available on request.",
        "features": ["Wooden floor", "LED lighting", "Rackets on request", "Shuttle vending machine"],
        "image_url": "",
        "capacity_per_slot": 4,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(22, 0),
    },
    {
        "name": "badminton",
        "display_name": "Badminton Court 2",
        "type": "court_badminton",
        "block": "Block B",
        "floor": "Terrace",
        "location": "Block B, Terrace Level",
        "description": "Synthetic-mat court suitable for casual play and doubles tournaments.",
        "features": ["Synthetic mat", "Tournament markings", "Spectator seating", "Water cooler"],
        "image_url": "",
        "capacity_per_slot": 4,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(22, 0),
    },

    # ── Tennis Courts (2) ─────────────────────────────────────────────
    {
        "name": "tennis",
        "display_name": "Tennis Court A - Clay",
        "type": "court_tennis",
        "block": "East Gate",
        "floor": "Ground Floor",
        "location": "Near East Gate",
        "description": "Professional-spec clay tennis court with floodlights for night play.",
        "features": ["Clay surface", "Floodlights", "Night play allowed", "Player benches"],
        "image_url": "",
        "capacity_per_slot": 4,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(22, 0),
    },
    {
        "name": "tennis",
        "display_name": "Tennis Court B - Hard",
        "type": "court_tennis",
        "block": "East Gate",
        "floor": "Ground Floor",
        "location": "Near East Gate",
        "description": "Hard-court tennis surface for fast-paced rallies. Coaching available on weekends.",
        "features": ["Hard court", "Floodlights", "Weekend coaching", "Ball machine on rent"],
        "image_url": "",
        "capacity_per_slot": 4,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(22, 0),
    },

    # ── Halls (2) ─────────────────────────────────────────────────────
    {
        "name": "community hall",
        "display_name": "Community Hall",
        "type": "hall",
        "block": "Block A",
        "floor": "2nd Floor",
        "location": "Block A, 2nd Floor",
        "description": "100-capacity AC hall ideal for small society meetings, talks and birthday gatherings.",
        "features": ["AC", "Seating for 100", "Projector + screen", "Mic system", "Adjacent pantry"],
        "image_url": "",
        "capacity_per_slot": 100,
        "slot_duration_mins": 120,
        "open_time": time(8, 0),
        "close_time": time(22, 0),
    },
    {
        "name": "community hall",
        "display_name": "Banquet Hall",
        "type": "hall",
        "block": "Block E",
        "floor": "Ground Floor",
        "location": "Block E, Ground Floor",
        "description": "Premium 200-capacity banquet hall for weddings, anniversaries and large celebrations.",
        "features": ["Seating for 200", "Premium decor", "Stage + dance floor", "Catering kitchen", "Valet parking"],
        "image_url": "",
        "capacity_per_slot": 200,
        "slot_duration_mins": 240,
        "open_time": time(9, 0),
        "close_time": time(23, 0),
    },

    # ── Clubhouse (1) ─────────────────────────────────────────────────
    {
        "name": "clubhouse",
        "display_name": "Greenfield Clubhouse",
        "type": "clubhouse",
        "block": "Main Gate",
        "floor": "1st Floor",
        "location": "Main Gate, 1st Floor",
        "description": "Members-only clubhouse with lounge, a small library nook and licensed bar.",
        "features": ["Lounge seating", "Reading nook", "Licensed bar", "Card tables", "TV viewing area"],
        "image_url": "",
        "capacity_per_slot": 30,
        "slot_duration_mins": 120,
        "open_time": time(11, 0),
        "close_time": time(23, 0),
    },

    # ── Studio (1) ────────────────────────────────────────────────────
    {
        "name": "studio",
        "display_name": "Yoga & Meditation Studio",
        "type": "studio",
        "block": "Block B",
        "floor": "2nd Floor",
        "location": "Block B, 2nd Floor",
        "description": "Quiet AC studio for yoga, meditation and small-group movement classes. Mats provided.",
        "features": ["AC", "Mats provided", "Mirror wall", "Sound system", "Aromatherapy"],
        "image_url": "",
        "capacity_per_slot": 12,
        "slot_duration_mins": 60,
        "open_time": time(6, 0),
        "close_time": time(21, 0),
    },

    # ── Spa (1) ───────────────────────────────────────────────────────
    {
        "name": "spa",
        "display_name": "Wellness Spa",
        "type": "spa",
        "block": "Block C",
        "floor": "Ground Floor",
        "location": "Block C, Backside (next to Main Pool)",
        "description": "Full-service wellness spa with massage rooms, sauna and steam — book in advance.",
        "features": ["Massage rooms", "Sauna", "Steam room", "Towel + robe", "Booking required"],
        "image_url": "",
        "capacity_per_slot": 4,
        "slot_duration_mins": 60,
        "open_time": time(10, 0),
        "close_time": time(21, 0),
    },

    # ── Library (1) ───────────────────────────────────────────────────
    {
        "name": "library",
        "display_name": "Reading Library",
        "type": "library",
        "block": "Main Gate",
        "floor": "2nd Floor",
        "location": "Clubhouse, 2nd Floor",
        "description": "Silent reading library with 2000+ titles, study desks and free Wi-Fi. No phone calls.",
        "features": ["2000+ books", "Silent zone", "Study desks", "Free Wi-Fi", "Newspapers + magazines"],
        "image_url": "",
        "capacity_per_slot": 20,
        "slot_duration_mins": 120,
        "open_time": time(8, 0),
        "close_time": time(22, 0),
    },
]


async def seed() -> None:
    await create_all_tables()
    added = 0
    skipped = 0
    async with AsyncSessionLocal() as db:
        for spec in AMENITIES:
            # Idempotency key: (org_id, display_name). We chose display_name
            # over name because multiple amenities now share the same name.
            existing = await db.execute(
                select(AmenityModel).where(
                    AmenityModel.org_id == ORG_ID,
                    AmenityModel.display_name == spec["display_name"],
                )
            )
            if existing.scalars().first():
                print(f"  skip {spec['display_name']} (exists)")
                skipped += 1
                continue

            payload = dict(spec)
            payload["features"] = json.dumps(payload.get("features", []))
            amenity = AmenityModel(
                amenity_id=str(uuid.uuid4()),
                org_id=ORG_ID,
                **payload,
            )
            db.add(amenity)
            print(f"  + {spec['display_name']} [{spec['type']}] @ {spec['location']}")
            added += 1

        await db.commit()
    print(f"\nSeeded {added} new, skipped {skipped} existing — total spec is {len(AMENITIES)} amenities for {ORG_ID}")


if __name__ == "__main__":
    asyncio.run(seed())
