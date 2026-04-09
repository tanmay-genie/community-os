"""
aria/tools/member.py — MCP tools for MEMBER side.

All tools call t2t_client which routes through:
  policy/ → orchestrator/ → adapter → audit/ → notify/
"""

import uuid
from aria.t2t_client import t2t
from aria.context.loader import save_user_action


def register(mcp):

    # ── BOOKING ────────────────────────────────────────────────────────────

    @mcp.tool()
    async def book_amenity(
        twin_id: str,
        org_id: str,
        user_api_key: str,
        amenity: str,
        slot_time: str,
    ) -> str:
        """
        Book an amenity (gym, pool, clubhouse, badminton court) for the resident.
        Call this when user says: 'Book gym at 7', 'Reserve pool for tomorrow 6am',
        'I want to use the clubhouse'.
        amenity: gym | pool | clubhouse | badminton | tennis
        slot_time: natural time like '7pm', '6:30am tomorrow'
        """
        try:
            result = await t2t.book_amenity(
                user_api_key=user_api_key,
                twin_id=twin_id,
                org_id=org_id,
                amenity=amenity,
                slot_time=slot_time,
                thread_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
            )
            await save_user_action(twin_id, f"booked {amenity} at {slot_time}")
            decision = result.get("decision", "ALLOW")
            if decision == "ALLOW":
                return f"Booked! {amenity.title()} is reserved for you at {slot_time}."
            elif decision == "ESCALATE":
                return f"Your booking request is pending approval. You'll be notified shortly."
            else:
                return f"Sorry, couldn't book {amenity} at {slot_time}. Slot may be taken."
        except Exception as e:
            return f"Booking service is unavailable right now. Please try again in a moment."

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
            lines = [f"Pending dues — total ₹{total:,.0f}:"]
            for d in dues:
                lines.append(f"• {d['type']}: ₹{d['amount']:,.0f} (due {d['due_date']})")
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
        'Clear my dues', 'Pay ₹5000'.
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
            await save_user_action(twin_id, f"paid {payment_type} ₹{amount}")
            return (
                f"Payment of ₹{amount:,.0f} for {payment_type} initiated. "
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
