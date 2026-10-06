"""Tests for the v2 suffix refresh (D21, Step 7).

Fakes from test_plan_v2_verified; clock pinned at 2026-10-20 08:00 UTC.
Trip: a=Trinity (prefix only), b=Guinness, c=The Brazen Head (pub, 90 min
default), d=Guinness again. Refreshing leg 1 (b -> c) must route only legs 1
and 2, starting at the planned departure, and leave stops a, b untouched.
Guinness is open 09:00-17:00 local (IST = UTC+1 until 25 Oct).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.deadline import DeadlineScope
from app.main import app
from app.routers import plan_v2
from app.services.errors import PlaceVerificationError
from tests.test_plan_v2_verified import _NOW, FakePlaces, FakeRoutes, _payload, _stop

PLANNED = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)  # 09:00 IST
LEG = timedelta(minutes=20)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> tuple[FakePlaces, FakeRoutes]:
    places, routes = FakePlaces(), FakeRoutes()
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: places)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)
    return places, routes


def _refresh_body(
    leg_index: int = 1,
    planned: datetime = PLANNED,
    *,
    mode: str = "transit",
    date: str = "2026-10-21",
    stays: dict[str, int] | None = None,
) -> dict[str, Any]:
    stays = stays or {}
    body = _payload(
        [
            _stop("a", "trinity", stays.get("a")),
            _stop("b", "guinness", stays.get("b")),
            _stop("c", "pub", stays.get("c")),
            _stop("d", "guinness", stays.get("d")),
        ],
        date=date,
        time_="08:00",
    )
    body.update({"leg_index": leg_index, "planned_departure": planned.isoformat(), "mode": mode})
    return body


def _post(body: dict[str, Any], path: str = "/api/v2/refresh") -> Any:
    return TestClient(app).post(path, json=body)


def _at(item: dict[str, Any], key: str) -> datetime:
    return datetime.fromisoformat(item[key])


def test_refresh_routes_only_the_suffix_from_the_planned_departure(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    places, routes = fakes
    resp = _post(_refresh_body())
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["result_type"] == "refresh_complete"
    assert body["leg_index"] == 1
    # N-1-k = 4-1-1 = 2 routing calls, the first at the planned departure (not now).
    assert len(routes.calls) == 2
    assert routes.calls[0]["depart_at"] == PLANNED
    assert routes.calls[0]["depart_at"] != _NOW
    # Unchanged prefix: no items for stops a/b or leg 0; prefix-only place not looked up.
    kinds = [(i["item_type"], i.get("instance_id") or i.get("to_stop_id")) for i in body["suffix"]]
    assert kinds == [("leg", "c"), ("stop", "c"), ("leg", "d"), ("stop", "d")]
    assert ("trinity", "stop") not in places.calls
    assert places.calls == [("city_dublin", "city"), ("guinness", "stop"), ("pub", "stop")]


def test_refreshed_times_propagate_through_stays_and_later_legs(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    _, routes = fakes
    suffix = _post(_refresh_body(stays={"c": 30})).json()["suffix"]
    leg1, stop_c, leg2, stop_d = suffix
    assert _at(leg1, "depart_at") == PLANNED
    assert _at(stop_c, "arrive_at") == PLANNED + LEG
    assert (stop_c["stay_minutes"], stop_c["stay_source"]) == (30, "user")  # preserved duration
    assert _at(leg2, "depart_at") == PLANNED + LEG + timedelta(minutes=30)
    assert routes.calls[1]["depart_at"] == PLANNED + LEG + timedelta(minutes=30)
    assert _at(stop_d, "arrive_at") == PLANNED + 2 * LEG + timedelta(minutes=30)


def test_downstream_hours_are_reassessed_for_new_times(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    """Pub default stay 90 min. Refreshing at 09:00 IST reaches Guinness at
    11:10 (open); at 16:00 IST it reaches Guinness at 18:10 (closed)."""
    early = _post(_refresh_body()).json()
    assert early["suffix"][3]["hours_status"] == "open"
    late = _post(_refresh_body(planned=datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc))).json()
    stop_d = late["suffix"][3]
    assert stop_d["hours_status"] == "closed_on_arrival"
    codes = {(w["affects_instance_id"], w["code"]) for w in late["warnings"]}
    assert ("d", "hours_closed_zero_minute") in codes
    assert all(w["affects_stop_index"] in (None, 2, 3) for w in late["warnings"])


def test_failure_halfway_keeps_refreshed_work_and_unknown_downstream(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = FakeRoutes(fail_at=1)  # leg 2 (c -> d) fails
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    body = _post(_refresh_body()).json()
    assert (body["result_type"], body["failed_at_leg_index"]) == ("refresh_partial", 2)
    assert [i["item_type"] for i in body["suffix"]] == ["leg", "stop", "failed_leg", "unknown_stop"]
    unknown = body["suffix"][-1]
    assert set(unknown) == {"item_type", "instance_id", "place_id", "name"}  # no stale times
    assert len(routes.calls) == 2


def test_refreshing_the_last_leg_makes_one_call(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    _, routes = fakes
    body = _post(_refresh_body(leg_index=2)).json()
    assert len(routes.calls) == 1
    assert [i["item_type"] for i in body["suffix"]] == ["leg", "stop"]


@pytest.mark.parametrize(
    ("mode", "planned", "date"),
    [
        ("walking", _NOW - timedelta(hours=1), "2026-10-20"),  # past: transit only
        ("transit", _NOW - timedelta(days=8), "2026-10-12"),  # > 7 days back
        ("transit", _NOW + timedelta(days=101), "2026-10-21"),  # > 100 days ahead
    ],
)
def test_unsupported_planned_departure_is_explained_not_replaced(
    fakes: tuple[FakePlaces, FakeRoutes], mode: str, planned: datetime, date: str
) -> None:
    places, routes = fakes
    resp = _post(_refresh_body(planned=planned, mode=mode, date=date))
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "planned_departure_unsupported"
    assert "Plan the day again" in detail["message"]
    assert places.calls == [] and routes.calls == []


def test_planned_departure_before_trip_departure_rejected(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    places, routes = fakes
    resp = _post(_refresh_body(planned=datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)))
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "planned_departure_unsupported"
    assert places.calls == [] and routes.calls == []


def test_leg_index_must_be_a_real_leg(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    assert _post(_refresh_body(leg_index=3)).status_code == 422


def test_suffix_verification_failure_makes_zero_routing_calls(
    fakes: tuple[FakePlaces, FakeRoutes],
) -> None:
    places, routes = fakes
    places.overrides["pub"] = PlaceVerificationError("pub", reason="not_found")
    resp = _post(_refresh_body())
    assert resp.status_code == 422
    assert resp.json()["detail"]["instance_ids"] == ["c"]
    assert routes.calls == []


# --- streaming --------------------------------------------------------------------


def _stream(body: dict[str, Any]) -> list[dict[str, Any]]:
    resp = _post(body, "/api/v2/refresh/stream")
    assert resp.status_code == 200, resp.text
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_refresh_stream_events_and_outcome(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    events = _stream(_refresh_body())
    ready = [
        (e["leg_index"], e["completed_legs"], e["total_legs"])
        for e in events
        if e["type"] == "leg_ready"
    ]
    assert ready == [(1, 1, 2), (2, 2, 2)]  # global leg indices, refresh-only totals
    stops = [e["stop_index"] for e in events if e["type"] == "stop_ready"]
    assert stops == [2, 3]  # no stop_ready for the unchanged prefix
    outcome = events[-1]["outcome"]
    assert outcome["outcome_type"] == "refresh"
    assert outcome["result"]["result_type"] == "refresh_complete"


def test_refresh_stream_timeout_keeps_refreshed_prefix(
    fakes: tuple[FakePlaces, FakeRoutes], monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = FakeRoutes(hang_at=1)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    monkeypatch.setattr(plan_v2, "DeadlineScope", lambda: DeadlineScope(deadline_seconds=0.3))
    outcome = _stream(_refresh_body())[-1]["outcome"]
    assert (outcome["outcome_type"], outcome["phase"]) == ("timeout", "routing")
    partial = outcome["partial"]
    assert partial["result_type"] == "refresh_partial"
    assert partial["failure_reason"] == "deadline_exceeded"
    assert [i["item_type"] for i in partial["suffix"]] == [
        "leg",
        "stop",
        "failed_leg",
        "unknown_stop",
    ]


def test_refresh_has_its_own_allowance(fakes: tuple[FakePlaces, FakeRoutes]) -> None:
    client = TestClient(app)
    plan_body = _payload([_stop("a", "trinity"), _stop("b", "pub")])
    for i in range(10):
        plan_body["operation_id"] = f"p{i}"
        assert client.post("/api/v2/plan", json=plan_body).status_code == 200
    assert client.post("/api/v2/plan", json=plan_body).status_code == 429
    assert client.post("/api/v2/refresh", json=_refresh_body()).status_code == 200
