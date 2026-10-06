"""Tests for backend-controlled suggestions and selection (D13, D26, D34-D36, D38).

Google traffic is mocked: provider clients via httpx.MockTransport, endpoints
via injected fake adapters. Rate-limit time is controlled through the limits
library's memory storage clock.
"""

from __future__ import annotations

import json
import shutil
import types
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.provider_accounting import InMemoryProviderAccounting
from app.main import app
from app.routers import selection
from app.services import adapter as adapter_module
from app.services import geocache
from app.services.area import Viewport
from app.services.autocomplete import (
    SUGGESTION_FIELD_MASK,
    Suggestion,
    build_request_body,
    fetch_suggestions,
)
from app.services.errors import (
    PlaceVerificationError,
    ProviderTemporaryError,
    QuotaExceededError,
    UsageControlUnavailableError,
)
from app.services.place_details import (
    STOP_SELECTION_FIELD_MASK,
    PlaceDetails,
    SelectedLocation,
    fetch_selected_location,
)

TOKEN = "3f2b8c1e-5d7a-4e2b-9c1d-0a1b2c3d4e5f"
DUBLIN_VP = Viewport(53.22, -6.45, 53.42, -6.05)


# --- provider client shape ------------------------------------------------------


@pytest.mark.asyncio
async def test_autocomplete_request_shape_and_minimal_mask() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "suggestions": [
                    {
                        "placePrediction": {
                            "placeId": "ChIJtrinity",
                            "structuredFormat": {
                                "mainText": {"text": "Trinity College"},
                                "secondaryText": {"text": "College Green, Dublin"},
                            },
                        }
                    },
                    {"queryPrediction": {"text": {"text": "trinity pizza"}}},
                    {"placePrediction": {"placeId": "bad id!", "structuredFormat": {}}},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await fetch_suggestions(
            "trinity", kind="place", session_token=TOKEN, bias=DUBLIN_VP, client=client
        )
    req = seen[0]
    assert req.url.path == "/v1/places:autocomplete"
    assert req.headers["X-Goog-FieldMask"] == SUGGESTION_FIELD_MASK
    body = json.loads(req.content)
    assert body["sessionToken"] == TOKEN
    assert body["locationBias"]["rectangle"]["low"] == {"latitude": 53.22, "longitude": -6.45}
    assert "locationRestriction" not in body  # bias only: outside-city stays selectable
    assert items == [Suggestion("ChIJtrinity", "Trinity College", "College Green, Dublin")]


def test_city_search_restricts_to_city_types() -> None:
    body = build_request_body("dub", kind="city", session_token=None, bias=None)
    assert body == {"input": "dub", "includedPrimaryTypes": ["(cities)"]}


@pytest.mark.asyncio
async def test_stop_selection_lookup_is_essentials_and_concludes_session() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "ChIJtrinity",
                "location": {"latitude": 53.3438, "longitude": -6.2546},
                "formattedAddress": "College Green, Dublin 2",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        loc = await fetch_selected_location("ChIJtrinity", session_token=TOKEN, client=client)
    assert seen[0].headers["X-Goog-FieldMask"] == STOP_SELECTION_FIELD_MASK
    assert "displayName" not in STOP_SELECTION_FIELD_MASK  # keeps it in Essentials
    assert seen[0].url.params["sessionToken"] == TOKEN
    assert (loc.lat, loc.lng, loc.formatted_address) == (
        53.3438,
        -6.2546,
        "College Green, Dublin 2",
    )


# --- endpoints with fake adapters --------------------------------------------------


class FakeSuggest:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result: list[Suggestion] | BaseException = [
            Suggestion("ChIJdublin", "Dublin", "Ireland")
        ]

    async def suggest(self, query: str, **kw: Any) -> list[Suggestion]:
        self.calls.append({"query": query, **kw})
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FakePlaces:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.error: BaseException | None = None
        self.city = PlaceDetails(
            place_id="ChIJdublin",
            name="Dublin",
            lat=53.3498,
            lng=-6.2603,
            formatted_address="Dublin, Ireland",
            viewport=DUBLIN_VP,
        )

    async def fetch_details(self, place_id: str, *, role: str, session_token: str | None = None):
        self.calls.append((place_id, session_token))
        if self.error:
            raise self.error
        return self.city

    async def fetch_selected_location(self, place_id: str, *, session_token: str | None):
        self.calls.append((place_id, session_token))
        if self.error:
            raise self.error
        from datetime import datetime, timezone

        return SelectedLocation(
            place_id, 53.3438, -6.2546, "College Green", datetime.now(timezone.utc)
        )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[FakeSuggest, FakePlaces]:
    s, p = FakeSuggest(), FakePlaces()
    monkeypatch.setattr(selection, "suggestion_adapter", lambda: s)
    monkeypatch.setattr(selection, "places_adapter", lambda: p)
    monkeypatch.setattr(settings, "cache_db_path", str(tmp_path / "c" / "places.db"))
    return s, p


def _client() -> TestClient:
    return TestClient(app)


def test_city_suggestions_return_identifying_context_only(fakes: Any) -> None:
    r = _client().post("/api/v2/suggest/cities", json={"query": "  dub  ", "session_token": TOKEN})
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "suggestions": [
            {"place_id": "ChIJdublin", "primary_text": "Dublin", "secondary_text": "Ireland"}
        ],
    }
    assert fakes[0].calls[0]["query"] == "dub"  # normalised
    assert fakes[0].calls[0]["kind"] == "city"


def test_place_suggestions_biased_by_selected_city(fakes: Any) -> None:
    vp = {"low_lat": 53.22, "low_lng": -6.45, "high_lat": 53.42, "high_lng": -6.05}
    r = _client().post("/api/v2/suggest/places", json={"query": "t", "city_viewport": vp})
    assert r.status_code == 200  # 1 char allowed (explicit Search)
    assert fakes[0].calls[0]["bias"] == DUBLIN_VP


def test_no_matches_is_distinct_success(fakes: Any) -> None:
    fakes[0].result = []
    r = _client().post("/api/v2/suggest/places", json={"query": "zzzz"})
    assert r.status_code == 200
    assert r.json() == {"status": "no_matches", "suggestions": []}


@pytest.mark.parametrize("query", ["", "   ", "a\x00b", "x" * 121])
def test_invalid_input_rejected_without_provider_call(fakes: Any, query: str) -> None:
    r = _client().post("/api/v2/suggest/cities", json={"query": query})
    assert r.status_code == 422
    assert fakes[0].calls == []


def test_invalid_session_token_rejected(fakes: Any) -> None:
    r = _client().post("/api/v2/suggest/cities", json={"query": "dub", "session_token": "x"})
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (QuotaExceededError("budget"), 429, "quota_exceeded"),
        (UsageControlUnavailableError("redis"), 503, "usage_control_unavailable"),
        (ProviderTemporaryError("down"), 503, "provider_unavailable"),
    ],
)
def test_provider_side_failures_are_distinct(
    fakes: Any, error: BaseException, status: int, code: str
) -> None:
    fakes[0].result = error
    r = _client().post("/api/v2/suggest/cities", json={"query": "dub"})
    assert r.status_code == status
    assert r.json()["detail"]["error"] == code
    assert "Retry-After" in r.headers


class _Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    import limits.storage.memory as memory

    c = _Clock()
    monkeypatch.setattr(memory, "time", types.SimpleNamespace(time=c.time))
    return c


def test_combined_minute_limit_across_city_place_and_select(fakes: Any, clock: _Clock) -> None:
    client = _client()
    endpoints = [
        ("/api/v2/suggest/cities", {"query": "du"}),
        ("/api/v2/suggest/places", {"query": "tr"}),
        ("/api/v2/select/city", {"place_id": "ChIJdublin"}),
    ]
    for i in range(30):
        path, body = endpoints[i % 3]
        assert client.post(path, json=body).status_code == 200, i
    r = client.post("/api/v2/suggest/places", json={"query": "x"})
    assert r.status_code == 429
    assert r.json()["error"] == "rate_limit_exceeded"  # per-IP limit, not provider budget
    clock.now += 61
    assert client.post("/api/v2/suggest/cities", json={"query": "du"}).status_code == 200


def test_combined_daily_limit(fakes: Any, clock: _Clock) -> None:
    client = _client()
    for i in range(100):
        if i and i % 30 == 0:
            clock.now += 61  # stay under the per-minute limit
        assert client.post("/api/v2/suggest/cities", json={"query": "du"}).status_code == 200
    clock.now += 61
    assert client.post("/api/v2/suggest/places", json={"query": "du"}).status_code == 429
    clock.now += 86_400
    assert client.post("/api/v2/suggest/places", json={"query": "du"}).status_code == 200


def test_spoofed_forwarded_for_does_not_reset_limit(fakes: Any, clock: _Clock) -> None:
    client = _client()
    for _ in range(30):
        client.post("/api/v2/suggest/cities", json={"query": "du"})
    r = client.post(
        "/api/v2/suggest/cities",
        json={"query": "du"},
        headers={"X-Forwarded-For": "203.0.113.99"},  # peer is not a trusted proxy
    )
    assert r.status_code == 429


# --- selection -----------------------------------------------------------------------


def test_select_city_returns_timezone_viewport_and_concludes_session(fakes: Any) -> None:
    r = _client().post(
        "/api/v2/select/city", json={"place_id": "ChIJdublin", "session_token": TOKEN}
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["name"], body["timezone"]) == ("Dublin", "Europe/Dublin")
    assert body["viewport"] == {
        "low_lat": 53.22,
        "low_lng": -6.45,
        "high_lat": 53.42,
        "high_lng": -6.05,
    }
    assert fakes[1].calls == [("ChIJdublin", TOKEN)]


def test_select_city_without_viewport_reports_none(fakes: Any) -> None:
    fakes[1].city = PlaceDetails(place_id="ChIJdublin", name="Dublin", lat=53.35, lng=-6.26)
    body = _client().post("/api/v2/select/city", json={"place_id": "ChIJdublin"}).json()
    assert body["viewport"] is None


def test_select_city_unresolvable_timezone_blocks(
    fakes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "resolve_timezone", lambda lat, lng: None)
    r = _client().post("/api/v2/select/city", json={"place_id": "ChIJdublin"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "timezone_unresolved"


def test_invalid_selection_is_reported(fakes: Any) -> None:
    fakes[1].error = PlaceVerificationError("ChIJgone", reason="not_found")
    r = _client().post(
        "/api/v2/select/place", json={"place_id": "ChIJgone", "session_token": TOKEN}
    )
    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "not_found"


@pytest.mark.asyncio
async def test_select_place_persists_only_coordinates_and_uses_cache_without_session(
    fakes: Any,
) -> None:
    client = _client()
    first = client.post(
        "/api/v2/select/place", json={"place_id": "ChIJtrinity", "session_token": TOKEN}
    ).json()
    assert first["source"] == "provider" and first["timezone"] == "Europe/Dublin"
    cached = await geocache.get_coordinates("ChIJtrinity", settings.cache_db_path, 30)
    assert cached is not None and (cached.lat, cached.lng) == (53.3438, -6.2546)
    raw = Path(settings.cache_db_path).read_bytes()
    assert b"College Green" not in raw  # address is request-scoped, never persisted

    again = client.post("/api/v2/select/place", json={"place_id": "ChIJtrinity"}).json()
    assert again["source"] == "cache"
    assert len(fakes[1].calls) == 1  # no provider call for the cache hit

    with_token = client.post(
        "/api/v2/select/place", json={"place_id": "ChIJtrinity", "session_token": TOKEN}
    ).json()
    assert with_token["source"] == "provider"  # a session must be concluded by Place Details


# --- accounting seam -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_calls_counted_by_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import provider_semaphore

    acct = InMemoryProviderAccounting()
    monkeypatch.setattr(provider_semaphore, "accounting", acct)

    async def fake_suggestions(*a: Any, **k: Any) -> list[Suggestion]:
        return []

    async def fake_location(place_id: str, **k: Any) -> SelectedLocation:
        from datetime import datetime, timezone

        return SelectedLocation(place_id, 1.0, 1.0, None, datetime.now(timezone.utc))

    monkeypatch.setattr(adapter_module, "fetch_suggestions", fake_suggestions)
    monkeypatch.setattr(adapter_module, "fetch_selected_location", fake_location)
    await adapter_module.GoogleSuggestionAdapter().suggest(
        "du", kind="city", session_token=None, bias=None
    )
    await adapter_module.GooglePlacesAdapter().fetch_selected_location("ChIJx", session_token=None)
    assert acct.snapshot() == {"autocomplete": 1, "place_details_essentials": 1}


# --- ephemeral cache (deployment decision D-2): correctness never depends on it ---


def test_cleared_cache_after_redeploy_falls_back_to_provider(fakes: Any) -> None:
    client = _client()
    client.post("/api/v2/select/place", json={"place_id": "ChIJtrinity", "session_token": TOKEN})
    shutil.rmtree(Path(settings.cache_db_path).parent)  # a redeploy discards the container FS

    again = client.post("/api/v2/select/place", json={"place_id": "ChIJtrinity"})
    assert again.status_code == 200
    body = again.json()
    assert body["source"] == "provider"
    assert (body["lat"], body["lng"]) == (53.3438, -6.2546)
    assert len(fakes[1].calls) == 2
    assert Path(settings.cache_db_path).exists()  # the empty cache is recreated on write


def test_unreadable_cache_falls_back_to_provider(fakes: Any) -> None:
    path = Path(settings.cache_db_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a sqlite database")

    r = _client().post("/api/v2/select/place", json={"place_id": "ChIJtrinity"})
    assert r.status_code == 200
    assert r.json()["source"] == "provider"
