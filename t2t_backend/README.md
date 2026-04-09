# GENIE AI — T2T Backend

**Twin-to-Twin Communication Protocol — Python / FastAPI Backend**

Policy-gated · Auditable · Event-driven · Idempotent · Reversible · Cryptographically Signed

---

## The Golden Rule

Every message must pass through this exact pipeline. No bypass. No exceptions.

```
Human → Personal Twin → SID Service → Policy Engine (Gate 1) → Agent Router
→ Target Twin → Policy Re-Validation (Gate 2) → Orchestration Layer
→ Execution Engine → Audit Log → Notification Service
```

---

## Project Structure

```
t2t_backend/
├── app.py                        # FastAPI entry point + router registration
├── config.py                     # Settings from .env (Pydantic)
├── redis_client.py               # Shared async Redis connection
├── requirements.txt
├── .env.example
├── PROJECT_DOCUMENTATION.txt     # Full file-by-file documentation
│
├── schemas/
│   ├── envelope.py               # MessageEnvelope + get_signable_bytes()
│   └── intents.py                # IntentType, MessageState, RiskLevel, enums
│
├── auth/
│   ├── auth.py                   # verify_twin() + TwinContext + register_twin()
│   ├── models.py                 # TwinModel ORM (with signing key + lookup hash)
│   ├── crypto.py                 # Ed25519 keygen, sign, verify (PyNaCl)
│   └── db.py                     # AsyncEngine + get_db() + Base
│
├── policy/
│   ├── policy.py                 # policy_check() → PolicyResult (ALLOW/DENY/ESCALATE)
│   ├── rbac_rules.py             # Role → allowed intents matrix
│   ├── abac_rules.py             # Clearance, risk, org boundary, autonomy rules
│   ├── contracts.py              # Cross-org contract model + validation
│   └── redaction.py              # Payload redaction profiles (PII stripping)
│
├── router/
│   ├── router.py                 # POST /send, GET /inbox, POST /reply
│   ├── store.py                  # DB ops + idempotency + ordering + loop detection
│   ├── messages.py               # MessageModel ORM + state machine
│   └── websocket.py              # WebSocket push (/t2t/ws/{twin_id})
│
├── orchestrator/
│   ├── planner.py                # Intent → WorkflowPlan (ordered steps)
│   ├── executor.py               # Step execution + failure handling
│   ├── compensation.py           # Rollback / undo logic
│   └── adapters/
│       ├── base.py               # BaseAdapter interface + registry
│       ├── dummy.py              # DummyAdapter (testing)
│       └── jira.py               # Jira integration (httpx + retry)
│
├── memory/
│   ├── user.py                   # Personal twin memory (Redis)
│   ├── org.py                    # Org-level shared memory
│   └── decision.py               # Decision graph
│
├── audit/
│   ├── audit.py                  # log_event() + EventModel
│   └── taxonomy.py               # EventType enum (50+ standard types)
│
├── notifications/
│   ├── notifications.py          # send_notification() + /notifications API
│   └── escalation.py             # Escalation tasks + /escalation API
│
├── admin/
│   └── admin_router.py           # Twin registration, audit queries, contracts
│
└── tests/
    └── test_t2t.py               # Integration tests (full pipeline)
```

---

## Setup

### 1. Clone & install

```bash
git clone <repo>
cd t2t_backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your local PostgreSQL and Redis URLs
```

Example `.env`:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/autocore
REDIS_URL=redis://localhost:6379/0
APP_ENV=development
ADMIN_SECRET=admin-secret-change-in-prod
```

### 3. Prerequisites

Make sure **PostgreSQL** is running locally with your configured database.
**Redis** is optional — without it, idempotency checks, loop detection, and memory features will be degraded, but the core pipeline works fine.

### 4. Run the server

```bash
uvicorn app:app --reload --port 8000
```

The server auto-creates all DB tables on first startup in development mode.

### 5. API docs

Open `http://localhost:8000/docs` for interactive Swagger UI.

---

## Registering Twins

Use the admin endpoint (protected by `X-Admin-Secret` header):

```bash
curl -X POST http://localhost:8000/admin/twins/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: admin-secret-change-in-prod" \
  -d '{
    "twin_id": "bilal_exec_twin",
    "org_id": "GENIE_AI",
    "role": "Founder_CEO",
    "clearance": "CONFIDENTIAL",
    "raw_api_key": "bilal-secret-key-2024",
    "autonomy_level": "SEMI_AUTONOMOUS",
    "max_risk_level": "HIGH",
    "signing_public_key": null
  }'
```

To enable Ed25519 signing for a twin, generate a keypair and pass the public key:

```python
from auth.crypto import generate_keypair
private_key, public_key = generate_keypair()
# Store private_key securely on the client side
# Pass public_key as signing_public_key during registration
```

---

## Sending a T2T Message

```bash
curl -X POST http://localhost:8000/t2t/send \
  -H "Authorization: Bearer bilal-secret-key-2024" \
  -H "Content-Type: application/json" \
  -d '{
    "from": {"org_id": "GENIE_AI", "twin_id": "bilal_exec_twin", "role": "Founder_CEO", "clearance": "CONFIDENTIAL"},
    "to": {"org_id": "GENIE_AI", "twin_id": "syed_product_twin"},
    "thread_id": "550e8400-e29b-41d4-a716-446655440000",
    "sequence_no": 1,
    "intent": {"type": "PROPOSE", "name": "PROPOSE_LAUNCH", "risk_level": "LOW", "sla_minutes": 1440},
    "payload": {"product": "ALBIS Enterprise Concierge", "timeline": "Q2"},
    "security": {
      "signature_alg": "ed25519",
      "idempotency_key": "550e8400-e29b-41d4-a716-446655440001",
      "nonce": "550e8400-e29b-41d4-a716-446655440002"
    }
  }'
```

Response:
```json
{"status": "routed", "message_id": "...", "decision": "ALLOW", "reason": "..."}
```

The send pipeline runs: auth → signature verify → loop detection → idempotency → policy gate 1 → redaction → save → WebSocket push → audit log.

---

## Fetching Inbox

```bash
curl http://localhost:8000/t2t/inbox/syed_product_twin \
  -H "Authorization: Bearer syed-secret-key-2024"
```

---

## Replying

```bash
curl -X POST http://localhost:8000/t2t/reply \
  -H "Authorization: Bearer syed-secret-key-2024" \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "550e8400-e29b-41d4-a716-446655440000",
    "original_message_id": "<message_id from send response>",
    "from_twin_id": "syed_product_twin",
    "intent_type": "CONFIRM",
    "payload": {"confirmed": true},
    "idempotency_key": "550e8400-e29b-41d4-a716-446655440099"
  }'
```

A CONFIRM triggers Policy Gate 2 → Orchestrator execution automatically.

---

## WebSocket Real-Time Push

Instead of polling `/inbox`, twins can connect via WebSocket for instant notifications:

```javascript
const ws = new WebSocket("ws://localhost:8000/t2t/ws/syed_product_twin");

ws.onopen = () => {
  ws.send(JSON.stringify({ token: "syed-secret-key-2024" }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "auth_ok") console.log("Connected!");
  if (data.type === "new_message") console.log("New message:", data.message_id);
};
```

---

## Cross-Org Contracts

Twins from different organizations can only communicate when an active contract exists:

```bash
# Create a contract
curl -X POST http://localhost:8000/admin/contracts \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: admin-secret-change-in-prod" \
  -d '{
    "org_a_id": "GENIE_AI",
    "org_b_id": "PARTNER_CORP",
    "redaction_profile": "CROSS_ORG_SAFE"
  }'

# List contracts for an org
curl http://localhost:8000/admin/contracts/GENIE_AI \
  -H "X-Admin-Secret: admin-secret-change-in-prod"
```

Redaction profiles:
- **INTERNAL_FULL** — no redaction (same org)
- **CROSS_ORG_SAFE** — strips PII fields (email, phone, SSN, etc.)
- **REGULATED_MINIMAL** — only keeps metadata (intent, status, type)

---

## Running Tests

```bash
pip install pytest pytest-asyncio httpx aiosqlite
pytest tests/ -v
```

---

## All API Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/t2t/send` | Bearer | Send T2T message |
| GET | `/t2t/inbox/{twin_id}` | Bearer | Fetch inbox |
| POST | `/t2t/reply` | Bearer | Reply to message |
| WS | `/t2t/ws/{twin_id}` | Token msg | Real-time push |
| GET | `/notifications/{twin_id}` | Bearer | Get notifications |
| PUT | `/notifications/{id}/read` | Bearer | Mark as read |
| GET | `/escalation/pending/{org_id}` | Bearer | Pending tasks |
| POST | `/escalation/{task_id}/approve` | Bearer | Approve escalation |
| POST | `/escalation/{task_id}/deny` | Bearer | Deny escalation |
| POST | `/admin/twins/register` | Admin | Register twin |
| GET | `/admin/health` | Admin | System health |
| GET | `/admin/audit/message/{id}` | Admin | Message audit trail |
| GET | `/admin/audit/twin/{id}` | Admin | Twin audit trail |
| GET | `/admin/audit/denied/{org_id}` | Admin | Denied events |
| POST | `/admin/contracts` | Admin | Create contract |
| GET | `/admin/contracts/{org_id}` | Admin | List contracts |
| GET | `/health` | None | Health check |

---

## Key Design Decisions

| Decision | Why |
|---|---|
| Two policy gates | Context can change between message send and execution |
| Ed25519 signing | Non-repudiation — every message is cryptographically signed |
| O(1) auth lookup | SHA-256 indexed hash avoids scanning all twins on every request |
| WebSocket + polling | Real-time push with polling fallback for reliability |
| Redis idempotency | Prevents double-execution from network retries |
| Loop detection | Redis hop counter prevents infinite message cycles between twins |
| Cross-org redaction | PII is automatically stripped from cross-org payloads |
| Background orchestration | HTTP returns immediately; execution is async |
| Append-only audit log | Immutable compliance record — never updated or deleted |
| Adapter pattern | Add new tool integrations without changing the core engine |
| Compensation engine | Every workflow step can be reversed if a later step fails |

---

## Database Tables

| Table | Model | Purpose |
|-------|-------|---------|
| `twins` | TwinModel | Twin identities + keys |
| `messages` | MessageModel | All T2T messages |
| `audit_events` | EventModel | Immutable audit trail |
| `escalation_tasks` | EscalationTaskModel | Human review tasks |
| `notifications` | NotificationModel | Twin notifications |
| `org_contracts` | OrgContractModel | Cross-org contracts |
