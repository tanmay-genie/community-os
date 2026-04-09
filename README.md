# CommunityOS — AI-Powered Housing Society Platform

> **ARIA** (Automated Resident Intelligence Assistant) + **GENIE AI T2T Backend**
>
> Voice + Chat AI for housing societies, powered by a policy-gated Twin-to-Twin communication protocol.

---

## Table of Contents

- [Overview](#overview)
- [Repository Structure](#repository-structure)
- [System Architecture](#system-architecture)
- [Module 1 — communityos-aria (ARIA Agent)](#module-1--communityos-aria-aria-agent)
- [Module 2 — t2t_backend (GENIE AI Backend)](#module-2--t2t_backend-genie-ai-backend)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the Project](#running-the-project)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Contributing](#contributing)

---

## Overview

CommunityOS is an AI-first platform for housing societies that brings together:

- **ARIA** — A voice + chat AI assistant for residents and admins of a housing society. Members can book amenities, raise tickets, check dues, and RSVP to events. Admins get AI-powered insights, escalation management, and content generation.
- **T2T Backend** — A secure, policy-gated Twin-to-Twin (T2T) communication backend powering GENIE AI. Every inter-agent message passes through a strict pipeline: authentication → policy engine → message router → orchestrator → audit log → notification service.

Together, they form a multi-agent AI system designed for real-world housing society operations.

---

## Repository Structure

```
community_os/
├── communityos-aria/          # ARIA Voice + Chat Agent
│   ├── server.py              # FastMCP server (MCP tool host)
│   ├── agent_aria.py          # LiveKit voice agent
│   ├── chat_api.py            # Chat REST API (FastAPI)
│   ├── pyproject.toml
│   ├── .env.example
│   └── aria/
│       ├── config.py          # All settings from .env
│       ├── t2t_client.py      # HTTP client for T2T backend
│       ├── tools/
│       │   ├── member.py      # Member-side MCP tools
│       │   └── admin.py       # Admin-side MCP tools
│       ├── prompts/
│       │   └── templates.py   # ARIA system prompts
│       └── context/
│           └── loader.py      # Redis user context loader
│
└── t2t_backend/               # GENIE AI — T2T Communication Backend
    ├── app.py                 # FastAPI entry point
    ├── config.py              # Pydantic settings
    ├── redis_client.py        # Shared async Redis connection
    ├── requirements.txt
    ├── .env.example
    ├── schemas/               # Message envelopes & intent types
    ├── auth/                  # Twin auth + Ed25519 crypto
    ├── policy/                # RBAC + ABAC policy engine
    ├── router/                # Message routing + WebSocket push
    ├── orchestrator/          # Workflow planner + executor + adapters
    ├── memory/                # Redis-backed twin memory
    ├── audit/                 # Immutable event audit log
    ├── notifications/         # Notifications + SLA escalation
    ├── admin/                 # Twin registration + admin API
    └── tests/                 # Integration tests
```

---

## System Architecture

### ARIA — End-to-End Flow

```
Voice Input (Sarvam STT)        Text (Chat Widget)
         │                              │
         └──────────────┬───────────────┘
                        ▼
            ARIA Core (Gemini 2.5 Flash LLM)
                        │
            MCP Tools (FastMCP server :9000)
              ├── book_amenity
              ├── create_ticket
              ├── get_society_events / rsvp_to_event
              ├── check_dues / pay_dues
              ├── get_notices
              ├── get_society_insights         [admin]
              ├── get_pending_escalations      [admin]
              ├── approve_escalation / deny_escalation [admin]
              ├── generate_announcement        [admin]
              └── moderate_content             [admin]
                        │
            T2T Backend (localhost:8000)
              ├── policy/       → permission check
              ├── orchestrator/ → workflow execution
              ├── audit/        → immutable log
              ├── memory/       → Redis context
              └── escalation/   → SLA queue
                        │
            CommunityOS DB (PostgreSQL + Redis)
```

### T2T Backend — Message Pipeline

Every message follows this exact pipeline — no bypass, no exceptions:

```
Human
  → Personal Twin
  → SID Service
  → Policy Engine (Gate 1: RBAC + ABAC)
  → Agent Router
  → Target Twin
  → Policy Re-Validation (Gate 2)
  → Orchestration Layer (Planner → Executor)
  → Execution Engine
  → Audit Log
  → Notification Service
```

---

## Module 1 — communityos-aria (ARIA Agent)

### What it does

ARIA is the conversational layer of CommunityOS. It understands natural language from residents and admins, routes requests through the appropriate MCP tools, and talks to the T2T backend to execute real actions.

**Member capabilities:**
- Amenity booking
- Support ticket creation
- Event listing and RSVP
- Due checking and payment
- Society notice board

**Admin capabilities:**
- Society-wide analytics and insights
- Pending escalation management (approve/deny)
- AI-generated announcements
- Content moderation

### Components

| File | Role |
|------|------|
| `server.py` | FastMCP server — hosts all MCP tools on `http://127.0.0.1:9000/sse` |
| `agent_aria.py` | LiveKit voice agent — STT → LLM → TTS pipeline |
| `chat_api.py` | FastAPI REST endpoint — `POST /aria/chat` for text-based widget |
| `aria/config.py` | Pydantic settings loaded from `.env` |
| `aria/t2t_client.py` | Async HTTP client for all T2T backend calls |
| `aria/tools/member.py` | MCP tools for resident users |
| `aria/tools/admin.py` | MCP tools for society admins |
| `aria/prompts/templates.py` | System prompt templates for ARIA and admin mode |
| `aria/context/loader.py` | Loads user context from Redis before each LLM call |

---

## Module 2 — t2t_backend (GENIE AI Backend)

### What it does

The T2T backend is a production-grade FastAPI server implementing the Twin-to-Twin Communication Protocol for GENIE AI. It enforces strict security, policy gating, orchestration, and auditability for every inter-agent interaction.

### Core Design Principles

- **Policy-gated** — Every message passes RBAC + ABAC checks before routing
- **Auditable** — Every event is written to an immutable audit log with 50+ event types
- **Idempotent** — Duplicate message detection via Redis-backed idempotency keys
- **Reversible** — Compensation/rollback logic for failed workflow steps
- **Cryptographically signed** — Ed25519 key pairs for twin identity verification
- **Event-driven** — WebSocket push for real-time twin-to-twin delivery

### Module Breakdown

#### `schemas/`
- `envelope.py` — `MessageEnvelope` Pydantic model + `get_signable_bytes()` for signing
- `intents.py` — `IntentType`, `MessageState`, `RiskLevel` enums

#### `auth/`
- `auth.py` — `verify_twin()`, `TwinContext`, `register_twin()`
- `models.py` — `TwinModel` SQLAlchemy ORM (stores hashed API key + signing public key)
- `crypto.py` — Ed25519 key generation, signing, and verification via PyNaCl
- `db.py` — Async PostgreSQL engine + `get_db()` + `Base`

#### `policy/`
- `policy.py` — `policy_check()` → `PolicyResult` (ALLOW / DENY / ESCALATE)
- `rbac_rules.py` — Role → allowed intents matrix
- `abac_rules.py` — Clearance level, risk tolerance, org boundary, autonomy rules
- `contracts.py` — Cross-org contract model + validation
- `redaction.py` — Payload redaction profiles (PII stripping)

#### `router/`
- `router.py` — `POST /send`, `GET /inbox`, `POST /reply`
- `store.py` — DB operations + idempotency + message ordering + loop detection
- `messages.py` — `MessageModel` ORM + state machine
- `websocket.py` — WebSocket push at `/t2t/ws/{twin_id}`

#### `orchestrator/`
- `planner.py` — Intent → `WorkflowPlan` (ordered steps with dependencies)
- `executor.py` — Step-by-step execution + failure handling + retry
- `compensation.py` — Rollback / undo logic for failed plans
- `adapters/`
  - `base.py` — `BaseAdapter` interface + adapter registry
  - `dummy.py` — `DummyAdapter` for testing
  - `jira.py` — Jira integration (httpx + retry via tenacity)
  - `llm_adapter.py` — LLM adapter for AI-driven step execution

#### `memory/`
- `user.py` — Personal twin memory (Redis)
- `org.py` — Org-level shared memory
- `decision.py` — Decision graph for multi-step reasoning

#### `audit/`
- `audit.py` — `log_event()` + `EventModel` ORM
- `taxonomy.py` — `EventType` enum (50+ standard audit event types)

#### `notifications/`
- `notifications.py` — `send_notification()` + `/notifications` API
- `escalation.py` — SLA-based escalation tasks + `/escalation` API

#### `admin/`
- `admin_router.py` — Twin registration, audit log queries, contract management

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | Gemini 2.5 Flash (swappable to OpenAI) |
| **MCP Server** | FastMCP |
| **Voice Pipeline** | LiveKit Agents |
| **STT** | Sarvam Saaras v3 (Indian-English optimized) |
| **TTS** | OpenAI nova |
| **Chat API** | FastAPI + Uvicorn |
| **T2T Backend** | FastAPI + Uvicorn |
| **Database** | PostgreSQL (asyncpg + SQLAlchemy 2.0) |
| **Cache / Memory** | Redis (async) |
| **Crypto** | PyNaCl (Ed25519) |
| **Auth** | JWT (python-jose) + Bcrypt |
| **HTTP Client** | httpx |
| **Retry Logic** | tenacity |
| **Logging** | structlog |
| **Testing** | pytest + pytest-asyncio |
| **Package Manager** | uv (ARIA) / pip (T2T backend) |

---

## Prerequisites

Make sure the following are installed and running:

- Python >= 3.11
- PostgreSQL (running with a configured database)
- Redis (optional but recommended — required for memory, idempotency, WebSocket push)
- `uv` package manager — `pip install uv`
- LiveKit Cloud account (free tier) — for voice agent

---

## Installation & Setup

### T2T Backend

```bash
cd community_os/t2t_backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your PostgreSQL and Redis credentials
```

**Minimum `.env` for T2T backend:**
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/communityos
REDIS_URL=redis://localhost:6379/0
APP_ENV=development
ADMIN_SECRET=change-me-in-production
```

### ARIA Agent

```bash
cd community_os/communityos-aria

# Install dependencies using uv
uv sync

# Configure environment
cp .env.example .env
# Fill in all API keys (Gemini, LiveKit, Sarvam, OpenAI, Redis)
```

---

## Running the Project

Start the services in this exact order:

### Step 1 — T2T Backend

```bash
cd t2t_backend
uvicorn app:app --reload --port 8000
# Swagger UI: http://localhost:8000/docs
```

### Step 2 — ARIA MCP Server (must start before voice/chat)

```bash
cd communityos-aria
uv run aria
# FastMCP server on: http://127.0.0.1:9000/sse
```

### Step 3 — Voice Agent (optional)

```bash
cd communityos-aria
uv run aria-voice
# Open LiveKit Agents Playground to test voice
```

### Step 4 — Chat API

```bash
cd communityos-aria
uvicorn chat_api:app --reload --port 8080
# REST endpoint: http://localhost:8080/aria/chat
```

---

## API Reference

### T2T Backend

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Service info + pipeline summary |
| `GET` | `/health` | Health check |
| `POST` | `/send` | Send a message through the T2T pipeline |
| `GET` | `/inbox` | Get messages for a twin |
| `POST` | `/reply` | Reply to a message |
| `GET` | `/t2t/ws/{twin_id}` | WebSocket connection for real-time push |
| `GET` | `/notifications` | Get notifications for a twin |
| `GET` | `/escalation` | Get escalation queue |
| `POST` | `/admin/twins/register` | Register a new twin (admin only) |
| `GET` | `/admin/audit` | Query audit log (admin only) |

**Register a twin (admin):**
```bash
curl -X POST http://localhost:8000/admin/twins/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: your-admin-secret" \
  -d '{
    "twin_id": "resident_twin_001",
    "org_id": "SUNRISE_SOCIETY",
    "role": "Resident",
    "clearance": "PUBLIC",
    "raw_api_key": "resident-secret-key",
    "autonomy_level": "SUPERVISED",
    "max_risk_level": "LOW"
  }'
```

### ARIA Chat API

**Send a chat message:**
```bash
curl -X POST http://localhost:8080/aria/chat \
  -H "Content-Type: application/json" \
  -d '{
    "twin_id": "resident_twin_001",
    "org_id": "SUNRISE_SOCIETY",
    "user_api_key": "resident-secret-key",
    "role": "member",
    "message": "Book gym at 7pm tomorrow"
  }'
```

**Response:**
```json
{
  "reply": "Done! Gym booked for tomorrow at 7pm.",
  "conversation_id": "uuid-here",
  "action_taken": "BOOKED_GYM"
}
```

---

## Environment Variables

### T2T Backend (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async URL | `postgresql+asyncpg://user:pass@localhost:5432/db` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `APP_ENV` | Environment (`development`/`production`) | `development` |
| `ADMIN_SECRET` | Header secret for admin endpoints | `change-in-production` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

### ARIA Agent (`.env`)

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `OPENAI_API_KEY` | OpenAI API key (TTS + fallback LLM) |
| `LIVEKIT_URL` | LiveKit server URL |
| `LIVEKIT_API_KEY` | LiveKit API key |
| `LIVEKIT_API_SECRET` | LiveKit API secret |
| `SARVAM_API_KEY` | Sarvam AI API key (STT) |
| `REDIS_URL` | Redis URL for context storage |
| `T2T_BASE_URL` | T2T backend URL (default: `http://localhost:8000`) |

---

## Switching LLM Provider (ARIA)

ARIA supports Gemini and OpenAI interchangeably. Open `agent_aria.py` and change one line:

```python
LLM_PROVIDER = "gemini"   # Options: "gemini" | "openai"
```

---

## Adding a New MCP Tool

1. Open `aria/tools/member.py` (for residents) or `aria/tools/admin.py` (for admins)
2. Add a new `@mcp.tool()` decorated function inside `register(mcp)`
3. If it needs a new backend call, add the corresponding method in `aria/t2t_client.py`
4. Restart the MCP server (`uv run aria`)

---

## Running Tests

```bash
cd t2t_backend
source venv/bin/activate
pytest tests/test_t2t.py -v
```


---

## License

Proprietary — GENIE AI / CommunityOS. All rights reserved.
