# ARIA Frontend (Next.js)

Next.js 14 (App Router) port of the vanilla `frontend/` dashboard.

## What changed vs `frontend/`

Nothing functional. This is a **safe port**:

- `index.html` → `app/page.tsx` (HTML transcribed to JSX, no logic moved)
- `styles.css` → `app/globals.css` (byte-identical, imported once in layout)
- `app.js` → `public/app.js` (byte-identical, loaded via `next/script` with `strategy="afterInteractive"`)

The 1,186-line client controller (`public/app.js`) still owns the DOM and runs exactly as it did in vanilla. Chat, JWT auth, voice input, file upload, theme toggle, role switch, admin dashboard, escalation queue, content moderation, export, mobile nav, modals, markdown rendering, typewriter effect, and localStorage all work as before.

## Run locally

```bash
npm install
npm run dev      # http://localhost:3000
```

The sidebar **Configuration** card sets the backend URL at runtime. By default it points to `http://localhost:8080` (local ARIA). For the deployed demo set it to `https://aria-backend-vyn0.onrender.com`.

## Deploy

Build is a static-friendly Next.js app. Either:

- **Vercel** — connect this directory (root = `communityos-aria/frontend-next`). No env vars required because the sidebar lets users set the API URL at runtime.
- **Any node host** — `npm run build && npm start`.

## Why not rewrite `app.js` into React components?

The vanilla controller is battle-tested against the ARIA chat API. Rewriting 1,186 lines of state machine + DOM logic in one pass carries high regression risk. This port keeps every feature working from day one. A future component-by-component migration is possible incrementally without breaking the live demo.
