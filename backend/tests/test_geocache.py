"""Tests for app/services/geocache.py.

All tests use tmp_path for the DB so they're isolated and leave no artifacts.
Network calls are mocked via httpx.MockTransport.
"""

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.geocache import _make_key, geocode_cached, get_cached, put_cached
from app.services.geocoder import GeocodedPlace

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

_PLACE = GeocodedPlace(
    place_id="ChIJABC123",
    name="Guinness Storehouse",
    lat=53.3418,
    lng=-6.2867,
    primary_type="brewery",
    types=["brewery", "tourist_attraction", "point_of_interest"],
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_cache.db")


# ---------------------------------------------------------------------------
# Test 1: write → read roundtrip
# ---------------------------------------------------------------------------


async def test_put_then_get_returns_same_place(db_path: str) -> None:
    key = _make_key("Guinness Storehouse", "Dublin, Ireland")
    await put_cached(key, _PLACE, db_path)
    result = await get_cached(key, db_path, ttl_days=30)

    assert result is not None
    assert result.place_id == _PLACE.place_id
    assert result.name == _PLACE.name
    assert result.lat == pytest.approx(_PLACE.lat)
    assert result.lng == pytest.approx(_PLACE.lng)
    assert result.primary_type == _PLACE.primary_type
    assert result.types == _PLACE.types


# ---------------------------------------------------------------------------
# Test 2: expired entry (TTL=0) returns None
# ---------------------------------------------------------------------------


async def test_expired_entry_returns_none(db_path: str) -> None:
    key = _make_key("Guinness Storehouse", "Dublin, Ireland")
    await put_cached(key, _PLACE, db_path)
    # TTL of 0 days means any cached entry is immediately stale.
    result = await get_cached(key, db_path, ttl_days=0)
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: DB file is created on first write (no pre-init needed)
# ---------------------------------------------------------------------------


async def test_db_created_on_first_write(db_path: str) -> None:
    from pathlib import Path

    assert not Path(db_path).exists()
    key = _make_key("Jameson Distillery", "Dublin, Ireland")
    await put_cached(key, _PLACE, db_path)
    assert Path(db_path).exists()


# ---------------------------------------------------------------------------
# Test 4: geocode_cached returns cached result on second call — no extra
#          network requests
# ---------------------------------------------------------------------------


async def test_geocode_cached_second_call_hits_cache_not_network(db_path: str) -> None:
    call_count = 0
    places_response: dict[str, Any] = {
        "places": [
            {
                "id": "ChIJABC123",
                "displayName": {"text": "Guinness Storehouse", "languageCode": "en"},
                "location": {"latitude": 53.3418, "longitude": -6.2867},
                "primaryType": "brewery",
                "types": ["brewery", "tourist_attraction", "point_of_interest"],
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=places_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await geocode_cached(
            "Guinness Storehouse", "Dublin, Ireland", db_path, ttl_days=30, client=client
        )
        second = await geocode_cached(
            "Guinness Storehouse", "Dublin, Ireland", db_path, ttl_days=30, client=client
        )

    assert call_count == 1  # API called only once
    assert first.place_id == second.place_id


# ---------------------------------------------------------------------------
# Test 5: geocode_cached writes to cache after an API call
# ---------------------------------------------------------------------------


async def test_geocode_cached_writes_to_cache_after_api_call(db_path: str) -> None:
    places_response: dict[str, Any] = {
        "places": [
            {
                "id": "ChIJABC123",
                "displayName": {"text": "Guinness Storehouse", "languageCode": "en"},
                "location": {"latitude": 53.3418, "longitude": -6.2867},
                "primaryType": "brewery",
                "types": ["brewery", "tourist_attraction"],
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=places_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await geocode_cached(
            "Guinness Storehouse", "Dublin, Ireland", db_path, ttl_days=30, client=client
        )

    key = _make_key("Guinness Storehouse", "Dublin, Ireland")
    cached = await get_cached(key, db_path, ttl_days=30)
    assert cached is not None
    assert cached.name == "Guinness Storehouse"
    assert cached.primary_type == "brewery"


# ---------------------------------------------------------------------------
# Test 6: upsert overwrites a stale entry
# ---------------------------------------------------------------------------


async def test_put_cached_overwrites_existing_entry(db_path: str) -> None:
    key = _make_key("Guinness Storehouse", "Dublin, Ireland")

    old_place = GeocodedPlace(
        place_id="OLD_ID",
        name="Old Name",
        lat=0.0,
        lng=0.0,
        primary_type=None,
        types=[],
    )
    await put_cached(key, old_place, db_path)

    await put_cached(key, _PLACE, db_path)
    result = await get_cached(key, db_path, ttl_days=30)

    assert result is not None
    assert result.place_id == _PLACE.place_id
    assert result.name == _PLACE.name
