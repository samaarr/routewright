"""Security regression checks for the v2 endpoints (Step 9).

Trusted-proxy identity, HTTPS/HSTS behaviour, response headers on JSON and
streaming endpoints, generic errors and server-key handling. No network.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import settings
from app.core.limiter import _client_ip
from app.main import app, validate_production
from app.routers import plan_v2, selection
from app.services import autocomplete, directions, place_details
from app.services.autocomplete import Suggestion
from tests.test_plan_v2_verified import _NOW, FakePlaces, FakeRoutes, _payload, _stop

SERVER_KEY = "AIzaSyTEST-server-key-must-not-leak-0123456"


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


# --- trusted proxies ----------------------------------------------------------------


def test_forwarded_for_ignored_from_untrusted_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    assert _client_ip(_request("203.0.113.5", "198.51.100.7")) == "203.0.113.5"


def test_forwarded_chain_uses_first_untrusted_hop_from_the_right(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    # client-supplied spoof, real client, then a trusted internal hop
    req = _request("10.0.0.2", "1.2.3.4, 198.51.100.7, 10.0.0.9")
    assert _client_ip(req) == "198.51.100.7"


def test_oversized_or_malformed_chain_falls_back_to_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    assert _client_ip(_request("10.0.0.2", ",".join(["1.1.1.1"] * 17))) == "10.0.0.2"
    assert _client_ip(_request("10.0.0.2", "not-an-ip")) == "10.0.0.2"


def test_obsolete_proxy_count_rejected_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_COUNT is obsolete"):
        validate_production()


# --- headers, HTTPS, generic errors ----------------------------------------------------


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: FakePlaces())
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: FakeRoutes())
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)

    class Fake:
        async def suggest(self, query: str, **kw: Any) -> list[Suggestion]:
            return []

    monkeypatch.setattr(selection, "suggestion_adapter", lambda: Fake())


def _plan_body() -> dict[str, Any]:
    return _payload([_stop("a", "trinity"), _stop("b", "pub")])


_ENDPOINTS = [
    ("/api/v2/plan", _plan_body),
    ("/api/v2/plan/stream", _plan_body),
    ("/api/v2/suggest/cities", lambda: {"query": "du"}),
]


@pytest.mark.parametrize(("path", "body"), _ENDPOINTS)
def test_security_headers_on_v2_endpoints(fakes: None, path: str, body: Any) -> None:
    resp = TestClient(app).post(path, json=body())
    assert resp.status_code == 200
    h = resp.headers
    assert h["cache-control"] == "no-store"
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "strict-transport-security" not in h  # off unless production + enabled


@pytest.mark.parametrize(("path", "body"), _ENDPOINTS[:2])
def test_hsts_only_in_production_when_enabled(
    fakes: None, monkeypatch: pytest.MonkeyPatch, path: str, body: Any
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "hsts_enabled", True)
    resp = TestClient(app).post(path, json=body())
    assert resp.headers["strict-transport-security"] == "max-age=31536000"


def test_unexpected_json_failure_is_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        async def fetch_leg(self, **kw: Any) -> Any:
            raise RuntimeError(f"provider said {SERVER_KEY}")

    monkeypatch.setattr(plan_v2, "places_adapter", lambda: FakePlaces())
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: Boom())
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)
    resp = TestClient(app, raise_server_exceptions=False).post("/api/v2/plan", json=_plan_body())
    assert resp.status_code == 503
    assert resp.json() == {"error": "service_unavailable"}
    assert SERVER_KEY not in resp.text


# --- server key handling ------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_key_sent_only_in_a_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_maps_api_key", SERVER_KEY)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(":computeRoutes"):
            return httpx.Response(
                200, json={"routes": [{"duration": "60s", "distanceMeters": 1, "legs": []}]}
            )
        if request.url.path.endswith(":autocomplete"):
            return httpx.Response(200, json={"suggestions": []})
        return httpx.Response(
            200, json={"id": "ChIJx", "location": {"latitude": 53.3, "longitude": -6.2}}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await place_details.fetch_selected_location(
            "ChIJx", session_token="tok-12345678", client=client
        )
        await autocomplete.fetch_suggestions(
            "du", kind="city", session_token=None, bias=None, client=client
        )
        await directions.fetch_leg(
            origin_lat=53.3,
            origin_lng=-6.2,
            destination_lat=53.4,
            destination_lng=-6.3,
            depart_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            mode="walking",
            client=client,
        )
    assert len(seen) == 3
    for request in seen:
        assert request.headers["x-goog-api-key"] == SERVER_KEY
        assert SERVER_KEY not in str(request.url)
        assert SERVER_KEY not in request.content.decode()


def test_server_key_never_in_v2_responses(fakes: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_maps_api_key", SERVER_KEY)
    client = TestClient(app)
    for path, body in _ENDPOINTS:
        resp = client.post(path, json=body())
        assert SERVER_KEY not in resp.text
        assert SERVER_KEY not in json.dumps(dict(resp.headers))
