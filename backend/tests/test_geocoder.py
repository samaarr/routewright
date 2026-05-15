"""Tests for app/services/geocoder.py.

All tests use httpx.MockTransport — no real network calls. The mock captures
the outgoing request so we can assert on headers and body shape.
"""

import json
from typing import Any

import httpx
import pytest

from app.services.geocoder import GeocoderError, GeocodedPlace, geocode

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

_TRINITY_PLACE: dict[str, Any] = {
    "id": "ChIJYY3Y6ef3Z0gRUNqsIoRBvZ0",
    "displayName": {"text": "Trinity College Dublin", "languageCode": "en"},
    "location": {"latitude": 53.3440, "longitude": -6.2546},
    "primaryType": "university",
    "types": ["university", "point_of_interest", "establishment"],
}


def _make_transport(
    status: int = 200,
    body: dict[str, Any] | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """Return a MockTransport and a list that accumulates captured requests."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = body if body is not None else {"places": [_TRINITY_PLACE]}
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), captured


def _client(transport: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport)


# ---------------------------------------------------------------------------
# Test 1: happy path — correct GeocodedPlace fields
# ---------------------------------------------------------------------------


async def test_geocode_happy_path_returns_correct_fields() -> None:
    transport, _ = _make_transport()
    async with _client(transport) as client:
        result = await geocode("Trinity College", "Dublin, Ireland", client=client)

    assert isinstance(result, GeocodedPlace)
    assert result.place_id == "ChIJYY3Y6ef3Z0gRUNqsIoRBvZ0"
    assert result.name == "Trinity College Dublin"
    assert result.lat == pytest.approx(53.3440)
    assert result.lng == pytest.approx(-6.2546)
    assert result.primary_type == "university"
    assert result.types == ["university", "point_of_interest", "establishment"]


# ---------------------------------------------------------------------------
# Test 2: textQuery contains the city suffix
# ---------------------------------------------------------------------------


async def test_geocode_appends_city_to_text_query() -> None:
    transport, captured = _make_transport()
    async with _client(transport) as client:
        await geocode("Trinity College", "Dublin, Ireland", client=client)

    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert body["textQuery"] == "Trinity College, Dublin, Ireland"


# ---------------------------------------------------------------------------
# Test 3: X-Goog-FieldMask header is sent
# ---------------------------------------------------------------------------


async def test_geocode_sends_field_mask_header() -> None:
    transport, captured = _make_transport()
    async with _client(transport) as client:
        await geocode("Trinity College", "Dublin, Ireland", client=client)

    headers = captured[0].headers
    assert "x-goog-fieldmask" in headers
    mask = headers["x-goog-fieldmask"]
    for expected_field in (
        "places.id",
        "places.displayName",
        "places.location",
        "places.primaryType",
        "places.types",
    ):
        assert expected_field in mask, f"missing {expected_field!r} in field mask"


# ---------------------------------------------------------------------------
# Test 4: maxResultCount is 1 in the request body
# ---------------------------------------------------------------------------


async def test_geocode_requests_max_one_result() -> None:
    transport, captured = _make_transport()
    async with _client(transport) as client:
        await geocode("Trinity College", "Dublin, Ireland", client=client)

    body = json.loads(captured[0].content)
    assert body["maxResultCount"] == 1


# ---------------------------------------------------------------------------
# Test 5: empty places array → GeocoderError
# ---------------------------------------------------------------------------


async def test_geocode_empty_places_raises_geocoder_error() -> None:
    transport, _ = _make_transport(body={"places": []})
    async with _client(transport) as client:
        with pytest.raises(GeocoderError, match="place not found"):
            await geocode("Nonexistent Place XYZ", "Dublin, Ireland", client=client)


# ---------------------------------------------------------------------------
# Test 6: HTTP 400 response → GeocoderError
# ---------------------------------------------------------------------------


async def test_geocode_http_error_raises_geocoder_error() -> None:
    transport, _ = _make_transport(status=400, body={"error": {"message": "Invalid request"}})
    async with _client(transport) as client:
        with pytest.raises(GeocoderError, match="400"):
            await geocode("Trinity College", "Dublin, Ireland", client=client)


# ---------------------------------------------------------------------------
# Test 7: primaryType absent in response → primary_type is None, no crash
# ---------------------------------------------------------------------------


async def test_geocode_missing_primary_type_returns_none() -> None:
    place_without_type = {k: v for k, v in _TRINITY_PLACE.items() if k != "primaryType"}
    transport, _ = _make_transport(body={"places": [place_without_type]})
    async with _client(transport) as client:
        result = await geocode("Trinity College", "Dublin, Ireland", client=client)

    assert result.primary_type is None
    # Other fields still populated correctly
    assert result.lat == pytest.approx(53.3440)


# ---------------------------------------------------------------------------
# Test 8: types absent in response → types is [], no crash
# ---------------------------------------------------------------------------


async def test_geocode_missing_types_returns_empty_list() -> None:
    place_without_types = {k: v for k, v in _TRINITY_PLACE.items() if k != "types"}
    transport, _ = _make_transport(body={"places": [place_without_types]})
    async with _client(transport) as client:
        result = await geocode("Trinity College", "Dublin, Ireland", client=client)

    assert result.types == []
    assert result.primary_type == "university"
