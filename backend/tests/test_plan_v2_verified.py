"""End-to-end tests for POST /api/v2/plan with verified selections and hours.

Deterministic Places/Routes fakes are injected through plan_v2.places_adapter /
plan_v2.routes_adapter; the clock is pinned through plan_v2._now. No network.

Fixed clock: 2026-10-20 08:00 UTC (Tuesday). Europe/Dublin is UTC+1 until the
fall-back on Sunday 2026-10-25. Weekly test hours are identical every day so
weekday choice does not matter unless a test says otherwise.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.deadline import DeadlineScope
from app.main import app
from app.routers import plan_v2
from app.services import verifier as verifier_module
from app.services.engine import RoutingResult
from app.services.errors import (
    NoRouteError,
    PlaceVerificationError,
    ProviderTemporaryError,
)
from app.services.place_details import PlaceDetails

_NOW = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
_LEG = timedelta(minutes=20)


def _weekly(open_h: int, close_h: int) -> dict[str, Any]:
    return {
        "periods": [
            {"open": {"day": g, "hour": open_h, "minute": 0}, "close": {"day": g, "hour": close_h}}
            for g in range(7)
        ]
    }


def _place(pid: str, name: str, lat: float, lng: float, **kw: Any) -> PlaceDetails:
    return PlaceDetails(place_id=pid, name=name, lat=lat, lng=lng, fetched_at=_NOW, **kw)


PLACES: dict[str, PlaceDetails] = {
    "city_dublin": _place("city_dublin", "Dublin", 53.3498, -6.2603),
    "city_belfast": _place("city_belfast", "Belfast", 54.5973, -5.9301),
    "trinity": _place(
        "trinity",
        "Trinity College Dublin",
        53.3438,
        -6.2546,
        primary_type="tourist_attraction",
        regular_hours_raw=_weekly(8, 22),
    ),
    "guinness": _place(
        "guinness",
        "Guinness Storehouse",
        53.3419,
        -6.2867,
        primary_type="tourist_attraction",
        types=["brewery"],
        regular_hours_raw=_weekly(9, 17),
    ),
    "pub": _place("pub", "The Brazen Head", 53.3448, -6.2765, primary_type="pub"),
    "nyc": _place("nyc", "Times Square", 40.758, -73.9855, primary_type="tourist_attraction"),
    "titanic": _place("titanic", "Titanic Belfast", 54.6081, -5.9099, primary_type="museum"),
    "botanic": _place("botanic", "Botanic Gardens", 54.5821, -5.9356, primary_type="park"),
}


class FakePlaces:
    def __init__(self, overrides: dict[str, BaseException] | None = None, hang: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.overrides = overrides or {}
        self.hang = hang

    async def fetch_details(self, place_id: str, *, role: str) -> PlaceDetails:
        self.calls.append((place_id, role))
        if self.hang:
            await asyncio.Event().wait()
        if place_id in self.overrides:
            raise self.overrides[place_id]
        return PLACES[place_id]


class FakeRoutes:
    def __init__(self, fail_at: int | None = None, hang_at: int | None = None):
        self.calls: list[dict[str, Any]] = []
        self.fail_at = fail_at
        self.hang_at = hang_at

    async def fetch_leg(self, **kw: Any) -> RoutingResult:
        idx = len(self.calls)
        self.calls.append(kw)
        if idx == self.hang_at:
            await asyncio.Event().wait()
        if idx == self.fail_at:
            raise NoRouteError("a", "b")
        return RoutingResult(
            duration_seconds=int(_LEG.total_seconds()),
            distance_meters=1000,
            arrive_at=kw["depart_at"] + _LEG,
            summary="Bus 15, 20 min",
            map_url="https://www.google.com/maps/dir/?api=1",
        )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> tuple[FakePlaces, FakeRoutes]:
    places, routes = FakePlaces(), FakeRoutes()
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: places)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)
    return places, routes


def _stop(iid: str, pid: str, stay: int | None = None, **sel: Any) -> dict[str, Any]:
    selection = {"place_id": pid, "name": sel.get("name", pid), "lat": 53.3, "lng": -6.2}
    selection.update({k: v for k, v in sel.items() if k in ("lat", "lng")})
    stop: dict[str, Any] = {"instance_id": iid, "selection": selection}
    if stay is not None:
        stop["stay_minutes"] = stay
    return stop


def _payload(
    stops: list[dict[str, Any]],
    *,
    city: str = "city_dublin",
    date: str = "2026-10-21",
    time_: str = "10:00",
    tz: str = "Europe/Dublin",
    occurrence: int | None = None,
) -> dict[str, Any]:
    departure: dict[str, Any] = {"local_date": date, "local_time": time_, "timezone": tz}
    if occurrence is not None:
        departure["occurrence"] = occurrence
    return {
        "operation_id": "op-1",
        "input_revision": 3,
        "city": {"place_id": city, "name": "Typed city", "lat": 0.5, "lng": 0.5},
        "stops": stops,
        "departure": departure,
    }


def _post(body: dict[str, Any]) -> Any:
    return TestClient(app).post("/api/v2/plan", json=body)


def _items(resp: Any, kind: str) -> list[dict[str, Any]]:
    return [i for i in resp.json()["timeline"] if i["item_type"] == kind]


# --- verification: provider values, zero routing calls on failure -------------


def test_forged_selection_location_ignored(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    _, routes = fakes
    forged = _stop("a", "trinity", name="Forged", lat=40.758, lng=-73.9855)  # New York
    resp = _post(_payload([forged, _stop("b", "pub")]))
    assert resp.status_code == 200, resp.json()
    first = _items(resp, "stop")[0]
    assert (first["name"], first["lat"], first["lng"]) == (
        "Trinity College Dublin",
        53.3438,
        -6.2546,
    )
    assert (routes.calls[0]["origin_lat"], routes.calls[0]["origin_lng"]) == (53.3438, -6.2546)
    assert resp.json()["city"] == "Dublin"  # provider name, not "Typed city"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (PlaceVerificationError("pub", reason="not_found"), 422, "place_invalid"),
        (ProviderTemporaryError("down"), 503, "place_temporary"),
    ],
)
def test_failed_stop_verification_makes_zero_routing_calls(
    fakes: tuple[FakePlaces, FakeRoutes], error: BaseException, status: int, code: str
) -> None:
    places, routes = fakes
    places.overrides["pub"] = error
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")]))
    assert resp.status_code == status
    assert resp.json()["detail"]["error"] == code
    if code == "place_invalid":
        assert resp.json()["detail"]["instance_ids"] == ["b"]
    assert routes.calls == []


def test_moved_place_reported_without_substitution(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    places, routes = fakes
    places.overrides["pub"] = PlaceVerificationError(
        "pub", reason="moved", moved_place_id="ChIJnew"
    )
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")]))
    detail = resp.json()["detail"]
    assert (resp.status_code, detail["reason"], detail["moved_place_id"]) == (
        422,
        "moved",
        "ChIJnew",
    )
    assert routes.calls == []
    assert ("ChIJnew", "stop") not in places.calls


def test_invalid_city_stops_before_stop_lookups(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    places, routes = fakes
    places.overrides["city_dublin"] = PlaceVerificationError(
        "city_dublin", reason="not_found", role="city"
    )
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")]))
    assert resp.status_code == 422
    assert resp.json()["detail"]["role"] == "city"
    assert places.calls == [("city_dublin", "city")]
    assert routes.calls == []


def test_unresolved_stop_zone_blocks(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, routes = fakes
    real = verifier_module.resolve_timezone

    def fake_tz(lat: float, lng: float) -> str | None:
        return None if lat == PLACES["pub"].lat else real(lat, lng)

    monkeypatch.setattr(verifier_module, "resolve_timezone", fake_tz)
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")]))
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "timezone_unresolved"
    assert resp.json()["detail"]["instance_ids"] == ["b"]
    assert routes.calls == []


def test_unresolved_city_zone_blocks_without_utc_fallback(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    places, routes = fakes
    monkeypatch.setattr(verifier_module, "resolve_timezone", lambda lat, lng: None)
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")], tz="UTC"))
    assert resp.status_code == 422
    assert resp.json()["detail"] == {
        "error": "timezone_unresolved",
        "message": "The timezone for Dublin could not be determined. Select another city.",
        "role": "city",
    }
    assert places.calls == [("city_dublin", "city")]
    assert routes.calls == []


def test_different_zone_stop_blocks(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    _, routes = fakes
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "nyc")]))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "timezone_conflict"
    assert detail["instance_ids"] == ["b"]
    assert routes.calls == []


def test_departure_zone_mismatch_blocks_before_stop_lookups(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    places, routes = fakes
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")], tz="Europe/London"))
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "departure_timezone_mismatch"
    assert places.calls == [("city_dublin", "city")]
    assert routes.calls == []


def test_city_determines_trip_zone(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    """Belfast resolves to Europe/London; a Europe/Dublin claim is rejected."""
    stops = [_stop("a", "titanic"), _stop("b", "botanic")]
    assert _post(_payload(stops, city="city_belfast")).status_code == 422
    resp = _post(_payload(stops, city="city_belfast", tz="Europe/London"))
    assert resp.status_code == 200, resp.json()
    assert resp.json()["timezone"] == "Europe/London"


# --- lookups and durations ----------------------------------------------------


def test_duplicate_visits_share_lookup_keep_distinct_stays(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    places, _ = fakes
    stops = [
        _stop("a", "trinity"),
        _stop("b", "trinity", stay=20),
        _stop("c", "guinness"),
        _stop("d", "trinity"),
    ]
    resp = _post(_payload(stops))
    assert resp.status_code == 200, resp.json()
    assert places.calls.count(("trinity", "stop")) == 1
    assert len(places.calls) == 3  # city + trinity + guinness
    stays = {s["instance_id"]: s["stay_minutes"] for s in _items(resp, "stop")}
    assert stays == {"a": 0, "b": 20, "c": 60, "d": 0}


def test_city_also_a_stop_is_fetched_once(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    places, _ = fakes
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")], city="trinity"))
    assert resp.status_code == 200, resp.json()
    assert places.calls == [("trinity", "stop"), ("pub", "stop")]


def test_duplicate_instance_ids_rejected(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    places, routes = fakes
    resp = _post(_payload([_stop("a", "trinity"), _stop("a", "pub")]))
    assert resp.status_code == 422
    assert places.calls == [] and routes.calls == []


def test_explicit_endpoint_default_middle_and_stay_shift(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    """First stop explicit 30 min; pub uses its place-type default (90);
    each leg departs at actual arrival + that stop's stay."""
    _, routes = fakes
    resp = _post(
        _payload([_stop("a", "trinity", stay=30), _stop("b", "pub"), _stop("c", "trinity")])
    )
    assert resp.status_code == 200, resp.json()
    a, b, c = _items(resp, "stop")
    assert (a["stay_minutes"], a["stay_source"]) == (30, "user")
    assert (b["stay_minutes"], b["stay_source"]) == (90, "default")
    assert c["stay_minutes"] == 0
    start = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)  # 10:00 IST
    assert routes.calls[0]["depart_at"] == start + timedelta(minutes=30)
    b_arrive = start + timedelta(minutes=30) + _LEG
    assert datetime.fromisoformat(b["arrive_at"]) == b_arrive
    assert routes.calls[1]["depart_at"] == b_arrive + timedelta(minutes=90)


# --- hours --------------------------------------------------------------------


def test_known_stops_get_assessed_hours_and_warnings(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    """Start 16:00 IST; Guinness (09–17) visited 16:20–17:20 → closes during visit."""
    resp = _post(
        _payload([_stop("a", "trinity"), _stop("b", "guinness"), _stop("c", "pub")], time_="16:00")
    )
    assert resp.status_code == 200, resp.json()
    a, b, c = _items(resp, "stop")
    assert a["hours_status"] == "open"
    assert a["hours_detail"]["hours_source"] == "weekly"
    assert a["hours_detail"]["exceptions_unconfirmed"] is True
    assert b["hours_status"] == "closes_during_visit"
    assert b["hours_detail"]["closes_at"] == "17:00"
    assert c["hours_status"] == "unknown"
    codes = {(w["affects_instance_id"], w["code"]) for w in resp.json()["warnings"]}
    assert ("b", "hours_closes_during_visit") in codes
    assert ("c", "hours_unknown") in codes
    assert b["stay_minutes"] == 60  # requested visit preserved, not shortened


def test_zero_minute_closed_endpoint_warns(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    """Guinness as a 0-minute final stop at 17:20 is closed: warning, not dropped."""
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "guinness")], time_="17:00"))
    assert resp.status_code == 200
    b = _items(resp, "stop")[1]
    assert (b["hours_status"], b["stay_minutes"]) == ("closed_on_arrival", 0)
    warning = next(w for w in resp.json()["warnings"] if w["affects_instance_id"] == "b")
    assert warning["code"] == "hours_closed_zero_minute"


def test_failed_route_keeps_prefix_and_unknown_downstream(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = FakeRoutes(fail_at=1)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "guinness"), _stop("c", "pub")]))
    body = resp.json()
    assert resp.status_code == 200
    assert (body["result_type"], body["failed_at_leg_index"]) == ("partial", 1)
    kinds = [i["item_type"] for i in body["timeline"]]
    assert kinds == ["stop", "leg", "stop", "failed_leg", "unknown_stop"]
    unknown = body["timeline"][-1]
    assert set(unknown) == {"item_type", "instance_id", "place_id", "name"}
    assert all(w["affects_instance_id"] != "c" for w in body["warnings"])
    assert len(routes.calls) == 2


# --- deadline -------------------------------------------------------------------


def _short_deadline(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    monkeypatch.setattr(plan_v2, "DeadlineScope", lambda: DeadlineScope(deadline_seconds=seconds))


def test_hanging_verification_bounded_by_deadline(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    places, routes = fakes
    places.hang = True
    _short_deadline(monkeypatch, 0.2)
    started = time.monotonic()
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "pub")]))
    assert time.monotonic() - started < 2.0
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "deadline_exceeded"
    assert routes.calls == []


def test_hanging_routing_bounded_returns_partial(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = FakeRoutes(hang_at=1)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    _short_deadline(monkeypatch, 0.3)
    started = time.monotonic()
    resp = _post(_payload([_stop("a", "trinity"), _stop("b", "guinness"), _stop("c", "pub")]))
    assert time.monotonic() - started < 2.0
    body = resp.json()
    assert (body["result_type"], body["failure_reason"]) == ("partial", "deadline_exceeded")
    assert len(routes.calls) == 2  # no further calls after expiry


# --- departure validation: controlled errors, no provider calls ---------------


@pytest.mark.parametrize(
    ("date", "time_", "occurrence", "code"),
    [
        ("2026-02-30", "10:00", None, "departure_invalid_date"),
        ("2027-03-28", "01:30", None, "departure_nonexistent"),
        ("2026-10-25", "01:30", None, "departure_ambiguous"),
        ("2026-10-21", "10:00", 1, "departure_occurrence_not_applicable"),
        ("2027-06-01", "10:00", None, "departure_out_of_range"),
        ("2026-10-01", "10:00", None, "departure_out_of_range"),
    ],
)
def test_departure_errors_fail_safely(
    fakes: tuple[FakePlaces, FakeRoutes],
    date: str,
    time_: str,
    occurrence: int | None,
    code: str,
) -> None:
    places, routes = fakes
    resp = _post(
        _payload(
            [_stop("a", "trinity"), _stop("b", "pub")],
            date=date,
            time_=time_,
            occurrence=occurrence,
        )
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == code
    assert places.calls == [] and routes.calls == []


@pytest.mark.parametrize(("occurrence", "utc_hour"), [(1, 0), (2, 1)])
def test_repeated_time_occurrences_are_chronological(
    fakes: tuple[FakePlaces, FakeRoutes], occurrence: int, utc_hour: int
) -> None:
    """01:30 on 2026-10-25 occurs at 00:30 UTC (first) and 01:30 UTC (second)."""
    resp = _post(
        _payload(
            [_stop("a", "trinity"), _stop("b", "pub")],
            date="2026-10-25",
            time_="01:30",
            occurrence=occurrence,
        )
    )
    assert resp.status_code == 200, resp.json()
    arrive = datetime.fromisoformat(_items(resp, "stop")[0]["arrive_at"])
    assert arrive == datetime(2026, 10, 25, utc_hour, 30, tzinfo=timezone.utc)


def test_walking_plan_in_the_past_rejected(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    body = _payload([_stop("a", "trinity"), _stop("b", "pub")], date="2026-10-19")
    body["mode"] = "walking"
    resp = _post(body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "departure_out_of_range"
