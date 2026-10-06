# RouteWright — context for Codex

## What this project is

A multi-stop transit itinerary planner. User pastes a list of places + city + start time, gets back a chronological timeline with real transit times and Google Maps deeplinks per leg. Solves the gap that Google Maps doesn't support multi-stop transit routing.

Validated against the TravelPlanner ICLR 2024 benchmark which shows pure-LLM planning fails (0.6% success on hard plans). RouteWright uses a hybrid architecture: simple text parsing for v1, Google Routes API for real schedule data, OR-Tools deferred to v1.5.

## What v1 does (locked scope)

- One endpoint: `POST /api/plan`
- Input: city, ordered stops, start time, transport mode
- Output: flat timeline of alternating Stop and Leg items
- User supplies stop order (no auto-optimisation in v1)
- Stay durations pre-filled from place-type table, user-editable
- Reorder = re-POST the full payload (stateless)

## What v1 does NOT do

- LLM parsing of free-text intent
- OR-Tools auto-optimisation
- Real-time GTFS-R ingestion
- User accounts or saved plans
- Native mobile apps

These are all v1.5+ based on real user feedback.

## Architecture

```
User input → Geocoder (Places Text Search + SQLite cache) → 
Stay defaults lookup → Chain calculator → Routes API per leg (parallel) → 
Conflict detector → Response builder → Frontend timeline
```

## Stack

- Backend: FastAPI on Railway ($5/mo Hobby)
- Frontend: Next.js 14 App Router on Vercel (Hobby — non-commercial)
- LLM: none in v1 (Codex Haiku 4.5 added in v1.5)
- Geocoding: Google Places API (New)
- Directions: Google Routes API (`computeRoutes`, not legacy Directions)
- Cache: SQLite, 30-day TTL

## Build timeline

14 days to a launched v1 with first 50 users. Day-by-day breakdown:

- **Day 1-2:** ✅ Scaffold + types + fixture endpoint (DONE)
- **Day 3-4:** Geocoder service with Places Text Search + SQLite cache
- **Day 5-6:** Wire stay_defaults into real geocode responses
- **Day 7-8:** Replace fixture with real pipeline (parallel Routes API calls)
- **Day 9-10:** Next.js frontend timeline UI
- **Day 11-12:** Drag-to-reorder + refresh-leg button
- **Day 13:** Edge cases, IP rate limiting, billing alerts
- **Day 14:** Deploy + launch on r/Dublin and r/solotravel

## Code conventions

- Python 3.11+, FastAPI async-first
- Pydantic v2 for all request/response models
- Services are stateless modules, no globals
- Settings only via `app.core.config.settings` (never `os.environ` directly)
- Tests use `httpx.MockTransport` for API mocking, never real network in CI
- Ruff for lint + format, mypy strict mode
- Run before committing: `ruff format . && ruff check . && mypy app && pytest`

## Critical gotchas (verified, do not relearn)

1. **`departure_time` is NOT in the public Google Maps URLs spec.** The official deeplink URL only supports origin/destination/waypoints/travelmode. Per-leg deeplinks in v1 do NOT include time — the real schedule comes from server-side Routes API calls shown inline.

2. **Routes API uses uppercase travel modes:** `DRIVE`, `WALK`, `TRANSIT` (not `driving`, `walking`, `transit`). Mode mapping handled in `app/services/directions.py`.

3. **`routingPreference: TRAFFIC_AWARE` is driving-only.** API returns 400 if set for transit or walking. The directions service guards against this.

4. **Routes API durations are protobuf-style strings:** `"300s"` not `300`. Parsed in `_parse_duration`.

5. **Field masks are required and affect billing.** Routes API SKU pricing depends on which fields you request. The current mask is the minimum for transit (line name, duration, distance).

6. **Vercel Hobby is non-commercial only.** Fine for portfolio v1 with no revenue. If RouteWright ever takes donations or runs ads, switch to Pro ($20/mo) or Cloudflare Pages.

7. **Google Maps $200 universal credit ended March 2025.** Now per-SKU free tiers: 10K Essentials, 5K Pro, 1K Enterprise events/month. RouteWright sits in the 5K Pro tier (~217 free generations/month at 8 stops each).

## Pre-launch Google Cloud setup

Run these steps once before going live. They prevent surprise bills and lock out API abuse.

### Budget alert (hard stop)
1. Google Cloud Console → Billing → Budgets & alerts
2. Create budget: amount = **$20/month**, scope = all services
3. Alert thresholds: 50%, 90%, 100% of budget → email to billing account owner
4. **Do NOT enable "cap API usage"** — Cloud Run / Railway will still need quota; instead, use the alert as a trigger to manually kill the API key if needed

### Places API quota cap
1. Google Cloud Console → APIs & Services → Google Places API (New) → Quotas
2. Set "Requests per day" to **2 000** (≈ 250 geocodes/day at 8 stops/plan; the SQLite cache means most re-geocodes are free)
3. Leave "Requests per minute" at default — burst traffic for cache misses is fine

### Routes API quota cap
1. APIs & Services → Routes API → Quotas
2. Set "Compute Routes requests per day" to **2 000** (same reasoning as Places)

### API key restriction
1. APIs & Services → Credentials → the RouteWright server key
2. Application restrictions: **IP addresses** → add Railway's static outbound IPs (found in Railway dashboard → project settings → networking)
3. API restrictions: restrict to **Places API (New)** and **Routes API** only
4. Rotate key before launch (generate new key, update Railway env var, delete old key)

### Vercel environment variable
- Frontend uses `NEXT_PUBLIC_API_URL` pointing to the Railway backend URL
- Never put a server-side API key in a `NEXT_PUBLIC_` variable

## Known v1 limitations (intentionally deferred)

- `primaryType` wins over types-array entries even when the latter is more accurate (see `test_guinness_storehouse_shape`). Fix in v1.5.
- No GTFS-R "ghost bus" detection. Routes API gives scheduled times, not real-time.
- 12-stop hard cap. Google Maps overview URL only supports 10 waypoints; 12 leaves buffer for overflow handling later.
- **Pre-chain leg timing approximation.** To enable parallel Routes API fetching, `plan()` computes each leg's `departureTime` using stay durations only (zero leg travel time assumed). For a stop mid-itinerary, the `departureTime` passed to the Routes API can be 30–90 min earlier than the real departure. This mostly doesn't matter for tourist day trips but can shift transit lookups across rush-hour boundaries on the last few legs of long plans.
- **Leg summary is a single string.** The Routes API returns one `summary` string per leg (e.g. "Take the 47, 18 min"). The UI shows this as-is; there is no sub-step breakdown (walk to stop → board → alight → walk to destination). Multi-step transit breakdown is a v1.5 enhancement.
- **"Get directions" opens Google Maps with live conditions, not the planned departure time.** Google's public Maps URL spec does not accept a `departure_time` parameter. The link is a navigation handoff ("tap when ready to leave"), not a schedule preview. The UI communicates this with a first-leg-only caption: "Tap when you're heading out — live times open in Google Maps."
- **Rate limit state is in-memory.** slowapi uses an in-process counter; a multi-replica Railway deployment would need Redis as the storage backend (`slowapi` supports it via `limits[redis]`). v1 runs single-replica so this is fine.
- **Duplicate stop queries are allowed by the backend but produce a degenerate plan.** Two stops with the same query (e.g. "Trinity College" twice) geocode to the same lat/lng; the leg between them will have near-zero duration and identical arrive/depart times. The frontend now assigns stable UUIDs to each form stop so drag-to-reorder stays correct even with duplicate queries, but the plan data itself is still odd. A v1.5 fix would validate for duplicates at the form level and reject before POSTing.

## v1.5 enhancement list

- Multi-step transit breakdown per leg (walk → board → alight → walk), requires parsing `routes.legs.steps` in `_parse_response` and adding a `steps` field to `LegItem`.
- OR-Tools stop-order optimisation.
- `primaryType` fallback accuracy (use types array when primaryType is generic).
- GTFS-R real-time ghost-bus detection.
- LLM (Codex Haiku) free-text intent parsing for v1.5 input UX.

## Post-launch design polish — when signal warrants

Pre-launch focused on engineering correctness, not visual polish. After 
100+ real users and retention data, these Codex skills are worth 
revisiting if motion or visual taste becomes a measurable retention 
bottleneck. Do NOT install them speculatively; each one nudges Codex 
Code toward a different aesthetic and can balloon scope unprompted.

### Available skills

- kylezantos/design-motion-principles 
  Install: npx skills add kylezantos/design-motion-principles
  Motion audit through three designers' philosophies (Emil Kowalski's 
  restraint, Jakub Krehel's polish, Jhey Tompkins's playfulness). 
  Best for: "the UI feels static or glitchy" — runs a context-aware 
  audit and flags conditional UI without transitions.

- emilkowalski/skill 
  Install: npx skills add emilkowalski/skill
  Emil Kowalski's design engineering principles — animations, 
  performance, code quality, UI primitives. Emil recommends 
  case-by-case use, not always-on. Best for: reviewing a specific 
  component or interaction, especially toasts, drawers, sheets, 
  and other primitive-shaped surfaces.

- leonxlnx/taste-skill 
  Install: npx skills add https://github.com/Leonxlnx/taste-skill
  Anti-slop frontend rules — layout variance, typography, spacing, 
  motion. Has tunable dials (DESIGN_VARIANCE, MOTION_INTENSITY, 
  VISUAL_DENSITY). Best for: when a v2 redesign needs more visual 
  ambition without a designer.

- impeccable.style 
  Aesthetic-leaning taste skill. Save for v2 if redesigning toward a 
  more editorial / premium look.

### Decision rules for when to install

INSTALL when:
- 100+ real users have used the app
- Retention or engagement signals show users dropping off at visual 
  friction points (not functional ones)
- A specific component needs polish (use Emil's skill scoped to it)
- A genuine v2 redesign is planned

DO NOT INSTALL when:
- Pre-launch or first 30 days post-launch
- The app has functional bugs unresolved
- "Polish" is being used as a reason to delay shipping
- The user feedback says the issue is wrong bus times, not motion

### Usage pattern

When installing one of these, ALWAYS scope the audit. Example:

  "Run a motion gap analysis on the timeline and form components only. 
  Identify conditional UI that appears or disappears without transitions. 
  Do NOT recommend hover micro-interactions, scroll animations, or 
  decorative motion. Maximum implementation budget: 1 hour."

Unscoped audits will produce 20+ recommendations, most of which are 
defensible individually but combine into a 1-2 week redesign. Bound 
the scope every time.

## What I want from Codex

Continue the build day-by-day. Each session, pick up where we left off, run tests first to confirm green, then implement the next piece. Always:

- Verify external API behaviour with web search before writing code that depends on it
- Add tests alongside new code, not after
- Document trade-offs as comments or test names (don't hide limitations)
- Keep services stateless and individually testable
- Respect the v1 scope — defer anything that smells like v1.5

## Useful commands

```bash
# Backend dev loop
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload                # dev server
ruff format . && ruff check . && mypy app    # before commit
pytest -q                                    # full suite
pytest --cov=app --cov-report=html           # with coverage report

# Frontend dev loop (once scaffolded)
cd frontend
npm run dev
npm run lint
npm run type-check
```

## Day 14 deploy order

Run these steps in sequence on launch day. Do not skip steps or reorder.

### 0. Pre-flight checks (run these first)
```bash
# Backend
cd backend && source .venv/bin/activate
python -m pytest -q               # must be all green
python -m ruff check . && python -m ruff format . --check
python -m mypy app

# Frontend
cd frontend
npm run lint
npm run type-check
npm run build                     # must compile with 0 errors
```

### 1. Deploy backend to Railway
```bash
# Install Railway CLI if needed: brew install railway
railway login
cd backend
railway up                        # deploys from current directory using Dockerfile
```
In Railway dashboard:
- Set env var: `GOOGLE_MAPS_API_KEY=<production key>`
- Set env var: `APP_ENV=production`
- Set env var: `LOG_LEVEL=INFO`
- Confirm `/healthz` returns `{"status":"ok"}` on the live URL

### 2. Deploy frontend to Vercel
```bash
# Install Vercel CLI if needed: npm i -g vercel
cd frontend
vercel --prod
```
In Vercel dashboard:
- Set env var: `NEXT_PUBLIC_API_URL=https://<railway-backend-url>`
- Confirm the app loads and can submit a 2-stop plan against the live backend

### 3. Smoke test on live
- Submit: Dublin, Ireland / Trinity College / Temple Bar / now+1h / transit
- Confirm 200, timeline shows 2 stops + 1 leg, map links open correctly
- Hit /api/plan 21 times from same IP — confirm 429 on the 21st

### 4. Announce
- r/Dublin: "I built a multi-stop transit planner for Dublin..."
- r/solotravel: "Planning a walking/transit day in any city? I built..."

### Docker build verification (local)
```bash
cd backend
# Requires Docker Desktop to be running
docker build -t routewright-backend .
docker run --rm -e GOOGLE_MAPS_API_KEY=test -p 8000:8000 routewright-backend &
curl http://localhost:8000/healthz   # expect {"status":"ok","version":"0.1.0",...}
docker stop $(docker ps -q --filter ancestor=routewright-backend)
```
Note: Docker daemon was not running at Day 13 verification. Run the above on Day 14 before Railway deploy.

## Reference docs

- Routes API: https://developers.google.com/maps/documentation/routes/compute_route_directions
- Places API (New): https://developers.google.com/maps/documentation/places/web-service/place-types
- Maps URLs spec: https://developers.google.com/maps/documentation/urls/get-started
- Google Maps pricing: https://developers.google.com/maps/billing-and-pricing/pricing

## Local environment gotcha

The user's machine has Anaconda's base environment ahead of the venv on PATH. Plain `pytest`, `mypy`, `ruff`, `uvicorn` all resolve to Anaconda's binaries, which don't have project plugins installed.

**Always invoke tools as Python modules:**
- `python -m pytest -q`
- `python -m mypy app`
- `python -m ruff check . && python -m ruff format .`
- `python -m uvicorn app.main:app --reload`

This routes through the venv's Python. Bare commands will fail with confusing plugin errors.

- Disambiguation gap: "Temple Bar" resolves to the famous pub, not the
  neighbourhood. maxResultCount: 1 takes Google's top result. v1.5 fix:
  show multi-result picker when types disagree.
- Guinness Storehouse returns primaryType=tourist_attraction, not brewery.
  Stay duration still works correctly via the types-array walk (brewery is
  in the array). Documents the value of the two-stage lookup.

  ## Post-launch design polish — when signal warrants

Pre-launch focused on engineering correctness, not visual polish. After 
100+ real users and retention data, these Codex skills are worth 
revisiting if motion or visual taste becomes a measurable retention 
bottleneck. Do NOT install them speculatively; each one nudges Codex 
Code toward a different aesthetic and can balloon scope unprompted.

### Available skills

- **kylezantos/design-motion-principles** 
  npx skills add kylezantos/design-motion-principles
  Motion audit through three designers' philosophies (Emil Kowalski's 
  restraint, Jakub Krehel's polish, Jhey Tompkins's playfulness). 
  Best for: "the UI feels static or glitchy" — runs a context-aware 
  audit and flags conditional UI without transitions.

- **emilkowalski/skill** 
  npx skills add emilkowalski/skill
  Emil Kowalski's design engineering principles — animations, 
  performance, code quality, UI primitives. Emil recommends 
  case-by-case use, not always-on. Best for: reviewing a specific 
  component or interaction, especially toasts, drawers, sheets, 
  and other primitive-shaped surfaces.

- **leonxlnx/taste-skill** 
  npx skills add https://github.com/Leonxlnx/taste-skill
  Anti-slop frontend rules — layout variance, typography, spacing, 
  motion. Has tunable dials (DESIGN_VARIANCE, MOTION_INTENSITY, 
  VISUAL_DENSITY). Best for: when a v2 redesign needs more visual 
  ambition without a designer.

- **impeccable.style** 
  Aesthetic-leaning taste skill. Save for v2 if redesigning toward a 
  more editorial / premium look.

### Decision rules for when to install

INSTALL when:
- 100+ real users have used the app
- Retention or engagement signals show users dropping off at visual 
  friction points (not functional ones)
- A specific component needs polish (use Emil's skill scoped to it)
- A genuine v2 redesign is planned

DO NOT INSTALL when:
- Pre-launch or first 30 days post-launch
- The app has functional bugs unresolved
- "Polish" is being used as a reason to delay shipping
- The user feedback says the issue is wrong bus times, not motion

### Usage pattern

When installing one of these, ALWAYS scope the audit. Example:

  "Run a motion gap analysis on the timeline and form components only. 
  Identify conditional UI that appears or disappears without transitions. 
  Do NOT recommend hover micro-interactions, scroll animations, or 
  decorative motion. Maximum implementation budget: 1 hour."

Unscoped audits will produce 20+ recommendations, most of which are 
defensible individually but combine into a 1-2 week redesign. Bound 
the scope every time.

## v1.5 backlog from user testing (pre-launch feedback)

### High priority
- Editable stay duration per stop. Tap the "stay X min" chip → number 
  input → re-fetch plan. Backend already supports stay_minutes override; 
  just needs UI exposure.

### Medium priority
- Visual polish pass. Two pre-launch testers described UI as "basic" 
  / "2016 feel." Install one of the taste skills (per AGENTS.md 
  post-launch section) AFTER 100+ users confirm visual polish is the 
  retention bottleneck. Specifically: subtle animations on state 
  transitions, spinner on Generate button, smoother card transitions.

### Low priority / v2 ask me before adding this in planning
- Embedded interactive map. Pins on Google Maps embed, drag-to-reorder 
  by geographic position, real-time plan update. Big feature (2-3 days). 
  Requires Google Maps JavaScript API (separate billing line). Worth 
  building only after v1.5 validates the core flow.