"""
Integration tests for ARIA chat_api HTTP endpoints.

Uses FastAPI TestClient against a real app (no mocks for middleware, auth,
rate limiting, correlation IDs). LLM calls are monkeypatched to avoid
hitting Gemini. DB/Redis layers run in-memory fallback when unavailable.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-xxx")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("T2T_ADMIN_SECRET", "test-admin")
os.environ.setdefault("ARIA_QUOTA_DAILY_CALLS", "9999")
os.environ.setdefault("ARIA_PERSIST_METRICS", "false")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    async def fake_call_gemini(*args, **kwargs):
        return "stub reply", {"latency_ms": 1.0, "input_tokens": 5, "output_tokens": 3, "error": None, "model": "gemini-2.5-flash", "cached": False, "attempts": 1}

    async def fake_stream(*args, **kwargs):
        for ch in ["stub ", "reply"]:
            yield ch

    import aria.ai.llm as llm
    monkeypatch_module.setattr(llm, "call_gemini", fake_call_gemini)
    monkeypatch_module.setattr(llm, "stream_gemini", fake_stream)

    import chat_api
    monkeypatch_module.setattr(chat_api, "ai_call_gemini", fake_call_gemini)
    monkeypatch_module.setattr(chat_api, "stream_gemini", fake_stream)

    with TestClient(chat_api.app) as c:
        yield c


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def token(client):
    resp = client.post("/aria/login", json={
        "twin_id": "tanmay_resident", "api_key": "tanmay-key-001", "org_id": "default",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_metrics_endpoint_exposes_prom(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"aria_http_requests_total" in r.content


def test_login_rejects_bad_key(client):
    r = client.post("/aria/login", json={
        "twin_id": "tanmay_resident", "api_key": "wrong", "org_id": "default",
    })
    assert r.status_code == 401


def test_login_rejects_unknown_twin(client):
    r = client.post("/aria/login", json={
        "twin_id": "nobody", "api_key": "x", "org_id": "default",
    })
    assert r.status_code == 401


def test_login_missing_fields_returns_422(client):
    r = client.post("/aria/login", json={"twin_id": "tanmay_resident"})
    assert r.status_code == 422


def test_chat_without_auth_returns_401(client):
    r = client.post("/aria/chat", json={"message": "hi"})
    assert r.status_code == 401


def test_chat_with_bearer_succeeds(client, token):
    r = client.post(
        "/aria/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "what are pool hours?", "conversation_id": "itest-1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "reply" in body
    assert body["conversation_id"] == "itest-1"


def test_chat_echoes_correlation_id(client, token):
    rid = "test-rid-abc"
    r = client.post(
        "/aria/chat",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": rid},
        json={"message": "hi", "conversation_id": "itest-rid"},
    )
    assert r.status_code == 200
    assert r.headers.get("x-request-id") == rid


def test_chat_auto_generates_correlation_id(client, token):
    r = client.post(
        "/aria/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hi", "conversation_id": "itest-rid-auto"},
    )
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid and rid != "-"
    assert len(rid) >= 8


def test_invalid_bearer_returns_401(client):
    r = client.post(
        "/aria/chat",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        json={"message": "hi"},
    )
    assert r.status_code == 401
