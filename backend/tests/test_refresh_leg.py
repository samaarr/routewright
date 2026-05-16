"""Tests for POST /api/refresh-leg.

All tests patch fetch_leg directly to avoid real Routes API calls.
The departure time is always datetime.now(UTC) inside the endpoint,
so tests verify shape/content rather than exact timestamps.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.services.directions import DirectionsError, LegResult


def _valid_payload() -> dict:
    return {
        "from_lat": 53.3440,
        "from_lng": -6.2546,
        "from_name": "Trinity College Dublin",
        "to_lat": 53.3418,
        "to_lng": -6.2867,
        "to_name": "Guinness Storehouse",
        "mode": "transit",
        "city": "Dublin, Ireland",
    }


def test_refresh_leg_returns_leg_item(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: valid payload → LegItem with correct structure."""
    now = datetime.now(timezone.utc)

    async def _fake_fetch_leg(**kwargs: object) -> LegResult:
        depart_at = kwargs["depart_at"]
        assert isinstance(depart_at, datetime)
        return LegResult(
            duration_seconds=18 * 60,
            distance_meters=3100,
            depart_at=depart_at,
            arrive_at=depart_at + timedelta(seconds=18 * 60),
            summary="Take the G1, 18 min",
            transit_line="G1",
        )

    monkeypatch.setattr("app.routers.refresh_leg.fetch_leg", _fake_fetch_leg)

    response = client.post("/api/refresh-leg", json=_valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["item_type"] == "leg"
    assert body["from_name"] == "Trinity College Dublin"
    assert body["to_name"] == "Guinness Storehouse"
    assert body["mode"] == "transit"
    assert body["duration_seconds"] == 18 * 60
    assert body["distance_meters"] == 3100
    assert body["summary"] == "Take the G1, 18 min"
    assert "Dublin" in body["map_url"]
    assert "travelmode=transit" in body["map_url"]
    # depart_at should be close to now (within 5 seconds of test execution)
    depart_at = datetime.fromisoformat(body["depart_at"].replace("Z", "+00:00"))
    assert abs((depart_at - now).total_seconds()) < 5


def test_refresh_leg_invalid_mode_returns_422(client: TestClient) -> None:
    """Invalid mode → 422 validation error, no network call made."""
    payload = {**_valid_payload(), "mode": "teleport"}
    response = client.post("/api/refresh-leg", json=payload)
    assert response.status_code == 422


def test_refresh_leg_directions_error_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Routes API failure → 503 with a descriptive message."""

    async def _failing_fetch_leg(**kwargs: object) -> LegResult:
        raise DirectionsError("Routes API timeout")

    monkeypatch.setattr("app.routers.refresh_leg.fetch_leg", _failing_fetch_leg)

    response = client.post("/api/refresh-leg", json=_valid_payload())

    assert response.status_code == 503
    assert "Trinity College Dublin" in response.json()["detail"]
    assert "Guinness Storehouse" in response.json()["detail"]
