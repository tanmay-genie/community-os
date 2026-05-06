"""aria.society.client — In-process helpers for ARIA's society features.

These wrap the pure async services in `booking_service` and `community_service`
with their own DB sessions so callers (e.g. ARIA tools, the chat tool layer
inside `t2t_client`) can invoke society logic without going through HTTP.

Why bother? T2T extraction made society features ARIA-owned. Going via HTTP
back into the same Python process would be wasteful and add a hard dependency
on ARIA's HTTP server being up before any tool can run. These helpers run
in-process and use the same SQLAlchemy session machinery as the HTTP routes.
"""
from __future__ import annotations

import datetime as dt
import logging

from aria.society.booking_service import (
    book_slot as _book_slot,
    cancel_booking as _cancel_booking,
    get_amenities as _get_amenities,
    get_amenities_by_type as _get_amenities_by_type,
    get_amenity_by_id as _get_amenity_by_id,
    get_available_slots as _get_available_slots,
    _amenity_to_dict,
)
from aria.society.community_service import (
    get_dues as _get_dues,
    get_events as _get_events,
    get_notices as _get_notices,
)
from aria.society.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


def _parse_date(raw: str) -> dt.date:
    if not raw or raw == "today":
        return dt.date.today()
    if raw == "tomorrow":
        return dt.date.today() + dt.timedelta(days=1)
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        # Mirror the routes' behavior for the ARIA tool layer: fail soft, log.
        logger.warning("Invalid date format %r — defaulting to today", raw)
        return dt.date.today()


# ── Bookings / Amenities ──────────────────────────────────────────────


async def list_amenities(org_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        return await _get_amenities(db, org_id)


async def list_amenities_by_type(org_id: str, amenity_type: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        return await _get_amenities_by_type(db, org_id, amenity_type)


async def get_amenity(org_id: str, amenity_id: str) -> dict | None:
    """Full enriched dict for a single amenity, or None if not found."""
    async with AsyncSessionLocal() as db:
        amenity = await _get_amenity_by_id(db, org_id, amenity_id)
        if not amenity:
            return None
        return _amenity_to_dict(amenity)


async def list_available_slots(
    org_id: str,
    amenity: str = "",
    date: str = "",
    *,
    amenity_id: str | None = None,
) -> dict:
    target = _parse_date(date)
    async with AsyncSessionLocal() as db:
        return await _get_available_slots(
            db, org_id, amenity_name=amenity or None,
            target_date=target, amenity_id=amenity_id,
        )


async def book_amenity_slot(
    org_id: str,
    amenity: str,
    twin_id: str,
    date: str,
    slot_start: str,
    *,
    amenity_id: str | None = None,
) -> dict:
    target = _parse_date(date)
    async with AsyncSessionLocal() as db:
        result = await _book_slot(
            db, org_id, amenity_name=amenity or None,
            twin_id=twin_id, target_date=target, slot_start_str=slot_start,
            amenity_id=amenity_id,
        )
        await db.commit()
        return result


async def cancel_amenity_booking(booking_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        result = await _cancel_booking(db, booking_id)
        await db.commit()
        return result


# ── Events / Dues / Notices ───────────────────────────────────────────


async def list_events(org_id: str, date: str = "") -> dict:
    target = _parse_date(date)
    async with AsyncSessionLocal() as db:
        events = await _get_events(db, org_id, target)
        return {"events": events}


async def list_dues(twin_id: str, org_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        return await _get_dues(db, twin_id, org_id)


async def list_notices(org_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        notices = await _get_notices(db, org_id)
        return {"notices": notices}
