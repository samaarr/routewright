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
