"""Tests for the Routes API client.

Uses httpx's MockTransport so we can verify request shaping and response
parsing without spending real API quota.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services.directions import (
    DirectionsError,
    _build_request_body,
    _extract_scheduled_times,
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
    for value in ["", "notanumber", "-1s", "nans", "infs"]:
        with pytest.raises(DirectionsError):
            _parse_duration(value)


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
                                    "transitLine": {"name": "Phibsborough", "nameShort": "47"},
                                    "stopDetails": {
                                        "departureTime": "2026-06-01T10:35:00Z",
                                        "arrivalTime": "2026-06-01T10:45:00Z",
                                    },
                                },
                            },
                            {"travelMode": "WALK", "staticDuration": "180s"},
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
        with pytest.raises(DirectionsError, match="request failed"):
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


# --- Scheduled time extraction ---


def test_extract_scheduled_times_uses_transit_step_times() -> None:
    depart_at = datetime(2026, 5, 18, 12, 3, tzinfo=timezone.utc)
    route = {
        "legs": [
            {
                "steps": [
                    {"travelMode": "WALK"},
                    {
                        "travelMode": "TRANSIT",
                        "transitDetails": {
                            "stopDetails": {
                                "departureTime": "2026-05-18T12:14:00Z",
                                "arrivalTime": "2026-05-18T12:35:00Z",
                            }
                        },
                    },
                    {"travelMode": "WALK", "staticDuration": "240s"},
                ]
            }
        ]
    }
    actual_depart, actual_arrive = _extract_scheduled_times(route, depart_at, 1260)
    assert actual_depart == datetime(2026, 5, 18, 12, 14, tzinfo=timezone.utc)
    # Alight 12:35 + documented 240 s walk to the destination.
    assert actual_arrive == datetime(2026, 5, 18, 12, 39, tzinfo=timezone.utc)


def test_extract_scheduled_times_falls_back_without_transit_steps() -> None:
    depart_at = datetime(2026, 5, 18, 12, 3, tzinfo=timezone.utc)
    route = {"legs": [{"steps": [{"travelMode": "WALK"}]}]}
    actual_depart, actual_arrive = _extract_scheduled_times(route, depart_at, 600)
    assert actual_depart == depart_at
    assert actual_arrive == depart_at + timedelta(seconds=600)


@pytest.mark.asyncio
async def test_fetch_leg_transit_uses_scheduled_times() -> None:
    """leg.depart_at and arrive_at reflect scheduled bus times, not computed times."""
    payload = {
        "routes": [
            {
                "duration": "1260s",
                "distanceMeters": 3800,
                "legs": [
                    {
                        "steps": [
                            {"travelMode": "WALK"},
                            {
                                "travelMode": "TRANSIT",
                                "transitDetails": {
                                    "transitLine": {"nameShort": "23"},
                                    "stopDetails": {
                                        "departureTime": "2026-05-18T12:14:00Z",
                                        "arrivalTime": "2026-05-18T12:35:00Z",
                                    },
                                },
                            },
                            {"travelMode": "WALK", "staticDuration": "300s"},
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
            depart_at=datetime(2026, 5, 18, 12, 3, tzinfo=timezone.utc),
            mode="transit",
            client=client,
        )

    assert result.depart_at == datetime(2026, 5, 18, 12, 14, tzinfo=timezone.utc)
    assert result.arrive_at == datetime(2026, 5, 18, 12, 40, tzinfo=timezone.utc)  # + 5 min walk
    assert result.transit_line == "23"


# ---------------------------------------------------------------------------
# Destination arrival includes the documented final walk (no invented time)
# ---------------------------------------------------------------------------

_T = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)


def _ride(dep: str, arr: str | None) -> dict:
    stop: dict = {"departureTime": f"2026-05-18T{dep}:00Z"}
    if arr is not None:
        stop["arrivalTime"] = f"2026-05-18T{arr}:00Z"
    return {"travelMode": "TRANSIT", "transitDetails": {"stopDetails": stop}}


def _walk(seconds: int | None) -> dict:
    return {"travelMode": "WALK"} | (
        {"staticDuration": f"{seconds}s"} if seconds is not None else {}
    )


def test_final_walk_after_last_ride_is_added_once() -> None:
    """Walks before/between rides are already inside the scheduled times; only
    steps after the LAST ride are added."""
    route = {
        "legs": [
            {
                "steps": [
                    _walk(300),
                    _ride("12:10", "12:20"),
                    _walk(240),
                    _ride("12:30", "12:45"),
                    _walk(120),
                    _walk(60),
                ]
            }
        ]
    }
    _, arrive = _extract_scheduled_times(route, _T, 9999)
    assert arrive == datetime(2026, 5, 18, 12, 48, tzinfo=timezone.utc)  # 12:45 + 120 s + 60 s


def test_no_final_walk_arrives_at_alighting() -> None:
    route = {"legs": [{"steps": [_walk(300), _ride("12:10", "12:20")]}]}
    assert _extract_scheduled_times(route, _T, 9999)[1] == datetime(
        2026, 5, 18, 12, 20, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    "steps",
    [
        [_ride("12:10", "12:20"), _walk(None)],  # final walk without a documented duration
        [_ride("12:10", None), _walk(60)],  # last ride without an arrival time
        [_ride("12:10", "12:20"), _ride("12:25", None)],  # earlier ride's time must not be reused
        [_ride("11:40", "11:50")],  # arrival before the requested departure
    ],
)
def test_undocumented_arrival_is_unknown_not_invented(steps: list[dict]) -> None:
    from app.services.directions import ArrivalUnknownError

    with pytest.raises(ArrivalUnknownError):
        _extract_scheduled_times({"legs": [{"steps": steps}]}, _T, 600)


def test_transit_field_mask_requests_step_durations() -> None:
    from app.services.directions import _FIELD_MASK_TRANSIT

    assert "routes.legs.steps.staticDuration" in _FIELD_MASK_TRANSIT
