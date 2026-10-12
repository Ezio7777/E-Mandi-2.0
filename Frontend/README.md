# E-Mandi 2.0 (Frontend)

Next.js 15 (App Router), TypeScript strict, Tailwind, Redux Toolkit (client state), TanStack Query (server state), React Hook Form + Zod, Framer Motion.
The backend is a separate repo; this app talks to it only through `src/lib/api/*`.

## Deploy to Vercel (no backend needed)
Import the repo into Vercel and deploy. **Set no environment variables.** With no `NEXT_PUBLIC_API_URL` the app runs on built-in sample data that is answered inside the browser (`src/lib/demo/`): demo logins for all three roles, the AI-grading and price flow, matching, orders, payments, admin approvals and the guided tour all work, with nothing else running. Data resets on refresh.

| Variables | Result |
|---|---|
| none | built-in demo data (what you want for a portfolio link) |
| `NEXT_PUBLIC_API_URL=https://your-api` | your real backend |
| `NEXT_PUBLIC_API_URL=…` + `NEXT_PUBLIC_DEMO_MODE=true` | demo data even though a URL is set |

The demo layer implements the same endpoints and DTOs as `docs/BACKEND_CONTRACT.md`, so switching to the real backend later needs no code change.

## Run
```bash
cp .env.example .env.local      # set NEXT_PUBLIC_API_URL
npm install
npm run dev                     # http://localhost:3000
npm test && npm run typecheck && npm run lint
```
## Docker
```bash
docker compose up --build       # or: docker build --build-arg NEXT_PUBLIC_API_URL=... -t emandi-web .
```

## Backend contract (what the frontend calls)
Auth: `POST /auth/login | /auth/otp/request | /auth/otp/verify | /auth/google {credential} | /auth/demo {role} | /auth/logout`, `GET /auth/me`.
Uploads: `POST /uploads/init` → `{uploadUrl, fields?, objectKey}` → browser PUT/POST to S3 → `POST /uploads/confirm {objectKey}`; `POST /uploads/sample {sampleId}`.
Grading: `POST /grading` → `{jobId}`; `GET /grading/:jobId`; optional WS `/ws/grading/:jobId`. Pricing: `GET /pricing/suggest`.
Marketplace/orders/payments/matching/admin/voice: see `src/lib/api/*.ts` and `src/types/index.ts` (DTOs).
Session: httpOnly cookie (CORS with credentials) or bearer `accessToken` in the login response (kept in memory).
The middleware reads a non-sensitive `emandi_session` hint cookie only for redirects; the backend enforces all auth.

## Still to wire when the backend exists
- Payment provider widget in `src/features/payments/payment-provider.ts` (sandbox stub included).
- Strict CSP once Google/payment script origins are final.
- Replace demo crop SVGs in `public/demo-crops/` with real photos (same filenames or update `sample-crops.ts`).

Full backend hand-off (endpoints, DTOs, CORS, camelCase rule): `docs/BACKEND_CONTRACT.md`.

## Local QA with the external mock server (optional)
You no longer need this just to see the app: with no `NEXT_PUBLIC_API_URL` it uses built-in demo data. `tools/mock-api/server.mjs` is only for testing the real-backend (HTTP) code path. It is a small stand-in that follows the contract above (seeded farmer/buyer/admin data). It exists only for QA and is not used by the app.
```bash
npm run mock-api                       # :8000
npm run build && npm start             # against NEXT_PUBLIC_API_URL=http://localhost:8000
npm i --no-save puppeteer-core         # then, with CHROME=/path/to/chrome:
cd tools/qa && node sweep.mjs   # (demo-session.mjs lets these scripts sign in on the built-in demo data)          # overflow / 200 / <h1> check per route (env: ROLE, WIDTHS, THEMES, LOCALE)
node tourshots.mjs                     # screenshots of the tour steps
node axe.mjs                           # axe-core accessibility audit (npm i --no-save axe-core)
node tourtl.mjs                        # frame-by-frame tour check (ROLE, W, H, STEPS, DUMP=0)
node sidebar.mjs && node drawer.mjs    # sidebar / mobile drawer motion curves
node flows.mjs                         # demo login, tour, sell wizard, redirects, role guard, theme
```
The mock has no WebSocket endpoint, so the browser console shows harmless 404s for `/ws/*` (the app falls back to polling).

## Notes
- Translated (EN/HI/KN): navigation, page titles, wizard, tables, dashboards, empty/error states and the landing page. The /how-it-works page, header and footer are translated too. The brand name stays "E-Mandi" in the logo.
- Saved UI prefs (language, tour progress) are restored after hydration via `rehydrateFromStorage` and the Provider's `serverState`. Applying them earlier causes React hydration mismatch (#418).
- Backend-supplied text (chart month labels, AI explanations, price notes) is shown as received.

## Motion
- **Guided tour** (`src/features/tour/`): each step is a strict sequence: the old card leaves → the spotlight closes (if the page changes) → route loads → spotlight springs to the new target → only then the card fades in. Nothing renders until the signed-in shell exists, so it never appears over the login page. Card placement is a pure function (`tour-layout.ts`, tested) that avoids covering the highlighted element and docks for tall targets.
- **Sidebar**: width and labels animate (≈270 ms, ease-out); icons never move. **Mobile drawer / dialogs / menus**: eased open (≈300 ms) and faster close. **Pages**: opacity-only fade (no transform, so the tour can measure targets mid-transition).
- Everything honours `prefers-reduced-motion`.
