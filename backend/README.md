# RouteWright Backend

FastAPI service for parsing free-text place lists, optimising the visit order with OR-Tools, and emitting Google Maps deeplinks.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in API keys
uvicorn app.main:app --reload
```

Visit:

- http://localhost:8000/docs — OpenAPI / Swagger UI
- http://localhost:8000/healthz — health check

## Structure

```
app/
├── main.py              # FastAPI entrypoint
├── core/
│   └── config.py        # Settings via pydantic-settings
├── routers/
│   ├── generate.py      # POST /api/generate
│   ├── recalculate.py   # POST /api/recalculate
│   └── health.py        # GET /healthz
├── services/
│   ├── parser.py        # LLM → structured place list
│   ├── geocoder.py      # Google Places + SQLite cache
│   ├── optimiser.py     # OR-Tools TSP-TW
│   ├── directions.py    # Google Directions API
│   ├── chain.py         # Roll up arrival/departure times
│   ├── conflicts.py     # Detect closure/window conflicts
│   ├── urls.py          # Google Maps deeplink builder
│   └── notes.py         # Human-readable timing notes
└── models/
    ├── request.py       # Pydantic request shapes
    └── response.py      # Pydantic response shapes
```

## Development commands

```bash
# Run the server with hot reload
uvicorn app.main:app --reload

# Lint + format
ruff check .
ruff format .

# Type check
mypy app

# Tests
pytest
pytest --cov=app --cov-report=html  # with coverage report
```

## Endpoints

### `GET /healthz`

Returns `{"status": "ok"}`. Used by the CI smoke test and the platform health probe.

### `POST /api/generate`

Generate an optimised itinerary from free-text input. **Stubbed in week 1**, fully wired by week 4.

### `POST /api/recalculate`

Re-chain timings after a user reorders stops. Skips parsing and geocoding. **Stubbed in week 1**, fully wired by week 4.

## Notes for contributors

- Configuration goes through `app.core.config.settings`. Never read `os.environ` directly outside of `core/config.py`.
- Every service is a stateless module — no globals, no singletons. Dependencies are passed via FastAPI `Depends`.
- The SQLite geocoding cache is the only persistent state. Treat it as a derivable cache; it can always be rebuilt.
