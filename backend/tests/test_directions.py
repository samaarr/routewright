"""Tests for the Routes API client.

Uses httpx's MockTransport so we can verify request shaping and response
parsing without spending real API quota.
"""

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.services.directions import (
    DirectionsError,
    _build_request_body,
    _extract_transit_line_name,
    _format_duration,
    _parse_duration,
    fetch_leg,
)

# --- Pure-function tests (no network) ---


def test_parse_duration_handles_normal_case() -> None:
    assert _parse_duration("300s") == 300


def test_parse_duration_handles_float() -> None:
    assert _parse_duration("300.5s") == 300


def test_parse_duration_handles_missing() -> None:
    assert _parse_duration("") == 0
    assert _parse_duration("notanumber") == 0


def test_format_duration_under_an_hour() -> None:
    assert _format_duration(540) == "9 min"


def test_format_duration_over_an_hour() -> None:
    assert _format_duration(3960) == "1 hr 6 min"
    assert _format_duration(3600) == "1 hr"


def test_extract_transit_line_picks_short_name() -> None:
    route = {
        "legs": [
            {
                "steps": [
                    {"travelMode": "WALK"},
                    {
                        "travelMode": "TRANSIT",
                        "transitDetails": {
                            "transitLine": {"name": "Route 47 Express", "nameShort": "47"}
                        },
                    },
                ]
            }
        ]
    }
    assert _extract_transit_line_name(route) == "47"


def test_extract_transit_line_falls_back_to_full_name() -> None:
    route = {
        "legs": [
            {
                "steps": [
                    {
                        "travelMode": "TRANSIT",
                        "transitDetails": {"transitLine": {"name": "Vermelha"}},
                    }
                ]
            }
        ]
    }
    assert _extract_transit_line_name(route) == "Vermelha"


def test_extract_transit_line_returns_none_when_only_walking() -> None:
    route = {"legs": [{"steps": [{"travelMode": "WALK"}]}]}
    assert _extract_transit_line_name(route) is None


def test_build_request_body_transit() -> None:
    depart = datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
    body = _build_request_body(53.34, -6.26, 53.35, -6.27, depart, "transit")

    assert body["travelMode"] == "TRANSIT"
    assert body["departureTime"] == "2026-06-01T10:30:00Z"
    # TRAFFIC_AWARE is driving-only; must not appear for transit.
    assert "routingPreference" not in body
    assert body["origin"]["location"]["latLng"]["latitude"] == 53.34


def test_build_request_body_driving_adds_traffic_aware() -> None:
    depart = datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
    body = _build_request_body(53.34, -6.26, 53.35, -6.27, depart, "driving")

    assert body["travelMode"] == "DRIVE"
    assert body["routingPreference"] == "TRAFFIC_AWARE"


def test_build_request_body_naive_datetime_is_treated_as_utc() -> None:
    depart = datetime(2026, 6, 1, 10, 30)  # no tzinfo
    body = _build_request_body(0, 0, 0, 0, depart, "walking")
    assert body["departureTime"].endswith("Z")


# --- Integration-shaped tests with MockTransport ---


def _mock_transport_returning(payload: dict, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(payload))

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fetch_leg_transit_with_bus_line() -> None:
    payload = {
        "routes": [
            {
                "duration": "1080s",
                "distanceMeters": 3200,
                "legs": [
                    {
                        "steps": [
                            {"travelMode": "WALK"},
                            {
                                "travelMode": "TRANSIT",
                                "transitDetails": {
                                    "transitLine": {"name": "Phibsborough", "nameShort": "47"}
                                },
                            },
                            {"travelMode": "WALK"},
                        ]
                    }
                ],
            }
        ]
    }
    transport = _mock_transport_returning(payload)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_leg(
            origin_lat=53.34,
            origin_lng=-6.26,
            destination_lat=53.35,
            destination_lng=-6.27,
            depart_at=datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
            mode="transit",
            client=client,
        )

    assert result.duration_seconds == 1080
    assert result.distance_meters == 3200
    assert result.transit_line == "47"
    assert "47" in result.summary
    assert "18 min" in result.summary


@pytest.mark.asyncio
async def test_fetch_leg_walking_no_transit_data() -> None:
    payload = {"routes": [{"duration": "540s", "distanceMeters": 600, "legs": [{"steps": []}]}]}
    transport = _mock_transport_returning(payload)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_leg(
            origin_lat=53.34,
            origin_lng=-6.26,
            destination_lat=53.35,
            destination_lng=-6.27,
            depart_at=datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
            mode="walking",
            client=client,
        )

    assert result.summary == "9 min walk"
    assert result.transit_line is None


@pytest.mark.asyncio
async def test_fetch_leg_raises_on_empty_routes() -> None:
    transport = _mock_transport_returning({"routes": []})
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DirectionsError, match="no routes"):
            await fetch_leg(
                origin_lat=0,
                origin_lng=0,
                destination_lat=0,
                destination_lng=0,
                depart_at=datetime.now(timezone.utc),
                mode="transit",
                client=client,
            )


@pytest.mark.asyncio
async def test_fetch_leg_raises_on_http_error() -> None:
    transport = _mock_transport_returning({"error": "bad"}, status_code=400)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(DirectionsError, match="400"):
            await fetch_leg(
                origin_lat=0,
                origin_lng=0,
                destination_lat=0,
                destination_lng=0,
                depart_at=datetime.now(timezone.utc),
                mode="transit",
                client=client,
            )


@pytest.mark.asyncio
async def test_fetch_leg_rejects_bad_mode() -> None:
    with pytest.raises(DirectionsError, match="unsupported mode"):
        await fetch_leg(
            origin_lat=0,
            origin_lng=0,
            destination_lat=0,
            destination_lng=0,
            depart_at=datetime.now(timezone.utc),
            mode="cycling",  # type: ignore[arg-type]
        )
