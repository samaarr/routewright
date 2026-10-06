"""Exercise security controls on real handlers and bounded ASGI admission."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.limiter import _client_ip, limiter, request_cost
from app.core.provider_semaphore import consume_provider_budget, get_provider_semaphore, reset_gates
from app.core.security import SecurityMiddleware
from app.main import validate_production


def payload():
    return {
        "city": "Dublin",
        "stops": [{"query": "Trinity College", "stay_minutes": 0}, {"query": "Temple Bar"}],
        "start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "mode": "transit",
    }


def test_untrusted_peer_cannot_spoof_whitelist(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.1/32")
    monkeypatch.setattr(settings, "rate_limit_whitelist_ips", "203.0.113.77")
    request = Request(
        {
            "type": "http",
            "client": ("198.51.100.1", 80),
            "headers": [(b"x-forwarded-for", b"203.0.113.77, 10.0.0.1")],
        }
    )
    assert _client_ip(request) == "198.51.100.1"
    assert request_cost(request) == 1


def test_actual_plan_burst_limit(client, mock_geocode, mock_directions):
    for _ in range(10):
        assert client.post("/api/plan", json=payload()).status_code == 200
    response = client.post("/api/plan", json=payload())
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 61
    assert response.headers["x-request-id"]


def test_validation_does_not_echo_unknown_key_or_timezone(client):
    data = payload()
    data.update({"timezone": "PRIVATE_MARKER", "PRIVATE_KEY_NAME": "secret"})
    response = client.post("/api/plan", json=data)
    assert response.status_code == 422
    assert "PRIVATE_" not in response.text


def test_body_and_media_limits(client):
    response = client.post(
        "/api/plan",
        content=b"x" * (settings.max_request_bytes + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/plan", content="hello").status_code == 415


@pytest.mark.asyncio
async def test_chunked_body_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_request_bytes", 1024)
    messages = iter(
        [
            {"type": "http.request", "body": b"x" * 700, "more_body": True},
            {"type": "http.request", "body": b"x" * 700, "more_body": False},
        ]
    )
    responses = []

    async def receive():
        return next(messages)

    async def send(message):
        responses.append(message)

    async def app(scope, receive, send):
        pytest.fail("Oversized body reached handler")

    await SecurityMiddleware(app)(
        {"type": "http", "method": "POST", "headers": [(b"content-type", b"application/json")]},
        receive,
        send,
    )
    assert responses[0]["status"] == 413


@pytest.mark.asyncio
async def test_concurrent_request_admission(monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_requests", 1)
    entered, release = asyncio.Event(), asyncio.Event()
    responses = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        responses.append(message)

    async def app(scope, receive, send):
        entered.set()
        await release.wait()

    middleware = SecurityMiddleware(app)
    scope = {"type": "http", "method": "GET", "headers": []}
    first = asyncio.create_task(middleware(scope, receive, send))
    await entered.wait()
    await middleware(scope, receive, send)
    assert responses[0]["status"] == 503
    release.set()
    await first
    assert middleware.active == 0


@pytest.mark.asyncio
async def test_provider_budget_and_storage_failure(monkeypatch):
    monkeypatch.setattr(settings, "provider_calls_per_day", 1)
    await consume_provider_budget()
    with pytest.raises(HTTPException) as error:
        await consume_provider_budget()
    assert error.value.status_code == 429

    def broken(*args):
        raise RuntimeError("PRIVATE_STORAGE_PASSWORD")

    monkeypatch.setattr(limiter.limiter, "hit", broken)
    with pytest.raises(HTTPException) as error:
        await consume_provider_budget()
    assert error.value.status_code == 503
    assert "PRIVATE" not in error.value.detail


@pytest.mark.asyncio
async def test_provider_capacity_times_out(monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_provider_calls", 1)
    monkeypatch.setattr(settings, "provider_wait_seconds", 0.01)
    reset_gates()
    async with get_provider_semaphore():
        with pytest.raises(HTTPException) as error:
            async with get_provider_semaphore():
                pytest.fail("Capacity cap bypassed")
        assert error.value.status_code == 503
    reset_gates()


def test_production_requires_shared_storage(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "google_maps_api_key", "test-placeholder")
    monkeypatch.setattr(settings, "rate_limit_storage_uri", "memory://")
    with pytest.raises(RuntimeError, match="shared Redis"):
        validate_production()


def test_trust_all_proxy_addresses_rejected(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_ips", "0.0.0.0/0")
    with pytest.raises(RuntimeError, match="all proxy"):
        validate_production()


def test_daily_retry_after_uses_daily_window(client, mock_geocode, mock_directions, monkeypatch):
    from limits import parse

    route_limit = limiter._route_limits["app.routers.plan.plan"][0]
    monkeypatch.setattr(route_limit, "limit", parse("1/day"))
    assert client.post("/api/plan", json=payload()).status_code == 200
    response = client.post("/api/plan", json=payload())
    assert response.status_code == 429
    assert 3600 < int(response.headers["retry-after"]) <= 86401


def test_budget_failure_is_not_a_fabricated_route(client, mock_geocode, monkeypatch):
    async def exhausted(*args, **kwargs):
        raise HTTPException(
            429, "Daily provider budget exhausted", headers={"Retry-After": "86400"}
        )

    monkeypatch.setattr("app.routers.plan.fetch_leg", exhausted)
    response = client.post("/api/plan", json=payload())
    assert response.status_code == 429
    assert "timeline" not in response.json()


@pytest.mark.asyncio
async def test_cache_cleanup_wired_to_startup(tmp_path, monkeypatch):
    import sqlite3
    import time

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.geocache import put_coordinates

    path = tmp_path / "places.db"
    await put_coordinates("ChIJexpired", 53.0, -6.0, str(path), 30, fetched_at=1)
    await put_coordinates("ChIJfresh", 53.0, -6.0, str(path), 30, fetched_at=time.time())
    monkeypatch.setattr(settings, "cache_db_path", str(path))
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
    with sqlite3.connect(path) as db:
        ids = [r[0] for r in db.execute("SELECT place_id FROM place_coordinates")]
    assert ids == ["ChIJfresh"]
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_budget_blocks_second_actual_outbound_call(monkeypatch):
    import httpx

    from app.services.directions import fetch_leg

    monkeypatch.setattr(settings, "provider_calls_per_day", 1)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"routes": [{"duration": "300s", "distanceMeters": 1000}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        args = dict(
            origin_lat=53,
            origin_lng=-6,
            destination_lat=53.1,
            destination_lng=-6.1,
            depart_at=datetime.now(timezone.utc),
            mode="walking",
            client=client,
        )
        await fetch_leg(**args)
        with pytest.raises(HTTPException) as error:
            await fetch_leg(**args)
        assert error.value.status_code == 429
    assert len(requests) == 1
