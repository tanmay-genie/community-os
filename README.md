# CommunityOS — AI Concierge for Canadian Condo Buildings

> **ARIA** (Automated Resident Intelligence Assistant) — citation-grounded
> AI for Canadian condo / strata buildings, sitting on a clean
> Twin-to-Twin (T2T) protocol layer for authenticated, audited
> agent-to-agent communication.
>
> **Status:** 39 / 39 eval cases passing · production-hardened · live demo

---

## What's New

The codebase reflects a 2-week AI sprint that delivered:

- ✅ **39-case golden eval suite** with auto-generated `REPORT.md` and CI gates
- ✅ **Bylaw RAG with §-citations** — boards ask "can I install hardwood?"
  → ARIA answers with the exact section quote (12 demo bylaws indexed)
- ✅ **Multi-turn state machine** — disambiguation, slot-fill, yes/no
  resume, polite decline (5-min TTL on parked actions)
- ✅ **English-only / Canadian-condo localization** — strata fees in CAD,
  Maple Heights demo, Tower / Lobby Level / Mezzanine terminology

See [`AI_SPRINT_REPORT.md`](./AI_SPRINT_REPORT.md) for the day-by-day
breakdown and [`PROJECT_DOCS.html`](./PROJECT_DOCS.html) for the
visual architecture deck.

---

## Table of Contents

- [Overview](#overview)
- [Repository Structure](#repository-structure)
- [Architecture](#architecture)
- [Module 1 — communityos-aria (ARIA Agent)](#module-1--communityos-aria-aria-agent)
- [Module 2 — t2t_backend (Protocol Layer)](#module-2--t2t_backend-protocol-layer)
- [Bylaw Lookup with Citations](#bylaw-lookup-with-citations)
- [Multi-turn Conversation State](#multi-turn-conversation-state)
- [Eval Suite & Quality Gates](#eval-suite--quality-gates)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the Project](#running-the-project)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Adding a New Tool](#adding-a-new-tool)
- [Running Tests](#running-tests)

---

## Overview

CommunityOS is an AI-first platform for Canadian condo and strata buildings.

- **ARIA** is the conversational layer. Residents type or speak in plain
  English; ARIA understands intent, picks the right tool, talks to T2T
  for state-changing actions, and renders rich cards (amenity catalog,
  booking confirmations, bylaw lookups).
- **T2T Backend** is the policy + audit layer. Every state-changing
  message — book a gym, raise a ticket, initiate a payment, approve
  an escalation — passes through authentication, policy/RBAC, audit
  logging, and notification dispatch.

Together they form a multi-agent system designed for the way Canadian
condo boards actually run buildings.

---

## Repository Structure

```
community_os/
├── communityos-aria/                 # ARIA — Voice + Chat AI
│   ├── chat_api.py                   # FastAPI REST entry (port 8080)
│   ├── server.py                     # FastMCP tool host
│   ├── agent_aria.py                 # LiveKit voice agent (optional)
│   ├── pyproject.toml
│   ├── alembic.ini · alembic/        # DB migrations (society + RAG + metrics)
│   ├── tests/
│   │   ├── test_http_api.py          # Integration tests (10)
│   │   ├── test_amenity_discovery.py # Amenity/booking tests (9)
│   │   └── evals/                    # 39-case golden suite
│   │       ├── cases.py
│   │       ├── runner.py
│   │       ├── test_eval_suite.py
│   │       └── REPORT.md             # auto-generated
│   ├── frontend/                     # Static demo UI
│   │   ├── index.html
│   │   ├── app.js                    # AMENITIES_LIST / BOOKING_RESULT / BYLAW_RESULT renderers
│   │   └── styles.css
│   └── aria/
│       ├── config.py
│       ├── auth.py                   # JWT (HS256) + per-twin API keys
│       ├── t2t_client.py             # HTTP/in-process bridge to T2T
│       ├── ai/
│       │   ├── llm.py                # Gemini wrapper + retry + caching
│       │   ├── intent_classifier.py  # Hybrid embedding + lexical
│       │   ├── conversation_memory.py
│       │   ├── conversation_state.py # Multi-turn pending-action state machine
│       │   ├── bylaws.py             # Citation-grounded RAG over condo bylaws
│       │   ├── rag.py                # Generic society-doc RAG
│       │   ├── hallucination_guard.py
│       │   ├── quota.py · metrics.py · prompt_cache.py
│       │   ├── moderation.py · safety.py · sentiment.py · triage.py
│       │   └── anomaly.py
│       ├── obs/                      # Prometheus + correlation IDs + structured logs
│       ├── society/                  # Society DB layer (tables, services, routes)
│       │   ├── models.py
│       │   ├── booking_service.py
│       │   ├── community_service.py
│       │   ├── routes.py
│       │   ├── seed_amenities.py     # 15 Maple Heights demo amenities
│       │   └── seed_community.py     # CAD-denominated demo data
│       ├── tools/
│       │   ├── member.py             # Member-side MCP tools
│       │   └── admin.py              # Admin-side MCP tools
│       ├── prompts/
│       │   └── templates.py
│       └── resources/
│           ├── rag_index/            # Generic RAG persistence
│           └── bylaws_index/         # Per-org bylaw indexes (JSON)
│
└── t2t_backend/                      # Twin-to-Twin Protocol Layer (port 8000)
    ├── app.py
    ├── config.py · redis_client.py · requirements.txt
    ├── obs/                          # Correlation + Prometheus
    ├── schemas/                      # MessageEnvelope, IntentType, etc.
    ├── auth/                         # Twin auth + Ed25519
    ├── policy/                       # RBAC + ABAC + contracts + redaction
    ├── router/                       # /send /inbox /reply + WebSocket
    ├── orchestrator/                 # Planner + executor + adapters
    ├── memory/                       # Twin / org / decision memory
    ├── audit/                        # Immutable event log
    ├── notifications/                # SLA escalations
    ├── admin/                        # Twin registration + audit queries
    ├── alembic/                      # T2T's own migrations
    └── tests/
```

---

## Architecture

```
                ┌──────────────────────────────────┐
                │  Browser  (frontend/index.html)  │
                │  • chat · cards · slot picker    │
                │  • JWT in localStorage           │
                └──────────────┬───────────────────┘
                               │ HTTP + JWT + X-Request-ID
                               ▼
┌──────────────────────────────────────────────────────────┐
│  ARIA  (communityos-aria, port 8080)                     │
│  ──────────────────────────────────                      │
│  • Chat orchestration (intent → tool → reply)            │
│  • Conversation memory + state machine                   │
│  • Bylaw RAG (per-org, citation-grounded)                │
│  • Society DB owner (amenities, bookings, dues, notices) │
│  • Quotas · rate limits · prompt cache                   │
│  • Prometheus /metrics · structured logs · correlation   │
└──────────────────────────────┬───────────────────────────┘
                               │ HTTP (only for state-changing
                               │       actions: book / ticket /
                               │       payment / escalation)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  T2T Backend  (t2t_backend, port 8000)                   │
│  ────────────────────────────────────                    │
│  • Twin identity + JWT                                   │
│  • Policy gate (RBAC + ABAC)                             │
│  • Audit log · escalations · notifications               │
│  • Domain-agnostic — zero condo / society code           │
└──────────────────────────────────────────────────────────┘
                  │
                  ▼
        Postgres · Redis (with fakeredis fallback)
```

**Key property:** read-only operations (list amenities, view notices,
bylaw lookup) run in-process inside ARIA. Only state changes traverse
T2T, so observability + policy + audit live in one place without
slowing down reads.

For the full visual breakdown with sequence diagrams, see
[`PROJECT_DOCS.html`](./PROJECT_DOCS.html).

---

## Module 1 — communityos-aria (ARIA Agent)

### What residents can do

| Capability | Example query | Tool |
|---|---|---|
| Browse amenities | "what amenities are here?" | `list_society_amenities` |
| Filter by type | "show me all the gyms" | `find_amenities_by_type` |
| Amenity detail | "tell me about the wellness spa" | `get_amenity_info` |
| Book an amenity | "book Tower 1 gym tomorrow at 8 am" | `book_amenity` |
| Look up a rule | "are pets allowed?" | `lookup_bylaws` |
| Raise a ticket | "AC isn't working in my unit" | `create_ticket` |
| Check fees | "any pending strata fees?" | `check_dues` |
| Pay fees | "pay my strata fee of $480" | `pay_dues` |
| RSVP | "sign me up for the rooftop social" | `rsvp_to_event` |
| See events | "what events are happening?" | `get_society_events` |
| See notices | "any new notices?" | `get_notices` |

### What admins / property managers can do

- `get_society_insights` — building health snapshot
- `get_pending_escalations` — approval queue
- `approve_escalation` / `deny_escalation`
- `generate_announcement` — draft a notice
- `moderate_content` — review flagged posts

Member queries that look like admin actions are blocked at the
classifier level (admin-keyword guard) so escalations don't leak.

---

## Module 2 — t2t_backend (Protocol Layer)

After the architectural cleanup, T2T is a **pure protocol layer** with
zero condo / society code:

- **Auth** — JWT + admin-secret + Ed25519 twin keys
- **Policy** — RBAC + ABAC + cross-org contracts + payload redaction
- **Router** — `/send`, `/inbox`, `/reply`, WebSocket push
- **Orchestrator** — workflow planner + executor + adapters
- **Audit** — immutable event log, 50+ event types
- **Notifications** — SLA-based escalation queue

Every state-changing action that ARIA fires goes through this layer.
Reads do not.

---

## Bylaw Lookup with Citations

The wedge feature for Canadian condo boards. Upload a building's bylaw
document, ask any rule question, get the exact section reference back.

```python
from aria.ai.bylaws import bootstrap_demo_bylaws, lookup

bootstrap_demo_bylaws("maple_heights")            # idempotent
result = lookup("maple_heights", "can I install hardwood floors?")

# {
#   "status": "found",
#   "results": [
#     {
#       "section":  "3.1",
#       "title":    "Hardwood Flooring and Floor Coverings",
#       "text":     "Hardwood, laminate, vinyl plank, ...",
#       "citation": "§3.1 Hardwood Flooring and Floor Coverings"
#     }
#   ],
#   "summary": "Top match: §3.1 Hardwood Flooring..."
# }
```

In the chat flow, this fires the `lookup_bylaws` intent, runs retrieval,
and emits a `BYLAW_RESULT::{json}` prefix the frontend renders as a
section card with a citation badge. If no relevant section is found,
ARIA explicitly refuses to invent a rule and refers the user to the
property manager.

The 12 demo sections cover every question Canadian boards actually
receive every week: pets, hardwood + acoustic underlay, quiet hours,
smoking, BBQ on balcony, alterations, parking + visitor parking,
move-in deposits, late fees, common-area rules, short-term rentals.

---

## Multi-turn Conversation State

ARIA tracks pending actions per conversation so follow-up answers
resume the right intent.

```
User:  book gym at 7pm tomorrow
ARIA:  We have a few gyms — Tower 1, Tower 2, or Tower 3?
       (parks PendingAction(intent=book_amenity, awaiting=amenity_choice,
                            options=[3 gyms], args={time:"19:00"}))
User:  Tower 1
ARIA:  resumes the booking with the chosen amenity_id → confirmation card
```

Three slot-fill flows are supported:

- **Disambiguation** — multiple matches → user picks by name / block / ordinal
- **Amount** — `pay_dues` without amount → user replies with $X
- **Yes/No** — tool dispatcher offers an alternative → user says yes/sure/please

Negative replies (`no`, `cancel`, `never mind`) clear the parked state
without firing anything. Pending actions auto-expire after 5 minutes so
abandoned conversations don't leak.

Module: `aria/ai/conversation_state.py`.

---

## Eval Suite & Quality Gates

Every prompt edit, classifier tweak, or tool change auto-runs against a
39-case golden test set.

```bash
cd communityos-aria
pytest tests/evals/

# Output:
#   tests/evals/REPORT.md (auto-generated, per-case)
#   pytest gates: minimum 80% pass rate AND all critical cases must pass
```

The suite covers:

- Discovery (3) · filter-by-type (3) · booking (2)
- Tickets (2 incl. urgent) · dues + CAD currency (3)
- Events (1) · notices (1)
- Bylaw lookups (6) · multi-turn (6 — 3 flows × 2 turns)
- Admin guards (4 — member-side blocks) · admin allow (2)
- Edge / chitchat / language hygiene (5)

Currency hygiene (no `Rs.`, no `₹`) and language hygiene (no Hindi
tokens) are checked with word-boundary regex so false positives like
"Rs." matching inside "loungers." don't fire.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **LLM** | Gemini 2.5 Flash (with Pro routing for hard intents) |
| **Embeddings** | sentence-transformers (`all-MiniLM-L6-v2`) when available; lexical IDF fallback otherwise |
| **Bylaw RAG** | Per-org JSON-persisted index with section-aware chunking |
| **Generic RAG** | sentence-transformers + pgvector (society docs / FAQ) |
| **Multi-turn state** | In-process `PendingActionStore` with 5-min TTL |
| **Auth** | HS256 JWT (PyJWT) + admin secret + Ed25519 (T2T) |
| **Chat API** | FastAPI + Uvicorn |
| **MCP server** | FastMCP |
| **Voice (configured)** | LiveKit + Sarvam (Indian-English STT — to be replaced for Canadian English) |
| **Database** | Postgres (asyncpg + SQLAlchemy 2.0) + Alembic |
| **Cache / Redis** | redis-py (with fakeredis fallback) |
| **Rate limiting** | slowapi (JWT-aware) |
| **Quotas** | Per-twin daily $/calls + burst, persisted in Postgres + Redis |
| **Observability** | Prometheus `/metrics`, structlog, X-Request-ID across services |
| **Eval gate** | pytest + 39-case golden set |
| **Tests** | pytest + pytest-asyncio + FastAPI TestClient |

---

## Prerequisites

- Python ≥ 3.11
- Postgres (any recent version; `autocore` DB is the default)
- Redis (optional; fakeredis fallback works for dev)
- `pip` for both modules; `uv` is supported but not required

---

## Installation & Setup

### T2T Backend

```bash
cd community_os/t2t_backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit
```

### ARIA

```bash
cd community_os/communityos-aria
pip install -e .
cp .env.example .env              # then edit
```

### Database

```bash
cd communityos-aria
alembic upgrade head                          # create society + RAG + metrics tables
python -m aria.society.seed_amenities         # 15 Maple Heights demo amenities
python -m aria.society.seed_community         # events + dues (CAD) + notices
```

---

## Running the Project

### Terminal A — T2T Backend

```bash
cd t2t_backend
python -m uvicorn app:app --port 8000
# Swagger:  http://localhost:8000/docs
# Health:   http://localhost:8000/health
# Metrics:  http://localhost:8000/metrics
```

### Terminal B — ARIA

```bash
cd communityos-aria
python chat_api.py                # listens on :8080
# Swagger:  http://localhost:8080/docs
# Health:   http://localhost:8080/health
# Metrics:  http://localhost:8080/metrics
```

### Browser — Frontend

Open `communityos-aria/frontend/index.html`. The default config is
pre-filled (`tanmay_resident` / `maple_heights` / `tanmay-key-001`).
Try the quick-action chips:

- **All Amenities** → 15-card grid
- **All Gyms** → 3 gym cards
- **Pet Rules** → bylaw card with `§2.1` citation
- **Airbnb Policy** → `§12.1`
- **Hardwood Rule** → `§3.1`
- **Book Gym** → triggers disambiguation; reply "Tower 1" to complete

---

## API Reference

### ARIA Chat API

```bash
# Login
curl -X POST http://localhost:8080/aria/login \
  -H "Content-Type: application/json" \
  -d '{
    "twin_id":  "tanmay_resident",
    "api_key":  "tanmay-key-001",
    "org_id":   "maple_heights"
  }'
# → { "access_token": "<jwt>", "expires_in": 86400, ... }

# Chat (Bearer-protected)
curl -X POST http://localhost:8080/aria/chat \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "message":         "can I install hardwood floors?",
    "conversation_id": "demo-001"
  }'
```

The reply may begin with one of these structured prefixes that the
frontend renders as cards:

| Prefix | Renders |
|---|---|
| `AMENITIES_LIST::{json}` | Grid of amenity cards |
| `BOOKING_RESULT::{json}` | Booking confirmation card |
| `BYLAW_RESULT::{json}` | Bylaw section cards with §-citation |

Plain replies (no prefix) render as conversational text.

### Society Endpoints (member-side, no T2T hop)

```
GET  /society/amenities?org_id=maple_heights
GET  /society/amenities/by-type?org_id=maple_heights&type=gym
GET  /society/amenities/{amenity_id}?org_id=maple_heights
GET  /society/amenities/slots?org_id=maple_heights&amenity=clubhouse&date=tomorrow
POST /society/bookings?org_id=...&amenity_id=...&twin_id=...&date=...&slot_start=HH:MM
POST /society/bookings/{booking_id}/cancel
GET  /society/events?org_id=maple_heights
POST /society/events/{event_id}/rsvp?twin_id=...&org_id=...
GET  /society/dues?twin_id=...&org_id=...
GET  /society/notices?org_id=maple_heights
```

### T2T Backend

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | DB + Redis health |
| `GET` | `/metrics` | Prometheus |
| `POST` | `/t2t/send` | Send a policy-gated message envelope |
| `GET` | `/t2t/inbox` | Read messages for a twin |
| `POST` | `/t2t/reply` | Reply to a message |
| `GET` | `/t2t/escalations/pending` | Approval queue |
| `POST` | `/t2t/escalations/{task_id}/approve` | Admin only |
| `POST` | `/t2t/escalations/{task_id}/deny` | Admin only |
| `GET` | `/admin/audit/recent` | Audit log query |
| `POST` | `/admin/twins/register` | Register a new twin |

---

## Environment Variables

### T2T Backend (`t2t_backend/.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | `redis://localhost:6379/0` (fakeredis fallback in dev) |
| `APP_ENV` | `development` / `production` |
| `ADMIN_SECRET` | Header secret for `/admin/*` endpoints |
| `LOG_LEVEL` | `INFO` / `DEBUG` |

### ARIA (`communityos-aria/.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Same Postgres as T2T (separate database recommended in prod) |
| `REDIS_URL` | Redis (fakeredis fallback) |
| `T2T_BASE_URL` | `http://localhost:8000` |
| `T2T_ADMIN_SECRET` | Match the T2T side |
| `GOOGLE_API_KEY` | Gemini API key |
| `JWT_SECRET` | HS256 signing secret (≥ 32 random chars; auto-generated in dev) |
| `JWT_ISSUER` | Default `communityos-aria` |
| `JWT_EXPIRY_HOURS` | Default `24` |
| `TWIN_KEY_TANMAY` / `TWIN_KEY_OPS` / `TWIN_KEY_ARIA` | Per-twin API keys |
| `ARIA_QUOTA_DAILY_USD` | Per-twin daily LLM spend cap |
| `ARIA_QUOTA_DAILY_CALLS` | Per-twin daily LLM call cap |
| `ARIA_QUOTA_BURST_CALLS_PER_MIN` | Burst limit |
| `ARIA_USE_EMBEDDINGS` | Enable embedding intent classifier |
| `ARIA_USE_RAG` | Enable RAG context injection |
| `ARIA_USE_PROMPT_CACHE` | Enable Gemini prompt cache |
| `LIVEKIT_*` / `SARVAM_API_KEY` | Voice (currently inactive — being researched) |

Production environments must set `APP_ENV=production`, real
`JWT_SECRET`, real `GOOGLE_API_KEY`, real `T2T_ADMIN_SECRET`, and an
explicit `ALLOWED_ORIGINS` list — the config validator fails fast
otherwise.

---

## Adding a New Tool

1. Open `aria/tools/member.py` (resident-side) or `admin.py` (admin-side)
2. Add an `@mcp.tool()` decorated async function inside `register(mcp)`
3. Register an intent regex in `chat_api.INTENT_PATTERNS` and add the
   action label to `chat_api.ACTION_MAP`
4. Add a tool dispatcher case in `chat_api.call_t2t_tool` (and
   `simulate_tool` if you want a fallback when T2T is unreachable)
5. Add a `_summarize_tool_result` case for the deterministic reply
   format
6. Add 1-2 eval cases in `tests/evals/cases.py` so the new tool is
   covered by the quality gate
7. `pytest tests/evals/` to confirm green
8. Restart `chat_api.py`

---

## Running Tests

```bash
cd communityos-aria

# Integration tests
pytest tests/test_http_api.py tests/test_amenity_discovery.py -v

# Eval suite (39 golden cases — fast mode, stubbed LLM)
pytest tests/evals/ -v
cat tests/evals/REPORT.md

# Full ARIA suite (excludes pre-existing AI threshold-drift tests)
pytest tests/ --ignore=tests/test_ai_eval.py -v
```

---

## Documentation

- [`PROJECT_DOCS.html`](./PROJECT_DOCS.html) — visual architecture
  deck (16 sections, embedded SVG diagrams, print-friendly)
- [`AI_SPRINT_REPORT.md`](./AI_SPRINT_REPORT.md) — day-by-day
  breakdown of the 2-week AI sprint (eval suite → bylaw RAG →
  multi-turn → polish)
- [`T2T_EXTRACTION_REPORT.md`](./T2T_EXTRACTION_REPORT.md) —
  architectural cleanup that turned T2T into a domain-agnostic
  protocol layer
- [`AMENITY_UPGRADE_REPORT.md`](./AMENITY_UPGRADE_REPORT.md) —
  multi-instance amenity overhaul (3 gyms, 2 pools, etc.)
- [`MIGRATION_PLAN.md`](./MIGRATION_PLAN.md) — original T2T extraction plan

---

## License

Proprietary — CommunityOS. All rights reserved.
