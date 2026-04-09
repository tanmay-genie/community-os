"""
aria/t2t_client.py — HTTP client to call the T2T backend.

All MCP tools use this to trigger policy checks,
orchestrator workflows, audit logs, and notifications.
"""

import httpx
from aria.config import settings


class T2TClient:
    """
    Thin async HTTP wrapper around the T2T backend.
    Tools call this instead of hitting T2T directly.
    """

    def __init__(self):
        self.base = settings.T2T_BASE_URL
        self.admin_secret = settings.T2T_ADMIN_SECRET

    def _bearer(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    def _admin(self) -> dict:
        return {"X-Admin-Secret": self.admin_secret}

    # ── Booking ────────────────────────────────────────────────────────────

    async def book_amenity(
        self,
        user_api_key: str,
        twin_id: str,
        org_id: str,
        amenity: str,
        slot_time: str,
        thread_id: str,
        idempotency_key: str,
    ) -> dict:
        """
        Sends a BOOK_AMENITY intent through T2T pipeline.
        Goes through: policy → orchestrator → BookingAdapter → audit → notify
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "RESIDENT",
                        "clearance": "INTERNAL",
                    },
                    "to": {
                        "org_id": org_id,
                        "twin_id": "communityos_ops_twin",
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
                        "requested_by": twin_id,
                    },
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
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "RESIDENT",
                        "clearance": "INTERNAL",
                    },
                    "to": {
                        "org_id": org_id,
                        "twin_id": "communityos_ops_twin",
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
                    "security": {
                        "idempotency_key": idempotency_key,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Events ────────────────────────────────────────────────────────────

    async def get_events(self, org_id: str, date: str) -> dict:
        """Fetch society events for a given date from CommunityOS API."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base}/communityos/events",
                params={"org_id": org_id, "date": date},
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()

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
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "RESIDENT",
                        "clearance": "INTERNAL",
                    },
                    "to": {"org_id": org_id, "twin_id": "communityos_ops_twin"},
                    "thread_id": thread_id,
                    "sequence_no": 1,
                    "intent": {
                        "type": "REQUEST",
                        "name": "RSVP_EVENT",
                        "risk_level": "LOW",
                        "sla_minutes": 5,
                    },
                    "payload": {"event_id": event_id, "user_twin_id": twin_id},
                    "security": {"idempotency_key": idempotency_key},
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Payments ──────────────────────────────────────────────────────────

    async def get_dues(self, twin_id: str, org_id: str) -> dict:
        """Fetch pending dues for a resident."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base}/communityos/dues",
                params={"twin_id": twin_id, "org_id": org_id},
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()

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
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base}/t2t/send",
                headers=self._bearer(user_api_key),
                json={
                    "from": {
                        "org_id": org_id,
                        "twin_id": twin_id,
                        "role": "RESIDENT",
                        "clearance": "INTERNAL",
                    },
                    "to": {"org_id": org_id, "twin_id": "communityos_ops_twin"},
                    "thread_id": thread_id,
                    "sequence_no": 1,
                    "intent": {
                        "type": "EXECUTE",
                        "name": "INITIATE_PAYMENT",
                        "risk_level": "MEDIUM",
                        "sla_minutes": 10,
                    },
                    "payload": {
                        "amount": amount,
                        "payment_type": payment_type,
                        "payer_twin_id": twin_id,
                    },
                    "security": {"idempotency_key": idempotency_key},
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Notices ───────────────────────────────────────────────────────────

    async def get_notices(self, org_id: str) -> dict:
        """Fetch latest society announcements."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base}/communityos/notices",
                params={"org_id": org_id},
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()

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

    async def get_pending_escalations(self, org_id: str) -> dict:
        """Fetch pending escalation tasks for admin."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base}/t2t/escalations/pending",
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()

    async def approve_escalation(self, task_id: str, reason: str) -> dict:
        """Admin approves a pending escalation through ARIA."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base}/t2t/escalations/{task_id}/approve",
                params={"reason": reason},
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()

    async def deny_escalation(self, task_id: str, reason: str) -> dict:
        """Admin denies a pending escalation through ARIA."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base}/t2t/escalations/{task_id}/deny",
                params={"reason": reason},
                headers=self._admin(),
            )
            resp.raise_for_status()
            return resp.json()


# Singleton — all tools import this
t2t = T2TClient()
