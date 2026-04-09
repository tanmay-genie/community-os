"""
tests/test_t2t.py — Integration tests for the T2T backend.

Tests the full pipeline:
  - Auth
  - Policy Engine (ALLOW / DENY / ESCALATE)
  - Router (/send / /inbox / /reply)
  - Audit trail verification
"""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import status


BASE = "http://test"
ADMIN_HEADERS = {"x-admin-secret": "admin-secret-change-in-prod"}

# Test twin credentials (registered in fixture)
BILAL_KEY = "bilal-test-api-key-2024"
SYED_KEY  = "syed-test-api-key-2024"
BILAL_ID  = "bilal_exec_twin"
SYED_ID   = "syed_product_twin"


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
async def app():
    """Set up test app with in-memory SQLite."""
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["DATABASE_URL_SYNC"] = "sqlite:///:memory:"
    os.environ["REDIS_URL"] = "redis://localhost:6379/1"
    os.environ["APP_ENV"] = "development"

    from app import app as _app
    return _app


@pytest.fixture(scope="session")
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
async def register_twins(client):
    """Register test twins before any tests run."""
    twins = [
        {
            "twin_id": BILAL_ID, "org_id": "GENIE_AI",
            "role": "Founder_CEO", "clearance": "CONFIDENTIAL",
            "raw_api_key": BILAL_KEY, "autonomy_level": "SEMI_AUTONOMOUS",
        },
        {
            "twin_id": SYED_ID, "org_id": "GENIE_AI",
            "role": "Product", "clearance": "INTERNAL",
            "raw_api_key": SYED_KEY, "autonomy_level": "SEMI_AUTONOMOUS",
        },
    ]
    for twin in twins:
        resp = await client.post("/admin/twins/register", json=twin, headers=ADMIN_HEADERS)
        assert resp.status_code in (200, 409), f"Failed to register {twin['twin_id']}: {resp.text}"


def make_envelope(
    from_twin: str,
    to_twin: str,
    intent_type: str = "REQUEST",
    intent_name: str = "REQUEST_STATUS",
    risk_level: str = "LOW",
    thread_id: str | None = None,
    sequence_no: int = 1,
    requires_human_confirmation: bool = False,
) -> dict:
    return {
        "from": {
            "org_id": "GENIE_AI",
            "twin_id": from_twin,
            "role": "Founder_CEO",
            "clearance": "CONFIDENTIAL",
        },
        "to": {
            "org_id": "GENIE_AI",
            "twin_id": to_twin,
        },
        "thread_id": thread_id or str(uuid.uuid4()),
        "sequence_no": sequence_no,
        "intent": {
            "type": intent_type,
            "name": intent_name,
            "risk_level": risk_level,
            "requires_human_confirmation": requires_human_confirmation,
            "sla_minutes": 60,
        },
        "payload": {"test": True},
        "security": {
            "idempotency_key": str(uuid.uuid4()),
            "nonce": str(uuid.uuid4()),
        },
    }


class TestHealth:
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuth:
    async def test_valid_key_passes(self, client):
        """Valid API key should allow inbox access."""
        resp = await client.get(
            f"/t2t/inbox/{BILAL_ID}",
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert resp.status_code == 200

    async def test_invalid_key_rejected(self, client):
        resp = await client.get(
            f"/t2t/inbox/{BILAL_ID}",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    async def test_inbox_mismatch_rejected(self, client):
        """Cannot read another twin's inbox."""
        resp = await client.get(
            f"/t2t/inbox/{SYED_ID}",
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert resp.status_code == 403


class TestPolicyAllow:
    async def test_ceo_can_propose(self, client):
        """CEO role should be allowed to send PROPOSE."""
        envelope = make_envelope(
            from_twin=BILAL_ID,
            to_twin=SYED_ID,
            intent_type="PROPOSE",
            intent_name="PROPOSE_LAUNCH",
        )
        resp = await client.post(
            "/t2t/send",
            json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert data["status"] == "routed"


class TestPolicyDeny:
    async def test_sender_mismatch_denied(self, client):
        """Sending as a different twin ID should be rejected."""
        envelope = make_envelope(from_twin="fake_twin", to_twin=SYED_ID)
        resp = await client.post(
            "/t2t/send",
            json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert resp.status_code == 403


class TestIdempotency:
    async def test_duplicate_key_returns_cached(self, client):
        """Same idempotency key should not re-process."""
        idem_key = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        envelope = make_envelope(BILAL_ID, SYED_ID, thread_id=thread_id)
        envelope["security"]["idempotency_key"] = idem_key

        resp1 = await client.post(
            "/t2t/send", json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert resp1.status_code == 200

        # Second request with same key — should return cached or 409
        resp2 = await client.post(
            "/t2t/send", json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert resp2.status_code in (200, 409)


class TestInboxReply:
    async def test_full_send_inbox_reply_flow(self, client):
        """Full end-to-end: send → inbox → reply CONFIRM."""
        thread_id = str(uuid.uuid4())

        # 1. Bilal sends to Syed
        envelope = make_envelope(
            from_twin=BILAL_ID,
            to_twin=SYED_ID,
            intent_type="PROPOSE",
            intent_name="PROPOSE_LAUNCH",
            thread_id=thread_id,
        )
        send_resp = await client.post(
            "/t2t/send", json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert send_resp.status_code == 200
        message_id = send_resp.json()["message_id"]

        # 2. Syed fetches inbox
        inbox_resp = await client.get(
            f"/t2t/inbox/{SYED_ID}",
            headers={"Authorization": f"Bearer {SYED_KEY}"},
        )
        assert inbox_resp.status_code == 200
        inbox = inbox_resp.json()
        assert any(m["message_id"] == message_id for m in inbox)

        # 3. Syed replies CONFIRM
        reply_resp = await client.post(
            "/t2t/reply",
            json={
                "thread_id": thread_id,
                "original_message_id": message_id,
                "from_twin_id": SYED_ID,
                "intent_type": "CONFIRM",
                "payload": {"confirmed": True},
                "idempotency_key": str(uuid.uuid4()),
            },
            headers={"Authorization": f"Bearer {SYED_KEY}"},
        )
        assert reply_resp.status_code == 200
        assert reply_resp.json()["decision"] == "CONFIRM"


class TestAuditTrail:
    async def test_audit_events_generated(self, client):
        """Sending a message should create audit events."""
        envelope = make_envelope(BILAL_ID, SYED_ID)
        send_resp = await client.post(
            "/t2t/send", json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        assert send_resp.status_code == 200
        message_id = send_resp.json()["message_id"]

        # Query audit trail
        audit_resp = await client.get(
            f"/admin/audit/message/{message_id}",
            headers=ADMIN_HEADERS,
        )
        assert audit_resp.status_code == 200
        events = audit_resp.json()
        event_types = [e["event_type"] for e in events]

        assert "MESSAGE_RECEIVED" in event_types
        assert "MESSAGE_VALIDATED" in event_types
        assert "MESSAGE_ROUTED" in event_types


class TestEscalation:
    async def test_high_risk_triggers_escalation(self, client):
        """HIGH risk + ADVISORY autonomy twin should trigger ESCALATE."""
        # This relies on the policy ABAC rules — CRITICAL risk always escalates
        envelope = make_envelope(
            from_twin=BILAL_ID,
            to_twin=SYED_ID,
            intent_type="EXECUTE",
            intent_name="EXECUTE_DEPLOYMENT",
            risk_level="CRITICAL",
        )
        resp = await client.post(
            "/t2t/send", json=envelope,
            headers={"Authorization": f"Bearer {BILAL_KEY}"},
        )
        # Should be 200 with decision=ESCALATE (not 403)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "ESCALATE"
        assert data.get("escalation_task_id") is not None
