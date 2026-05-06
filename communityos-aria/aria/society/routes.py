"""aria.society.routes — HTTP API for society features.

Endpoints (mounted under `/society` on ARIA's chat_api app):

  GET  /society/amenities
  GET  /society/amenities/by-type
  GET  /society/amenities/{amenity_id}
  GET  /society/amenities/slots
  POST /society/bookings
  POST /society/bookings/{booking_id}/cancel
  GET  /society/events
  POST /society/events/{event_id}/rsvp
  GET  /society/dues
  GET  /society/notices

Moved from `t2t_backend/communityos/routes.py` as part of the T2T extraction.
The route prefix changed from `/communityos` to `/society` to make the new
ownership explicit. ARIA's `t2t_client` and tests have been updated accordingly.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from aria.society.booking_service import (
    book_slot,
    cancel_booking,
    get_amenities,
    get_amenities_by_type,
    get_amenity_by_id,
    get_available_slots,
    _amenity_to_dict,
)
from aria.society.community_service import (
    get_dues as _get_dues,
    get_events as _get_events,
    get_notices as _get_notices,
    rsvp_event as _rsvp_event,
)
from aria.society.db import get_db

society_router = APIRouter(prefix="/society", tags=["Society"])


def _parse_date(raw: str) -> dt.date:
    if not raw or raw == "today":
        return dt.date.today()
    if raw == "tomorrow":
        return dt.date.today() + dt.timedelta(days=1)
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format: '{raw}'. Use YYYY-MM-DD.",
        )


@society_router.get("/amenities")
async def list_amenities(
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await get_amenities(db, org_id)


@society_router.get("/amenities/by-type")
async def list_amenities_by_type(
    org_id: str = Query(...),
    type: str = Query(..., description="Canonical amenity type, e.g. gym|pool|court_badminton"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all amenities of a given canonical type for an org.

    Response shape: ``{"type": ..., "count": N, "items": [...]}``.
    """
    items = await get_amenities_by_type(db, org_id, type)
    return {"type": type.strip().lower(), "count": len(items), "items": items}


@society_router.get("/amenities/slots")
async def list_available_slots(
    org_id: str = Query(...),
    amenity: str = Query(default="", description="Short name (e.g. 'gym'). Required if amenity_id is not provided."),
    amenity_id: str = Query(default="", description="Specific amenity_id (preferred when names are ambiguous)."),
    date: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = _parse_date(date)
    if not amenity and not amenity_id:
        raise HTTPException(status_code=400, detail="Provide either 'amenity' or 'amenity_id'")
    return await get_available_slots(
        db, org_id, amenity_name=amenity or None,
        target_date=target, amenity_id=amenity_id or None,
    )


@society_router.get("/amenities/{amenity_id}")
async def get_amenity_detail(
    amenity_id: str,
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    amenity = await get_amenity_by_id(db, org_id, amenity_id)
    if not amenity:
        raise HTTPException(status_code=404, detail=f"Amenity '{amenity_id}' not found")
    return _amenity_to_dict(amenity)


@society_router.post("/bookings")
async def create_booking(
    org_id: str = Query(...),
    twin_id: str = Query(...),
    date: str = Query(...),
    slot_start: str = Query(...),
    amenity: str = Query(default="", description="Short name (legacy). Optional if amenity_id given."),
    amenity_id: str = Query(default="", description="Preferred selector when present."),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = _parse_date(date)
    if not amenity and not amenity_id:
        raise HTTPException(status_code=400, detail="Provide either 'amenity' or 'amenity_id'")
    result = await book_slot(
        db, org_id,
        amenity_name=amenity or None,
        twin_id=twin_id,
        target_date=target,
        slot_start_str=slot_start,
        amenity_id=amenity_id or None,
    )
    # Disambiguation case: name matched multiple amenities. Surface options
    # with HTTP 400 so the client can re-prompt the user.
    if not result.get("success") and result.get("options"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": result.get("error", "ambiguous amenity"),
                "options": result["options"],
            },
        )
    return result


@society_router.post("/bookings/{booking_id}/cancel")
async def cancel_booking_endpoint(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await cancel_booking(db, booking_id)


# ── Events ────────────────────────────────────────────────────────────


@society_router.get("/events")
async def list_events(
    org_id: str = Query(...),
    date: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = _parse_date(date)
    events = await _get_events(db, org_id, target)
    return {"events": events}


@society_router.post("/events/{event_id}/rsvp")
async def rsvp_event_endpoint(
    event_id: str,
    twin_id: str = Query(...),
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _rsvp_event(db, org_id, event_id, twin_id)


# ── Dues ──────────────────────────────────────────────────────────────


@society_router.get("/dues")
async def list_dues(
    twin_id: str = Query(...),
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _get_dues(db, twin_id, org_id)


# ── Notices ───────────────────────────────────────────────────────────


@society_router.get("/notices")
async def list_notices(
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    notices = await _get_notices(db, org_id)
    return {"notices": notices}
