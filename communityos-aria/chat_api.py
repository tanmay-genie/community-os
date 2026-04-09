"""
chat_api.py — ARIA Chat API (Text Mode) with Gemini Function Calling
Run: uvicorn chat_api:app --reload --port 8080

REST endpoint for the CommunityOS frontend chat widget.
Member and admin both hit this — role determined by JWT/auth.

POST /aria/chat
{
  "twin_id": "tanmay_resident",
  "org_id": "SUNRISE_SOCIETY",
  "user_api_key": "resident-api-key",
  "role": "member",
  "message": "Book gym at 7pm"
}

Gemini function calling flow:
  1. User message -> Gemini returns function_call
  2. Execute function -> get result
  3. Send function result back -> Gemini generates final text
  4. Return text to user
"""

import uuid
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from aria.config import settings
from aria.context.loader import build_context_string, save_user_action
from aria.prompts.templates import get_prompt

logger = logging.getLogger("aria.chat_api")

# ── In-memory conversation store (per conversation_id) ───────────────────
# Each entry is a list of Content objects from Gemini chat history
conversation_store: dict[str, list] = defaultdict(list)

app = FastAPI(title="ARIA Chat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    twin_id: str
    org_id: str
    user_api_key: str
    role: str = "member"           # "member" | "admin"
    message: str
    conversation_id: str = ""      # optional — for multi-turn memory


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    action_taken: str = ""         # e.g. "BOOKED_GYM", "TICKET_RAISED"


# ── Gemini Function Declarations ──────────────────────────────────────────

def _get_member_tools():
    """Function declarations for member role."""
    import google.generativeai as genai

    return [
        genai.protos.Tool(function_declarations=[
            genai.protos.FunctionDeclaration(
                name="book_amenity",
                description=(
                    "Book a society amenity (gym, pool, clubhouse, badminton court, tennis court) "
                    "for the resident. Call when user says: 'Book gym at 7', 'Reserve pool tomorrow'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "amenity_name": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Amenity to book: gym | pool | clubhouse | badminton | tennis",
                        ),
                        "date": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Date for booking in YYYY-MM-DD format or 'today'/'tomorrow'",
                        ),
                        "time_slot": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Time slot like '7pm', '6:30am', '18:00'",
                        ),
                        "unit": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Resident's unit/flat number, e.g. 'A-401'",
                        ),
                    },
                    required=["amenity_name", "time_slot"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="create_ticket",
                description=(
                    "Raise a maintenance or service request ticket. "
                    "Call when user says: 'AC not working', 'Lift stuck', 'Water leakage', 'Report issue'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "subject": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Short summary of the issue, e.g. 'AC not cooling'",
                        ),
                        "description": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Detailed description of the problem",
                        ),
                        "unit": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Resident's unit/flat number",
                        ),
                        "priority": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Priority: normal | urgent. Use 'urgent' only for safety (fire, flood, gas leak).",
                        ),
                    },
                    required=["subject", "description"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_society_events",
                description=(
                    "Fetch upcoming society events. "
                    "Call when user says: 'What events are happening?', 'Anything on this weekend?'"
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="rsvp_to_event",
                description=(
                    "RSVP to a society event. "
                    "Call when user says: 'Join the cricket match', 'Sign me up for Holi event'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "event_name": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Name of the event to RSVP for",
                        ),
                        "unit": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Resident's unit/flat number",
                        ),
                    },
                    required=["event_name"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="check_dues",
                description=(
                    "Check pending dues, rent, or maintenance fees for the resident. "
                    "Call when user says: 'How much do I owe?', 'Any pending payments?', 'Check my dues'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "unit": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Resident's unit/flat number",
                        ),
                    },
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="pay_dues",
                description=(
                    "Initiate payment for rent or maintenance fees. "
                    "Call when user says: 'Pay my rent', 'Pay maintenance', 'Clear my dues'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "unit": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Resident's unit/flat number",
                        ),
                        "amount": genai.protos.Schema(
                            type=genai.protos.Type.NUMBER,
                            description="Amount to pay in INR",
                        ),
                    },
                    required=["amount"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_notices",
                description=(
                    "Fetch latest society announcements and notices. "
                    "Call when user says: 'Any announcements?', 'Latest notices?', 'Society updates'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
        ])
    ]


def _get_admin_tools():
    """Function declarations for admin role."""
    import google.generativeai as genai

    return [
        genai.protos.Tool(function_declarations=[
            genai.protos.FunctionDeclaration(
                name="get_society_insights",
                description=(
                    "Generate society health report from audit data. "
                    "Call when admin says: 'Give me a summary', 'Society report', 'What's going on?'"
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "days": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description="Number of past days to analyse (default 7)",
                        ),
                    },
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_pending_escalations",
                description=(
                    "Fetch all pending escalations waiting for admin decision. "
                    "Call when admin says: 'Any pending approvals?', 'What needs my attention?'"
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "org_id": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Organisation / society ID",
                        ),
                    },
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="approve_escalation",
                description=(
                    "Approve a pending escalation to resume its workflow. "
                    "Call when admin says: 'Approve that', 'Green light it', 'Approve task <id>'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "task_id": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The escalation task ID",
                        ),
                        "reason": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Reason for approval",
                        ),
                    },
                    required=["task_id"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="deny_escalation",
                description=(
                    "Deny a pending escalation to terminate its workflow. "
                    "Call when admin says: 'Deny that', 'Reject it', 'Deny task <id>'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "task_id": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The escalation task ID",
                        ),
                        "reason": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Reason for denial",
                        ),
                    },
                    required=["task_id"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="generate_announcement",
                description=(
                    "Draft a polished society announcement from admin's rough note. "
                    "Call when admin says: 'Write an announcement', 'Draft a notice about water cut'."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "topic": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Topic of the announcement, e.g. 'water cut tomorrow'",
                        ),
                        "details": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="Additional details or rough notes for the announcement",
                        ),
                    },
                    required=["topic"],
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="moderate_content",
                description=(
                    "Analyse a post or message for policy violations. "
                    "Call when admin says: 'Check this post', 'Is this okay to publish?'"
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "content": genai.protos.Schema(
                            type=genai.protos.Type.STRING,
                            description="The text content to moderate",
                        ),
                    },
                    required=["content"],
                ),
            ),
        ])
    ]


# ── Tool Execution ────────────────────────────────────────────────────────

# Maps function names to action_taken codes
ACTION_MAP = {
    "book_amenity": "BOOKED_AMENITY",
    "create_ticket": "TICKET_RAISED",
    "get_society_events": "FETCHED_EVENTS",
    "rsvp_to_event": "RSVP_CONFIRMED",
    "check_dues": "CHECKED_DUES",
    "pay_dues": "PAYMENT_INITIATED",
    "get_notices": "FETCHED_NOTICES",
    "get_society_insights": "FETCHED_INSIGHTS",
    "get_pending_escalations": "FETCHED_ESCALATIONS",
    "approve_escalation": "ESCALATION_APPROVED",
    "deny_escalation": "ESCALATION_DENIED",
    "generate_announcement": "ANNOUNCEMENT_DRAFTED",
    "moderate_content": "CONTENT_MODERATED",
}


async def _is_t2t_available() -> bool:
    """Quick health check on T2T backend."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{settings.T2T_BASE_URL}/health")
            return resp.status_code == 200
    except Exception:
        return False


async def _execute_tool_via_t2t(
    func_name: str,
    args: dict,
    twin_id: str,
    org_id: str,
    user_api_key: str,
) -> dict:
    """
    Try calling T2T backend. If unavailable, fall through to simulation.
    Raises httpx errors on failure so caller can fall back.
    """
    from aria.t2t_client import t2t

    if func_name == "book_amenity":
        return await t2t.book_amenity(
            user_api_key=user_api_key,
            twin_id=twin_id,
            org_id=org_id,
            amenity=args.get("amenity_name", "gym"),
            slot_time=args.get("time_slot", "7pm"),
            thread_id=str(uuid.uuid4()),
            idempotency_key=str(uuid.uuid4()),
        )

    elif func_name == "create_ticket":
        return await t2t.create_ticket(
            user_api_key=user_api_key,
            twin_id=twin_id,
            org_id=org_id,
            issue=args.get("subject", args.get("description", "General issue")),
            unit=args.get("unit", "unknown"),
            priority=args.get("priority", "normal"),
            thread_id=str(uuid.uuid4()),
            idempotency_key=str(uuid.uuid4()),
        )

    elif func_name == "get_society_events":
        return await t2t.get_events(org_id=org_id, date="today")

    elif func_name == "rsvp_to_event":
        return await t2t.rsvp_event(
            user_api_key=user_api_key,
            twin_id=twin_id,
            org_id=org_id,
            event_id=str(uuid.uuid4()),  # In production, resolve from event_name
            thread_id=str(uuid.uuid4()),
            idempotency_key=str(uuid.uuid4()),
        )

    elif func_name == "check_dues":
        return await t2t.get_dues(twin_id=twin_id, org_id=org_id)

    elif func_name == "pay_dues":
        return await t2t.initiate_payment(
            user_api_key=user_api_key,
            twin_id=twin_id,
            org_id=org_id,
            amount=args.get("amount", 0),
            payment_type="maintenance",
            thread_id=str(uuid.uuid4()),
            idempotency_key=str(uuid.uuid4()),
        )

    elif func_name == "get_notices":
        return await t2t.get_notices(org_id=org_id)

    elif func_name == "get_society_insights":
        return await t2t.get_audit_summary(
            org_id=org_id,
            days=args.get("days", 7),
        )

    elif func_name == "get_pending_escalations":
        return await t2t.get_pending_escalations(org_id=args.get("org_id", org_id))

    elif func_name == "approve_escalation":
        return await t2t.approve_escalation(
            task_id=args["task_id"],
            reason=args.get("reason", "Approved by admin"),
        )

    elif func_name == "deny_escalation":
        return await t2t.deny_escalation(
            task_id=args["task_id"],
            reason=args.get("reason", "Denied by admin"),
        )

    # Local tools that don't need T2T
    raise KeyError(f"No T2T mapping for {func_name}")


def _simulate_tool_response(
    func_name: str,
    args: dict,
    twin_id: str,
    org_id: str,
) -> dict:
    """
    Return realistic simulated responses when T2T backend is unavailable.
    Allows the frontend to work standalone for demos and development.
    """
    now = datetime.utcnow()
    booking_id = str(uuid.uuid4())[:8].upper()
    ticket_id = f"TKT-{str(uuid.uuid4())[:6].upper()}"

    if func_name == "book_amenity":
        amenity = args.get("amenity_name", "gym")
        time_slot = args.get("time_slot", "7pm")
        date = args.get("date", "today")
        return {
            "status": "success",
            "decision": "ALLOW",
            "booking_id": f"BK-{booking_id}",
            "amenity": amenity,
            "date": date,
            "time_slot": time_slot,
            "booked_by": twin_id,
            "confirmed_at": now.isoformat() + "Z",
            "message": f"{amenity.title()} booked for {time_slot} on {date}.",
        }

    elif func_name == "create_ticket":
        priority = args.get("priority", "normal")
        return {
            "status": "success",
            "ticket_id": ticket_id,
            "subject": args.get("subject", "General issue"),
            "description": args.get("description", ""),
            "unit": args.get("unit", "unknown"),
            "priority": priority,
            "created_at": now.isoformat() + "Z",
            "assigned_to": "Maintenance Team",
            "eta_minutes": 30 if priority == "urgent" else 120,
            "message": f"Ticket {ticket_id} raised successfully.",
        }

    elif func_name == "get_society_events":
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        weekend = (now + timedelta(days=(5 - now.weekday()) % 7 + 1)).strftime("%Y-%m-%d")
        return {
            "status": "success",
            "events": [
                {
                    "event_id": "EVT-001",
                    "title": "Morning Yoga Session",
                    "date": now.strftime("%Y-%m-%d"),
                    "time": "6:30 AM",
                    "location": "Clubhouse Terrace",
                    "rsvp_count": 12,
                },
                {
                    "event_id": "EVT-002",
                    "title": "Kids Cricket Tournament",
                    "date": tomorrow,
                    "time": "4:00 PM",
                    "location": "Society Ground",
                    "rsvp_count": 24,
                },
                {
                    "event_id": "EVT-003",
                    "title": "Society General Meeting",
                    "date": weekend,
                    "time": "10:00 AM",
                    "location": "Community Hall",
                    "rsvp_count": 45,
                },
            ],
        }

    elif func_name == "rsvp_to_event":
        event_name = args.get("event_name", "Event")
        return {
            "status": "success",
            "event_name": event_name,
            "rsvp_id": f"RSVP-{booking_id}",
            "confirmed_for": twin_id,
            "confirmed_at": now.isoformat() + "Z",
            "message": f"RSVP confirmed for {event_name}.",
        }

    elif func_name == "check_dues":
        return {
            "status": "success",
            "twin_id": twin_id,
            "dues": [
                {
                    "type": "Maintenance",
                    "amount": 4500,
                    "due_date": (now + timedelta(days=5)).strftime("%Y-%m-%d"),
                    "status": "pending",
                },
                {
                    "type": "Parking",
                    "amount": 1500,
                    "due_date": (now + timedelta(days=5)).strftime("%Y-%m-%d"),
                    "status": "pending",
                },
            ],
            "total_pending": 6000,
        }

    elif func_name == "pay_dues":
        amount = args.get("amount", 0)
        return {
            "status": "success",
            "payment_id": f"PAY-{booking_id}",
            "amount": amount,
            "payment_type": "maintenance",
            "initiated_at": now.isoformat() + "Z",
            "expected_confirmation": "Within 2 minutes",
            "message": f"Payment of Rs.{amount:,.0f} initiated successfully.",
        }

    elif func_name == "get_notices":
        return {
            "status": "success",
            "notices": [
                {
                    "notice_id": "NTC-001",
                    "title": "Water Supply Maintenance",
                    "body": "Water supply will be interrupted on April 12 from 10 AM to 2 PM for tank cleaning.",
                    "posted_at": (now - timedelta(hours=6)).isoformat() + "Z",
                    "priority": "normal",
                },
                {
                    "notice_id": "NTC-002",
                    "title": "Parking Rule Update",
                    "body": "Visitor parking is now limited to 4 hours. Please inform your guests.",
                    "posted_at": (now - timedelta(days=1)).isoformat() + "Z",
                    "priority": "normal",
                },
            ],
        }

    elif func_name == "get_society_insights":
        days = args.get("days", 7)
        return {
            "status": "success",
            "period_days": days,
            "summary": {
                "total_tickets": 23,
                "resolved_tickets": 18,
                "pending_escalations": 3,
                "amenity_bookings": 47,
                "payments_collected": 156000,
            },
            "trends": [
                {"category": "Plumbing", "count": 8, "trend": "rising"},
                {"category": "Electrical", "count": 5, "trend": "stable"},
                {"category": "Lift Maintenance", "count": 4, "trend": "declining"},
            ],
            "risk_flags": [
                "Plumbing complaints up 60% — consider preventive inspection.",
            ],
        }

    elif func_name == "get_pending_escalations":
        return {
            "status": "success",
            "tasks": [
                {
                    "task_id": "ESC-7A3F",
                    "reason": "Late-night pool booking request (11 PM)",
                    "risk_level": "MEDIUM",
                    "requested_by": "resident_402",
                    "sla_remaining_minutes": 25,
                    "created_at": (now - timedelta(minutes=35)).isoformat() + "Z",
                },
                {
                    "task_id": "ESC-9B1D",
                    "reason": "Urgent plumbing ticket — water flooding in B-wing",
                    "risk_level": "HIGH",
                    "requested_by": "resident_108",
                    "sla_remaining_minutes": 8,
                    "created_at": (now - timedelta(minutes=52)).isoformat() + "Z",
                },
            ],
        }

    elif func_name == "approve_escalation":
        return {
            "status": "success",
            "task_id": args.get("task_id", "unknown"),
            "action": "APPROVED",
            "reason": args.get("reason", "Approved by admin"),
            "approved_at": now.isoformat() + "Z",
            "message": "Escalation approved. Workflow resumed.",
        }

    elif func_name == "deny_escalation":
        return {
            "status": "success",
            "task_id": args.get("task_id", "unknown"),
            "action": "DENIED",
            "reason": args.get("reason", "Denied by admin"),
            "denied_at": now.isoformat() + "Z",
            "message": "Escalation denied. Workflow terminated.",
        }

    elif func_name == "generate_announcement":
        topic = args.get("topic", "General Update")
        details = args.get("details", "")
        detail_line = f" {details}" if details else ""
        return {
            "status": "success",
            "draft": (
                f"Dear Residents,\n\n"
                f"This is to inform you regarding {topic}.{detail_line}\n\n"
                f"We appreciate your cooperation and understanding.\n\n"
                f"Regards,\nSociety Management"
            ),
            "note": "Review and edit before publishing.",
        }

    elif func_name == "moderate_content":
        content = args.get("content", "")
        content_lower = content.lower()
        abusive = ["cheat", "fraud", "steal", "liar", "chor"]
        spam = ["buy now", "click here", "whatsapp", "discount"]

        severity = "CLEAN"
        reason = "No issues detected."
        action = "ALLOW"

        if any(w in content_lower for w in abusive):
            severity = "HIGH"
            reason = "Potentially defamatory or abusive language detected."
            action = "HIDE and escalate to admin review"
        elif any(p in content_lower for p in spam):
            severity = "MEDIUM"
            reason = "Possible spam or promotional content."
            action = "Flag for admin review"

        return {
            "status": "success",
            "content_id": f"MOD-{str(uuid.uuid4())[:6].upper()}",
            "severity": severity,
            "reason": reason,
            "recommended_action": action,
        }

    # Fallback for unknown tools
    return {"status": "error", "message": f"Unknown tool: {func_name}"}


async def _execute_tool(
    func_name: str,
    args: dict,
    twin_id: str,
    org_id: str,
    user_api_key: str,
) -> dict:
    """
    Execute a tool function. Tries T2T backend first, falls back to simulation.
    Local-only tools (generate_announcement, moderate_content) always run locally.
    """
    # Tools that run locally without T2T
    local_only_tools = {"generate_announcement", "moderate_content"}

    if func_name in local_only_tools:
        return _simulate_tool_response(func_name, args, twin_id, org_id)

    # Try T2T backend first
    try:
        if await _is_t2t_available():
            result = await _execute_tool_via_t2t(
                func_name, args, twin_id, org_id, user_api_key,
            )
            # Save user action for context on write operations
            if func_name in ("book_amenity", "create_ticket", "rsvp_to_event", "pay_dues"):
                action_desc = ACTION_MAP.get(func_name, func_name)
                await save_user_action(twin_id, f"{action_desc}: {json.dumps(args)}")
            return result
    except Exception as e:
        logger.warning("T2T call failed for %s: %s — falling back to simulation", func_name, e)

    # Fallback: simulated response
    logger.info("Using simulated response for %s (T2T unavailable)", func_name)
    result = _simulate_tool_response(func_name, args, twin_id, org_id)

    # Still save user action for simulated write operations
    if func_name in ("book_amenity", "create_ticket", "rsvp_to_event", "pay_dues"):
        try:
            action_desc = ACTION_MAP.get(func_name, func_name)
            await save_user_action(twin_id, f"{action_desc} (simulated): {json.dumps(args)}")
        except Exception:
            pass  # Don't fail the response if context save fails

    return result


# ── Chat endpoint ──────────────────────────────────────────────────────────

@app.post("/aria/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    Main chat endpoint.
    Loads user context -> builds prompt -> calls LLM (Gemini) with tools -> returns reply.
    Gemini function calls are executed and results fed back for natural response.
    """
    conv_id = req.conversation_id or str(uuid.uuid4())

    # 1. Load user context from Redis
    context_str = await build_context_string(req.twin_id)

    # 2. Build full prompt
    system_prompt = get_prompt(req.role)
    full_system = (
        f"{system_prompt}\n\n"
        f"CRITICAL RULES:\n"
        f"- NEVER output raw code, tool_code blocks, or print() statements in your reply.\n"
        f"- Use the provided function tools to perform actions. Do NOT simulate tool calls in text.\n"
        f"- If a tool returns data, summarize it in natural conversational language.\n"
        f"- Always respond in natural language, not code.\n\n"
        f"--- CURRENT USER CONTEXT ---\n{context_str}\n"
        f"org_id: {req.org_id}\n"
        f"twin_id: {req.twin_id}\n"
        f"user_api_key: {req.user_api_key}"
    )

    # 3. Call Gemini with conversation history and function calling
    try:
        reply, action_taken = await _call_llm_with_tools(
            system_prompt=full_system,
            user_message=req.message,
            conversation_id=conv_id,
            role=req.role,
            twin_id=req.twin_id,
            org_id=req.org_id,
            user_api_key=req.user_api_key,
        )
    except Exception as e:
        logger.exception("LLM error in chat endpoint")
        # Graceful fallback — never show raw error to user
        reply = "I'm having a moment — could you say that again?"
        action_taken = ""

    return ChatResponse(
        reply=reply,
        conversation_id=conv_id,
        action_taken=action_taken,
    )


async def _call_llm_with_tools(
    system_prompt: str,
    user_message: str,
    conversation_id: str,
    role: str,
    twin_id: str,
    org_id: str,
    user_api_key: str,
) -> tuple[str, str]:
    """
    Calls Gemini with full conversation history and function calling.

    Returns (reply_text, action_taken).

    Function call loop:
      1. Send user message -> Gemini may return function_call
      2. Execute function -> get result
      3. Send function result back -> Gemini generates final text or another call
      4. Up to 3 function calls per turn
    """
    import google.generativeai as genai

    genai.configure(api_key=settings.GOOGLE_API_KEY)

    # Select tools based on role
    tools = _get_member_tools() if role == "member" else _get_admin_tools()

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=system_prompt,
        tools=tools,
    )

    # Get or create conversation history
    history = conversation_store[conversation_id]

    # Start a multi-turn chat with existing history
    chat = model.start_chat(history=history)

    action_taken = ""
    last_tool_result = None
    max_function_calls = 3

    # Send the new user message with retry for empty responses
    for attempt in range(3):
        try:
            response = chat.send_message(user_message)
        except Exception as e:
            logger.warning("Gemini send_message failed (attempt %d): %s", attempt + 1, e)
            chat = model.start_chat(history=history)
            continue

        # Function call loop — entire block wrapped for safety
        function_calls_made = 0
        try:
            while function_calls_made < max_function_calls:
                # Safely get function call from response
                fc_name, fc_args = _extract_function_call(response)
                if not fc_name:
                    break  # No function call — text response or blocked

                logger.info("Gemini called tool: %s(%s)", fc_name, json.dumps(fc_args))

                if fc_name in ACTION_MAP:
                    action_taken = ACTION_MAP[fc_name]

                # Execute the tool
                try:
                    tool_result = await _execute_tool(
                        func_name=fc_name,
                        args=fc_args,
                        twin_id=twin_id,
                        org_id=org_id,
                        user_api_key=user_api_key,
                    )
                except Exception as e:
                    logger.error("Tool execution failed for %s: %s", fc_name, e)
                    tool_result = {"status": "error", "message": f"Tool {fc_name} failed: {str(e)}"}

                last_tool_result = tool_result

                # Send function result back to Gemini
                function_response = genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fc_name,
                        response={"result": tool_result},
                    )
                )

                try:
                    response = chat.send_message(function_response)
                except Exception as e:
                    logger.warning("Failed to send function response: %s", e)
                    break

                function_calls_made += 1

        except Exception as e:
            logger.warning("Function call loop error: %s", e)

        # Extract final text — robust against all failure modes
        text = _safe_extract_text(response)
        if text:
            conversation_store[conversation_id] = list(chat.history)
            if len(conversation_store[conversation_id]) > 50:
                conversation_store[conversation_id] = conversation_store[conversation_id][-50:]
            return text, action_taken

        # If we got a tool result but Gemini blocked the summary, describe it ourselves
        if last_tool_result and action_taken:
            status = last_tool_result.get("status", "completed")
            msg = last_tool_result.get("message", "")
            summary = f"Done! {action_taken.replace('_', ' ').title()} — {status}. {msg}".strip()
            return summary, action_taken

        logger.warning("Empty response from Gemini (attempt %d)", attempt + 1)
        chat = model.start_chat(history=history)
        continue

    # All retries failed
    if action_taken and last_tool_result:
        return f"Action completed: {action_taken}. {last_tool_result.get('message', '')}", action_taken
    return "Sorry, I couldn't process that right now. Could you try rephrasing?", ""


def _extract_function_call(response) -> tuple[str, dict]:
    """Safely extract function call name and args from Gemini response."""
    try:
        if not response.candidates:
            return "", {}
        candidate = response.candidates[0]
        if not candidate or not candidate.content or not candidate.content.parts:
            return "", {}
        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call and part.function_call.name:
                fc = part.function_call
                return fc.name, dict(fc.args) if fc.args else {}
    except (AttributeError, IndexError, TypeError) as e:
        logger.warning("Failed to extract function call: %s", e)
    return "", {}


def _safe_extract_text(response) -> str:
    """Safely extract text from Gemini response, handling all edge cases."""
    try:
        # Try the standard accessor first
        text = response.text
        if text and text.strip():
            return text.strip()
    except (ValueError, AttributeError):
        pass

    # Fallback: manually walk candidates/parts
    try:
        for candidate in (response.candidates or []):
            for part in (candidate.content.parts or []):
                if hasattr(part, 'text') and part.text and part.text.strip():
                    return part.text.strip()
    except (AttributeError, IndexError, TypeError):
        pass

    return ""


# ── Health check ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    t2t_up = await _is_t2t_available()
    return {
        "status": "ok",
        "service": "ARIA Chat API",
        "t2t_backend": "connected" if t2t_up else "unavailable (using simulated responses)",
    }


# ── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("chat_api:app", host="0.0.0.0", port=8080, reload=True)
