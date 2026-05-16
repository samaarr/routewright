"""Rate limiting tests.

Each test builds its own isolated FastAPI app with a fresh Limiter instance
so tests never share counters or exhaust the production 20/day limit.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


def _make_app(plan_limit: str, refresh_limit: str) -> FastAPI:
    """Return a minimal app with independent rate-limited routes."""
    lim = Limiter(key_func=lambda request: "test-ip")

    app = FastAPI()
    app.state.limiter = lim

    async def _rate_limit_handler(_req: Request, _exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "detail": "Daily limit reached — try again tomorrow.",
            },
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    @app.post("/api/plan")
    @lim.limit(plan_limit)
    async def plan_route(request: Request) -> dict:
        return {"ok": True}

    @app.post("/api/refresh-leg")
    @lim.limit(refresh_limit)
    async def refresh_route(request: Request) -> dict:
        return {"ok": True}

    return app


def test_plan_under_limit_succeeds():
    app = _make_app(plan_limit="2/minute", refresh_limit="60/day")
    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/api/plan")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_plan_over_limit_returns_429_with_json_body():
    app = _make_app(plan_limit="1/minute", refresh_limit="60/day")
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/plan")  # consume the one allowed request
    r = client.post("/api/plan")
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limit_exceeded"
    assert "tomorrow" in body["detail"]


def test_plan_and_refresh_limits_are_independent():
    """Exhausting the plan limit must not affect the refresh-leg limit."""
    app = _make_app(plan_limit="1/minute", refresh_limit="2/minute")
    client = TestClient(app, raise_server_exceptions=False)

    # exhaust plan
    client.post("/api/plan")
    r_plan = client.post("/api/plan")
    assert r_plan.status_code == 429

    # refresh-leg still has capacity
    r_refresh = client.post("/api/refresh-leg")
    assert r_refresh.status_code == 200
