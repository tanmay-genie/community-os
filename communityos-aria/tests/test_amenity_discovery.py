"""
Integration tests for ARIA's amenity discovery + booking flow.

Covers the post-extraction enhancements:
  - GET /society/amenities returns enriched amenity rows (type, description,
    features, block, floor, image_url)
  - GET /society/amenities/by-type?type=gym returns ALL gyms (not just one)
  - GET /society/amenities/{amenity_id} returns full detail
  - POST /society/bookings with an ambiguous short name returns 400 with a
    disambiguation `options` payload
  - POST /society/bookings with an explicit amenity_id succeeds
  - The seed fixture (`aria.society.seed_amenities.seed`) provisions the
    expected catalogue (>=12 amenities, >=3 gyms)

A dedicated SQLite file is used so we never touch the developer's main DB.
Gemini calls are stubbed; LLM is not exercised here — the assertions target
the HTTP contract that the LLM tools and the frontend cards rely on.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

# ── Test environment (must be set BEFORE importing chat_api) ──────────────
_DB_FILE = Path(tempfile.gettempdir()) / f"aria_amenity_test_{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_FILE.as_posix()}"
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-xxx")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("T2T_ADMIN_SECRET", "test-admin")
os.environ.setdefault("ARIA_QUOTA_DAILY_CALLS", "9999")
os.environ.setdefault("ARIA_PERSIST_METRICS", "false")

import pytest
from fastapi.testclient import TestClient


ORG = "maple_heights"


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    """TestClient against ARIA's real chat_api with a freshly seeded SQLite DB."""
    async def fake_call_gemini(*args, **kwargs):
        return "stub", {
            "latency_ms": 1.0, "input_tokens": 1, "output_tokens": 1,
            "error": None, "model": "stub", "cached": False, "attempts": 1,
        }

    async def fake_stream(*args, **kwargs):
        yield "stub"

    import aria.ai.llm as llm
    monkeypatch_module.setattr(llm, "call_gemini", fake_call_gemini)
    monkeypatch_module.setattr(llm, "stream_gemini", fake_stream)

    import chat_api
    monkeypatch_module.setattr(chat_api, "ai_call_gemini", fake_call_gemini)
    monkeypatch_module.setattr(chat_api, "stream_gemini", fake_stream)

    # Materialise tables and seed the amenity catalogue against this test DB.
    from aria.society.db import create_all_tables
    from aria.society.seed_amenities import seed

    asyncio.get_event_loop().run_until_complete(create_all_tables())
    asyncio.get_event_loop().run_until_complete(seed())

    with TestClient(chat_api.app) as c:
        yield c

    try:
        _DB_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ── /society/amenities ────────────────────────────────────────────────────


def test_amenities_list_returns_enriched_catalogue(client):
    r = client.get("/society/amenities", params={"org_id": ORG})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 12, f"expected >=12 amenities, got {len(rows)}"

    # Every row must carry the new enriched fields
    required = {
        "amenity_id", "name", "display_name", "location",
        "type", "description", "features", "block", "floor", "image_url",
        "capacity_per_slot", "slot_duration_mins", "open_time", "close_time",
    }
    for row in rows:
        missing = required - set(row.keys())
        assert not missing, f"amenity {row.get('display_name')} missing fields: {missing}"
        # features must come back parsed, not as a JSON-encoded string
        assert isinstance(row["features"], list), (
            f"features must be a list (was {type(row['features']).__name__}) "
            f"on {row['display_name']}"
        )


def test_amenities_include_multiple_gyms(client):
    r = client.get("/society/amenities", params={"org_id": ORG})
    assert r.status_code == 200
    rows = r.json()
    gyms = [a for a in rows if a["type"] == "gym"]
    assert len(gyms) >= 3, f"expected >=3 gyms, got {len(gyms)}: {[g['display_name'] for g in gyms]}"

    blocks = {g["block"] for g in gyms if g.get("block")}
    assert len(blocks) >= 2, f"gyms should be spread across blocks, got blocks={blocks}"


# ── /society/amenities/by-type ────────────────────────────────────────────


def test_amenities_by_type_gym(client):
    r = client.get("/society/amenities/by-type", params={"org_id": ORG, "type": "gym"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "gym"
    assert body["count"] >= 3
    items = body["items"]
    assert len(items) == body["count"]
    assert all(a["type"] == "gym" for a in items)


def test_amenities_by_type_unknown_type_returns_empty(client):
    r = client.get(
        "/society/amenities/by-type",
        params={"org_id": ORG, "type": "nonexistent_type"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["items"] == []


# ── /society/amenities/{amenity_id} ───────────────────────────────────────


def test_amenity_detail_by_id(client):
    listing = client.get("/society/amenities", params={"org_id": ORG}).json()
    target = listing[0]
    r = client.get(
        f"/society/amenities/{target['amenity_id']}",
        params={"org_id": ORG},
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["amenity_id"] == target["amenity_id"]
    assert detail["display_name"] == target["display_name"]
    assert detail["type"] == target["type"]


def test_amenity_detail_unknown_id_returns_404(client):
    r = client.get(
        "/society/amenities/does-not-exist",
        params={"org_id": ORG},
    )
    assert r.status_code == 404


# ── /society/bookings (disambiguation + id-based booking) ─────────────────


def test_booking_with_ambiguous_name_returns_disambiguation(client):
    """Booking 'gym' when 3 gyms exist must return options, not silently pick one."""
    r = client.post(
        "/society/bookings",
        params={
            "org_id": ORG, "amenity": "gym",
            "twin_id": "ambig_test_user",
            "date": "tomorrow", "slot_start": "07:00",
        },
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

    # The API may surface the disambiguation either as a 400 with detail,
    # or as 200 with success=False+options. Both are acceptable contracts;
    # only the *content* matters for the LLM/frontend.
    if r.status_code == 200:
        assert body.get("success") is False
        opts = body.get("options") or []
        assert len(opts) >= 3, f"expected >=3 disambiguation options, got {opts!r}"
    else:
        assert r.status_code == 400, r.text
        # FastAPI's default HTTPException puts the payload under "detail"
        detail = body.get("detail")
        if isinstance(detail, dict):
            opts = detail.get("options") or []
        else:
            opts = body.get("options") or []
        assert len(opts) >= 3, f"expected >=3 options in detail, got {detail!r}"


def test_booking_with_amenity_id_succeeds(client):
    body = client.get(
        "/society/amenities/by-type",
        params={"org_id": ORG, "type": "gym"},
    ).json()
    assert body.get("items"), "seed missing gyms"
    target = body["items"][0]

    r = client.post(
        "/society/bookings",
        params={
            "org_id": ORG, "amenity_id": target["amenity_id"],
            "twin_id": "id_booking_user",
            "date": "tomorrow", "slot_start": "08:00",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True, body
    assert body.get("amenity") == target["display_name"]
    assert body.get("booking_id")


def test_booking_missing_selector_returns_400(client):
    r = client.post(
        "/society/bookings",
        params={
            "org_id": ORG, "twin_id": "no_selector_user",
            "date": "tomorrow", "slot_start": "09:00",
        },
    )
    assert r.status_code == 400
