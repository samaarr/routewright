"""Tests for POST /api/plan.

These test the contract, not the implementation. All tests that POST to
/api/plan require both mock_geocode and mock_directions (defined in
conftest.py) to avoid real Places API and Routes API calls in CI.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.directions import DirectionsError, LegResult


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


# ---------------------------------------------------------------------------
# Original contract tests (Days 1-2 scope, updated for mock_directions)
# ---------------------------------------------------------------------------


def test_plan_returns_alternating_timeline(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    assert response.status_code == 200
    timeline = response.json()["timeline"]
    assert len(timeline) == 5
    assert timeline[0]["item_type"] == "stop"
    assert timeline[1]["item_type"] == "leg"
    assert timeline[2]["item_type"] == "stop"
    assert timeline[3]["item_type"] == "leg"
    assert timeline[4]["item_type"] == "stop"


def test_plan_honours_user_stay_override(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[0]["stay_source"] == "default"
    assert stops[2]["stay_source"] == "user"
    assert stops[2]["stay_minutes"] == 90


def test_plan_builds_overview_url(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    body = response.json()
    assert body["overview_map_url"].startswith("https://www.google.com/maps/dir/?api=1")
    assert "travelmode=driving" in body["overview_map_url"]
    assert "waypoints=" in body["overview_map_url"]


def test_plan_rejects_single_stop(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    payload = _valid_payload()
    payload["stops"] = [{"query": "Trinity College"}]
    response = client.post("/api/plan", json=payload)
    assert response.status_code == 422


def test_plan_rejects_missing_city(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    payload = _valid_payload()
    del payload["city"]
    response = client.post("/api/plan", json=payload)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Day 6: geocoder + stay_defaults wiring
# ---------------------------------------------------------------------------


def test_plan_stop_name_comes_from_geocoder(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[0]["name"] == "Trinity College Dublin"
    assert stops[0]["query"] == "Trinity College"
    assert stops[1]["name"] == "Temple Bar"
    assert stops[2]["name"] == "Guinness Storehouse"


def test_plan_stop_lat_lng_come_from_geocoder(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[0]["lat"] == pytest.approx(53.3440)
    assert stops[0]["lng"] == pytest.approx(-6.2546)
    assert stops[0]["lat"] != 0.0
    assert stops[0]["lng"] != 0.0


def test_plan_default_stay_uses_type_table(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    payload = _valid_payload()
    payload["stops"][2] = {"query": "Guinness Storehouse"}  # remove explicit override
    response = client.post("/api/plan", json=payload)
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[0]["stay_minutes"] == 0    # first stop — anchor, type lookup skipped
    assert stops[0]["stay_source"] == "default"
    assert stops[1]["stay_minutes"] == 60   # tourist_attraction (Temple Bar, middle)
    assert stops[1]["stay_source"] == "default"
    assert stops[2]["stay_minutes"] == 0    # last stop — anchor, type lookup skipped
    assert stops[2]["stay_source"] == "default"


# ---------------------------------------------------------------------------
# First/last anchor defaults
# ---------------------------------------------------------------------------


def test_first_stop_default_stay_is_zero(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    response = client.post("/api/plan", json=_valid_payload())
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[0]["stay_minutes"] == 0
    assert stops[0]["stay_source"] == "default"


def test_last_stop_default_stay_is_zero(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    payload = _valid_payload()
    payload["stops"][-1] = {"query": "Guinness Storehouse"}  # no user override
    response = client.post("/api/plan", json=payload)
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[-1]["stay_minutes"] == 0
    assert stops[-1]["stay_source"] == "default"


def test_user_override_on_first_stop_honored(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    payload = _valid_payload()
    payload["stops"][0] = {"query": "Trinity College", "stay_minutes": 30}
    response = client.post("/api/plan", json=payload)
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]
    assert stops[0]["stay_minutes"] == 30
    assert stops[0]["stay_source"] == "user"


def test_plan_geocoder_error_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.geocoder import GeocoderError

    async def _always_fail(
        query: str, city: str, db_path: str, ttl_days: int, client: object = None
    ) -> None:
        raise GeocoderError(f"place not found: {query!r}")

    monkeypatch.setattr("app.routers.plan.geocode_cached", _always_fail)
    response = client.post("/api/plan", json=_valid_payload())
    assert response.status_code == 400
    assert "geocode" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Day 7-8: real parallel Routes API leg fetching
# ---------------------------------------------------------------------------


def test_plan_leg_duration_comes_from_routes_api(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    """Leg duration_seconds reflects the Routes API result, not the old 15-min stub."""
    response = client.post("/api/plan", json=_valid_payload())
    legs = [i for i in response.json()["timeline"] if i["item_type"] == "leg"]
    assert len(legs) == 2
    for leg in legs:
        assert leg["duration_seconds"] == 20 * 60  # mock returns 20 min


def test_plan_leg_fetch_called_with_geocoded_coordinates(
    client: TestClient, mock_geocode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fetch_leg receives real lat/lng from the geocoder, not 0.0/0.0."""
    captured: list[dict] = []

    async def _capturing(
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        depart_at: datetime,
        mode: str,
        client: object = None,
    ) -> LegResult:
        captured.append({"origin_lat": origin_lat, "origin_lng": origin_lng})
        return LegResult(
            duration_seconds=20 * 60,
            distance_meters=2000,
            depart_at=depart_at,
            arrive_at=depart_at + timedelta(seconds=20 * 60),
            summary="Mock: 20 min",
            transit_line=None,
        )

    monkeypatch.setattr("app.routers.plan.fetch_leg", _capturing)
    client.post("/api/plan", json=_valid_payload())

    # First leg originates from Trinity College (mock lat/lng from conftest)
    assert captured[0]["origin_lat"] == pytest.approx(53.3440)
    assert captured[0]["origin_lng"] == pytest.approx(-6.2546)
    assert captured[0]["origin_lat"] != 0.0


def test_plan_stop_arrive_at_accounts_for_real_leg_duration(
    client: TestClient, mock_geocode: None, mock_directions: None
) -> None:
    """Second stop's arrive_at = first stop's depart_at + real leg duration (20 min)."""
    response = client.post("/api/plan", json=_valid_payload())
    stops = [i for i in response.json()["timeline"] if i["item_type"] == "stop"]

    first_depart = datetime.fromisoformat(stops[0]["depart_at"])
    second_arrive = datetime.fromisoformat(stops[1]["arrive_at"])
    assert second_arrive - first_depart == timedelta(minutes=20)


def test_plan_leg_failure_surfaces_warning_not_500(
    client: TestClient, mock_geocode: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DirectionsError on any leg returns 200 with a warning, not a 500."""

    async def _always_fail(*args: object, **kwargs: object) -> None:
        raise DirectionsError("network error")

    monkeypatch.setattr("app.routers.plan.fetch_leg", _always_fail)
    response = client.post("/api/plan", json=_valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert len(body["warnings"]) > 0
    # Both legs should still appear in the timeline (degraded, not missing)
    legs = [i for i in body["timeline"] if i["item_type"] == "leg"]
    assert len(legs) == 2
