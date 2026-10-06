"""Destination arrival includes the final walk — end to end through the real
Routes response parser (mocked HTTP), for planning, refresh and comparison.

Each mocked transit response is: walk to the stop, one ride (scheduled
departure/arrival), then a final WALK step whose staticDuration is chosen per
test. Arrival at the destination must be ride arrival + final walk.
Geometry/places from test_compare_v2 (A, C, B, D along one street).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import plan_v2
from app.services import adapter as adapter_module
from app.services import directions
from app.services.adapter import GoogleRoutesAdapter
from tests.test_compare_v2 import LNG, _geo
from tests.test_plan_v2_verified import _NOW, PLACES, FakePlaces, _payload, _stop

START = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)  # 09:00 Europe/Dublin


def _pid(lng: float) -> str:
    return next(p for p, v in LNG.items() if abs(v - lng) < 1e-9)


class MockGoogleRoutes:
    """HTTP-level Routes mock: per (from, to): wait before boarding, ride and final walk."""

    def __init__(
        self, spec: dict[str, tuple[int, int, int]], default: tuple[int, int, int] = (0, 600, 0)
    ):
        self.spec = spec
        self.default = default
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        o = body["origin"]["location"]["latLng"]["longitude"]
        d = body["destination"]["location"]["latLng"]["longitude"]
        wait, ride, walk = self.spec.get(_pid(o) + _pid(d), self.default)
        depart = datetime.fromisoformat(body["departureTime"].replace("Z", "+00:00"))
        board = depart + timedelta(seconds=wait)
        alight = board + timedelta(seconds=ride)
        iso = lambda t: t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        steps = [
            {"travelMode": "WALK", "staticDuration": "60s"},
            {
                "travelMode": "TRANSIT",
                "transitDetails": {
                    "transitLine": {"nameShort": "15"},
                    "stopDetails": {"departureTime": iso(board), "arrivalTime": iso(alight)},
                },
            },
            {"travelMode": "WALK", "staticDuration": f"{walk}s"},
        ]
        total = wait + ride + walk
        return httpx.Response(
            200,
            json={
                "routes": [
                    {"duration": f"{total}s", "distanceMeters": 1500, "legs": [{"steps": steps}]}
                ]
            },
        )


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    for pid, lng in LNG.items():
        monkeypatch.setitem(PLACES, pid, _geo(pid, lng))
    state: dict[str, Any] = {"mock": MockGoogleRoutes({})}
    real = directions.fetch_leg

    async def via_mock(**kw: Any) -> directions.LegResult:
        transport = httpx.MockTransport(state["mock"].handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await real(**kw, client=client)

    monkeypatch.setattr(adapter_module.directions, "fetch_leg", via_mock)
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: FakePlaces())
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: GoogleRoutesAdapter())
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)
    return state


def _stops(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["instance_id"]: i for i in res["timeline"] if i["item_type"] == "stop"}


def _plan(order: str, **stays: int) -> dict[str, Any]:
    body = _payload(
        [_stop(p.lower(), p, stays.get(p.lower())) for p in order], date="2026-10-21", time_="09:00"
    )
    resp = TestClient(app).post("/api/v2/plan", json=body)
    assert resp.status_code == 200, resp.json()
    return resp.json()


@pytest.mark.parametrize(
    ("walk", "arrive_b", "next_departure"), [(0, "08:10", "08:40"), (600, "08:20", "08:50")]
)
def test_final_walk_shifts_arrival_and_next_departure(
    google: dict[str, Any], walk: int, arrive_b: str, next_departure: str
) -> None:
    google["mock"] = MockGoogleRoutes({"AB": (0, 600, walk)})
    res = _plan("ABC", b=30)
    b = _stops(res)["b"]
    assert b["arrive_at"].startswith(f"2026-10-21T{arrive_b}")
    # Leg B->C is requested at actual arrival (incl. walk) + 30 min stay.
    assert google["mock"].requests[1]["departureTime"].startswith(f"2026-10-21T{next_departure}")


@pytest.mark.parametrize(("walk", "status"), [(0, "closes_soon"), (600, "closed_on_arrival")])
def test_final_walk_changes_opening_hours_status(
    google: dict[str, Any], monkeypatch: pytest.MonkeyPatch, walk: int, status: str
) -> None:
    """B closes 09:15 local. Alighting 09:10 is 'closes soon'; with a 10 min
    walk the visitor arrives 09:20 — after closing."""
    monkeypatch.setitem(
        PLACES,
        "B",
        _geo(
            "B",
            LNG["B"],
            regular_hours_raw={
                "periods": [
                    {"open": {"day": g, "hour": 8}, "close": {"day": g, "hour": 9, "minute": 15}}
                    for g in range(7)
                ]
            },
        ),
    )
    google["mock"] = MockGoogleRoutes({"AB": (0, 600, walk)})
    assert _stops(_plan("ABC", b=0))["b"]["hours_status"] == status


def test_refresh_includes_final_walk(google: dict[str, Any]) -> None:
    google["mock"] = MockGoogleRoutes({"BC": (120, 600, 420)})
    body = _payload(
        [_stop("a", "A"), _stop("b", "B"), _stop("c", "C")], date="2026-10-21", time_="09:00"
    )
    planned = START + timedelta(minutes=30)
    body.update({"leg_index": 1, "planned_departure": planned.isoformat()})
    res = TestClient(app).post("/api/v2/refresh", json=body).json()
    leg, stop_c = res["suffix"]
    # wait 2 min + ride 10 min + final walk 7 min after the planned departure
    assert datetime.fromisoformat(stop_c["arrive_at"]) == planned + timedelta(minutes=19)
    assert datetime.fromisoformat(leg["arrive_at"]) == planned + timedelta(minutes=19)


_RIDES = {  # original A-B-C-D = 60 min of rides; candidate A-C-B-D = 55 min
    "AB": (0, 1200, 0),
    "BC": (0, 1200, 0),
    "CD": (0, 1200, 0),
    "AC": (0, 600, 0),
    "CB": (0, 1200, 0),
    "BD": (0, 1500, 0),
}


@pytest.mark.parametrize(
    ("walks", "status", "saving"),
    [
        ({}, "recommended", 300),  # rides alone: exactly 300 s
        ({"CB": 60}, "not_faster", 240),  # a candidate final walk erases the saving
        ({"AB": 60}, "recommended", 360),  # an original final walk adds to it
    ],
)
def test_final_walks_change_the_comparison(
    google: dict[str, Any], walks: dict[str, int], status: str, saving: int
) -> None:
    spec = {k: (w, r, walks.get(k, f)) for k, (w, r, f) in _RIDES.items()}
    google["mock"] = MockGoogleRoutes(spec)
    body = _payload([_stop(p.lower(), p, 0) for p in "ABCD"], date="2026-10-21", time_="09:00")
    body.update({"fixed_first": True, "fixed_last": True})
    res = TestClient(app).post("/api/v2/compare", json=body).json()
    assert (res["status"], res["saving_seconds"]) == (status, saving)


def test_undocumented_final_walk_fails_the_leg_without_inventing_time(
    google: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = MockGoogleRoutes({})
    original = mock.handler

    def no_walk_duration(request: httpx.Request) -> httpx.Response:
        resp = original(request)
        data = json.loads(resp.content)
        del data["routes"][0]["legs"][0]["steps"][-1]["staticDuration"]
        return httpx.Response(200, json=data)

    mock.handler = no_walk_duration  # type: ignore[method-assign]
    google["mock"] = mock
    res = _plan("ABC")
    assert res["result_type"] == "partial"
    assert res["failure_reason"] == "arrival_unknown"
    assert [i["item_type"] for i in res["timeline"]] == [
        "stop",
        "failed_leg",
        "unknown_stop",
        "unknown_stop",
    ]
