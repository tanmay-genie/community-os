"""Golden test cases for ARIA quality eval.

Each case is a dict with:
  id                        unique identifier ("amenity-001")
  message                   user input
  role                      "member" | "admin"
  expected_intent           expected detected intent (or None)
  expected_action           expected ACTION_MAP value (or None)
  must_emit_prefix          structured prefix the reply MUST start with
                            ("AMENITIES_LIST::", "BOOKING_RESULT::", or None)
  must_not_emit_prefix      structured prefix that MUST NOT appear
  reply_must_contain        list of strings (case-insensitive) the reply must contain
  reply_must_not_contain    list of strings that MUST NOT appear (currency
                            leaks, Hindi words, hallucinated locations, etc.)
  max_reply_length          guardrail against bloat
  notes                     human notes for debugging

The cases below are organised by capability cluster.
"""
from __future__ import annotations

# Currency / language guardrails applied to nearly every case
HINDI_TOKENS = ["kya", "hai", "kitne", "nahi", "haan", "yaar", "bhai", "abhi", "kuch"]
RUPEE_TOKENS = ["Rs.", "₹", "rupees", "INR"]
SOCIETY_TOKENS = ["society"]  # Canadian product uses "building"

# We keep the guardrails as separate constants so individual cases can opt out
# (e.g. an admin moderation case may legitimately discuss the word "society"
# in user-generated content).
GLOBAL_FORBIDDEN = HINDI_TOKENS + RUPEE_TOKENS

CASES: list[dict] = [

    # ── Discovery (member) ────────────────────────────────────────────
    {
        "id": "amenity-list-001",
        "message": "what amenities are here?",
        "role": "member",
        "expected_intent": "list_society_amenities",
        "expected_action": "LISTED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
        "reply_must_contain": [],
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Bare discovery query — must produce structured cards.",
    },
    {
        "id": "amenity-list-002",
        "message": "show me all facilities",
        "role": "member",
        "expected_intent": "list_society_amenities",
        "expected_action": "LISTED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
    },
    {
        "id": "amenity-list-003",
        "message": "what can I book?",
        "role": "member",
        "expected_intent": "list_society_amenities",
        "expected_action": "LISTED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
    },

    # ── By type (member) ──────────────────────────────────────────────
    {
        "id": "amenity-type-001",
        "message": "show me all the gyms",
        "role": "member",
        "expected_intent": "find_amenities_by_type",
        "expected_action": "FILTERED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
    },
    {
        "id": "amenity-type-002",
        "message": "list all pools",
        "role": "member",
        "expected_intent": "find_amenities_by_type",
        "expected_action": "FILTERED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
    },
    {
        "id": "amenity-type-003",
        "message": "show me badminton courts",
        "role": "member",
        "expected_intent": "find_amenities_by_type",
        "expected_action": "FILTERED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
    },

    # ── Booking (specific — only 1 clubhouse exists, should succeed) ──
    {
        "id": "book-specific-001",
        "message": "book the clubhouse for tomorrow at 7pm",
        "role": "member",
        "expected_intent": "book_amenity",
        "expected_action": "BOOKED_AMENITY",
        "must_emit_prefix": "BOOKING_RESULT::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Only 1 clubhouse exists — must resolve uniquely.",
    },

    # ── Booking (ambiguous — must NOT silently pick) ──────────────────
    {
        "id": "book-ambig-001",
        "message": "book gym at 7pm tomorrow",
        "role": "member",
        "expected_intent": "book_amenity",
        "expected_action": "BOOKED_AMENITY",  # tool fires but returns options
        "must_not_emit_prefix": "BOOKING_RESULT::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "3 gyms exist — must surface options, not pick silently.",
    },

    # ── Tickets ───────────────────────────────────────────────────────
    {
        "id": "ticket-001",
        "message": "AC is not working in my unit",
        "role": "member",
        "expected_intent": "create_ticket",
        "expected_action": "TICKET_RAISED",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
    },
    {
        "id": "ticket-urgent-001",
        "message": "there is a water leak flooding my bathroom, urgent!",
        "role": "member",
        "expected_intent": "create_ticket",
        "expected_action": "TICKET_RAISED",
        "reply_must_contain": ["urgent"],
        "notes": "Urgent issues should be acknowledged as urgent.",
    },

    # ── Dues / Payments — currency must be CAD only ───────────────────
    {
        "id": "dues-001",
        "message": "any pending fees for me?",
        "role": "member",
        "expected_intent": "check_dues",
        "expected_action": "CHECKED_DUES",
        "reply_must_contain": ["CAD"],
        "reply_must_not_contain": ["Rs.", "₹", "rupees", "INR"],
    },
    {
        "id": "dues-002",
        "message": "how much do I owe?",
        "role": "member",
        "expected_intent": "check_dues",
        "expected_action": "CHECKED_DUES",
        "reply_must_contain": ["CAD"],
        "reply_must_not_contain": ["Rs.", "₹"],
    },
    {
        "id": "dues-003",
        "message": "is my strata fee paid?",
        "role": "member",
        "expected_intent": "check_dues",
        "expected_action": "CHECKED_DUES",
        "reply_must_not_contain": ["Rs.", "₹", "rupees"],
    },

    # ── Events / Notices ──────────────────────────────────────────────
    {
        "id": "events-001",
        "message": "what events are happening?",
        "role": "member",
        "expected_intent": "get_society_events",
        "expected_action": "FETCHED_EVENTS",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
    },
    {
        "id": "notices-001",
        "message": "any new notices?",
        "role": "member",
        "expected_intent": "get_notices",
        "expected_action": "FETCHED_NOTICES",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
    },

    # ── Admin queries from MEMBER must NOT leak admin tools ──────────
    {
        "id": "admin-block-001",
        "message": "show me all pending escalations",
        "role": "member",
        "expected_intent": None,           # blocked by admin keyword guard
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Pre-fix bug: misclassified as list_amenities. Must stay blocked.",
    },
    {
        "id": "admin-block-002",
        "message": "approve the most urgent escalation",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
    },
    {
        "id": "admin-block-003",
        "message": "give me a society summary for last 7 days",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
    },
    {
        "id": "admin-block-004",
        "message": "write an announcement about water disruption",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
    },

    # ── Greetings / chitchat (no tool fires) ──────────────────────────
    {
        "id": "chitchat-001",
        "message": "hi",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
    },
    {
        "id": "chitchat-002",
        "message": "thank you",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
    },

    # ── Edge / adversarial ────────────────────────────────────────────
    {
        "id": "empty-001",
        "message": " ",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "notes": "Empty message — should not crash, should not call a tool.",
    },
    {
        "id": "gibberish-001",
        "message": "asdfgh qwerty",
        "role": "member",
        "expected_intent": None,
        "expected_action": "",
        "must_not_emit_prefix": "AMENITIES_LIST::",
    },
    {
        "id": "currency-leak-001",
        "message": "tell me about my dues again",
        "role": "member",
        "expected_intent": "check_dues",
        "expected_action": "CHECKED_DUES",
        "reply_must_not_contain": ["Rs.", "₹", "rupees", "INR"],
        "notes": "Regression test for the dues-currency hallucination bug.",
    },

    # ── English-only enforcement ──────────────────────────────────────
    {
        "id": "lang-en-001",
        "message": "list all the amenities please",
        "role": "member",
        "expected_intent": "list_society_amenities",
        "expected_action": "LISTED_AMENITIES",
        "must_emit_prefix": "AMENITIES_LIST::",
        "reply_must_not_contain": HINDI_TOKENS,
    },

    # ── Multi-turn — disambiguation follow-up ─────────────────────────
    # These two cases run on the SAME conversation_id sequentially: the
    # first parks a pending action, the second resumes it. The runner
    # detects "convo:<id>" prefix on the case id and reuses it.
    {
        "id": "convo:gym-pick / 1-ambig",
        "message": "book gym at 7pm tomorrow",
        "role": "member",
        "expected_intent": "book_amenity",
        "expected_action": "BOOKED_AMENITY",
        "must_not_emit_prefix": "BOOKING_RESULT::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Parks disambiguation — 3 gyms.",
    },
    {
        "id": "convo:gym-pick / 2-resume",
        "message": "Tower 1",
        "role": "member",
        "expected_intent": "book_amenity",
        "expected_action": "BOOKED_AMENITY",
        "must_emit_prefix": "BOOKING_RESULT::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Resumes the parked book_amenity with chosen amenity_id.",
    },

    # ── Multi-turn — yes/no decline (must clear pending) ──────────────
    {
        "id": "convo:gym-decline / 1-ambig",
        "message": "book the gym",
        "role": "member",
        "expected_intent": "book_amenity",
        "expected_action": "BOOKED_AMENITY",
    },
    {
        "id": "convo:gym-decline / 2-cancel",
        "message": "never mind",
        "role": "member",
        "expected_intent": None,         # decline → cleared, no new intent
        "expected_action": "",
        "must_not_emit_prefix": "BOOKING_RESULT::",
        "notes": "Negative reply must clear the pending action without picking a gym.",
    },

    # ── Multi-turn — amount fill (pay_dues) ───────────────────────────
    {
        "id": "convo:pay / 1-noamount",
        "message": "i want to pay",
        "role": "member",
        # pay_dues fires; tool returns need_amount; we park
        "expected_action": "PAYMENT_INITIATED",
    },
    {
        "id": "convo:pay / 2-amount",
        "message": "$480",
        "role": "member",
        "expected_intent": "pay_dues",
        "expected_action": "PAYMENT_INITIATED",
        "reply_must_not_contain": ["Rs.", "₹", "rupees"],
    },

    # ── Bylaw RAG with citations ──────────────────────────────────────
    {
        "id": "bylaw-pets-001",
        "message": "are pets allowed in the building?",
        "role": "member",
        "expected_intent": "lookup_bylaws",
        "expected_action": "BYLAW_LOOKED_UP",
        "must_emit_prefix": "BYLAW_RESULT::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Should retrieve §2.1 / §2.2 (Pets).",
    },
    {
        "id": "bylaw-hardwood-001",
        "message": "can I install hardwood floors?",
        "role": "member",
        "expected_intent": "lookup_bylaws",
        "expected_action": "BYLAW_LOOKED_UP",
        "must_emit_prefix": "BYLAW_RESULT::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
        "notes": "Should retrieve §3.1 (Hardwood Flooring).",
    },
    {
        "id": "bylaw-quiet-001",
        "message": "what time do quiet hours start?",
        "role": "member",
        "expected_intent": "lookup_bylaws",
        "expected_action": "BYLAW_LOOKED_UP",
        "must_emit_prefix": "BYLAW_RESULT::",
    },
    {
        "id": "bylaw-bbq-001",
        "message": "is BBQ allowed on the balcony?",
        "role": "member",
        "expected_intent": "lookup_bylaws",
        "expected_action": "BYLAW_LOOKED_UP",
        "must_emit_prefix": "BYLAW_RESULT::",
    },
    {
        "id": "bylaw-airbnb-001",
        "message": "can I list my unit on Airbnb?",
        "role": "member",
        "expected_intent": "lookup_bylaws",
        "expected_action": "BYLAW_LOOKED_UP",
        "must_emit_prefix": "BYLAW_RESULT::",
        "notes": "Should retrieve §12.1 (Short-Term Rentals).",
    },
    {
        "id": "bylaw-movein-001",
        "message": "what's the move-in deposit policy?",
        "role": "member",
        "expected_intent": "lookup_bylaws",
        "expected_action": "BYLAW_LOOKED_UP",
        "must_emit_prefix": "BYLAW_RESULT::",
    },

    # ── Admin role — should reach admin intents ───────────────────────
    {
        "id": "admin-allow-001",
        "message": "show me all pending escalations",
        "role": "admin",
        "expected_intent": "get_pending_escalations",
        "expected_action": "FETCHED_ESCALATIONS",
        "must_not_emit_prefix": "AMENITIES_LIST::",
        "reply_must_not_contain": GLOBAL_FORBIDDEN,
    },
    {
        "id": "admin-allow-002",
        "message": "give me a society summary",
        "role": "admin",
        "expected_intent": "get_society_insights",
        "expected_action": "FETCHED_INSIGHTS",
    },
]


def case_count_by_role() -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in CASES:
        counts[c["role"]] = counts.get(c["role"], 0) + 1
    return counts
