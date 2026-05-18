"""
chat_api.py — ARIA Chat API (Text Mode) — AI-enhanced architecture.
Run: uvicorn chat_api:app --reload --port 8080

Pipeline per message:
  1. Safety — prompt-injection detection + sanitization
  2. Sentiment + language + anomaly signals
  3. Hybrid intent classification (regex + embeddings + lexical)
  4. Tool execution (T2T or simulated)
  5. Smart-routed Gemini call with RAG context + cached prompt
  6. Hallucination guard + confidence scoring
  7. Proactive follow-up suggestions
  8. Streaming endpoint available at /aria/chat/stream
"""

import asyncio
import json
import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from aria.ai.anomaly import detector as anomaly_detector
from aria.ai.announcement import draft_announcement
from aria.ai.confidence import score_decision
from aria.ai.conversation_memory import memory as conv_memory, build_summarization_prompt
from aria.ai.conversation_state import (
    PENDING as pending_actions,
    park_amount,
    park_disambiguation,
    park_yes_no,
    try_resume,
)
from aria.ai.hallucination_guard import safe_format, validate_reply
from aria.ai.intent_classifier import classify_intent
from aria.ai.language import detect_language, language_hint
from aria.ai.llm import call_gemini as ai_call_gemini, stream_gemini
from aria.ai.metrics import metrics
from aria.ai.quota import QuotaExceededError, check_quota
from aria.ai.model_router import choose_model
from aria.ai.moderation import moderate
from aria.ai.proactive import suggest_followups
from aria.ai.rag import bootstrap_default_index, retrieve_context
from aria.ai.safety import detect_injection, sanitize_user_input, wrap_user_input
from aria.ai.sentiment import analyze as analyze_sentiment, soften_tone_hint
from aria.ai.triage import triage_ticket
from aria.auth import ADMIN_API_KEY, ADMIN_TWIN_ID, TWIN_API_KEYS, authenticate, issue_token
from aria.config import settings
from aria.obs.correlation import RequestIDMiddleware, install_logging
from aria.obs.prom import PromMiddleware, rag_chunks_gauge, render_metrics
from aria.context.loader import build_context_string, save_user_action
from aria.prompts.templates import get_prompt
from aria.society.db import create_all_tables as create_society_tables, dispose_engine as dispose_society_engine
from aria.society.routes import society_router
from aria.t2t_client import t2t

logger = logging.getLogger("aria.chat_api")

conversation_store: dict[str, list] = defaultdict(list)
pending_booking: dict[str, dict] = {}

def _rate_limit_key(request: Request) -> str:
    """Per-twin when authenticated, else per-IP."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        import jwt as _jwt
        try:
            payload = _jwt.decode(auth[7:].strip(), settings.JWT_SECRET, algorithms=["HS256"], options={"verify_exp": False})
            return f"twin:{payload.get('sub', 'unknown')}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"


install_logging()
limiter = Limiter(key_func=_rate_limit_key, default_limits=["200/minute"])
app = FastAPI(title="ARIA Chat API", version="3.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(PromMiddleware)

_allowed = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()] or ["*"]
if settings.APP_ENV.lower() in ("production", "prod", "staging") and "*" in _allowed:
    raise RuntimeError("ALLOWED_ORIGINS must be explicit in production (cannot be '*')")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    allow_credentials=True,
)


@app.on_event("startup")
async def _startup() -> None:
    try:
        size = bootstrap_default_index()
        rag_chunks_gauge.set(size)
        logger.info("RAG index ready: %d chunks", size)
    except Exception as e:
        logger.warning("RAG bootstrap failed: %s", e)

    try:
        from aria.ai.bylaws import bootstrap_demo_bylaws
        n = bootstrap_demo_bylaws("maple_heights")
        logger.info("Bylaw index ready for maple_heights: %d sections", n)
    except Exception as e:
        logger.warning("Bylaw bootstrap failed: %s", e)

    # Society tables live in ARIA's DB now (extracted from T2T). Create them
    # in dev/test; production should use Alembic migrations under
    # `communityos-aria/alembic/`.
    if settings.APP_ENV.lower() not in ("production", "prod", "staging"):
        try:
            await create_society_tables()
        except Exception as e:
            logger.warning("Society DB bootstrap failed: %s", e)

    # One-shot demo bootstrap: when ARIA_BOOTSTRAP_DEMO_DATA=true (set by
    # the Render blueprint), create schema + seed Maple Heights data so a
    # fresh Render deploy is immediately demo-ready. Idempotent — the
    # seed scripts skip rows that already exist.
    if os.getenv("ARIA_BOOTSTRAP_DEMO_DATA", "").lower() == "true":
        try:
            await create_society_tables()
            from aria.society.seed_amenities import seed as seed_amenities
            from aria.society.seed_community import seed as seed_community
            await seed_amenities()
            await seed_community()
            logger.info("Demo bootstrap: society tables + Maple Heights seed loaded")
        except Exception as e:
            logger.warning("Demo bootstrap failed: %s", e)


@app.on_event("shutdown")
async def _shutdown() -> None:
    try:
        await dispose_society_engine()
    except Exception:
        pass


app.include_router(society_router)


@app.get("/metrics", include_in_schema=False)
async def prom_metrics():
    return render_metrics()


class ChatRequest(BaseModel):
    twin_id: str = ""
    org_id: str = ""
    user_api_key: str = ""
    role: str = "member"
    message: str
    conversation_id: str = ""


class LoginRequest(BaseModel):
    twin_id: str
    org_id: str
    api_key: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    twin_id: str
    role: str


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    action_taken: str = ""
    confidence: float = 0.0
    confidence_label: str = ""
    suggestions: list[dict] = []
    signals: dict = {}


INTENT_PATTERNS = {
    # Discovery intents — must come BEFORE book_amenity so we don't accidentally
    # treat "what amenities are here" as a booking request.
    "list_society_amenities": [
        r"^\s*(?:what|which|tell me|show me|list|all)\s+(?:are\s+the\s+)?(?:amenities|facilities|things|stuff)\b",
        r"^\s*(?:show|list)\s+(?:me\s+)?(?:all\s+)?(?:amenities|facilities)\b",
        r"\bwhat\s+(?:can|could)\s+i\s+book\b",
        r"\b(?:available)\s+amenities\b",
        r"\bbuilding\s+(?:has|amenities)\b",
    ],
    "find_amenities_by_type": [
        r"\b(?:show|list|all|how many)\s+(?:me\s+)?(?:all\s+|the\s+)?(gyms?|pools?|halls?|courts?|studios?|spas?|libraries|clubhouses?)\b",
        r"\b(gyms?|pools?|halls?|studios?|spas?|libraries)\s+(?:available|in\s+(?:the\s+)?building|here)",
        r"\b(badminton\s+courts?|tennis\s+courts?)\b\s*(?:available|list)?",
    ],
    "get_amenity_info": [
        r"\btell\s+me\s+about\s+(?:the\s+)?(.+?\b(?:gym|pool|hall|court|spa|studio|clubhouse|library))\b",
        r"\b(?:details|info|information)\s+(?:on|about|of)\s+(?:the\s+)?(.+)\b",
        r"\bwhat'?s\s+(?:in|inside)\s+(?:the\s+)?(.+\b(?:gym|pool|hall|spa|studio|clubhouse|library))\b",
        r"\bdescribe\s+(?:the\s+)?(.+)\b",
    ],
    "show_amenity_slots": [
        r"\b(gym|pool|clubhouse|badminton|tennis|community hall|hall|spa|studio|library)\s+slots?\b",
        r"\bslots?\s+(?:for|of)\s+(?:the\s+)?(gym|pool|clubhouse|badminton|tennis|hall|spa|studio|library)\b",
        r"\bwhen\s+can\s+i\s+book\s+(?:the\s+)?(gym|pool|clubhouse|badminton|tennis|hall|spa|studio|library)\b",
        r"\b(?:available\s+)?timings?\s+(?:for|of)\s+(?:the\s+)?(gym|pool|clubhouse|badminton|tennis|hall|spa|studio|library)\b",
    ],
    "book_amenity": [
        r"book\s+(?:the\s+|a\s+|an\s+)?(gym|pool|clubhouse|badminton|tennis|community hall)",
        r"reserve\s+(?:the\s+|a\s+|an\s+)?(gym|pool|clubhouse|badminton|tennis|community hall)",
        r"(gym|pool|clubhouse|badminton|tennis)\s+(book|reserve|slot)",
        r"(?:i\s+)?(?:want|need|like)\s+(?:to\s+)?(?:book|reserve|use)\s+(?:the\s+|a\s+)?(gym|pool|clubhouse|badminton|tennis|community hall)",
        r"(?:can\s+(?:i|you)\s+)?book\s+(?:the\s+|a\s+)?(gym|pool|clubhouse|badminton|tennis|community hall)",
        r"(?:is\s+(?:the\s+)?)(gym|pool|clubhouse|badminton|tennis|community hall)\s+(?:available|free)",
    ],
    "cancel_booking": [
        r"cancel\s+(?:my\s+)?(?:booking|reservation|slot)",
        r"cancel\s+(?:the\s+)?(gym|pool|clubhouse|badminton|tennis|community hall)\s*(?:booking|reservation|slot)?",
        r"(?:i\s+)?(?:want|need)\s+to\s+cancel",
        r"cancel\s+(?:booking\s+)?(?:id\s+)?([A-Z0-9\-]+)",
    ],
    "create_ticket": [
        r"(ac|air\s*condition(?:er|ing)?|lift|elevator|water|plumbing|electric(?:ity|al)?|light|led|parking|gate|intercom|cctv|camera)\s+(?:is\s+)?(not\s+working|broken|issue|problem|stuck|leakage|leak|flooding|flickering|down|faulty|damaged)",
        r"(not\s+working|broken|stuck|leaking|flooding|flickering)\s+(ac|lift|water|light|led)",
        r"(?:please\s+)?raise\s+(?:a\s+)?ticket",
        r"(?:please\s+)?report\s+(?:a\s+)?(issue|problem|maintenance|complaint)",
        r"(?:there(?:'s| is)\s+(?:a|an)\s+)?(issue|problem|leak|flood|fire)\s+(?:in|at|with)",
        r"urgent\s*(issue|problem|ticket|!)",
        r"(water\s+leak|gas\s+leak|fire|flood)",
        r"(?:my|the|our)\s+(ac|lift|water|light|parking|gate|intercom)\s+(?:has\s+)?(?:a\s+)?(?:problem|issue)",
    ],
    "get_society_events": [
        r"(?:what|any|show|list|tell)\s*(?:me\s+)?(?:are\s+)?(?:the\s+)?(events?|happening|going\s+on)",
        r"events?\s+(?:today|tomorrow|this\s+week|upcoming|next\s+week)",
        r"what'?s\s+(?:happening|on\s+today|going\s+on)",
        r"(?:is\s+)?(?:there\s+)?(?:any(?:thing)?)\s+(?:happening|planned|scheduled)",
    ],
    "rsvp_to_event": [
        r"(?:sign\s+me\s+up|rsvp|join|attend|register)\s+(?:for|to)?\s*",
        r"i'?(?:m|ll\s+be)\s+(?:coming|attending|joining|there)",
        r"(?:count\s+me\s+in|put\s+me\s+down)",
    ],
    "check_dues": [
        r"(?:pending|check|my|any|show)\s*(?:my\s+)?(?:dues?|payment|balance|owe|fees?|strata\s+fee|maintenance\s+fee)",
        r"(?:how\s+much|what)\s+(?:do\s+i\s+)?(?:owe|due|pending)",
        r"(?:is\s+)?my\s+(?:rent|strata\s+fee|maintenance\s+fee)\s+(?:paid|due|pending)",
        r"(?:do\s+i\s+have\s+any)\s+(?:pending\s+)?(?:dues|payments|balance|fees)",
        r"\b(?:any|pending)\s+(?:fees?|strata|maintenance)\b",
    ],
    "pay_dues": [
        r"pay\s+(?:my\s+)?(?:rent|maintenance|dues|bill|strata\s+fee|fees?)",
        r"(?:clear|settle)\s+(?:my\s+)?(?:dues|payment|balance|fees?)",
        r"pay\s+.*\d+",
        r"(?:i\s+)?(?:want|need)\s+to\s+pay",
        r"make\s+(?:a\s+)?payment",
    ],
    "get_notices": [
        r"(?:any|new|latest|show|get|read)\s*(?:my\s+)?(?:notices?|announcement|update|circular)",
        r"(?:notices?|announcement)\s*(?:from|of)\s*(?:the\s+)?(?:society|building)",
        r"(?:society|building)\s+(?:update|news|notice)",
        r"(?:what'?s\s+)?new\s+(?:in\s+(?:the\s+)?)?(?:society|building)",
    ],
    "lookup_bylaws": [
        # Direct bylaw / rule queries — must come BEFORE generic intents so
        # "what does the bylaw say about pets" doesn't fall to get_notices.
        r"\b(?:bylaw|by-law|rule|rules|policy|policies|condo\s+rule|strata\s+rule)\b",
        r"\b(?:am\s+i|are\s+(?:we|residents)|can\s+i|may\s+i|am\s+i\s+allowed)\b",
        r"\b(?:is|are)\s+(?:.+?)\s+(?:allowed|permitted|prohibited|banned|legal|ok|okay)\b",
        r"\bwhat\s+(?:does\s+the\s+)?(?:bylaw|rule|policy|condo|strata)\s+say\b",
        r"\bquiet\s+hours?\b",
        r"\b(?:pet|dog|cat)s?\s+(?:rules?|policy|allowed|restriction|permitted)\b",
        r"\b(?:are\s+)?pets?\s+(?:allowed|permitted)\b",
        r"\b(?:hardwood|flooring|floor\s+covering)\b",
        r"\b(?:smoking|smoke|cannabis|vape|vaping)\b",
        r"\b(?:bbq|barbecue|barbeque|grill)\b",
        r"\b(?:short[- ]term\s+rental|airbnb|vrbo|list\s+my\s+unit)\b",
        r"\bmove[- ](?:in|out)\b",
        r"\b(?:install|installation)\s+(?:hardwood|flooring|wood|tile|carpet)\b",
    ],
    "get_society_insights": [
        r"(society|community)\s*(summary|insight|report|health|overview|status)",
        r"give\s+me\s+(a\s+)?summary",
        r"(what'?s|how'?s)\s+(the\s+)?society\s+(doing|status)",
    ],
    "get_pending_escalations": [
        r"(pending|show|list|get)\s*(escalation|approval|queue)",
        r"(what|any)\s*(needs|pending)\s*(my\s+)?(attention|approval)",
        r"escalation\s+(queue|list)",
    ],
    "approve_escalation": [
        r"approve\s+(escalation|task|the|esc)",
        r"green\s*light",
        r"approve\s+(it|that|this)",
    ],
    "deny_escalation": [
        r"deny\s+(escalation|task|the|esc)",
        r"reject\s+(escalation|task|the|it|that)",
        r"deny\s+(it|that|this)",
    ],
    "generate_announcement": [
        r"(write|draft|create|generate)\s+(an?\s+)?(announcement|notice|circular)",
    ],
    "moderate_content": [
        r"(check|moderate|review|flag)\s+(this\s+)?(message|content|post|text)\s+(for\s+)?violation",
        r"is\s+this\s+(ok|okay|appropriate|safe)",
    ],
}

ACTION_MAP = {
    "list_society_amenities": "LISTED_AMENITIES",
    "find_amenities_by_type": "FILTERED_AMENITIES",
    "get_amenity_info": "FETCHED_AMENITY_DETAIL",
    "show_amenity_slots": "FETCHED_AMENITY_SLOTS",
    "book_amenity": "BOOKED_AMENITY",
    "cancel_booking": "BOOKING_CANCELLED",
    "create_ticket": "TICKET_RAISED",
    "get_society_events": "FETCHED_EVENTS",
    "rsvp_to_event": "RSVP_CONFIRMED",
    "check_dues": "CHECKED_DUES",
    "pay_dues": "PAYMENT_INITIATED",
    "get_notices": "FETCHED_NOTICES",
    "lookup_bylaws": "BYLAW_LOOKED_UP",
    "get_society_insights": "FETCHED_INSIGHTS",
    "get_pending_escalations": "FETCHED_ESCALATIONS",
    "approve_escalation": "ESCALATION_APPROVED",
    "deny_escalation": "ESCALATION_DENIED",
    "generate_announcement": "ANNOUNCEMENT_DRAFTED",
    "moderate_content": "CONTENT_MODERATED",
}

ADMIN_INTENTS = {"get_society_insights", "get_pending_escalations", "approve_escalation",
                 "deny_escalation", "generate_announcement", "moderate_content"}

# Keywords that strongly indicate an admin-style query. If a member sends one
# of these, we must NOT fall through to the embedding classifier — it tends
# to mis-bucket "Show me all pending escalations" into list_society_amenities
# because of the "show me all" stem. Returning None here lets the LLM respond
# politely ("I can't do that, but I can…") without firing a wrong tool.
ADMIN_KEYWORDS = (
    "escalation", "escalations",
    "approve", "deny", "reject",
    "society summary", "society insight", "society report", "society overview",
    "society health", "society status",
    "announcement", "circular", "draft",
    "moderate", "moderation", "violation", "flag this",
    "residents complain", "complaint trend", "complaints trend",
    "sla", "ticket trend", "ticket trends",
)


def detect_intent_hybrid(message: str, role: str, conv_id: str = "") -> tuple[str | None, float, str]:
    """
    Hybrid intent detection:
      1. Multi-turn pending booking context
      2. Regex patterns (fast, exact)
      3. Admin-keyword guard (prevents embedding misclassification for members)
      4. Embeddings/lexical classifier (fuzzy)
    Returns (intent, confidence, method).
    """
    msg_lower = message.lower().strip()

    if conv_id and conv_id in pending_booking:
        if re.search(r'(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)', msg_lower) \
                or re.match(r'^(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)?$', msg_lower) \
                or re.match(r'^(\d{1,2})$', msg_lower.strip()):
            return "book_amenity", 0.95, "pending_context"

    for intent, patterns in INTENT_PATTERNS.items():
        if intent in ADMIN_INTENTS and role != "admin":
            continue
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                return intent, 0.95, "regex"

    if role != "admin" and any(kw in msg_lower for kw in ADMIN_KEYWORDS):
        return None, 0.0, "admin_query_blocked"

    pred = classify_intent(message, role)
    if pred.intent:
        return pred.intent, pred.confidence, pred.method
    return None, 0.0, "none"


def extract_args(intent: str, message: str, conv_id: str = "") -> dict:
    msg_lower = message.lower()
    args: dict = {}

    if intent == "list_society_amenities":
        # No args needed — org_id is injected at call time.
        return args

    if intent == "lookup_bylaws":
        # Pass the original message as the question; the bylaw module
        # does its own retrieval ranking. Strip leading polite hedges so
        # they don't pollute the embedding query.
        cleaned = re.sub(
            r"^\s*(hi|hey|hello|please|excuse me|quick question|sorry)[,!]?\s+",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        args["question"] = cleaned or message
        return args

    if intent == "find_amenities_by_type":
        TYPE_KEYWORDS = {
            "gym": "gym", "gyms": "gym",
            "pool": "pool", "pools": "pool",
            "clubhouse": "clubhouse", "clubhouses": "clubhouse",
            "hall": "hall", "halls": "hall", "community hall": "hall", "banquet hall": "hall",
            "badminton": "court_badminton", "badminton court": "court_badminton",
            "tennis": "court_tennis", "tennis court": "court_tennis",
            "spa": "spa", "spas": "spa",
            "studio": "studio", "studios": "studio", "yoga": "studio",
            "library": "library", "libraries": "library",
        }
        for kw, canonical in TYPE_KEYWORDS.items():
            if kw in msg_lower:
                args["amenity_type"] = canonical
                break
        return args

    if intent == "get_amenity_info":
        # Try to capture the amenity reference. We pass the raw query after
        # stripping common preambles; the tool will resolve by id-or-name.
        cleaned = re.sub(
            r"^\s*(?:tell\s+me\s+about|details\s+(?:on|about|of)|info\s+(?:on|about)|describe|what'?s\s+in|what\s+is)\s+",
            "",
            msg_lower,
        ).strip().strip("?.!,")
        if cleaned.startswith("the "):
            cleaned = cleaned[4:]
        args["amenity_id_or_name"] = cleaned or message.strip()
        return args

    if intent == "show_amenity_slots":
        for amenity in [
            "gym", "pool", "clubhouse", "badminton", "tennis", "community hall",
            "hall", "spa", "studio", "library",
        ]:
            if amenity in msg_lower:
                args["amenity_id_or_name"] = amenity
                break
        if "amenity_id_or_name" not in args:
            args["amenity_id_or_name"] = message.strip()
        if "tomorrow" in msg_lower:
            args["date"] = "tomorrow"
        elif "today" in msg_lower:
            args["date"] = "today"
        else:
            args["date"] = "today"
        return args

    if intent == "book_amenity":
        pending = pending_booking.get(conv_id, {}) if conv_id else {}

        for amenity in ["gym", "pool", "clubhouse", "badminton", "tennis", "community hall"]:
            if amenity in msg_lower:
                args["amenity_name"] = amenity
                break
        if "amenity_name" not in args and pending.get("amenity"):
            args["amenity_name"] = pending["amenity"]

        time_match = re.search(r'(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)', msg_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            period = time_match.group(3)
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            args["time_slot"] = f"{hour:02d}:{minute:02d}"
        else:
            bare_24 = re.search(r'\b([01]?\d|2[0-3]):([0-5]\d)\b', msg_lower)
            if bare_24:
                args["time_slot"] = f"{int(bare_24.group(1)):02d}:{bare_24.group(2)}"
            elif pending.get("available_slots"):
                num_match = re.match(r'^(\d{1,2})$', msg_lower.strip())
                if num_match:
                    idx = int(num_match.group(1)) - 1
                    slots = pending["available_slots"]
                    if 0 <= idx < len(slots):
                        args["time_slot"] = slots[idx]["start"]

        if "tomorrow" in msg_lower:
            args["date"] = "tomorrow"
        elif "today" in msg_lower:
            args["date"] = "today"
        else:
            day_match = re.search(r'(monday|tuesday|wednesday|thursday|friday|saturday|sunday)', msg_lower)
            if day_match:
                args["date"] = day_match.group(1).title()
            elif pending.get("date"):
                args["date"] = pending["date"]
            else:
                args["date"] = "today"

        unit_match = re.search(r'([a-zA-Z][\-]?\d{3,4})', message)
        if unit_match:
            args["unit"] = unit_match.group(1)

    elif intent == "cancel_booking":
        booking_match = re.search(r'([A-Fa-f0-9\-]{8,})', message)
        if booking_match:
            args["booking_id"] = booking_match.group(1)
        for amenity in ["gym", "pool", "clubhouse", "badminton", "tennis", "community hall"]:
            if amenity in msg_lower:
                args["amenity_name"] = amenity
                break

    elif intent == "create_ticket":
        args["subject"] = message[:80]
        args["description"] = message
        unit_match = re.search(r'([a-zA-Z][\-]?\d{3,4})', message)
        if unit_match:
            args["unit"] = unit_match.group(1)

    elif intent == "rsvp_to_event":
        event_match = re.search(r'(?:for|to)\s+(?:the\s+)?(.+?)(?:\s*$|\.)', message, re.IGNORECASE)
        if event_match:
            args["event_name"] = event_match.group(1).strip()
        else:
            args["event_name"] = "event"

    elif intent == "check_dues":
        unit_match = re.search(r'([a-zA-Z][\-]?\d{3,4})', message)
        if unit_match:
            args["unit"] = unit_match.group(1)

    elif intent == "pay_dues":
        amount_match = re.search(r'[\u20B9₹]?\s*(\d[\d,]*)', message)
        if amount_match:
            args["amount"] = float(amount_match.group(1).replace(",", ""))

    elif intent in ("approve_escalation", "deny_escalation"):
        task_match = re.search(r'(ESC[\-_]?\w+)', message, re.IGNORECASE)
        args["task_id"] = task_match.group(1).upper() if task_match else ("MOST_URGENT" if intent == "approve_escalation" else "LATEST")
        reason_match = re.search(r'reason[:\s]+(.+)', message, re.IGNORECASE)
        if reason_match:
            args["reason"] = reason_match.group(1).strip()

    elif intent == "get_society_insights":
        days_match = re.search(r'(\d+)\s*days?', msg_lower)
        if days_match:
            args["days"] = int(days_match.group(1))

    elif intent == "generate_announcement":
        about_match = re.search(r'about\s+(.+)', message, re.IGNORECASE)
        if about_match:
            args["topic"] = about_match.group(1).strip()
            args["details"] = about_match.group(1).strip()
        else:
            args["topic"] = message

    elif intent == "moderate_content":
        quote_match = re.search(r'["\u201C](.+?)["\u201D]', message)
        args["content"] = quote_match.group(1) if quote_match else message

    return args


async def call_t2t_tool(func_name: str, args: dict, twin_id: str, org_id: str, conv_id: str = "") -> dict:
    api_key = TWIN_API_KEYS.get(twin_id, "tanmay-key-001")
    thread_id = str(uuid.uuid4())
    idem_key = str(uuid.uuid4())

    try:
        if func_name == "list_society_amenities":
            items = await t2t.get_amenities_list(org_id=org_id)
            return {"status": "success", "scope": "all", "items": items, "count": len(items)}

        elif func_name == "find_amenities_by_type":
            atype = args.get("amenity_type", "")
            if not atype:
                return {"status": "error", "message": "Could not detect amenity type."}
            items = await t2t.list_amenities_by_type(org_id=org_id, amenity_type=atype)
            return {"status": "success", "scope": "by_type", "type": atype, "items": items, "count": len(items)}

        elif func_name == "get_amenity_info":
            ref = args.get("amenity_id_or_name", "").strip()
            if not ref:
                return {"status": "error", "message": "Please tell me which amenity to look up."}
            info = await t2t.get_amenity(org_id=org_id, amenity_id=ref) if "-" in ref and len(ref) > 16 else None
            if not info:
                # Fall back: scan the list for a name/display_name match.
                items = await t2t.get_amenities_list(org_id=org_id)
                needle = ref.lower()
                for it in items:
                    if (
                        it.get("display_name", "").lower() == needle
                        or it.get("name", "").lower() == needle
                        or needle in it.get("display_name", "").lower()
                    ):
                        info = it
                        break
            if not info:
                return {"status": "error", "message": f"I couldn't find '{ref}' in our amenities."}
            return {"status": "success", "amenity": info}

        elif func_name == "show_amenity_slots":
            ref = args.get("amenity_id_or_name", "").strip()
            booking_date = args.get("date", "today")
            if not ref:
                return {"status": "error", "message": "Please tell me which amenity to check slots for."}
            looks_like_id = "-" in ref and len(ref) >= 16
            slots_data = await t2t.get_available_slots(
                org_id=org_id,
                amenity="" if looks_like_id else ref,
                amenity_id=ref if looks_like_id else None,
                date=booking_date,
            )
            if slots_data.get("error") and slots_data.get("options"):
                return {
                    "status": "need_disambiguation",
                    "message": f"Multiple matches for '{ref}' — please specify which one.",
                    "options": slots_data["options"],
                }
            if slots_data.get("error"):
                return {"status": "error", "message": slots_data["error"]}
            return {
                "status": "success",
                "amenity": slots_data.get("amenity", ref),
                "amenity_id": slots_data.get("amenity_id", ""),
                "location": slots_data.get("location", ""),
                "date": slots_data.get("date", booking_date),
                "slots": slots_data.get("slots", []),
            }

        elif func_name == "cancel_booking":
            booking_id = args.get("booking_id", "")
            if not booking_id:
                return {"status": "error", "message": "Please provide the booking ID to cancel (e.g., 'cancel booking ABC12345')."}
            result = await t2t.cancel_booking_direct(org_id=org_id, booking_id=booking_id)
            if result.get("success"):
                return {"status": "cancelled", "booking_id": booking_id,
                        "message": f"Booking {booking_id[:8].upper()} has been cancelled."}
            return {"status": "error", "message": result.get("error", "Cancellation failed")}

        elif func_name == "book_amenity":
            amenity = args.get("amenity_name", "gym")
            time_slot = args.get("time_slot", "")
            booking_date = args.get("date", "today")

            if not time_slot:
                slots_data = await t2t.get_available_slots(
                    org_id=org_id, amenity=amenity, date=booking_date,
                )
                if slots_data.get("error"):
                    return {"status": "error", "message": slots_data["error"]}
                available = [s for s in slots_data.get("slots", []) if s.get("available")]
                if conv_id:
                    pending_booking[conv_id] = {
                        "amenity": amenity, "date": booking_date,
                        "available_slots": available[:8],
                    }
                return {
                    "status": "need_slot_selection",
                    "amenity": slots_data.get("amenity", amenity),
                    "location": slots_data.get("location", ""),
                    "date": slots_data.get("date", booking_date),
                    "available_slots": available[:8],
                    "total_available": len(available),
                    "message": f"Found {len(available)} available slots for {slots_data.get('amenity', amenity)}.",
                }

            t2t_result = await t2t.book_amenity(
                user_api_key=api_key, twin_id=twin_id, org_id=org_id,
                amenity=amenity, slot_time=time_slot, date=booking_date,
                thread_id=thread_id, idempotency_key=idem_key,
            )
            if t2t_result.get("decision") == "DENY":
                return {"status": "denied", "message": t2t_result.get("reason", "Policy denied"),
                        "t2t_response": t2t_result}

            from datetime import date as date_cls, timedelta as td
            today = date_cls.today()
            if booking_date == "today":
                target_iso = today.isoformat()
            elif booking_date == "tomorrow":
                target_iso = (today + td(days=1)).isoformat()
            else:
                target_iso = booking_date

            booking = await t2t.book_slot_direct(
                org_id=org_id, amenity=amenity, twin_id=twin_id,
                date=target_iso, slot_start=time_slot,
            )
            if booking.get("success"):
                if conv_id and conv_id in pending_booking:
                    del pending_booking[conv_id]
                anomaly_detector.record_booking(twin_id, amenity, time_slot)
                return {
                    "status": "booked",
                    "booking_id": booking["booking_id"],
                    "amenity": booking.get("amenity", amenity),
                    "location": booking.get("location", ""),
                    "date": booking.get("date", target_iso),
                    "slot": booking.get("slot", time_slot),
                    "remaining_capacity": booking.get("remaining_capacity"),
                    "message": f"{booking.get('amenity', amenity)} booked! Slot: {booking.get('slot', time_slot)} on {booking.get('date', target_iso)}. Booking ID: {booking['booking_id'][:8].upper()}",
                }
            return {"status": "error", "message": booking.get("error", "Booking failed"), "t2t_approved": True}

        elif func_name == "create_ticket":
            issue = args.get("description", args.get("subject", "Issue reported"))
            unit = args.get("unit", "unknown")
            triage = await triage_ticket(issue)
            priority = triage.get("priority", "normal")
            args["priority"] = priority

            result = await t2t.create_ticket(
                user_api_key=api_key, twin_id=twin_id, org_id=org_id,
                issue=issue, unit=unit, priority=priority,
                thread_id=thread_id, idempotency_key=idem_key,
            )
            anomaly_detector.record_ticket(unit, priority, issue)
            return {
                "status": result.get("status", "success"),
                "t2t_response": result,
                "ticket_id": result.get("message_id", f"TKT-{idem_key[:6].upper()}"),
                "subject": args.get("subject", "Issue"),
                "priority": priority,
                "category": triage.get("category", "other"),
                "assigned_to": triage.get("assigned_team", "Maintenance Team"),
                "eta": f"{triage.get('sla_minutes', 120)} mins",
                "tags": triage.get("tags", []),
                "triage_source": triage.get("source", "heuristic"),
                "message": f"Ticket raised through T2T pipeline. ID: {result.get('message_id', 'pending')}",
            }

        elif func_name == "get_notices":
            result = await t2t.get_notices(org_id=org_id)
            return {"status": "success", "notices": result if isinstance(result, list) else result.get("notices", [])}

        elif func_name == "lookup_bylaws":
            from aria.ai.bylaws import lookup as bylaw_lookup
            question = (args.get("question") or args.get("query") or "").strip()
            return bylaw_lookup(org_id, question)

        elif func_name == "check_dues":
            result = await t2t.get_dues(twin_id=twin_id, org_id=org_id)
            return {"status": "success", "dues": result.get("dues", []), "total": result.get("total", 0)}

        elif func_name == "pay_dues":
            amount = args.get("amount", 0)
            if not amount or amount <= 0:
                dues = await t2t.get_dues(twin_id=twin_id, org_id=org_id)
                total = dues.get("total", 0)
                if total > 0:
                    return {"status": "need_amount", "total_due": total,
                            "dues": dues.get("dues", []),
                            "message": f"You have CAD ${total:,.0f} in pending dues. How much would you like to pay?"}
                return {"status": "error", "message": "No pending dues found."}
            result = await t2t.initiate_payment(
                user_api_key=api_key, twin_id=twin_id, org_id=org_id,
                amount=amount, payment_type="maintenance",
                thread_id=thread_id, idempotency_key=idem_key,
            )
            return {"status": result.get("status", "success"), "t2t_response": result,
                    "payment_id": result.get("message_id", f"PAY-{idem_key[:8].upper()}"),
                    "amount": amount,
                    "message": f"Payment of CAD ${amount:,.0f} initiated through T2T pipeline."}

        elif func_name == "get_society_events":
            today = datetime.utcnow().strftime("%Y-%m-%d")
            result = await t2t.get_events(org_id=org_id, date=today)
            return {"status": "success", "events": result.get("events", []) if isinstance(result, dict) else result}

        elif func_name == "rsvp_to_event":
            event_name = args.get("event_name", "event")
            result = await t2t.rsvp_event(
                user_api_key=api_key, twin_id=twin_id, org_id=org_id,
                event_id=event_name, thread_id=thread_id, idempotency_key=idem_key,
            )
            return {"status": result.get("status", "success"), "event": event_name,
                    "rsvp_id": result.get("message_id", f"RSVP-{idem_key[:8].upper()}"),
                    "message": f"RSVP for {event_name} sent through T2T pipeline."}

        elif func_name == "get_society_insights":
            days = args.get("days", 7)
            result = await t2t.get_audit_summary(org_id=org_id, days=days)
            return {"status": "success", "period": f"Last {days} days",
                    "audit_events": result if isinstance(result, list) else [],
                    "message": "Audit summary fetched from T2T backend."}

        elif func_name == "get_pending_escalations":
            result = await t2t.get_pending_escalations(admin_api_key=ADMIN_API_KEY)
            tasks = result if isinstance(result, list) else result.get("tasks", [])
            return {"status": "success", "tasks": tasks}

        elif func_name == "approve_escalation":
            task_id = args.get("task_id", "")
            reason = args.get("reason", "Approved by admin via ARIA")
            await t2t.approve_escalation(admin_api_key=ADMIN_API_KEY, task_id=task_id, reason=reason)
            return {"status": "success", "task_id": task_id, "action": "APPROVED",
                    "message": f"Escalation {task_id} approved via T2T backend."}

        elif func_name == "deny_escalation":
            task_id = args.get("task_id", "")
            reason = args.get("reason", "Denied by admin via ARIA")
            await t2t.deny_escalation(admin_api_key=ADMIN_API_KEY, task_id=task_id, reason=reason)
            return {"status": "success", "task_id": task_id, "action": "DENIED",
                    "reason": reason, "message": f"Escalation {task_id} denied."}

        elif func_name == "generate_announcement":
            topic = args.get("topic", "Update")
            details = args.get("details", args.get("topic", ""))
            tone = args.get("tone", "friendly")
            result = await draft_announcement(notes=details, topic=topic, tone=tone)
            return {"status": "success", **result}

        elif func_name == "moderate_content":
            content = args.get("content", "")
            result = await moderate(content)
            return {"status": "success", **result}

        else:
            return await simulate_tool(func_name, args, twin_id, org_id)

    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = str(e)
        logger.warning("T2T call failed for %s (HTTP %s): %s", func_name, e.response.status_code, detail)
        sim = await simulate_tool(func_name, args, twin_id, org_id)
        sim["_t2t_note"] = f"T2T backend returned {e.response.status_code}: {detail}. Showing simulated data."
        return sim

    except Exception as e:
        logger.warning("T2T call failed for %s: %s — falling back to simulation", func_name, e)
        sim = await simulate_tool(func_name, args, twin_id, org_id)
        sim["_t2t_note"] = f"T2T backend unavailable ({e}). Showing simulated data."
        return sim


def _parse_clock_to_24h(t: str) -> str:
    """Best-effort '7pm' / '7:00pm' / '19' → 'HH:MM'. Returns input unchanged on failure."""
    s = (t or "").strip().lower().replace(" ", "")
    if not s:
        return t
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", s)
    if not m:
        return t
    hh = int(m.group(1))
    mm = int(m.group(2) or 0)
    suf = m.group(3)
    if suf == "pm" and hh < 12:
        hh += 12
    if suf == "am" and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm:02d}"


async def simulate_tool(func_name: str, args: dict, twin_id: str, org_id: str) -> dict:
    now = datetime.utcnow()
    bid = str(uuid.uuid4())[:8].upper()

    if func_name == "book_amenity":
        amenity = args.get("amenity_name", "gym")
        time_slot = args.get("time_slot", "7pm") or args.get("slot_time", "7pm")
        date = args.get("date", "today")
        # Use the in-process society client so disambiguation + real DB
        # bookings still happen even when T2T HTTP is unreachable. The
        # simulation must NOT fabricate a booking when multiple amenities
        # share the requested name — it must surface the options list so
        # the LLM can ask the user to disambiguate.
        try:
            from aria.society import client as society_client
            slot_24h = time_slot if ":" in (time_slot or "") else _parse_clock_to_24h(time_slot)
            booking = await society_client.book_amenity_slot(
                org_id=org_id, amenity=amenity, twin_id=twin_id,
                date=date, slot_start=slot_24h,
            )
            if booking.get("success"):
                return {
                    "status": "booked",
                    "booking_id": booking["booking_id"],
                    "amenity": booking.get("amenity", amenity),
                    "amenity_id": booking.get("amenity_id", ""),
                    "location": booking.get("location", ""),
                    "date": booking.get("date", date),
                    "slot": booking.get("slot", time_slot),
                    "remaining_capacity": booking.get("remaining_capacity"),
                    "message": f"{booking.get('amenity', amenity)} booked for {booking.get('slot', time_slot)} on {booking.get('date', date)}.",
                }
            # Disambiguation or genuine failure — surface as-is so the LLM
            # asks the user which one.
            return {
                "status": "needs_disambiguation" if booking.get("options") else "error",
                "amenity": amenity,
                "error": booking.get("error", "Could not book"),
                "options": booking.get("options", []),
                "message": booking.get("error", "Booking could not be completed."),
            }
        except Exception as ex:
            logger.warning("In-process booking simulation failed: %s", ex)
            return {"status": "error", "message": str(ex)}

    elif func_name == "cancel_booking":
        return {"status": "cancelled", "booking_id": args.get("booking_id", f"BK-{bid}"),
                "message": "Booking cancelled successfully."}

    elif func_name == "create_ticket":
        tid = f"TKT-{bid[:6]}"
        priority = args.get("priority", "normal")
        return {"status": "success", "ticket_id": tid, "subject": args.get("subject", "Issue"),
                "priority": priority, "assigned_to": "Maintenance Team",
                "eta": "30 mins" if priority == "urgent" else "2 hours",
                "message": f"Ticket {tid} raised. Team will contact you shortly."}

    elif func_name == "get_society_events":
        tmrw = (now + timedelta(days=1)).strftime("%d %b")
        return {"status": "success", "events": [
            {"title": "Morning Yoga", "date": "Today", "time": "6:30 AM", "location": "Terrace"},
            {"title": "Kids Cricket", "date": tmrw, "time": "4:00 PM", "location": "Ground"},
            {"title": "Society Meeting", "date": "This Sunday", "time": "10:00 AM", "location": "Community Hall"},
        ]}

    elif func_name == "rsvp_to_event":
        return {"status": "success", "event": args.get("event_name", "Event"),
                "rsvp_id": f"RSVP-{bid}", "message": f"You're registered for {args.get('event_name', 'the event')}!"}

    elif func_name == "check_dues":
        return {"status": "success", "dues": [
            {"type": "Maintenance", "amount": 4500, "due": "18 Apr 2026"},
            {"type": "Parking", "amount": 1500, "due": "18 Apr 2026"},
        ], "total": 6000}

    elif func_name == "pay_dues":
        amt = args.get("amount", 0)
        return {"status": "success", "payment_id": f"PAY-{bid}", "amount": amt,
                "message": f"Payment of CAD ${amt:,.0f} initiated. Confirmation in 2 minutes."}

    elif func_name == "get_notices":
        return {"status": "success", "notices": [
            {"title": "Water Shutoff Notice", "body": "Water shutoff May 14, 10 AM-2 PM for Tower 2 maintenance.", "priority": "urgent"},
            {"title": "Spring Maintenance Walkthrough", "body": "Property manager inspection of common areas on May 16.", "priority": "normal"},
            {"title": "Visitor Parking Reminder", "body": "Visitor parking limited to 24 hours; valid pass required.", "priority": "normal"},
        ]}

    elif func_name == "lookup_bylaws":
        from aria.ai.bylaws import lookup as bylaw_lookup
        question = (args.get("question") or args.get("query") or "").strip()
        return bylaw_lookup(org_id, question)

    elif func_name == "get_society_insights":
        return {"status": "success", "period": f"Last {args.get('days', 7)} days",
                "tickets": 23, "resolved": 18, "pending_escalations": 3, "bookings": 47,
                "top_complaints": ["Plumbing (8)", "Electrical (5)", "Lift (4)"],
                "risk": "Plumbing complaints up 60% - consider inspection."}

    elif func_name == "get_pending_escalations":
        return {"status": "success", "tasks": [
            {"id": "ESC-7A3F", "reason": "Late-night pool booking (11 PM)", "risk": "MEDIUM", "sla_left": "25 min"},
            {"id": "ESC-9B1D", "reason": "Water flooding in B-wing", "risk": "HIGH", "sla_left": "8 min"},
        ]}

    elif func_name == "approve_escalation":
        return {"status": "success", "task_id": args.get("task_id", "ESC-001"),
                "action": "APPROVED", "message": "Escalation approved. Workflow resumed."}

    elif func_name == "deny_escalation":
        return {"status": "success", "task_id": args.get("task_id", "ESC-001"),
                "action": "DENIED", "reason": args.get("reason", "Denied by admin"),
                "message": "Escalation denied."}

    elif func_name == "generate_announcement":
        topic = args.get("topic", "Update")
        return {"status": "success", "draft": (
            f"Dear Residents,\n\nThis is regarding {topic}.\n\n"
            f"We appreciate your cooperation.\n\nRegards,\nSociety Management"
        )}

    elif func_name == "moderate_content":
        content = args.get("content", "")
        abusive = any(w in content.lower() for w in ["cheat", "fraud", "steal", "liar"])
        return {"status": "success", "severity": "HIGH" if abusive else "LOW",
                "reason": "Potentially defamatory language" if abusive else "No issues",
                "action": "flag" if abusive else "allow"}

    return {"status": "success", "message": "Action completed."}


def _summarize_tool_result(intent: str, result: dict) -> str:
    status = result.get("status", "")

    if intent == "list_society_amenities":
        items = result.get("items", [])
        if not items:
            return "No amenities found in this society yet."
        groups: dict[str, list[dict]] = {}
        for it in items:
            groups.setdefault(it.get("type", "other"), []).append(it)
        lines = [f"Society has {len(items)} amenities:"]
        for tkey, group in groups.items():
            names = ", ".join([g.get("display_name", "") for g in group[:5]])
            lines.append(f"  - {tkey} ({len(group)}): {names}")
        lines.append("STRUCTURED_PAYLOAD: AMENITIES_LIST::" + json.dumps({"items": items}, ensure_ascii=False))
        lines.append("Note: the structured payload above will be rendered as cards in the UI. Keep your reply brief and conversational; do not echo the JSON.")
        return "\n".join(lines)

    if intent == "find_amenities_by_type":
        items = result.get("items", [])
        atype = result.get("type", "amenity")
        if not items:
            return f"No {atype} amenities found."
        lines = [f"Found {len(items)} {atype} amenities:"]
        for it in items[:8]:
            lines.append(f"  - {it.get('display_name', '')} at {it.get('location', '')}")
        lines.append("STRUCTURED_PAYLOAD: AMENITIES_LIST::" + json.dumps({"items": items, "type": atype}, ensure_ascii=False))
        lines.append("Note: a card grid is rendered automatically. Reply briefly in 1-2 sentences without the JSON.")
        return "\n".join(lines)

    if intent == "get_amenity_info":
        info = result.get("amenity")
        if not info:
            return result.get("message", "Amenity not found.")
        feats = ", ".join((info.get("features") or [])[:5])
        return (
            f"{info.get('display_name', '')} ({info.get('type', '')}) at {info.get('location', '')}\n"
            f"Hours: {info.get('open_time', '')}-{info.get('close_time', '')}, capacity {info.get('capacity_per_slot', '')}\n"
            f"Features: {feats}\n"
            f"{info.get('description', '')}"
        )

    if intent == "show_amenity_slots":
        if status == "need_disambiguation":
            opts = result.get("options", [])
            lines = [result.get("message", "Multiple matches.")]
            for o in opts[:6]:
                lines.append(f"  - {o.get('display_name', '')} ({o.get('location') or o.get('block', '')})")
            lines.append("Ask the user to pick one.")
            return "\n".join(lines)
        slots = [s for s in result.get("slots", []) if s.get("available")]
        if not slots:
            return f"No free slots for {result.get('amenity', '')} on {result.get('date', '')}."
        lines = [
            f"{result.get('amenity', '')} ({result.get('location', '')}) on {result.get('date', '')}:",
            f"Available slots ({len(slots)}):",
        ]
        for i, s in enumerate(slots[:8], 1):
            lines.append(f"  {i}. {s.get('slot_start', '')}-{s.get('slot_end', '')} ({s.get('remaining', '?')} spots)")
        return "\n".join(lines)

    if intent == "book_amenity":
        if status == "need_slot_selection":
            slots = result.get("available_slots", [])
            lines = [f"Amenity: {result.get('amenity', '')} ({result.get('location', '')})",
                     f"Date: {result.get('date', 'today')}",
                     f"Available slots ({result.get('total_available', len(slots))} total):"]
            for i, s in enumerate(slots, 1):
                lines.append(f"  {i}. {s.get('start', '')} - {s.get('end', '')} ({s.get('remaining', '?')} spots left)")
            lines.append("Ask the user to pick a time slot.")
            return "\n".join(lines)
        elif status == "booked":
            return (f"BOOKING CONFIRMED: {result.get('amenity', '')} at {result.get('location', '')}\n"
                    f"Date: {result.get('date', '')}, Slot: {result.get('slot', '')}\n"
                    f"Booking ID: {result.get('booking_id', '')[:8].upper()}\n"
                    f"Remaining capacity: {result.get('remaining_capacity', 'N/A')}")
        elif status == "denied":
            return f"BOOKING DENIED by policy: {result.get('message', '')}"
        elif status == "error":
            return f"BOOKING FAILED: {result.get('message', '')}"

    elif intent == "cancel_booking":
        if status == "cancelled":
            return f"Booking {result.get('booking_id', '')[:8].upper()} has been cancelled successfully."
        return f"Cancellation failed: {result.get('message', '')}"

    elif intent == "create_ticket":
        return (f"Ticket raised: ID {result.get('ticket_id', '')}\n"
                f"Category: {result.get('category', 'other')}, Priority: {result.get('priority', 'normal')}\n"
                f"Assigned to: {result.get('assigned_to', 'Maintenance')}, ETA: {result.get('eta', '2 hours')}")

    elif intent == "check_dues":
        dues = result.get("dues", [])
        lines = ["Pending dues (CAD):"]
        for d in dues:
            lines.append(f"  - {d.get('type', 'Item')}: CAD ${d.get('amount', 0):,.2f} (due {d.get('due', d.get('due_date', ''))})")
        lines.append(f"Total: CAD ${result.get('total', 0):,.2f}")
        return "\n".join(lines)

    elif intent == "pay_dues":
        if status == "need_amount":
            dues = result.get("dues", [])
            lines = [f"Total pending: CAD ${result.get('total_due', 0):,.2f}"]
            for d in dues:
                lines.append(f"  - {d.get('type', 'Item')}: CAD ${d.get('amount', 0):,}")
            lines.append("Ask the user how much they want to pay.")
            return "\n".join(lines)
        return f"Payment of CAD ${result.get('amount', 0):,.0f} initiated. ID: {result.get('payment_id', '')}"

    elif intent == "lookup_bylaws":
        if result.get("status") != "found":
            return result.get(
                "summary",
                "I don't see a specific bylaw covering this. Please check with your property manager.",
            )
        results = result.get("results", []) or []
        lines = [f"Found {len(results)} relevant bylaw section(s):"]
        for r in results[:3]:
            snippet = (r.get("text", "") or "").strip().split("\n")[0]
            if len(snippet) > 220:
                snippet = snippet[:217] + "..."
            lines.append(f"  - §{r.get('section')} {r.get('title')}: {snippet}")
        lines.append("(See cards below for full text and citations.)")
        return "\n".join(lines)

    elif intent == "get_notices":
        notices = result.get("notices", [])
        lines = ["Society notices:"]
        for n in notices:
            lines.append(f"  - {n.get('title', '')}: {n.get('body', '')}")
        return "\n".join(lines)

    elif intent == "get_society_events":
        events = result.get("events", [])
        lines = ["Upcoming events:"]
        for e in events:
            lines.append(f"  - {e.get('title', '')} on {e.get('date', '')} at {e.get('time', '')} ({e.get('location', '')})")
        return "\n".join(lines)

    elif intent == "rsvp_to_event":
        return f"RSVP confirmed for {result.get('event', 'the event')}. ID: {result.get('rsvp_id', '')}"

    elif intent == "get_society_insights":
        return (f"Society report ({result.get('period', '')}):\n"
                f"Tickets: {result.get('tickets', 0)}, Resolved: {result.get('resolved', 0)}\n"
                f"Pending escalations: {result.get('pending_escalations', 0)}, Bookings: {result.get('bookings', 0)}\n"
                f"Top complaints: {', '.join(result.get('top_complaints', []))}\n"
                f"Risk: {result.get('risk', 'None')}")

    elif intent == "get_pending_escalations":
        tasks = result.get("tasks", [])
        lines = ["Pending escalations:"]
        for t in tasks:
            lines.append(f"  - {t.get('id', '')} [{t.get('risk', '')}]: {t.get('reason', '')} (SLA: {t.get('sla_left', '?')})")
        return "\n".join(lines)

    elif intent in ("approve_escalation", "deny_escalation"):
        return f"Escalation {result.get('task_id', '')} {result.get('action', 'processed')}. {result.get('message', '')}"

    elif intent == "generate_announcement":
        return f"Draft announcement:\n{result.get('draft', '')}"

    elif intent == "moderate_content":
        return f"Moderation: Severity={result.get('severity', '?')}, Category={result.get('category', '?')}, Action={result.get('action', '?')}, Reason={result.get('reason', '')}"

    return result.get("message", json.dumps(result))


def _structured_prefix(intent: str | None, tool_result: dict | None) -> str:
    """
    Return the structured prefix the frontend looks for, or "".

    The frontend (frontend/app.js) parses replies that begin with
    ``AMENITIES_LIST::{json}`` or ``BOOKING_RESULT::{json}`` and renders
    rich cards. For non-JS clients the human-readable caption from the
    LLM still follows after a blank line, so the reply remains useful.
    """
    if not tool_result or tool_result.get("status") not in ("success", "booked", "found"):
        return ""
    if intent in ("list_society_amenities", "find_amenities_by_type"):
        items = tool_result.get("items") or []
        if not items:
            return ""
        payload = {"items": items}
        if tool_result.get("type"):
            payload["type"] = tool_result["type"]
        return f"AMENITIES_LIST::{json.dumps(payload, ensure_ascii=False)}"
    if intent == "lookup_bylaws" and tool_result.get("status") == "found":
        payload = {
            "question": tool_result.get("question", ""),
            "results": tool_result.get("results", []),
        }
        return f"BYLAW_RESULT::{json.dumps(payload, ensure_ascii=False)}"
    if intent == "book_amenity" and tool_result.get("status") in ("booked", "success"):
        payload = {
            "booking_id": tool_result.get("booking_id", ""),
            "amenity_id": tool_result.get("amenity_id", "") or "",
            "amenity": tool_result.get("amenity", ""),
            "location": tool_result.get("location", ""),
            "date": tool_result.get("date", ""),
            "slot": tool_result.get("slot", "") or tool_result.get("time_slot", ""),
            "remaining_capacity": tool_result.get("remaining_capacity"),
        }
        return f"BOOKING_RESULT::{json.dumps(payload, ensure_ascii=False)}"
    return ""


async def _build_system_prompt(req: ChatRequest, intent: str | None, message: str,
                               sentiment_signal, language: str) -> str:
    """Compose the full system prompt with RAG, memory, and tone hints."""
    context_str = await build_context_string(req.twin_id)
    system_prompt = get_prompt(req.role)

    conv_context = conv_memory.context_snapshot(req.conversation_id or "", req.twin_id)
    rag_query = f"{intent or ''} {message}".strip()
    rag_context = retrieve_context(rag_query, top_k=3) if rag_query else ""

    tone_hint = soften_tone_hint(sentiment_signal)
    lang_hint = language_hint(language)

    parts = [
        system_prompt,
        "",
        "IMPORTANT: Always respond in natural, conversational language. Never output code or raw JSON.",
        "",
        f"--- USER CONTEXT ---\n{context_str}",
        f"org_id: {req.org_id}\ntwin_id: {req.twin_id}",
    ]
    if conv_context:
        parts.append(f"\n--- CONVERSATION MEMORY ---\n{conv_context}")
    if rag_context:
        parts.append(f"\n{rag_context}")
    if tone_hint:
        parts.append(f"\n--- TONE ---\n{tone_hint}")
    if lang_hint:
        parts.append(f"\n--- LANGUAGE ---\n{lang_hint}")
    return "\n".join(parts)


@app.post("/aria/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest) -> LoginResponse:
    expected = TWIN_API_KEYS.get(req.twin_id)
    if not expected or expected != req.api_key:
        raise HTTPException(status_code=401, detail="invalid credentials")
    role = "admin" if req.twin_id == ADMIN_TWIN_ID else "member"
    token = issue_token(req.twin_id, role, req.org_id)
    return LoginResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRY_HOURS * 3600,
        twin_id=req.twin_id,
        role=role,
    )


@app.post("/aria/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat_endpoint(request: Request, req: ChatRequest, authorization: str | None = Header(default=None)) -> ChatResponse:
    principal = authenticate(authorization, req.twin_id, req.user_api_key, req.org_id)
    req.twin_id = principal.twin_id
    req.org_id = principal.org_id
    req.role = principal.role
    try:
        await check_quota(req.twin_id, req.role)
    except QuotaExceededError as qe:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quota_exceeded", "kind": qe.kind,
                "current": qe.current, "limit": qe.limit,
                "retry_after_s": qe.retry_after_s,
            },
            headers={"Retry-After": str(qe.retry_after_s)},
        )
    conv_id = req.conversation_id or str(uuid.uuid4())
    signals: dict = {}

    suspicious, reason = detect_injection(req.message)
    if suspicious:
        signals["injection_suspected"] = True
        signals["injection_reason"] = reason
        logger.warning("Prompt injection suspected conv=%s reason=%s", conv_id[:8], reason)

    sanitized = sanitize_user_input(req.message)
    sentiment_signal = analyze_sentiment(sanitized)
    language = detect_language(sanitized)
    signals["sentiment"] = sentiment_signal.label
    signals["sentiment_score"] = sentiment_signal.score
    signals["urgency"] = sentiment_signal.urgency
    signals["language"] = language

    anomaly = anomaly_detector.record_message(req.twin_id, sanitized)
    if anomaly:
        signals["anomaly"] = {"kind": anomaly.kind, "severity": anomaly.severity}
        logger.info("Anomaly detected: %s %s", anomaly.kind, anomaly.subject)

    user_profile = conv_memory.get_or_create_user(req.twin_id)
    if sentiment_signal.frustration:
        user_profile.frustration_count += 1
        conv_memory.persist_user(req.twin_id)

    conv_memory.add_turn(conv_id, req.twin_id, "user", sanitized)

    # Multi-turn: if a previous turn parked a pending action (disambiguation,
    # yes/no, slot-fill), try to resume it FIRST. This is what fixes the
    # "ARIA asked, user said yes, ARIA forgot" class of bugs.
    resumed = try_resume(conv_id, sanitized)
    intent: str | None = None
    intent_confidence: float = 0.0
    intent_method: str = ""
    args_override: dict | None = None

    if resumed and resumed.resumed_intent:
        intent = resumed.resumed_intent
        intent_confidence = 0.97
        intent_method = f"resume:{resumed.reason}"
        args_override = resumed.resumed_args
        logger.info("Resumed pending action: conv=%s intent=%s reason=%s",
                    conv_id[:8], intent, resumed.reason)
    elif resumed and resumed.cleared:
        # User said no/cancel — drop the pending and re-classify the
        # current message normally (no resume).
        logger.info("Pending action cleared by user: conv=%s reason=%s",
                    conv_id[:8], resumed.reason)
        intent, intent_confidence, intent_method = detect_intent_hybrid(sanitized, req.role, conv_id)
    else:
        intent, intent_confidence, intent_method = detect_intent_hybrid(sanitized, req.role, conv_id)

    signals["intent_method"] = intent_method
    signals["intent_confidence"] = round(intent_confidence, 3)

    action_taken = ""
    tool_context = ""
    tool_result: dict | None = None
    used_fallback = False

    if intent:
        args = args_override if args_override is not None else extract_args(intent, sanitized, conv_id)
        logger.info("intent=%s confidence=%.2f method=%s args=%s",
                    intent, intent_confidence, intent_method, json.dumps(args))
        tool_result = await call_t2t_tool(intent, args, req.twin_id, req.org_id, conv_id)
        if tool_result.get("_t2t_note"):
            used_fallback = True
        action_taken = ACTION_MAP.get(intent, "")
        user_profile.record_action(intent, args)
        conv_memory.persist_user(req.twin_id)

        # Park disambiguation state — when book_amenity returns options,
        # remember them so the next message ("Tower 1") completes the booking.
        if (
            intent == "book_amenity"
            and tool_result.get("status") == "needs_disambiguation"
            and tool_result.get("options")
        ):
            park_disambiguation(
                conv_id=conv_id,
                intent="book_amenity",
                args=dict(args),
                options=tool_result["options"],
                prompt=tool_result.get("error", "Multiple matches — please pick one"),
            )
        # Park amount-needed state — when pay_dues fires without an amount,
        # remember so a follow-up "$480" completes the payment.
        elif (
            intent == "pay_dues"
            and tool_result.get("status") == "need_amount"
        ):
            park_amount(
                conv_id=conv_id,
                intent="pay_dues",
                args=dict(args),
                prompt="How much would you like to pay?",
            )

        summary = _summarize_tool_result(intent, tool_result)
        tool_context = (
            f"\n\n--- ACTION RESULT ---\n"
            f"Action: {intent}\n"
            f"{summary}\n"
            f"---\n"
            f"Summarize this conversationally. Be brief and friendly. Never show full IDs or technical details unless the user needs them. "
            f"Stay faithful to the numbers and IDs above — do not invent any."
        )

    full_system = await _build_system_prompt(req, intent, sanitized, sentiment_signal, language)

    gemini_input = wrap_user_input(sanitized) + tool_context
    model = choose_model(intent, sanitized, req.role)
    signals["model"] = model

    history = conversation_store[conv_id]
    reply, telemetry = await ai_call_gemini(
        system_prompt=full_system,
        user_message=gemini_input,
        model=model,
        history=history,
        conversation_id=conv_id,
        twin_id=req.twin_id,
    )
    signals["latency_ms"] = telemetry.get("latency_ms")
    if telemetry.get("history"):
        conversation_store[conv_id] = telemetry["history"]
        if len(conversation_store[conv_id]) > 40:
            conversation_store[conv_id] = conversation_store[conv_id][-40:]

    hallucination = validate_reply(reply, tool_result, intent)
    if not hallucination.ok and tool_result:
        logger.warning("Hallucination guard triggered: %s", hallucination.issues)
        signals["hallucination_issues"] = hallucination.issues
        reply = safe_format(intent or "", tool_result)

    if not reply:
        if intent and tool_result:
            reply = safe_format(intent, tool_result) or _summarize_tool_result(intent, tool_result)
        else:
            reply = "I'm here to help! You can ask me to book amenities, raise maintenance tickets, check building events, view your strata fees, and more."

    # Strip any STRUCTURED_PAYLOAD line the LLM may have echoed from the
    # tool context, then prepend the canonical structured prefix ourselves
    # so the frontend can reliably render cards.
    reply = re.sub(r"^STRUCTURED_PAYLOAD:.*$", "", reply, flags=re.MULTILINE).strip()
    # Also strip any in-line ``AMENITIES_LIST::...`` the LLM may have copied.
    reply = re.sub(r"AMENITIES_LIST::\{[^\n]*\}", "", reply).strip()
    reply = re.sub(r"BOOKING_RESULT::\{[^\n]*\}", "", reply).strip()
    prefix = _structured_prefix(intent, tool_result)
    if prefix:
        reply = f"{prefix}\n\n{reply}".strip()

    if conv_memory.needs_summarization(conv_id):
        asyncio.create_task(_summarize_conversation(conv_id, full_system))

    suggestions = suggest_followups(req.twin_id, intent, tool_result)
    confidence = score_decision(
        intent_confidence=intent_confidence,
        tool_success=bool(tool_result and tool_result.get("status") not in ("error", "denied")),
        hallucination_ok=hallucination.ok,
        sentiment_score=sentiment_signal.score,
        has_required_args=True,
        used_fallback=used_fallback,
    )

    conv_memory.add_turn(conv_id, req.twin_id, "assistant", reply, intent=intent, action=action_taken)

    return ChatResponse(
        reply=reply,
        conversation_id=conv_id,
        action_taken=action_taken,
        confidence=confidence.score,
        confidence_label=confidence.label,
        suggestions=[{"intent": s.intent, "display": s.display} for s in suggestions],
        signals=signals,
    )


async def _summarize_conversation(conv_id: str, system_prompt: str) -> None:
    try:
        conv = conv_memory._convs.get(conv_id)
        if not conv:
            return
        turns = list(conv.turns)
        prompt = build_summarization_prompt(turns)
        text, _ = await ai_call_gemini(
            system_prompt="You are a conversation summarizer. Output 2-3 sentences only.",
            user_message=prompt, model="gemini-2.5-flash",
            conversation_id=conv_id, temperature=0.2,
        )
        if text:
            conv_memory.compress(conv_id, text)
            logger.info("Conversation %s compressed", conv_id[:8])
    except Exception as e:
        logger.warning("Summarization failed: %s", e)


@app.post("/aria/chat/stream")
@limiter.limit("15/minute")
async def chat_stream(request: Request, req: ChatRequest, authorization: str | None = Header(default=None)):
    """SSE streaming endpoint — emits text chunks + final event."""
    principal = authenticate(authorization, req.twin_id, req.user_api_key, req.org_id)
    req.twin_id = principal.twin_id
    req.org_id = principal.org_id
    req.role = principal.role
    try:
        await check_quota(req.twin_id, req.role)
    except QuotaExceededError as qe:
        raise HTTPException(
            status_code=429,
            detail={"error": "quota_exceeded", "kind": qe.kind, "limit": qe.limit},
            headers={"Retry-After": str(qe.retry_after_s)},
        )
    conv_id = req.conversation_id or str(uuid.uuid4())
    sanitized = sanitize_user_input(req.message)
    sentiment_signal = analyze_sentiment(sanitized)
    language = detect_language(sanitized)

    conv_memory.add_turn(conv_id, req.twin_id, "user", sanitized)
    intent, intent_confidence, intent_method = detect_intent_hybrid(sanitized, req.role, conv_id)

    tool_context = ""
    tool_result: dict | None = None
    action_taken = ""
    if intent:
        args = extract_args(intent, sanitized, conv_id)
        tool_result = await call_t2t_tool(intent, args, req.twin_id, req.org_id, conv_id)
        action_taken = ACTION_MAP.get(intent, "")
        summary = _summarize_tool_result(intent, tool_result)
        tool_context = f"\n\n--- ACTION RESULT ---\n{summary}\n---\n"

    full_system = await _build_system_prompt(req, intent, sanitized, sentiment_signal, language)
    gemini_input = wrap_user_input(sanitized) + tool_context
    model = choose_model(intent, sanitized, req.role)

    structured = _structured_prefix(intent, tool_result)

    async def gen():
        yield f"event: start\ndata: {json.dumps({'conversation_id': conv_id, 'model': model, 'intent': intent, 'action': action_taken})}\n\n"
        # Emit the structured prefix as its own event up-front so the
        # frontend can start preparing the card grid while the LLM streams
        # the human caption.
        if structured:
            yield f"event: structured\ndata: {json.dumps({'prefix': structured})}\n\n"
        full_reply = ""
        try:
            async for chunk in stream_gemini(
                system_prompt=full_system, user_message=gemini_input,
                model=model, conversation_id=conv_id, twin_id=req.twin_id,
            ):
                if chunk:
                    full_reply += chunk
                    yield f"event: chunk\ndata: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)[:200]})}\n\n"

        if tool_result:
            guard = validate_reply(full_reply, tool_result, intent)
            if not guard.ok:
                corrected = safe_format(intent or "", tool_result)
                yield f"event: correction\ndata: {json.dumps({'text': corrected, 'issues': guard.issues})}\n\n"
                full_reply = corrected

        # Persist the canonical (prefix + caption) form so memory matches
        # what the non-streaming endpoint stores.
        persisted = (f"{structured}\n\n{full_reply}".strip()) if structured else full_reply
        conv_memory.add_turn(conv_id, req.twin_id, "assistant", persisted, intent=intent, action=action_taken)
        suggestions = suggest_followups(req.twin_id, intent, tool_result)
        yield f"event: done\ndata: {json.dumps({'action': action_taken, 'suggestions': [{'intent': s.intent, 'display': s.display} for s in suggestions]})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/aria/metrics")
async def get_metrics():
    return metrics.snapshot()


@app.get("/aria/metrics/conversation/{conv_id}")
async def get_conversation_metrics(conv_id: str):
    return metrics.conversation_summary(conv_id)


@app.get("/health")
async def health():
    t2t_ok = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.T2T_BASE_URL}/health")
            t2t_ok = resp.status_code == 200
    except Exception:
        pass
    from aria.ai.rag import rag
    return {
        "status": "ok", "service": "ARIA Chat API", "version": "3.0.0",
        "t2t_backend": "connected" if t2t_ok else "unavailable",
        "rag_chunks": rag.size,
        "metrics_calls": metrics.snapshot()["total_calls"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("chat_api:app", host="0.0.0.0", port=8080, reload=False)
