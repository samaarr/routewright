# RouteWright

> Turn a messy list of places into an optimised, transit-aware day plan in under ten seconds.

RouteWright solves the multi-stop public transit routing problem that Google Maps doesn't handle. Type or paste a list of places, get back an ordered itinerary with real Google Maps deeplinks for each leg.

## Why this exists

Google Maps supports multi-stop routing for driving, but **not** for public transit. If you're a tourist with six places to see and no car, you're on your own. RouteWright fills that gap with a hybrid architecture: an LLM parses your input, OR-Tools optimises the order, and Google Maps handles the actual navigation via deeplinks.

The architecture is validated by the TravelPlanner benchmark (Xie et al., ICLR 2024), which showed GPT-4 alone achieves only 0.6% success on multi-constraint travel planning. Hybrid LLM-solver approaches achieve near-human performance.

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
