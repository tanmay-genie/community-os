"""Eval runner — executes each golden case against the in-process ARIA app.

In FAST mode (default) the LLM is stubbed so the eval measures:
  - intent classification accuracy
  - tool selection / action_taken
  - structured prefix emission
  - currency hygiene (CAD only, no Rs./₹)
  - language hygiene (English only)
  - pre/post hardening guardrails (no admin leak from member role)

The stub returns empty string so the deterministic safe_format / fallback
path runs — that's the production behavior we want to score, not raw LLM
chatter.

In FULL mode (env: ARIA_EVAL_FULL=1) real Gemini is used and we additionally
score response quality. Requires GOOGLE_API_KEY and burns quota.
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Test environment (must precede chat_api import) ──────────────────────
_DB_FILE = Path(tempfile.gettempdir()) / f"aria_eval_{uuid.uuid4().hex[:8]}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_FILE.as_posix()}"
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "eval-secret-at-least-32-characters-xxx")
os.environ.setdefault("GOOGLE_API_KEY", "test-key-eval")
os.environ.setdefault("T2T_ADMIN_SECRET", "eval-admin")
os.environ.setdefault("ARIA_QUOTA_DAILY_CALLS", "99999")
os.environ.setdefault("ARIA_PERSIST_METRICS", "false")

from fastapi.testclient import TestClient


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    def add(self, r: CaseResult) -> None:
        self.results.append(r)
        self.total += 1
        if r.passed:
            self.passed += 1

    def by_failure_type(self) -> dict[str, int]:
        buckets: dict[str, int] = {}
        for r in self.results:
            for f in r.failures:
                key = f.split(":", 1)[0]
                buckets[key] = buckets.get(key, 0) + 1
        return buckets

    def to_markdown(self) -> str:
        lines = [
            "# ARIA Eval Report",
            "",
            f"**Total cases:** {self.total}",
            f"**Passed:** {self.passed}  ({self.pass_rate:.1%})",
            f"**Failed:** {self.total - self.passed}",
            "",
        ]
        if self.passed < self.total:
            lines += ["## Failure breakdown", ""]
            for kind, count in sorted(self.by_failure_type().items(), key=lambda x: -x[1]):
                lines.append(f"- **{kind}**: {count}")
            lines += ["", "## Failed cases", ""]
            for r in self.results:
                if r.passed:
                    continue
                lines.append(f"### `{r.case_id}`")
                for f in r.failures:
                    lines.append(f"  - {f}")
                if r.raw:
                    sample = (r.raw.get("reply") or "")[:160].replace("\n", " ")
                    lines.append(f"  - reply preview: `{sample}`")
                lines.append("")
        else:
            lines += ["", "All cases passing 🎉"]
        return "\n".join(lines)


def build_test_client(monkeypatch) -> TestClient:
    """Set up the ARIA app with stubbed LLM + seeded DB. Returns TestClient."""
    async def fake_call_gemini(*args, **kwargs):
        # Empty stub: forces chat_api to fall through to safe_format /
        # _summarize_tool_result, which is the deterministic path we want
        # to test in FAST mode.
        return "", {
            "latency_ms": 1.0, "input_tokens": 1, "output_tokens": 1,
            "error": None, "model": "stub", "cached": False, "attempts": 1,
        }

    async def fake_stream(*args, **kwargs):
        if False:
            yield ""

    import aria.ai.llm as llm
    monkeypatch.setattr(llm, "call_gemini", fake_call_gemini)
    monkeypatch.setattr(llm, "stream_gemini", fake_stream)

    import chat_api
    monkeypatch.setattr(chat_api, "ai_call_gemini", fake_call_gemini)
    monkeypatch.setattr(chat_api, "stream_gemini", fake_stream)

    # Seed amenities + community data into the eval DB
    from aria.society.db import create_all_tables
    from aria.society.seed_amenities import seed as seed_amenities
    from aria.society.seed_community import seed as seed_community
    from aria.ai.bylaws import bootstrap_demo_bylaws

    loop = asyncio.get_event_loop()
    loop.run_until_complete(create_all_tables())
    loop.run_until_complete(seed_amenities())
    loop.run_until_complete(seed_community())
    bootstrap_demo_bylaws("maple_heights")

    return TestClient(chat_api.app)


def _login(client: TestClient, role: str) -> str:
    """Issue a JWT for the given role. Member uses tanmay_resident; admin uses ops twin."""
    if role == "admin":
        twin_id, api_key = "communityos_ops", "ops-key-001"
    else:
        twin_id, api_key = "tanmay_resident", "tanmay-key-001"
    r = client.post(
        "/aria/login",
        json={"twin_id": twin_id, "api_key": api_key, "org_id": "maple_heights"},
    )
    assert r.status_code == 200, f"login failed for role={role}: {r.text}"
    return r.json()["access_token"]


def _conv_id_for(case: dict) -> str:
    """Cases with id 'convo:<group> / <step>' share a conversation_id by group."""
    cid = case["id"]
    if cid.startswith("convo:"):
        # 'convo:gym-pick / 1-ambig' → group='gym-pick'
        rest = cid.split(":", 1)[1].strip()
        group = rest.split("/")[0].strip()
        return f"eval-convo-{group}"
    return f"eval-{cid}"


def run_case(client: TestClient, case: dict, token: str) -> CaseResult:
    """Run a single case and return PASS/FAIL with reasons."""
    r = client.post(
        "/aria/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": case["message"],
            "role": case["role"],
            "conversation_id": _conv_id_for(case),
        },
    )
    if r.status_code != 200:
        return CaseResult(
            case_id=case["id"],
            passed=False,
            failures=[f"http: status={r.status_code} body={r.text[:200]}"],
        )
    body = r.json()
    reply = body.get("reply", "") or ""
    action = body.get("action_taken", "") or ""
    failures: list[str] = []

    if "expected_action" in case:
        expected = case["expected_action"] or ""
        if action != expected:
            failures.append(f"action: expected={expected!r} got={action!r}")

    prefix_required = case.get("must_emit_prefix")
    if prefix_required and not reply.startswith(prefix_required):
        failures.append(f"prefix-missing: expected {prefix_required!r}")

    prefix_forbidden = case.get("must_not_emit_prefix")
    if prefix_forbidden and reply.startswith(prefix_forbidden):
        failures.append(f"prefix-leaked: forbidden {prefix_forbidden!r}")

    # For "must contain" we tolerate substring matching; for "must not contain"
    # we use word-boundary matching to avoid false positives (e.g. "hai"
    # matching inside "chairs" or "Heights").
    for needle in case.get("reply_must_contain", []) or []:
        if needle.lower() not in reply.lower():
            failures.append(f"missing: {needle!r}")

    for needle in case.get("reply_must_not_contain", []) or []:
        # Always anchor with a leading word boundary so "Rs." doesn't match
        # inside "loungers." or "Heights" doesn't trigger "hai". For
        # alphanumeric needles we also require trailing word boundary;
        # tokens that end in punctuation (Rs.) are already self-anchoring.
        if needle and needle[-1].isalnum():
            pattern = rf"\b{re.escape(needle)}\b"
        else:
            pattern = rf"\b{re.escape(needle)}"
        if re.search(pattern, reply, flags=re.IGNORECASE):
            failures.append(f"forbidden-token: {needle!r}")

    max_len = case.get("max_reply_length")
    if max_len and len(reply) > max_len:
        failures.append(f"too-long: {len(reply)} > {max_len}")

    return CaseResult(
        case_id=case["id"],
        passed=not failures,
        failures=failures,
        raw=body,
    )


def run_all(client: TestClient, cases: list[dict]) -> EvalReport:
    """Run every case once and aggregate the report."""
    member_token = _login(client, "member")
    admin_token = _login(client, "admin")
    report = EvalReport()
    for case in cases:
        token = admin_token if case["role"] == "admin" else member_token
        report.add(run_case(client, case, token))
    return report
