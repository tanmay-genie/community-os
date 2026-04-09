# ARIA — CommunityOS AI Assistant

> Automated Resident Intelligence Assistant

Voice + Chat AI for housing societies.
Member side: booking, tickets, events, payments.
Admin side: insights, escalations, moderation, content generation.

---

## Architecture

```
Voice (Sarvam STT)          Text (Chat Widget)
        │                           │
        └──────────┬────────────────┘
                   ▼
         ARIA Core (LLM — Gemini 2.5 Flash)
                   │
         MCP Tools (FastMCP server)
           ├── book_amenity
           ├── create_ticket
           ├── get_society_events
           ├── rsvp_to_event
           ├── check_dues / pay_dues
           ├── get_notices
           ├── get_society_insights    [admin]
           ├── get_pending_escalations [admin]
           ├── approve/deny_escalation [admin]
           ├── generate_announcement   [admin]
           └── moderate_content        [admin]
                   │
         T2T Backend (your ZIP)
           ├── policy/     → permission check
           ├── orchestrator/ → workflow execution
           ├── audit/      → immutable log
           ├── memory/     → Redis context
           └── escalation/ → SLA queue
                   │
         CommunityOS DB (PostgreSQL + Redis)
```

---

## Folder structure

```
communityos-aria/
├── server.py           # MCP server — uv run aria
├── agent_aria.py       # Voice agent — uv run aria-voice
├── chat_api.py         # Chat REST API — uvicorn chat_api:app
├── pyproject.toml
├── .env.example
│
└── aria/
    ├── config.py           # All settings from .env
    ├── t2t_client.py       # HTTP client for T2T backend
    ├── tools/
    │   ├── member.py       # Member-side MCP tools
    │   ├── admin.py        # Admin-side MCP tools
    │   └── __init__.py     # Tool registry
    ├── prompts/
    │   └── templates.py    # ARIA + Admin system prompts
    └── context/
        └── loader.py       # Redis user context loader
```

---

## Setup

### 1. Prerequisites

- Python >= 3.11
- uv: `pip install uv`
- LiveKit Cloud account (free tier)
- T2T backend running at `localhost:8000`
- PostgreSQL + Redis running

### 2. Install

```bash
git clone <repo>
cd communityos-aria
uv sync
```

### 3. Configure

```bash
cp .env.example .env
# Fill in all API keys
```

### 4. Run — 3 terminals

**Terminal 1 — MCP Server** (must start first)
```bash
uv run aria
# Starts FastMCP on http://127.0.0.1:9000/sse
```

**Terminal 2 — Voice Agent** (member)
```bash
uv run aria-voice
# Open LiveKit Agents Playground to talk
```

**Terminal 3 — Chat API** (text mode)
```bash
uvicorn chat_api:app --reload --port 8080
# POST /aria/chat for chat widget
```

---

## Chat API usage

```bash
curl -X POST http://localhost:8080/aria/chat \
  -H "Content-Type: application/json" \
  -d '{
    "twin_id": "tanmay_resident",
    "org_id": "SUNRISE_SOCIETY",
    "user_api_key": "resident-api-key",
    "role": "member",
    "message": "Book gym at 7pm"
  }'
```

Response:
```json
{
  "reply": "Done! Gym is booked for you at 7pm.",
  "conversation_id": "uuid",
  "action_taken": "BOOKED_GYM"
}
```

---

## Adding a new tool

1. Open `aria/tools/member.py` or `aria/tools/admin.py`
2. Add a new `@mcp.tool()` function inside `register(mcp)`
3. Add the t2t call in `aria/t2t_client.py` if needed
4. Restart the MCP server

---

## Switching LLM

Open `agent_aria.py` and change:
```python
LLM_PROVIDER = "gemini"   # "gemini" | "openai"
```
That's it. One line swap.

---

## Tech stack

| Component | Technology |
|-----------|-----------|
| MCP server | FastMCP |
| Voice pipeline | LiveKit Agents |
| STT | Sarvam Saaras v3 (Indian-English) |
| LLM | Gemini 2.5 Flash (swappable) |
| TTS | OpenAI nova |
| Chat API | FastAPI |
| Tool backend | T2T (your ZIP) |
| Memory | Redis |
| DB | PostgreSQL |
