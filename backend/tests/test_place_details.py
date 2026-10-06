"""Tests for the Place Details (New) client and GooglePlacesAdapter.

All provider traffic goes through httpx.MockTransport; no network in CI.
"""

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app.services import adapter as adapter_module
from app.services.adapter import GooglePlacesAdapter, GoogleRoutesAdapter
from app.services.errors import (
    PlaceVerificationError,
    ProviderCapacityError,
    ProviderTemporaryError,
    QuotaExceededError,
)
from app.services.place_details import (
    CITY_FIELD_MASK,
    STOP_FIELD_MASK,
    fetch_place_details,
)

_OK = {
    "id": "ChIJtrinity",
    "displayName": {"text": "Trinity College Dublin", "languageCode": "en"},
    "location": {"latitude": 53.3438, "longitude": -6.2546},
    "primaryType": "university",
    "types": ["university", "tourist_attraction"],
    "businessStatus": "OPERATIONAL",
    "regularOpeningHours": {"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]},
}


def _client(status: int, body: Any, seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_details_request_shape_and_provider_values() -> None:
    seen: list[httpx.Request] = []
    async with _client(200, _OK, seen) as client:
        d = await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)
    req = seen[0]
    assert req.method == "GET"
    assert req.url.path == "/v1/places/ChIJtrinity"
    assert req.headers["X-Goog-FieldMask"] == STOP_FIELD_MASK
    assert "places." not in req.headers["X-Goog-FieldMask"]
    assert (d.name, d.lat, d.lng) == ("Trinity College Dublin", 53.3438, -6.2546)
    assert d.primary_type == "university"
    assert d.regular_hours_raw is not None


@pytest.mark.asyncio
async def test_city_mask_requests_viewport_but_no_hours() -> None:
    seen: list[httpx.Request] = []
    body = {
        **_OK,
        "viewport": {
            "low": {"latitude": 53.2, "longitude": -6.4},
            "high": {"latitude": 53.4, "longitude": -6.1},
        },
    }
    async with _client(200, body, seen) as client:
        d = await fetch_place_details("ChIJtrinity", purpose="city", client=client)
    assert seen[0].headers["X-Goog-FieldMask"] == CITY_FIELD_MASK
    assert "OpeningHours" not in CITY_FIELD_MASK
    assert d.viewport is not None and d.viewport.high_lng == -6.1


@pytest.mark.parametrize(
    ("status", "reason"),
    [(404, "not_found"), (400, "invalid_id")],
)
@pytest.mark.asyncio
async def test_invalid_or_obsolete_id_is_invalid_selection(status: int, reason: str) -> None:
    async with _client(status, {"error": {}}) as client:
        with pytest.raises(PlaceVerificationError) as exc:
            await fetch_place_details("ChIJgone", purpose="stop_verification", client=client)
    assert exc.value.reason == reason
    assert exc.value.role == "stop"


@pytest.mark.parametrize("status", [403, 500, 503])
@pytest.mark.asyncio
async def test_provider_failures_are_not_reported_as_invalid_places(status: int) -> None:
    async with _client(status, {"error": {}}) as client:
        with pytest.raises(ProviderTemporaryError):
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)


@pytest.mark.asyncio
async def test_provider_429_is_quota() -> None:
    async with _client(429, {"error": {}}) as client:
        with pytest.raises(QuotaExceededError):
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)


@pytest.mark.asyncio
async def test_network_error_is_temporary() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(ProviderTemporaryError):
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)


@pytest.mark.asyncio
async def test_moved_place_is_surfaced_not_substituted() -> None:
    body = {**_OK, "businessStatus": "CLOSED_PERMANENTLY", "movedPlaceId": "ChIJnew"}
    async with _client(200, body) as client:
        with pytest.raises(PlaceVerificationError) as exc:
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)
    assert exc.value.reason == "moved"
    assert exc.value.moved_place_id == "ChIJnew"


@pytest.mark.asyncio
async def test_permanently_closed_without_move() -> None:
    body = {**_OK, "businessStatus": "CLOSED_PERMANENTLY"}
    async with _client(200, body) as client:
        with pytest.raises(PlaceVerificationError) as exc:
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)
    assert exc.value.reason == "permanently_closed"


@pytest.mark.asyncio
async def test_identity_mismatch_is_not_adopted() -> None:
    body = {**_OK, "id": "ChIJsomethingElse"}
    async with _client(200, body) as client:
        with pytest.raises(PlaceVerificationError) as exc:
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)
    assert exc.value.reason == "identity_changed"


@pytest.mark.parametrize(
    "location",
    [None, {"latitude": 0.0, "longitude": 0.0}, {"latitude": 95, "longitude": 1}],
)
@pytest.mark.asyncio
async def test_unusable_location_rejected(location: Any) -> None:
    body = {**_OK, "location": location}
    async with _client(200, body) as client:
        with pytest.raises(PlaceVerificationError) as exc:
            await fetch_place_details("ChIJtrinity", purpose="stop_verification", client=client)
    assert exc.value.reason == "no_location"


@pytest.mark.asyncio
async def test_malformed_place_id_makes_no_request() -> None:
    seen: list[httpx.Request] = []
    async with _client(200, _OK, seen) as client:
        with pytest.raises(PlaceVerificationError) as exc:
            await fetch_place_details(
                "../places:searchText", purpose="stop_verification", client=client
            )
    assert exc.value.reason == "invalid_id"
    assert seen == []


# --- adapter: shared admission + budget --------------------------------------


@pytest.mark.asyncio
async def test_adapter_malformed_id_consumes_no_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def counting_budget(kind: str = "unclassified") -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(adapter_module, "consume_provider_budget", counting_budget)
    with pytest.raises(PlaceVerificationError):
        await GooglePlacesAdapter().fetch_details("bad id!", role="stop")
    assert calls == 0


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, QuotaExceededError), (503, ProviderCapacityError)],
)
@pytest.mark.asyncio
async def test_adapter_maps_budget_rejection(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: type[Exception]
) -> None:
    async def rejected(kind: str = "unclassified") -> None:
        raise HTTPException(status, "no")

    monkeypatch.setattr(adapter_module, "consume_provider_budget", rejected)
    with pytest.raises(expected):
        await GooglePlacesAdapter().fetch_details("ChIJtrinity", role="stop")


@pytest.mark.asyncio
async def test_routes_adapter_maps_budget_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def rejected(**_: object) -> None:
        raise HTTPException(429, "Daily provider budget exhausted")

    monkeypatch.setattr(adapter_module.directions, "fetch_leg", rejected)
    from datetime import datetime, timezone

    with pytest.raises(QuotaExceededError):
        await GoogleRoutesAdapter().fetch_leg(
            origin_lat=53.3,
            origin_lng=-6.2,
            dest_lat=53.34,
            dest_lng=-6.26,
            mode="transit",
            depart_at=datetime(2026, 10, 21, 9, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_hanging_lookup_bounded_releases_slot_and_counts_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung Place Details call is cancelled at the deadline; the provider slot is
    released and the already-consumed budget is not refunded."""
    from app.core import provider_semaphore
    from app.core.deadline import DeadlineExceededError, DeadlineScope

    provider_semaphore.reset_gates()
    budget_hits = 0

    async def counting_budget(kind: str = "unclassified") -> None:
        nonlocal budget_hits
        budget_hits += 1

    async def hang(*_: object, **__: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(adapter_module, "consume_provider_budget", counting_budget)
    monkeypatch.setattr(adapter_module, "fetch_place_details", hang)
    sem = provider_semaphore._provider
    assert sem is not None
    free_before = sem._value

    scope = DeadlineScope(deadline_seconds=0.05)
    with pytest.raises(DeadlineExceededError):
        await scope.bound(GooglePlacesAdapter().fetch_details("ChIJtrinity", role="stop"))

    assert sem._value == free_before  # slot released by cancellation
    assert budget_hits == 1  # counted before sending; not refunded
