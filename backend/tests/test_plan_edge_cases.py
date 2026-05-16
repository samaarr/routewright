"""Edge-case tests for POST /api/plan.

Each test covers one guard added in Day 13:
  - start_time more than 30 days in the past → 422
  - 13 stops (over max_length=12) → 422
  - single-char stop query (under min_length=2) → 422
  - consecutive same-location stops → warning in response
  - disambiguation: neighbourhood-looking query resolves to food type → info warning
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.geocoder import GeocodedPlace


def _base_payload() -> dict:
    return {
        "city": "Dublin, Ireland",
        "stops": [
            {"query": "Trinity College"},
            {"query": "Temple Bar"},
        ],
        "start_time": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
        "mode": "transit",
    }


# ---------------------------------------------------------------------------
# Pydantic-layer 422s (no geocode/directions needed)
# ---------------------------------------------------------------------------


def test_start_time_over_30_days_past_returns_422(client: TestClient) -> None:
    payload = _base_payload()
    stale = datetime.now(timezone.utc) - timedelta(days=31)
    payload["start_time"] = stale.isoformat()
    r = client.post("/api/plan", json=payload)
    assert r.status_code == 422


def test_thirteen_stops_returns_422(client: TestClient) -> None:
    payload = _base_payload()
    payload["stops"] = [{"query": f"Stop {i}"} for i in range(13)]
    r = client.post("/api/plan", json=payload)
    assert r.status_code == 422


def test_single_char_query_returns_422(client: TestClient) -> None:
    payload = _base_payload()
    payload["stops"] = [{"query": "A"}, {"query": "Trinity College"}]
    r = client.post("/api/plan", json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Same-location warning
# ---------------------------------------------------------------------------


def test_same_location_consecutive_stops_emits_warning(
    client: TestClient,
    mock_directions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive stops that geocode to the same place_id trigger a warning."""
    same_place = GeocodedPlace(
        place_id="ChIJ_SAME",
        name="Trinity College Dublin",
        lat=53.344,
        lng=-6.254,
        primary_type="tourist_attraction",
        types=["tourist_attraction"],
    )

    async def _fake(query: str, city: str, db_path: str, ttl_days: int, client: object = None) -> GeocodedPlace:
        return same_place

    monkeypatch.setattr("app.routers.plan.geocode_cached", _fake)

    payload = _base_payload()
    r = client.post("/api/plan", json=payload)
    assert r.status_code == 200
    warnings = r.json()["warnings"]
    assert any("same location" in w["message"] for w in warnings)


# ---------------------------------------------------------------------------
# Disambiguation warning
# ---------------------------------------------------------------------------


def test_neighbourhood_query_resolving_to_food_type_emits_info_warning(
    client: TestClient,
    mock_directions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'Temple Bar' resolving to primary_type='bar' should emit an info warning."""
    bar_place = GeocodedPlace(
        place_id="ChIJ_PUB",
        name="The Temple Bar",
        lat=53.345,
        lng=-6.267,
        primary_type="bar",
        types=["bar", "point_of_interest"],
    )
    other_place = GeocodedPlace(
        place_id="ChIJ_TC",
        name="Trinity College Dublin",
        lat=53.344,
        lng=-6.254,
        primary_type="tourist_attraction",
        types=["tourist_attraction"],
    )

    async def _fake(query: str, city: str, db_path: str, ttl_days: int, client: object = None) -> GeocodedPlace:
        return bar_place if "temple bar" in query.lower() else other_place

    monkeypatch.setattr("app.routers.plan.geocode_cached", _fake)

    payload = _base_payload()
    r = client.post("/api/plan", json=payload)
    assert r.status_code == 200
    warnings = r.json()["warnings"]
    assert any(w["severity"] == "info" and "neighbourhood" in w["message"] for w in warnings)
