"""aria.society.booking_service — Amenity booking business logic.

Pure async functions — no FastAPI dependencies. Both the HTTP routes in
`aria.society.routes` and the in-process helpers in `aria.society.client`
call these.

Discovery support
-----------------
The 0004 schema added per-amenity ``type`` and rich descriptive fields.
This module exposes:

  - ``get_amenities``        — full list (now returns enriched dicts)
  - ``get_amenities_by_type``— filter by canonical type
  - ``get_amenity_by_id``    — unique-instance lookup (preferred)
  - ``find_amenities_by_name`` — *all* matches by name (for disambiguation)
  - ``get_available_slots`` / ``book_slot`` — accept either ``amenity_id``
    (preferred) or short ``name`` (legacy, may return a disambiguation
    error when multiple amenities share the name).

Moved from `t2t_backend/communityos/booking_service.py` as part of the T2T
extraction.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aria.society.models import AmenityModel, BookingModel

logger = logging.getLogger(__name__)


def _decode_features(raw: str | None) -> list[str]:
    """Safely decode the JSON-encoded features list."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(x) for x in val]
    except (ValueError, TypeError):
        logger.warning("Could not decode features %r — returning empty list", raw)
    return []


def _amenity_to_dict(a: AmenityModel) -> dict:
    """Single source of truth for the on-the-wire shape of an amenity."""
    return {
        "amenity_id": a.amenity_id,
        "name": a.name,
        "display_name": a.display_name,
        "type": a.type,
        "description": a.description or "",
        "features": _decode_features(a.features),
        "image_url": a.image_url or "",
        "block": a.block or "",
        "floor": a.floor or "",
        "location": a.location or "",
        "capacity_per_slot": a.capacity_per_slot,
        "slot_duration_mins": a.slot_duration_mins,
        "open_time": a.open_time.strftime("%H:%M"),
        "close_time": a.close_time.strftime("%H:%M"),
    }


# ── Discovery ─────────────────────────────────────────────────────────


async def get_amenities(db: AsyncSession, org_id: str) -> list[dict]:
    """All active amenities for the org, sorted (type, display_name)."""
    result = await db.execute(
        select(AmenityModel).where(
            AmenityModel.org_id == org_id,
            AmenityModel.active == True,  # noqa: E712
        ).order_by(AmenityModel.type, AmenityModel.display_name)
    )
    return [_amenity_to_dict(a) for a in result.scalars().all()]


async def get_amenities_by_type(db: AsyncSession, org_id: str, amenity_type: str) -> list[dict]:
    """All active amenities of a given canonical type for the org."""
    result = await db.execute(
        select(AmenityModel).where(
            AmenityModel.org_id == org_id,
            AmenityModel.type == amenity_type.strip().lower(),
            AmenityModel.active == True,  # noqa: E712
        ).order_by(AmenityModel.display_name)
    )
    return [_amenity_to_dict(a) for a in result.scalars().all()]


async def get_amenity_by_id(db: AsyncSession, org_id: str, amenity_id: str) -> AmenityModel | None:
    result = await db.execute(
        select(AmenityModel).where(
            AmenityModel.org_id == org_id,
            AmenityModel.amenity_id == amenity_id,
            AmenityModel.active == True,  # noqa: E712
        )
    )
    return result.scalars().first()


async def find_amenities_by_name(
    db: AsyncSession, org_id: str, name: str,
) -> list[AmenityModel]:
    """All amenities whose short name OR display_name matches (case-insensitive)."""
    needle = name.strip().lower()
    if not needle:
        return []
    result = await db.execute(
        select(AmenityModel).where(
            AmenityModel.org_id == org_id,
            AmenityModel.active == True,  # noqa: E712
            (
                (func.lower(AmenityModel.name) == needle)
                | (func.lower(AmenityModel.display_name) == needle)
                | (func.lower(AmenityModel.display_name).like(f"%{needle}%"))
            ),
        ).order_by(AmenityModel.display_name)
    )
    return list(result.scalars().all())


async def _resolve_amenity(
    db: AsyncSession,
    org_id: str,
    amenity_id: str | None,
    amenity_name: str | None,
) -> tuple[AmenityModel | None, dict | None]:
    """
    Given either an amenity_id (preferred) or a short name, return the
    AmenityModel.

    Returns ``(amenity, None)`` on success or ``(None, error_dict)``
    on failure. The error_dict shape is:

        {"success": False, "error": "...", "options": [...]?}

    A non-empty ``options`` list signals a disambiguation case: the LLM
    should ask the user to pick one of the listed display_names.
    """
    if amenity_id:
        amenity = await get_amenity_by_id(db, org_id, amenity_id)
        if not amenity:
            return None, {"success": False, "error": f"Amenity '{amenity_id}' not found"}
        return amenity, None

    if not amenity_name:
        return None, {"success": False, "error": "amenity_id or amenity name required"}

    matches = await find_amenities_by_name(db, org_id, amenity_name)
    if not matches:
        return None, {"success": False, "error": f"Amenity '{amenity_name}' not found"}
    if len(matches) > 1:
        return None, {
            "success": False,
            "error": f"Multiple {amenity_name}s found — please specify which one",
            "options": [
                {
                    "amenity_id": a.amenity_id,
                    "display_name": a.display_name,
                    "block": a.block or "",
                    "floor": a.floor or "",
                    "location": a.location or "",
                }
                for a in matches
            ],
        }
    return matches[0], None


# ── Slot generation + booking ────────────────────────────────────────


def _generate_slots(amenity: AmenityModel, target_date: date) -> list[dict]:
    """Generate all possible time slots for an amenity on a given date."""
    slots = []
    current = datetime.combine(target_date, amenity.open_time)
    end = datetime.combine(target_date, amenity.close_time)
    delta = timedelta(minutes=amenity.slot_duration_mins)

    while current + delta <= end:
        slot_end = current + delta
        slots.append({
            "slot_start": current.time().strftime("%H:%M"),
            "slot_end": slot_end.time().strftime("%H:%M"),
            "capacity": amenity.capacity_per_slot,
        })
        current = slot_end
    return slots


async def get_available_slots(
    db: AsyncSession,
    org_id: str,
    amenity_name: str | None = None,
    target_date: date = None,
    *,
    amenity_id: str | None = None,
) -> dict:
    if target_date is None:
        target_date = date.today()

    amenity, err = await _resolve_amenity(db, org_id, amenity_id, amenity_name)
    if err:
        return {"error": err.get("error"), "options": err.get("options", []), "slots": []}

    all_slots = _generate_slots(amenity, target_date)

    bookings_result = await db.execute(
        select(BookingModel.slot_start, func.count(BookingModel.booking_id)).where(
            BookingModel.amenity_id == amenity.amenity_id,
            BookingModel.slot_date == target_date,
            BookingModel.status == "CONFIRMED",
        ).group_by(BookingModel.slot_start)
    )
    booked_counts = {row[0]: row[1] for row in bookings_result}

    available = []
    for slot in all_slots:
        slot_time = datetime.strptime(slot["slot_start"], "%H:%M").time()
        booked = booked_counts.get(slot_time, 0)
        remaining = slot["capacity"] - booked
        available.append({
            **slot,
            "booked": booked,
            "remaining": remaining,
            "available": remaining > 0,
        })

    return {
        "amenity": amenity.display_name,
        "amenity_id": amenity.amenity_id,
        "type": amenity.type,
        "location": amenity.location,
        "block": amenity.block or "",
        "floor": amenity.floor or "",
        "date": target_date.isoformat(),
        "slots": available,
    }


async def book_slot(
    db: AsyncSession,
    org_id: str,
    amenity_name: str | None,
    twin_id: str,
    target_date: date,
    slot_start_str: str,
    *,
    amenity_id: str | None = None,
) -> dict:
    """Reserve a slot. Returns booking confirmation or error."""
    amenity, err = await _resolve_amenity(db, org_id, amenity_id, amenity_name)
    if err:
        return err

    try:
        slot_start = datetime.strptime(slot_start_str, "%H:%M").time()
    except ValueError:
        return {"success": False, "error": f"Invalid slot time '{slot_start_str}', expected HH:MM"}

    slot_end = (
        datetime.combine(target_date, slot_start)
        + timedelta(minutes=amenity.slot_duration_mins)
    ).time()

    if slot_start < amenity.open_time or slot_end > amenity.close_time:
        return {
            "success": False,
            "error": (
                f"{amenity.display_name} is open "
                f"{amenity.open_time.strftime('%H:%M')}-{amenity.close_time.strftime('%H:%M')} only"
            ),
        }

    booked_count_result = await db.execute(
        select(func.count(BookingModel.booking_id)).where(
            BookingModel.amenity_id == amenity.amenity_id,
            BookingModel.slot_date == target_date,
            BookingModel.slot_start == slot_start,
            BookingModel.status == "CONFIRMED",
        )
    )
    booked_count = booked_count_result.scalar() or 0

    if booked_count >= amenity.capacity_per_slot:
        return {
            "success": False,
            "error": f"Slot {slot_start_str} is fully booked ({booked_count}/{amenity.capacity_per_slot})",
        }

    existing = await db.execute(
        select(BookingModel).where(
            BookingModel.amenity_id == amenity.amenity_id,
            BookingModel.slot_date == target_date,
            BookingModel.slot_start == slot_start,
            BookingModel.twin_id == twin_id,
            BookingModel.status == "CONFIRMED",
        )
    )
    if existing.scalars().first():
        return {
            "success": False,
            "error": f"You already have a booking for {amenity.display_name} at {slot_start_str}",
        }

    booking = BookingModel(
        booking_id=str(uuid.uuid4()),
        amenity_id=amenity.amenity_id,
        org_id=org_id,
        twin_id=twin_id,
        slot_date=target_date,
        slot_start=slot_start,
        slot_end=slot_end,
        status="CONFIRMED",
    )
    db.add(booking)
    await db.flush()

    logger.info(
        "Booking created: %s -> %s on %s at %s",
        twin_id, amenity.display_name, target_date, slot_start_str,
    )
    return {
        "success": True,
        "booking_id": booking.booking_id,
        "amenity_id": amenity.amenity_id,
        "amenity": amenity.display_name,
        "type": amenity.type,
        "location": amenity.location,
        "block": amenity.block or "",
        "floor": amenity.floor or "",
        "date": target_date.isoformat(),
        "slot": f"{slot_start.strftime('%H:%M')}-{slot_end.strftime('%H:%M')}",
        "remaining_capacity": amenity.capacity_per_slot - booked_count - 1,
    }


async def cancel_booking(db: AsyncSession, booking_id: str) -> dict:
    result = await db.execute(
        select(BookingModel).where(BookingModel.booking_id == booking_id)
    )
    booking = result.scalars().first()
    if not booking:
        return {"success": False, "error": "Booking not found"}
    if booking.status == "CANCELLED":
        return {"success": False, "error": "Booking already cancelled"}

    booking.status = "CANCELLED"
    booking.cancelled_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info("Booking cancelled: %s", booking_id)
    return {"success": True, "booking_id": booking_id, "status": "CANCELLED"}
