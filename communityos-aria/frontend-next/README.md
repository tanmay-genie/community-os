# ARIA Frontend — Next.js Reference Implementation

A working Next.js 14 reference frontend for the ARIA backend. **Use this as
the starting point** for the production frontend — it demonstrates every
integration pattern (auth, chat, structured-card rendering) end-to-end.

The goal isn't to ship this UI to production. The goal is to show the
frontend dev *how to integrate with the ARIA backend* so they can rebuild
the UX in whatever design language is required.

---

## What's Inside

```
frontend-next/
├── app/
│   ├── layout.tsx         # Root layout · loads Inter + Tailwind
│   ├── page.tsx           # Single-route app (no login screen by design)
│   └── globals.css
├── components/
│   ├── ChatPanel.tsx      # Top-level: status bar + messages + input + quick-actions
│   ├── ChatInput.tsx      # Send-on-Enter / disabled-while-sending
│   ├── MessageBubble.tsx  # Routes a reply to AmenityGrid / BookingCard / BylawCard / text
│   ├── AmenityCard.tsx    # + AmenityGrid
│   ├── BookingCard.tsx
│   ├── BylawCard.tsx
│   └── QuickActions.tsx   # Demo prompts that exercise each tool
├── lib/
│   ├── types.ts           # TS types for every API shape
│   ├── api.ts             # ARIA REST client · JWT · auto-retry on 401
│   ├── auth.ts            # ensureToken() · refreshToken() · localStorage
│   └── structured.ts      # Parser for AMENITIES_LIST:: / BOOKING_RESULT:: / BYLAW_RESULT::
├── next.config.mjs
├── tailwind.config.ts     # Brand palette pinned (purple/cyan gradient)
├── tsconfig.json
├── vercel.json
├── package.json
└── .env.example
```

---

## Run Locally

```bash
cd communityos-aria/frontend-next
cp .env.example .env.local      # then edit if your backend is elsewhere
npm install
npm run dev                     # → http://localhost:3000
```

You also need the ARIA backend running locally on port 8080. See
[`../README.md`](../README.md) for backend setup.

---

## Environment Variables

| Var | Purpose | Default |
| --- | --- | --- |
| `NEXT_PUBLIC_ARIA_API_URL` | ARIA REST base URL | `http://localhost:8080` |
| `NEXT_PUBLIC_DEMO_TWIN_ID` | Twin to auto-login as | `tanmay_resident` |
| `NEXT_PUBLIC_DEMO_API_KEY` | API key for that twin | `tanmay-key-001` |
| `NEXT_PUBLIC_DEMO_ORG_ID` | Building org_id | `maple_heights` |

> ⚠️ All `NEXT_PUBLIC_*` vars are baked into the browser bundle. For real
> authentication, exchange these for a server-side flow (httpOnly cookies,
> NextAuth, building-issued one-time codes, etc.).

---

## The Three Patterns This Demo Teaches

### 1 · Authentication (`lib/auth.ts`)

ARIA issues **HS256 JWT** tokens via `POST /aria/login`. The demo
auto-logs-in on app start using the `NEXT_PUBLIC_DEMO_*` env vars, caches
the token in `localStorage`, and refreshes on 401.

```ts
// One line — handles cache + refresh + retry
const token = await ensureToken();
fetch(url, { headers: { Authorization: `Bearer ${token}` } });
```

For production, replace `DEMO_IDENTITY` with whatever your auth flow
produces. The rest of the app doesn't change.

### 2 · Chat with Per-Request Correlation (`lib/api.ts`)

Every request to ARIA carries a unique `X-Request-ID`. ARIA echoes it
back in response headers and uses it across its own logs + T2T calls.
When something breaks at 3 AM, you can trace one user message across
every service from this single ID.

```ts
fetch(url, {
  headers: {
    'Authorization': `Bearer ${token}`,
    'X-Request-ID':  genRequestId(),
  },
});
```

The `request()` helper in `api.ts` also automatically retries once on a
401 (token expired → refresh → retry). After the retry it gives up — no
infinite loops.

### 3 · Structured Reply Protocol (`lib/structured.ts` + `MessageBubble.tsx`)

This is the most important pattern. **ARIA's reply isn't always plain
text.** When ARIA wants the UI to render a rich card, it prefixes the
reply with one of these markers:

```
AMENITIES_LIST::{json}\n\n<short human caption>
BOOKING_RESULT::{json}\n\n<short human caption>
BYLAW_RESULT::{json}\n\n<short human caption>
```

The frontend parses the prefix, deserialises the JSON, and renders the
matching card component. The caption (after the blank line) is the
LLM's natural-language summary, shown above the cards.

If no prefix is present, the reply renders as a plain chat bubble.

**This protocol means you don't need a complex `tool_calls` schema on
every reply** — the LLM's reply text *is* the contract.

```ts
const parsed = parseStructured(reply);
switch (parsed.kind) {
  case 'amenities': return <AmenityGrid items={parsed.data.items} />;
  case 'booking':   return <BookingCard booking={parsed.data} />;
  case 'bylaw':     return <BylawCardList payload={parsed.data} />;
  case 'text':      return <p>{parsed.caption}</p>;
}
```

To add a new card type:

1. Define the payload type in `lib/types.ts`
2. Add the prefix string to `PREFIX_KIND` in `lib/structured.ts`
3. Build a new `<NewThingCard />` component
4. Wire it into `MessageBubble.tsx`
5. Backend emits `NEW_THING::{json}` from the matching tool

---

## Multi-turn Flows (free — no extra UI work)

ARIA's backend tracks conversation state by `conversation_id`. As long
as the frontend sends the same ID on follow-ups, the backend resumes
parked actions automatically:

```
USER:  book gym at 7pm tomorrow
ARIA:  We have a few gyms. Tower 1, Tower 2, or Tower 3?
USER:  Tower 1                              ← same conversation_id
ARIA:  ✓ Maple Heights Gym - Tower 1 booked  ← BOOKING_RESULT card
```

The `ChatPanel` component creates one `convId` per mount and reuses it
for every message. That's all the multi-turn integration that's needed
on the client side. The state machine lives in
`communityos-aria/aria/ai/conversation_state.py`.

---

## Deploy to Vercel

1. Vercel → **Add New Project** → import this repo
2. **Root Directory:** `communityos-aria/frontend-next`
3. Vercel auto-detects Next.js
4. Set the four env vars (above table) in **Project Settings → Environment Variables**
5. Click **Deploy**

The backend deploy guide ([`../../DEPLOY.md`](../../DEPLOY.md)) handles
the Render side. After deploying both, update `ALLOWED_ORIGINS` on
Render to include the Vercel URL.

---

## Why So Simple

This is intentional. The production frontend dev should:

- Pick their own UI library (ShadCN, MUI, Mantine, custom design system)
- Build their own component hierarchy
- Add their own state management
- Add their own auth flow

**But not re-invent the API integration.** The `lib/` folder is the
durable contract — copy it into the real frontend repo and the
integration is done.

The components in `components/` are the *minimum* renderers. They show
the data shape. The real frontend dev will redo them.

---

## Backend Contracts Reference

All endpoints live on the ARIA backend (port 8080 locally):

| Method | Path | Used in this demo? |
| --- | --- | --- |
| POST | `/aria/login` | yes — `lib/auth.ts` |
| POST | `/aria/chat` | yes — `lib/api.ts → chat()` |
| GET  | `/aria/chat/stream` | not yet (recommended next step — SSE streaming) |
| GET  | `/health` | yes — connection status |
| GET  | `/society/amenities` | example only |
| GET  | `/society/amenities/by-type` | example only |
| GET  | `/society/amenities/{id}` | example only |
| GET  | `/society/amenities/slots` | example only |
| POST | `/society/bookings` | example only |
| POST | `/society/bookings/{id}/cancel` | example only |
| GET  | `/society/events` | example only |
| POST | `/society/events/{id}/rsvp` | example only |
| GET  | `/society/dues` | example only |
| GET  | `/society/notices` | example only |
| GET  | `/metrics` | Prometheus (ops only) |

The chat endpoint covers every flow shown above — the rest are for when
you want direct REST access to the same data without going through the
LLM.

---

## Suggested Next Steps For The Production Frontend Dev

In rough order of impact:

1. **Replace the auto-login** with a real auth flow (NextAuth + email/SMS)
2. **Switch to SSE streaming** via `/aria/chat/stream` for word-by-word replies
3. **Add a slot-picker modal** for booking flows (the backend already
   serves `/society/amenities/slots`)
4. **Push notifications** via the web-push API
5. **Real-time updates** via the WebSocket endpoint planned at `/aria/ws/{twin_id}`
6. **Admin panel** mirroring the dummy HTML demo's admin role
7. **Mobile-first responsive polish** (current breakpoints are desktop-first)
8. **i18n** (English-only today; add French for Quebec when ready)

---

**Maintained by:** AI/backend team. Owned by frontend dev going forward.
