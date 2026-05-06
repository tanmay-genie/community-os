"""
aria/t2t_client.py — Hybrid client for ARIA's twin-to-twin protocol calls.

Two responsibilities, both routed through this single class:
  1. Cross-twin protocol calls — go over HTTP to the T2T backend
     (envelope send, audit summary, escalation queue).
  2. Society domain calls — handled in-process by ARIA itself
     (`aria.society.client`). T2T no longer carries society code.

Method names are kept stable for backwards compatibility with
`chat_api.call_t2t_tool` and `aria.tools.member` so the migration is
surgical and doesn't ripple into call sites.
"""

import asyncio
import time as _time
import httpx
from aria.config import settings
from aria.obs.correlation import HEADER_NAME as _RID_HEADER, current_request_id
from aria.society import client as society_client

OPS_TWIN_ID = "communityos_ops"
CONTRACT_CACHE_TTL = 300


class T2TClient:
    """
    Thin async HTTP wrapper around the T2T backend.
    Tools call this instead of hitting T2T directly.
    """

    def __init__(self):
        self.base = settings.T2T_BASE_URL
        self.admin_secret = settings.T2T_ADMIN_SECRET
        self._contract_cache: dict[tuple[str, str], tuple[str | None, float]] = {}
        self._contract_lock = asyncio.Lock()

    def _rid(self) -> dict:
        rid = current_request_id()
        return {_RID_HEADER: rid} if rid and rid != "-" else {}

    def _bearer(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}", **self._rid()}

    def _admin(self) -> dict:
        return {"X-Admin-Secret": self.admin_secret, **self._rid()}

    async def resolve_contract_id(self, sender_org: str, recipient_org: str) -> str | None:
        """Return an active contract_id between two orgs, or None for same-org."""
        if sender_org == recipient_org:
            return None
        key = tuple(sorted([sender_org, recipient_org]))
        async with self._contract_lock:
            if key in self._contract_cache:
                cached_val, cached_at = self._contract_cache[key]
                if _time.monotonic() - cached_at < CONTRACT_CACHE_TTL:
                    return cached_val
                del self._contract_cache[key]
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self.base}/admin/contracts/{sender_org}",
                    headers=self._admin(),
                )
                resp.raise_for_status()
                contracts = resp.json()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Contract lookup failed for %s: %s", sender_org, e)
            contracts = []
        contract_id: str | None = None
        for c in contracts:
            other = c["org_b_id"] if c["org_a_id"] == sender_org else c["org_a_id"]
            if other == recipient_org and c.get("status") == "ACTIVE":
                contract_id = c["contract_id"]
                break
        async with self._contract_lock:
            self._contract_cache[key] = (contract_id, _time.monotonic())
        return contract_id

    async def _scope(self, sender_org: str, recipient_org: str) -> dict:
        """Build envelope scope, injecting contract_id when cross-org."""
        cid = await self.resolve_contract_id(sender_org, recipient_org)
        return {"contract_id": cid} if cid else {}

    # ── Society: Bookings (in-process; ARIA owns this data) ───────────────

    async def book_slot_direct(
        self,
        org_id: str,
        amenity: str,
        twin_id: str,
        date: str,
        slot_start: str,
        *,
        amenity_id: str | None = None,
    ) -> dict:
        """Directly book a slot. Routes to ARIA's own society service in-process.

        ``amenity_id`` is preferred when set; ``amenity`` (short name) is
        retained for back-compat with the legacy chat flow. When the name
        matches multiple amenities, the underlying service returns a
        disambiguation error with an ``options`` list.
        """
        return await society_client.book_amenity_slot(
            org_id=org_id,
            amenity=amenity,
            twin_id=twin_id,
            date=date,
            slot_start=slot_start,
            amenity_id=amenity_id,
        )

    async def get_available_slots(
        self,
        org_id: str,
        amenity: str = "",
        date: str = "",
        *,
        amenity_id: str | None = None,
    ) -> dict:
        """Fetch available time slots. Routes to ARIA's own society service in-process."""
        return await society_client.list_available_slots(
            org_id=org_id, amenity=amenity, date=date, amenity_id=amenity_id,
        )

    async def cancel_booking_direct(self, org_id: str, booking_id: str) -> dict:
        """Cancel a booking. Routes to ARIA's own society service in-process."""
        return await society_client.cancel_amenity_booking(booking_id=booking_id)

    async def get_amenities_list(self, org_id: str) -> list[dict]:
        """Fetch all amenities. Routes to ARIA's own society service in-process."""
        return await society_client.list_amenities(org_id=org_id)

    async def list_amenities_by_type(self, org_id: str, amenity_type: str) -> list[dict]:
        """Fetch amenities filtered by canonical type."""
        return await society_client.list_amenities_by_type(
            org_id=org_id, amenity_type=amenity_type,
        )

    async def get_amenity(self, org_id: str, amenity_id: str) -> dict | None:
        """Fetch a single amenity by id (or None if not found)."""
        return await society_client.get_amenity(org_id=org_id, amenity_id=amenity_id)

    async def book_amenity(
        self,
        user_api_key: str,
        twin_id: str,
        org_id: str,
        amenity: str,
        slot_time: str,
        date: str,
        thread_id: str,
        idempotency_key: str,
    ) -> dict:
        """
        Sends a BOOK_AMENITY intent through T2T pipeline.
        Goes through: policy → orchestrator → BookingAdapter → audit → notify
        """
        scope = await self._scope(org_id, org_id)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "MEMBER",
                        "clearance": "INTERNAL",
                    },
                    "to": {
                        "org_id": org_id,
                        "twin_id": OPS_TWIN_ID,
                    },
                    "thread_id": thread_id,
                    "sequence_no": 1,
                    "intent": {
                        "type": "REQUEST",
                        "name": "BOOK_AMENITY",
                        "risk_level": "LOW",
                        "sla_minutes": 5,
                    },
                    "payload": {
                        "amenity": amenity,
                        "slot_time": slot_time,
                        "date": date,
                        "org_id": org_id,
                        "requested_by": twin_id,
                    },
                    "scope": scope,
                    "security": {
                        "idempotency_key": idempotency_key,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Complaints / Tickets ───────────────────────────────────────────────

    async def create_ticket(
        self,
        user_api_key: str,
        twin_id: str,
        org_id: str,
        issue: str,
        unit: str,
        priority: str,
        thread_id: str,
        idempotency_key: str,
    ) -> dict:
        """
        Raises a service request ticket through T2T.
        Goes through: policy → orchestrator → ComplaintAdapter → escalation if HIGH
        """
        risk = "HIGH" if priority == "urgent" else "LOW"
        scope = await self._scope(org_id, org_id)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "MEMBER",
                        "clearance": "INTERNAL",
                    },
                    "to": {
                        "org_id": org_id,
                        "twin_id": OPS_TWIN_ID,
                    },
                    "thread_id": thread_id,
                    "sequence_no": 1,
                    "intent": {
                        "type": "REQUEST",
                        "name": "CREATE_TICKET",
                        "risk_level": risk,
                        "sla_minutes": 60,
                    },
                    "payload": {
                        "issue": issue,
                        "unit": unit,
                        "priority": priority,
                        "reported_by": twin_id,
                    },
                    "scope": scope,
                    "security": {
                        "idempotency_key": idempotency_key,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Society: Events (in-process; ARIA owns this data) ─────────────────

    async def get_events(self, org_id: str, date: str) -> dict:
        """Fetch society events. Routes to ARIA's own society service in-process."""
        return await society_client.list_events(org_id=org_id, date=date)

    async def rsvp_event(
        self,
        user_api_key: str,
        twin_id: str,
        org_id: str,
        event_id: str,
        thread_id: str,
        idempotency_key: str,
    ) -> dict:
        """RSVP to a society event through T2T."""
        scope = await self._scope(org_id, org_id)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "MEMBER",
                        "clearance": "INTERNAL",
                    },
                    "to": {"org_id": org_id, "twin_id": OPS_TWIN_ID},
                    "thread_id": thread_id,
                    "sequence_no": 1,
                    "intent": {
                        "type": "REQUEST",
                        "name": "RSVP_EVENT",
                        "risk_level": "LOW",
                        "sla_minutes": 5,
                    },
                    "payload": {"event_id": event_id, "user_twin_id": twin_id},
                    "scope": scope,
                    "security": {"idempotency_key": idempotency_key},
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Society: Dues (in-process; ARIA owns this data) ───────────────────

    async def get_dues(self, twin_id: str, org_id: str) -> dict:
        """Fetch pending dues. Routes to ARIA's own society service in-process."""
        return await society_client.list_dues(twin_id=twin_id, org_id=org_id)

    # ── Payments ──────────────────────────────────────────────────────────

    async def initiate_payment(
        self,
        user_api_key: str,
        twin_id: str,
        org_id: str,
        amount: float,
        payment_type: str,
        thread_id: str,
        idempotency_key: str,
    ) -> dict:
        """Initiate rent / maintenance payment through T2T."""
        scope = await self._scope(org_id, org_id)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "MEMBER",
                        "clearance": "INTERNAL",
                    },
                    "to": {"org_id": org_id, "twin_id": OPS_TWIN_ID},
                    "thread_id": thread_id,
                    "sequence_no": 1,
                    "intent": {
                        "type": "REQUEST",
                        "name": "INITIATE_PAYMENT",
                        "risk_level": "LOW",
                        "sla_minutes": 10,
                    },
                    "payload": {
                        "amount": amount,
                        "payment_type": payment_type,
                        "payer_twin_id": twin_id,
                    },
                    "scope": scope,
                    "security": {"idempotency_key": idempotency_key},
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Society: Notices (in-process; ARIA owns this data) ────────────────

    async def get_notices(self, org_id: str) -> dict:
        """Fetch latest society notices. Routes to ARIA's own society service in-process."""
        return await society_client.list_notices(org_id=org_id)

    # ── Admin: Insights ────────────────────────────────────────────────────

    async def get_audit_summary(self, org_id: str, days: int = 7) -> dict:
        """Pull audit events for admin insights engine."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base}/admin/audit/denied/{org_id}",
                params={"days": days},
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()

    async def get_pending_escalations(self, admin_api_key: str) -> dict:
        """Fetch pending escalation tasks for admin (Bearer auth as admin twin)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base}/t2t/escalations/pending",
                headers=self._bearer(admin_api_key),
            )
            resp.raise_for_status()
            return resp.json()

    async def approve_escalation(self, admin_api_key: str, task_id: str, reason: str) -> dict:
        """Admin approves a pending escalation (Bearer auth as admin twin)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base}/t2t/escalations/{task_id}/approve",
                params={"reason": reason},
                headers=self._bearer(admin_api_key),
            )
            resp.raise_for_status()
            return resp.json()

    async def deny_escalation(self, admin_api_key: str, task_id: str, reason: str) -> dict:
        """Admin denies a pending escalation (Bearer auth as admin twin)."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base}/t2t/escalations/{task_id}/deny",
                params={"reason": reason},
                headers=self._bearer(admin_api_key),
            )
            resp.raise_for_status()
            return resp.json()


# Singleton — all tools import this
t2t = T2TClient()
