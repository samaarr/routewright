"""Tests for POST /api/plan.

These test the contract, not the implementation. The fixture today and the
real pipeline in week 2 should both pass the same assertions about shape.

All tests that POST to /api/plan require the mock_geocode fixture (defined
in conftest.py) to avoid real Places API calls.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def _valid_payload() -> dict:
    return {
        "city": "Dublin, Ireland",
        "stops": [
            {"query": "Trinity College"},
            {"query": "Temple Bar"},
            {"query": "Guinness Storehouse", "stay_minutes": 90},
        ],
        "start_time": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
        "mode": "transit",
    }


def test_plan_returns_alternating_timeline(client: TestClient, mock_geocode: None) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    assert response.status_code == 200
    body = response.json()

    timeline = body["timeline"]
    # 3 stops + 2 legs = 5 items
    assert len(timeline) == 5
    assert timeline[0]["item_type"] == "stop"
    assert timeline[1]["item_type"] == "leg"
    assert timeline[2]["item_type"] == "stop"
    assert timeline[3]["item_type"] == "leg"
    assert timeline[4]["item_type"] == "stop"


def test_plan_honours_user_stay_override(client: TestClient, mock_geocode: None) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    body = response.json()
    stops = [item for item in body["timeline"] if item["item_type"] == "stop"]

    # First two stops have no override → default. Third has explicit 90.
    assert stops[0]["stay_source"] == "default"
    assert stops[2]["stay_source"] == "user"
    assert stops[2]["stay_minutes"] == 90


def test_plan_builds_overview_url(client: TestClient, mock_geocode: None) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    body = response.json()
    assert body["overview_map_url"].startswith("https://www.google.com/maps/dir/?api=1")
    assert "travelmode=driving" in body["overview_map_url"]
    # Three stops → first as origin, last as destination, middle as waypoint.
    assert "waypoints=" in body["overview_map_url"]


def test_plan_rejects_single_stop(client: TestClient, mock_geocode: None) -> None:
    payload = _valid_payload()
    payload["stops"] = [{"query": "Trinity College"}]
    response = client.post("/api/plan", json=payload)
    assert response.status_code == 422


def test_plan_rejects_missing_city(client: TestClient, mock_geocode: None) -> None:
    payload = _valid_payload()
    del payload["city"]
    response = client.post("/api/plan", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Day 6: assertions that verify geocoder + stay_defaults are actually wired
# ---------------------------------------------------------------------------


def test_plan_stop_name_comes_from_geocoder(client: TestClient, mock_geocode: None) -> None:
    """StopItem.name is the resolved place name, not the raw user query."""
    response = client.post("/api/plan", json=_valid_payload())
    stops = [item for item in response.json()["timeline"] if item["item_type"] == "stop"]

    assert stops[0]["name"] == "Trinity College Dublin"
    assert stops[0]["query"] == "Trinity College"  # raw query preserved separately
    assert stops[1]["name"] == "Temple Bar"
    assert stops[2]["name"] == "Guinness Storehouse"


def test_plan_stop_lat_lng_come_from_geocoder(client: TestClient, mock_geocode: None) -> None:
    """StopItem lat/lng are geocoded coordinates, not 0.0/0.0."""
    response = client.post("/api/plan", json=_valid_payload())
    stops = [item for item in response.json()["timeline"] if item["item_type"] == "stop"]

    assert stops[0]["lat"] == pytest.approx(53.3440)
    assert stops[0]["lng"] == pytest.approx(-6.2546)
    assert stops[0]["lat"] != 0.0
    assert stops[0]["lng"] != 0.0


def test_plan_default_stay_uses_type_table(client: TestClient, mock_geocode: None) -> None:
    """Stops without a user override get stay_minutes from the place-type table.

    Guinness Storehouse has no stay_minutes in this payload — but its mock
    primaryType is 'brewery', which maps to 90 min in the defaults table.
    Contrast with Trinity/Temple Bar (tourist_attraction → 60 min).
    """
    payload = _valid_payload()
    # Remove the explicit stay override from Guinness so it falls through to defaults.
    payload["stops"][2] = {"query": "Guinness Storehouse"}

    response = client.post("/api/plan", json=payload)
    stops = [item for item in response.json()["timeline"] if item["item_type"] == "stop"]

    assert stops[0]["stay_minutes"] == 60   # tourist_attraction default
    assert stops[0]["stay_source"] == "default"
    assert stops[1]["stay_minutes"] == 60   # tourist_attraction default
    assert stops[1]["stay_source"] == "default"
    assert stops[2]["stay_minutes"] == 90   # brewery default
    assert stops[2]["stay_source"] == "default"


def test_plan_geocoder_error_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stop that fails to geocode returns HTTP 400, not 500."""
    from app.services.geocoder import GeocoderError

    async def _always_fail(
        query: str, city: str, db_path: str, ttl_days: int, client: object = None
    ) -> None:
        raise GeocoderError(f"place not found: {query!r}")

    monkeypatch.setattr("app.routers.plan.geocode_cached", _always_fail)

    response = client.post("/api/plan", json=_valid_payload())
    assert response.status_code == 400
    assert "geocode" in response.json()["detail"].lower()
