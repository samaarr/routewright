# RouteWright

> Multi-stop transit planning that Google Maps doesn't do.

Live at [routewright.vercel.app](https://routewright.vercel.app)

Type a city, a list of places, and a start time. Get back an ordered timeline with real bus routes, transit durations, and per-leg handoffs to Google Maps for live navigation.

---

## Why this exists

As a student without a car, planning a day trip meant spending hours juggling Google Maps and YouTube. List the places. Mark them on Maps. Check the multi-stop driving route. Then click through each leg one by one to see if buses actually run between them. Then reorder based on opening hours, closing times, dinner reservations, and which side of the city each place is on. Then check the weather so the outdoor spots land on the sunny afternoon and the museums on the quiet morning.

Google Maps does multi-stop driving directions, but not multi-stop transit. So the "no car" version of that planning problem is fundamentally manual. RouteWright is a small step toward fixing it.

This is v1. It does the core thing: ordered stops, real transit timings, clean handoff to Google Maps for live navigation. It doesn't yet do weather, opening hours, route optimisation, or visual map editing. Those are on the roadmap.

---

## What this project is

This is an AI engineering project. The build itself was the goal, specifically, learning the parts of being a full-stack engineer that come *after* writing code:

- Working effectively with an AI coding agent (Claude Code) on a multi-week project
- Deploying to real cloud platforms (Railway, Vercel) and getting them to talk to each other
- Managing API billing, quotas, restrictions, and cost safety (Google Cloud)
- Debugging production-only issues: build failures, env var shadowing, Docker volume permissions, timezone bugs, browser interference
- Making product trade-off calls in real time during deploys
- Translating user feedback into focused fixes vs deferred backlog items

The architecture, design decisions, trade-offs, and debugging direction were mine. Claude Code translated those into code. Claude is listed as a contributor in the commit history.

The build took 3 days end-to-end. The original plan called for 14 days. Working with an AI agent on a tight, well-scoped problem compresses the timeline dramatically, but only if the architecture, the verification discipline, and the trade-off judgment are in place. Those don't come from the AI.

---

## What I learned

The interesting bugs from this build, in roughly the order they bit me:

- **Railway switched its default builder from Nixpacks to Railpack mid-deploy.** Railpack couldn't auto-detect the FastAPI start command from a subdirectory layout. Fix: explicit `Custom Start Command` in Railway dashboard pointing to uvicorn.

- **`pydantic-settings` reads `.env` files from inside the Docker container at runtime,** silently shadowing real production env vars. My local `.env` was being copied into the production image because there was no `.dockerignore`. The "real" Railway env var lost. Fix: add `.dockerignore` excluding `.env`, and conditionally disable `env_file` in pydantic-settings when `APP_ENV=production`.

- **Railway volumes mount as `root:root` at container runtime,** after the Dockerfile's `USER` directive switches to a non-root user. The non-root process can't write to the mounted volume. Workaround for v1: use `/tmp` for SQLite cache (always writable, but resets on redeploy). Proper fix is an entrypoint script that chowns the mount before dropping privileges.

- **`crypto.randomUUID()` requires a secure context** (HTTPS or localhost). Testing via LAN IP from a phone reveals this; production HTTPS hides it. The "+ Add stop" button would silently fail on non-HTTPS access. Fix: fallback to a `Math.random()`-based UUID generator.

- **`<input type="datetime-local">` returns naive ISO strings** with no timezone. The backend strictly required timezone-aware datetimes. Every Generate would have 422'd. Fix: `new Date(input).toISOString()` in the frontend before POSTing.

- **Google's Routes API and Google Maps optimise for different things.** Same trip, different recommended buses. Showing scheduled times in the leg summary made my app appear to disagree with Maps. Cleaner v1: don't display scheduled times; let "Get directions" be the authoritative source.

- **Real user testing surfaced more issues than the test suite did.** The original timeline used a `13:00 → 14:30` arrow between arrival and departure times. Users read it as travel time, not stay time. Full redesign: separate stay duration from times, show clean monotonic chains.

The repo's commit history shows the build order, the bugs, and the iteration.

---

## Architecture

## Architecture

```
User input (free text + start time + mode)
        ↓
  LLM Parser     → structured places, intent, constraints
        ↓
  Geocoder       → Google Places API → cached lat/lng + opening hours
        ↓
  Optimiser      → OR-Tools TSP-with-time-windows on Haversine matrix
        ↓
  Directions     → Google Directions API for N-1 ordered legs
        ↓
  Chain calc     → roll up arrival/departure times across the day
        ↓
  Conflicts      → flag closures, impossible windows, gaps
        ↓
  URL builder    → overview deeplink + per-leg deeplinks
        ↓
  Response: ordered timeline + map links + notes
```

## Stack

| Layer | Tech | Notes |
|---|---|---|
| Frontend | Next.js 14 (App Router) | Vercel-deployable |
| Backend | FastAPI | Python 3.11+ |
| LLM | Claude Haiku | Pluggable via env |
| Optimisation | OR-Tools | TSP-with-time-windows |
| Geocoding | Google Places API | SQLite cache, 30-day TTL |
| Directions | Google Directions API | transit / walking / driving |
| Hosting | Vercel + Railway | Free-tier eligible at MVP scale |

## Repository structure

```
routewright/
├── backend/                    # FastAPI app
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint
│   │   ├── core/               # Config, settings
│   │   ├── routers/            # API routes
│   │   ├── services/           # Parser, geocoder, optimiser, etc.
│   │   └── models/             # Pydantic request/response models
│   ├── tests/                  # pytest
│   ├── pyproject.toml          # Dependencies, ruff, mypy config
│   └── Dockerfile
├── frontend/                   # Next.js app
│   ├── app/                    # App Router pages
│   ├── components/             # React components
│   ├── lib/                    # API client, types
│   └── package.json
├── cache/                      # Local SQLite cache (gitignored content)
├── .github/workflows/          # CI pipelines
├── docs/                       # Spec, pitch, literature review
└── README.md
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in API keys
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for the auto-generated OpenAPI UI.

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local  # set NEXT_PUBLIC_API_URL
npm run dev
```

Open http://localhost:3000.

## API

Two endpoints. The full schema lives in `backend/app/models/`.

### `POST /api/generate`

Input: free-text place list, start time, transport mode.
Output: optimised timeline with map links.

### `POST /api/recalculate`

Lightweight reorder. Skips parsing and geocoding. Used when the user drags stops in the UI.

## Roadmap

Eight-week build, one shippable deliverable per week.

| Week | Deliverable |
|---|---|
| 1 | Repo scaffold, CI green, stubbed endpoints |
| 2 | LLM parser + geocoding cache |
| 3 | OR-Tools optimiser with benchmarks |
| 4 | End-to-end generation: input → optimised plan |
| 5 | Frontend with drag-to-reorder |
| 6 | Polish, edge cases, rate limiting |
| 7 | Public launch |
| 8 | First iteration based on real usage |

See `docs/routewright-pitch.md` for the full vision and `docs/routewright-spec-v2.md` for the technical spec.

## License

MIT
