"""
aria/tools/member.py — MCP tools for MEMBER side.

All tools call t2t_client which routes through:
  policy/ → orchestrator/ → adapter → audit/ → notify/

Amenity discovery
-----------------
Four discovery tools (``list_society_amenities``, ``find_amenities_by_type``,
``get_amenity_info``, ``show_amenity_slots``) emit a structured prefix —
``AMENITIES_LIST::<json>`` or ``BOOKING_RESULT::<json>`` — followed by a
human-readable caption. The frontend parses the prefix to render rich
cards; non-JS clients still get the caption as a usable plain-text reply.
"""

import json
import logging
import uuid

from aria.context.loader import save_user_action
from aria.t2t_client import t2t

logger = logging.getLogger(__name__)


# Canonical type list — mirrors what seed_amenities.py emits and what the
# frontend renders. Kept here so the LLM tool description can reference it.
AMENITY_TYPES = (
    "gym", "pool", "court_badminton", "court_tennis",
    "hall", "studio", "spa", "library", "clubhouse",
)


def _summarize_amenities_for_caption(items: list[dict]) -> str:
    """Build a friendly grouped summary like '3 gyms (Block A, Block C, Block D)'."""
    if not items:
        return "No amenities found."
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it.get("type", "other"), []).append(it)
    type_label = {
        "gym": "gym", "pool": "pool", "court_badminton": "badminton court",
        "court_tennis": "tennis court", "hall": "hall", "studio": "studio",
        "spa": "spa", "library": "library", "clubhouse": "clubhouse",
        "other": "facility",
    }
    parts = []
    for tkey, group in groups.items():
        label = type_label.get(tkey, tkey)
        plural = label + ("es" if label.endswith("s") else "s") if len(group) > 1 else label
        locations = []
        for g in group[:4]:
            tag = g.get("block") or g.get("location") or g.get("display_name", "")
            locations.append(tag)
        loc_str = ", ".join([l for l in locations if l])
        parts.append(f"{len(group)} {plural} ({loc_str})" if loc_str else f"{len(group)} {plural}")
    return "Here's what we have: " + "; ".join(parts) + "."


def register(mcp):

    # ── DISCOVERY ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_society_amenities(org_id: str) -> str:
        """
        List ALL amenities available in the society, grouped by type with
        full location, hours, capacity and feature details. Call when the
        user asks: 'what amenities are here?', 'kya kya available hai?',
        'show me all facilities', 'what can I book?', 'list everything'.

        Returns a structured ``AMENITIES_LIST::<json>`` prefix followed by
        a human-readable caption so the frontend can render amenity cards
        and non-JS clients still get a usable reply.
        """
        try:
            items = await t2t.get_amenities_list(org_id=org_id)
        except Exception as exc:
            logger.warning("list_society_amenities failed: %s", exc)
            return "I couldn't fetch the amenity list right now. Please try again in a moment."

        if not items:
            return "I couldn't find any amenities for this society yet."

        payload = json.dumps({"items": items, "scope": "all"}, ensure_ascii=False)
        caption = _summarize_amenities_for_caption(items)
        return f"AMENITIES_LIST::{payload}\n\n{caption}"

    @mcp.tool()
    async def find_amenities_by_type(org_id: str, amenity_type: str) -> str:
        """
        Find all amenities of a specific type. Call when user says 'show all gyms',
        'kitne gym hai?', 'list all courts', 'all the pools', 'tennis courts available'.

        amenity_type: gym | pool | court_badminton | court_tennis | hall | studio | spa | library | clubhouse

        Returns ``AMENITIES_LIST::<json>`` prefix + caption. Frontend renders
        amenity cards; non-JS clients see a grouped summary.
        """
        normalized = (amenity_type or "").strip().lower().replace(" ", "_")
        # Friendly aliasing: user may say "badminton court" rather than "court_badminton"
        ALIASES = {
            "gyms": "gym", "pools": "pool",
            "badminton": "court_badminton", "badminton_court": "court_badminton",
            "tennis": "court_tennis", "tennis_court": "court_tennis",
            "halls": "hall", "community_hall": "hall", "banquet_hall": "hall",
            "yoga": "studio", "meditation": "studio",
        }
        normalized = ALIASES.get(normalized, normalized)

        if normalized not in AMENITY_TYPES:
            valid = ", ".join(AMENITY_TYPES)
            return f"I don't recognize amenity type '{amenity_type}'. Try one of: {valid}."

        try:
            items = await t2t.list_amenities_by_type(org_id=org_id, amenity_type=normalized)
        except Exception as exc:
            logger.warning("find_amenities_by_type failed: %s", exc)
            return f"I couldn't fetch the {amenity_type} list right now. Please try again."

        if not items:
            return f"No {amenity_type} amenities are listed in this society yet."

        payload = json.dumps({"items": items, "scope": "by_type", "type": normalized}, ensure_ascii=False)
        caption = _summarize_amenities_for_caption(items)
        return f"AMENITIES_LIST::{payload}\n\n{caption}"

    @mcp.tool()
    async def get_amenity_info(org_id: str, amenity_id_or_name: str) -> str:
        """
        Get full details about a specific amenity (location, hours, capacity, features).
        Call when user says 'tell me about Block A gym', 'gym A details',
        'what's in the spa?', 'spa kahan hai?'. Pass the amenity_id when known,
        otherwise the name/display_name (first match wins).
        """
        if not amenity_id_or_name:
            return "Please tell me which amenity you'd like to know about."

        # Try id first (UUID-shaped), then fall back to a name match.
        info: dict | None = None
        try:
            info = await t2t.get_amenity(org_id=org_id, amenity_id=amenity_id_or_name)
        except Exception:
            info = None

        if not info:
            try:
                items = await t2t.get_amenities_list(org_id=org_id)
            except Exception as exc:
                logger.warning("get_amenity_info fallback failed: %s", exc)
                return "I couldn't fetch amenity details right now."
            needle = amenity_id_or_name.strip().lower()
            for it in items:
                if (
                    it.get("display_name", "").lower() == needle
                    or it.get("name", "").lower() == needle
                    or needle in it.get("display_name", "").lower()
                ):
                    info = it
                    break

        if not info:
            return f"I couldn't find '{amenity_id_or_name}' in our amenities. Want me to list everything?"

        features = info.get("features") or []
        feat_str = ", ".join(features[:5]) if features else "—"
        return (
            f"{info.get('display_name', 'Amenity')}\n"
            f"Type: {info.get('type', 'facility')} | Location: {info.get('location', '—')}\n"
            f"Hours: {info.get('open_time', '?')}–{info.get('close_time', '?')}, "
            f"Capacity per slot: {info.get('capacity_per_slot', '?')}\n"
            f"Features: {feat_str}\n"
            f"{info.get('description', '')}".strip()
        )

    @mcp.tool()
    async def show_amenity_slots(
        org_id: str,
        amenity_id_or_name: str,
        date: str = "today",
    ) -> str:
        """
        Show available booking slots for a specific amenity on a given date.
        Call when user says 'gym slots for tomorrow', 'when can I book the pool?',
        'kal ke slots dikhao'. date: today | tomorrow | YYYY-MM-DD.
        """
        if not amenity_id_or_name:
            return "Please tell me which amenity you want slots for."

        # If the input looks like a UUID, route via amenity_id; otherwise use name.
        looks_like_id = (
            len(amenity_id_or_name) >= 16
            and amenity_id_or_name.count("-") >= 3
        )
        try:
            if looks_like_id:
                data = await t2t.get_available_slots(
                    org_id=org_id, amenity="", date=date,
                    amenity_id=amenity_id_or_name,
                )
            else:
                data = await t2t.get_available_slots(
                    org_id=org_id, amenity=amenity_id_or_name, date=date,
                )
        except Exception as exc:
            logger.warning("show_amenity_slots failed: %s", exc)
            return "I couldn't fetch slots right now. Please try again."

        if data.get("error") and data.get("options"):
            opts = data["options"]
            lines = [
                f"Multiple matches for '{amenity_id_or_name}'. Which one?"
            ] + [f"  • {o['display_name']} ({o.get('location') or o.get('block', '')})" for o in opts]
            return "\n".join(lines)

        if data.get("error"):
            return data["error"]

        slots = [s for s in data.get("slots", []) if s.get("available")]
        if not slots:
            return f"No free slots for {data.get('amenity', amenity_id_or_name)} on {data.get('date', date)}."

        lines = [
            f"{data.get('amenity', '')} ({data.get('location', '')}) — {data.get('date', date)}",
            f"Available slots ({len(slots)}):",
        ]
        for i, s in enumerate(slots[:10], 1):
            lines.append(f"  {i}. {s['slot_start']}–{s['slot_end']} ({s['remaining']} spots left)")
        if len(slots) > 10:
            lines.append(f"  …and {len(slots) - 10} more")
        return "\n".join(lines)

    # ── BOOKING ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def book_amenity(
        twin_id: str,
        org_id: str,
        user_api_key: str,
        amenity: str,
        slot_time: str,
        date: str = "today",
        amenity_id: str = "",
    ) -> str:
        """
        Book an amenity for the resident.

        Call this when user says: 'Book gym at 7', 'Reserve pool for tomorrow 6am',
        'I want to use the clubhouse', 'Book Block A gym at 7'.

        amenity:    gym | pool | clubhouse | badminton | tennis | community hall
                    OR a specific display_name like 'Greenfield Gym - Block A'
        amenity_id: preferred when present — bypasses ambiguity entirely.
        slot_time:  '7pm', '19:00', '07:00'
        date:       'today' | 'tomorrow' | 'YYYY-MM-DD'

        Returns a ``BOOKING_RESULT::<json>`` prefix on success so the frontend
        can render a confirmation card. On ambiguity (e.g. 'gym' matches three
        instances), returns a friendly disambiguation message with the options.
        """
        try:
            # Send through T2T policy/orchestrator pipeline first (audit+notify).
            t2t_result = await t2t.book_amenity(
                user_api_key=user_api_key,
                twin_id=twin_id,
                org_id=org_id,
                amenity=amenity,
                slot_time=slot_time,
                date=date,
                thread_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
            )
            decision = t2t_result.get("decision", "ALLOW")
            if decision == "DENY":
                return f"Sorry, that booking was denied. {t2t_result.get('reason', '')}".strip()
            if decision == "ESCALATE":
                return "Your booking request is pending approval. You'll be notified shortly."

            # Now actually persist the slot via the society service.
            booking = await t2t.book_slot_direct(
                org_id=org_id,
                amenity=amenity,
                twin_id=twin_id,
                date=date,
                slot_start=slot_time,
                amenity_id=amenity_id or None,
            )
            if booking.get("success"):
                await save_user_action(twin_id, f"booked {booking.get('amenity', amenity)} at {slot_time}")
                payload = json.dumps({
                    "booking_id": booking["booking_id"],
                    "amenity_id": booking.get("amenity_id", ""),
                    "amenity": booking.get("amenity", amenity),
                    "type": booking.get("type", ""),
                    "location": booking.get("location", ""),
                    "block": booking.get("block", ""),
                    "floor": booking.get("floor", ""),
                    "date": booking.get("date", date),
                    "slot": booking.get("slot", slot_time),
                    "remaining_capacity": booking.get("remaining_capacity"),
                }, ensure_ascii=False)
                return (
                    f"BOOKING_RESULT::{payload}\n\n"
                    f"Booked! {booking.get('amenity', amenity)} reserved for "
                    f"{booking.get('slot', slot_time)} on {booking.get('date', date)}."
                )

            # Disambiguation: name matches multiple amenities.
            if booking.get("options"):
                opts = booking["options"]
                lines = [
                    f"There's more than one {amenity} — which would you like to book?",
                ] + [
                    f"  • {o['display_name']} ({o.get('location') or o.get('block', '')})"
                    for o in opts
                ]
                lines.append("Tell me the full name (e.g. 'Greenfield Gym - Block A').")
                return "\n".join(lines)

            return f"Couldn't book {amenity}: {booking.get('error', 'slot may be taken.')}"
        except Exception as exc:
            logger.warning("book_amenity failed: %s", exc)
            return "Booking service is unavailable right now. Please try again in a moment."

    # ── COMPLAINTS / TICKETS ───────────────────────────────────────────────

    @mcp.tool()
    async def create_ticket(
        twin_id: str,
        org_id: str,
        user_api_key: str,
        issue: str,
        unit: str,
        priority: str = "normal",
    ) -> str:
        """
        Raise a service request / maintenance ticket.
        Call this when user says: 'AC not working', 'Lift is stuck',
        'Water leakage in bathroom', 'Report an issue'.
        priority: normal | urgent
        Set priority='urgent' only for safety issues (fire, flood, gas leak).
        """
        try:
            result = await t2t.create_ticket(
                user_api_key=user_api_key,
                twin_id=twin_id,
                org_id=org_id,
                issue=issue,
                unit=unit,
                priority=priority,
                thread_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
            )
            await save_user_action(twin_id, f"raised ticket: {issue}")
            if priority == "urgent":
                return (
                    f"Urgent ticket raised for: {issue}. "
                    f"The maintenance team has been alerted immediately."
                )
            return (
                f"Ticket raised for: {issue}. "
                f"Our team will look into it and update you shortly."
            )
        except Exception:
            return "Couldn't raise the ticket right now. Please try again."

    # ── EVENTS ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_society_events(
        org_id: str,
        date: str = "today",
    ) -> str:
        """
        Fetch what events are happening in the society.
        Call this when user says: 'What's happening today?', 'Any events this weekend?',
        'What's going on in the society?'
        date: 'today' | 'tomorrow' | 'this week' | specific date like '2026-04-10'
        """
        try:
            data = await t2t.get_events(org_id=org_id, date=date)
            events = data.get("events", [])
            if not events:
                return f"Nothing scheduled {date} in the society. A quiet one!"
            lines = [f"Here's what's on {date}:"]
            for ev in events[:5]:
                lines.append(f"• {ev['title']} at {ev['time']} — {ev['location']}")
            return "\n".join(lines)
        except Exception:
            return "Couldn't fetch events right now. Try again in a moment."

    @mcp.tool()
    async def rsvp_to_event(
        twin_id: str,
        org_id: str,
        user_api_key: str,
        event_id: str,
        event_name: str,
    ) -> str:
        """
        RSVP to a society event.
        Call this when user says: 'I want to join the cricket match',
        'Sign me up for the Holi event', 'RSVP for tonight's party'.
        """
        try:
            await t2t.rsvp_event(
                user_api_key=user_api_key,
                twin_id=twin_id,
                org_id=org_id,
                event_id=event_id,
                thread_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
            )
            await save_user_action(twin_id, f"RSVP'd to {event_name}")
            return f"You're in! RSVP confirmed for {event_name}. See you there."
        except Exception:
            return "Couldn't complete your RSVP. Please try again."

    # ── PAYMENTS ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def check_dues(
        twin_id: str,
        org_id: str,
    ) -> str:
        """
        Check pending dues, rent, or maintenance fees.
        Call this when user says: 'How much do I owe?', 'Any pending payments?',
        'Check my dues', 'Is my rent paid?'
        """
        try:
            data = await t2t.get_dues(twin_id=twin_id, org_id=org_id)
            dues = data.get("dues", [])
            if not dues:
                return "You're all clear! No pending dues."
            total = sum(d.get("amount", 0) for d in dues)
            lines = [f"Pending dues — total Rs.{total:,.0f}:"]
            for d in dues:
                lines.append(f"• {d['type']}: Rs.{d['amount']:,.0f} (due {d['due_date']})")
            return "\n".join(lines)
        except Exception:
            return "Couldn't fetch your dues right now."

    @mcp.tool()
    async def pay_dues(
        twin_id: str,
        org_id: str,
        user_api_key: str,
        amount: float,
        payment_type: str,
    ) -> str:
        """
        Initiate a payment for rent or maintenance fees.
        Call this when user says: 'Pay my rent', 'Pay maintenance',
        'Clear my dues', 'Pay Rs.5000'.
        payment_type: rent | maintenance | parking | other
        """
        try:
            result = await t2t.initiate_payment(
                user_api_key=user_api_key,
                twin_id=twin_id,
                org_id=org_id,
                amount=amount,
                payment_type=payment_type,
                thread_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
            )
            await save_user_action(twin_id, f"paid {payment_type} Rs.{amount}")
            return (
                f"Payment of Rs.{amount:,.0f} for {payment_type} initiated. "
                f"You'll receive a confirmation shortly."
            )
        except Exception:
            return "Payment could not be processed. Please try again."

    # ── NOTICES ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_notices(org_id: str) -> str:
        """
        Fetch latest society announcements and notices.
        Call this when user says: 'Any announcements?', 'What's the latest notice?',
        'Any updates from the society?'
        """
        try:
            data = await t2t.get_notices(org_id=org_id)
            notices = data.get("notices", [])
            if not notices:
                return "No new notices from the society right now."
            lines = ["Latest notices:"]
            for n in notices[:3]:
                lines.append(f"• {n['title']}: {n['body']}")
            return "\n".join(lines)
        except Exception:
            return "Couldn't fetch notices right now."
