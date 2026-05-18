# Deploy Guide — Render (backend) + Vercel (frontend)

Free-tier production deploy for CommunityOS, suitable for demo and pilot.

| Layer | Where | Cost | Notes |
| --- | --- | --- | --- |
| Frontend (Next.js) | **Vercel** | Free Hobby | Auto HTTPS · global CDN |
| ARIA + T2T backend | **Render Web Services** | Free | 15-min idle spindown · ~30 s cold start |
| Postgres | **Render free Postgres** | Free | 1 GB · 90-day expiry (renewable) |
| Redis | _not used_ | — | ARIA falls back to fakeredis in-memory |

---

## 0 · Prerequisites

- GitHub account · this repo pushed
- [render.com](https://render.com) account (sign in with GitHub)
- [vercel.com](https://vercel.com) account (sign in with GitHub)
- Real **Google Gemini API key** (Render env var)

---

## 1 · Backend — Render

### 1.1 Open the Blueprint

1. Render dashboard → **New** → **Blueprint**
2. Connect this repo · select branch `main`
3. Render reads [`render.yaml`](./render.yaml) and previews three services:
   - `t2t-backend` (web service)
   - `aria-backend` (web service)
   - `communityos-db` (Postgres database)
4. Click **Apply** — first build takes ~5 min.

### 1.2 Set the secrets

After the first deploy completes, open `aria-backend` → **Environment** and
set the values marked `sync: false`:

| Var | Value |
| --- | --- |
| `GOOGLE_API_KEY` | Your real Gemini key |
| `ALLOWED_ORIGINS` | Your Vercel URL (set this after Vercel deploy — Step 2.3) |

Save → Render redeploys automatically.

### 1.3 Verify

```
https://t2t-backend.onrender.com/health
https://aria-backend.onrender.com/health
https://aria-backend.onrender.com/society/amenities?org_id=maple_heights
```

The last URL should return 15 Maple Heights amenities — that confirms the
auto-bootstrap (`ARIA_BOOTSTRAP_DEMO_DATA=true`) seeded the database on
first run.

Copy the **`aria-backend`** URL — you'll need it for Vercel.

### 1.4 Pre-warm before demo

Render free tier sleeps after 15 min of no traffic. To stay warm:

- Hit `/health` once a minute before the demo, OR
- Set up [UptimeRobot](https://uptimerobot.com/) free → ping both
  `/health` URLs every 5 min (also free).

---

## 2 · Frontend — Vercel

### 2.1 Import the Next.js project

1. Vercel dashboard → **Add New** → **Project**
2. Import the same GitHub repo
3. **Root directory:** `communityos-aria/frontend-next`
4. Framework: auto-detected as **Next.js**
5. Build command, output dir: leave defaults

### 2.2 Set the environment variables

In Vercel's project settings → **Environment Variables**:

| Var | Value |
| --- | --- |
| `NEXT_PUBLIC_ARIA_API_URL` | `https://aria-backend.onrender.com` (your Render URL) |
| `NEXT_PUBLIC_DEMO_TWIN_ID` | `tanmay_resident` |
| `NEXT_PUBLIC_DEMO_API_KEY` | `tanmay-key-001` |
| `NEXT_PUBLIC_DEMO_ORG_ID` | `maple_heights` |

Click **Deploy**. First build ~2 min.

### 2.3 Add the Vercel URL to ARIA's CORS

Vercel gave you a URL like `https://aria-demo.vercel.app`. Go back to
Render → `aria-backend` → **Environment** → set:

```
ALLOWED_ORIGINS=https://aria-demo.vercel.app,https://aria-demo-*.vercel.app
```

The wildcard pattern covers preview deploys. Render redeploys
automatically.

### 2.4 Verify end-to-end

Open the Vercel URL. The chat panel should:

- Show "Connected" (green dot) within ~30 s
- Render messages when you type
- Display amenity cards for "what amenities are available?"
- Display bylaw cards with §-citations for "are pets allowed?"

---

## 3 · Custom Domain (optional)

### Frontend (Vercel)

Vercel → project → **Domains** → add your domain → set DNS CNAME to
`cname.vercel-dns.com`. Vercel handles HTTPS.

### Backend (Render)

Render → service → **Settings** → **Custom Domains** → add → set DNS
CNAME to the `*.onrender.com` host shown. Render handles HTTPS.

After custom-domaining the backend, update `NEXT_PUBLIC_ARIA_API_URL` on
Vercel and `ALLOWED_ORIGINS` on Render.

---

## 4 · Maintenance Notes

### Postgres expiry (90 days)

Render's free Postgres expires after 90 days. Before that:

1. Render dashboard → `communityos-db` → **Settings**
2. Click **Renew Free Database**
3. Or: upgrade to Starter plan (~$7/mo) for permanent storage.

If you let it expire, you'll need to re-create the DB and re-deploy
`aria-backend` (the auto-bootstrap will reseed Maple Heights demo data).

### Updating the demo

- Push to `main` on GitHub → Render and Vercel both auto-deploy.
- The Maple Heights seed is **idempotent** — `seed_amenities.py` skips
  rows that already exist by `display_name`. Editing the seed file and
  re-deploying adds new amenities without disturbing existing ones.

### Switching to real building data

When the first real building onboards:

1. Set `ARIA_BOOTSTRAP_DEMO_DATA=false` on Render (or remove the var).
2. Replace `aria/society/seed_amenities.py` with the real building's
   amenities — OR (preferred) write a CSV import script and run it once
   from the Render shell against the real DB.
3. Update `NEXT_PUBLIC_DEMO_*` env vars on Vercel with the real
   building's twin keys.

---

## 5 · Troubleshooting

| Symptom | Fix |
| --- | --- |
| Vercel page loads but shows "Offline" | `NEXT_PUBLIC_ARIA_API_URL` wrong, or `ALLOWED_ORIGINS` on Render doesn't include the Vercel domain |
| First request after demo hangs ~30 s | Cold start from Render free spindown — wait or set up UptimeRobot pings |
| "401 Unauthorized" on `/aria/chat` | Demo twin keys (`TWIN_KEY_TANMAY`) on Render don't match `NEXT_PUBLIC_DEMO_API_KEY` on Vercel |
| "ALLOWED_ORIGINS missing" build error | Production fail-fast — set the var on Render before redeploying |
| Empty `/society/amenities` response | `ARIA_BOOTSTRAP_DEMO_DATA` not set to `true` on first deploy — set it and redeploy once |
| `T2T_BASE_URL` shows blank | Render hadn't finished `t2t-backend` before `aria-backend` built — restart `aria-backend` |

---

## 6 · Going Beyond Free

When traffic outgrows the free tier:

- **Render Starter ($7/mo per service · $7/mo Postgres):** no spindown,
  permanent Postgres, more RAM.
- **Vercel Pro ($20/mo):** team domains, more preview environments,
  better analytics.
- **Move LLM to a higher rate limit** by upgrading the Gemini API plan.
- **Add Redis** (Render Starter Redis $7/mo) to replace fakeredis and
  unlock persistent prompt cache + multi-replica quotas.

Total monthly bill for the first paying customer: **~$30** infra.

---

**Done.** A green-dot Connected chat, live on the public internet, for
zero dollars.
