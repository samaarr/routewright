"""Tests for the Step 8 comparison (one local candidate vs a fresh original).

Geometry (all Dublin, Europe/Dublin; clock 2026-10-20 08:00 UTC):
    A lng -6.30   C lng -6.28   B lng -6.20   D lng -6.18
Original order A,B,C,D zig-zags; the distance optimiser (both ends pinned)
proposes A,C,B,D. Leg durations come from a per-journey table so savings,
closures and failures are exact. Departure 09:00 IST (08:00Z) on 2026-10-21.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import provider_semaphore
from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.main import app
from app.models.request import ComparisonRequest
from app.routers import plan_v2
from app.services import comparison
from app.services.comparison import RoutingBudget, RoutingBudgetExceededError
from app.services.engine import OperationContext, RoutingResult
from app.services.place_details import PlaceDetails
from tests.test_plan_v2_verified import _NOW, PLACES, FakePlaces, _payload, _stop


def _weekly(open_h: int, close_h: int) -> dict[str, Any]:
    return {
        "periods": [
            {"open": {"day": g, "hour": open_h}, "close": {"day": g, "hour": close_h}}
            for g in range(7)
        ]
    }


LNG = {"A": -6.30, "C": -6.28, "B": -6.20, "D": -6.18, "E": -6.25}


def _geo(pid: str, lng: float, **kw: Any) -> PlaceDetails:
    return PlaceDetails(
        pid, f"Place {pid}", 53.34, lng, primary_type="tourist_attraction", fetched_at=_NOW, **kw
    )


@pytest.fixture(autouse=True)
def geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    for pid, lng in LNG.items():
        monkeypatch.setitem(PLACES, pid, _geo(pid, lng))


class PairRoutes:
    """Routing fake: seconds per (from, to) place; records every call."""

    def __init__(
        self, seconds: dict[str, int], fail_at: int | None = None, hang_at: int | None = None
    ) -> None:
        self.seconds = seconds
        self.calls: list[str] = []
        self.fail_at = fail_at
        self.hang_at = hang_at

    @staticmethod
    def _pid(lng: float) -> str:
        return next(p for p, v in LNG.items() if abs(v - lng) < 1e-9)

    async def fetch_leg(self, **kw: Any) -> RoutingResult:
        key = self._pid(kw["origin_lng"]) + self._pid(kw["dest_lng"])
        idx = len(self.calls)
        self.calls.append(key)
        if idx == self.hang_at:
            await asyncio.Event().wait()
        if idx == self.fail_at:
            from app.services.errors import NoRouteError

            raise NoRouteError("x", "y")
        s = self.seconds.get(key, 1000)
        return RoutingResult(s, 1000, kw["depart_at"] + timedelta(seconds=s), "Bus", "m")


def _routes_for_saving(saving: int) -> PairRoutes:
    # Original A-B-C-D: AB + BC + CD = 3000. Candidate A-C-B-D: AC + CB + BD.
    return PairRoutes(
        {"AB": 1000, "BC": 1000, "CD": 1000, "AC": 500, "CB": 1000, "BD": 1500 - saving}
    )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"places": FakePlaces(), "routes": _routes_for_saving(600)}
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: state["places"])
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: state["routes"])
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)
    return state


def _body(
    order: str = "ABCD", *, first: bool = True, last: bool = True, **stays: int
) -> dict[str, Any]:
    body = _payload(
        [_stop(p.lower(), p, stays.get(p.lower())) for p in order], date="2026-10-21", time_="09:00"
    )
    body.update({"fixed_first": first, "fixed_last": last})
    return body


def _compare(body: dict[str, Any]) -> dict[str, Any]:
    resp = TestClient(app).post("/api/v2/compare", json=body)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def _stops(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in plan["timeline"] if i["item_type"] == "stop"]


# --- candidate generation, pins, unchanged order ------------------------------------


def test_unchanged_order_makes_no_routing_calls(env: dict[str, Any]) -> None:
    res = _compare(_body("ACBD"))
    assert res["status"] == "no_different_order"
    assert res["message"] == "No different order found by the current search."
    assert "fastest" not in res["message"].lower()
    assert res["routing_calls"] == 0 and env["routes"].calls == []
    assert res["original"] is None and res["candidate"] is None


def test_two_pinned_stops_leave_no_freedom(env: dict[str, Any]) -> None:
    res = _compare(_body("AB"))
    assert (res["status"], res["routing_calls"]) == ("no_different_order", 0)


def test_pins_keep_endpoints_and_candidate_is_one_reordering(env: dict[str, Any]) -> None:
    res = _compare(_body())
    assert res["candidate_order"] == ["a", "c", "b", "d"]
    assert res["original_order"] == ["a", "b", "c", "d"]
    assert res["candidate_distance_km"] < res["original_distance_km"]  # heuristic only


def test_unpinned_endpoint_moves_but_keeps_its_zero_duration(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fixed, D free: best distance order moves the original last stop (E) inward.
    env["routes"] = PairRoutes({}, fail_at=None)
    res = _compare(_body("ABCE", last=False, b=45))
    order = res["candidate_order"]
    assert order[0] == "a" and order[-1] != "e"
    durations = {s["instance_id"]: s["stay_minutes"] for s in _stops(res["original"])}
    assert durations["e"] == 0 and durations["b"] == 45  # resolved once, by instance


# --- savings threshold and hours eligibility ------------------------------------


@pytest.mark.parametrize(
    ("saving", "status"),
    [
        (-200, "not_faster"),
        (0, "not_faster"),
        (299, "not_faster"),
        (300, "recommended"),
        (301, "recommended"),
    ],
)
def test_exact_threshold_before_rounding(env: dict[str, Any], saving: int, status: str) -> None:
    env["routes"] = _routes_for_saving(saving)
    res = _compare(_body())
    assert (res["status"], res["saving_seconds"]) == (status, saving)
    assert res["original_seconds"] - res["candidate_seconds"] == saving
    assert res["routing_calls"] == 6  # 2(N-1) for N=4
    if status == "recommended":
        cand = res["candidate"]
        assert [s["instance_id"] for s in _stops(cand)] == res["candidate_order"]
        assert cand["result_type"] == "complete"
    else:
        assert res["candidate"] is None


def test_faster_candidate_rejected_for_closure_on_arrival(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C opens 10:00. Candidate reaches C at 09:08 (closed, 60 min visit) even
    though it saves 600 s; the original reaches C after 10:00."""
    monkeypatch.setitem(PLACES, "C", _geo("C", LNG["C"], regular_hours_raw=_weekly(10, 18)))
    res = _compare(_body())
    assert res["status"] == "hours_ineligible"
    assert res["saving_seconds"] == 600
    assert res["ineligible_instance_ids"] == ["c"]
    assert res["candidate"] is None


def test_closing_during_visit_only_warns(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C closes 09:30: the candidate arrives 09:08 (open) and stays past closing:
    a warning, not a disqualification (D42)."""
    monkeypatch.setitem(
        PLACES,
        "C",
        _geo(
            "C",
            LNG["C"],
            regular_hours_raw={
                "periods": [
                    {"open": {"day": g, "hour": 6}, "close": {"day": g, "hour": 9, "minute": 30}}
                    for g in range(7)
                ]
            },
        ),
    )
    res = _compare(_body())
    assert res["status"] == "recommended"
    warn = [w for w in res["candidate"]["warnings"] if w["affects_instance_id"] == "c"]
    assert warn and warn[0]["code"] == "hours_closes_during_visit"


def test_durations_identical_in_both_orders(env: dict[str, Any]) -> None:
    res = _compare(_body(b=45, c=0))
    orig = {s["instance_id"]: s["stay_minutes"] for s in _stops(res["original"])}
    cand = {s["instance_id"]: s["stay_minutes"] for s in _stops(res["candidate"])}
    assert orig == cand == {"a": 0, "b": 45, "c": 0, "d": 0}


# --- failures, budgets, shared details ----------------------------------------------


def test_original_failure_stops_comparison(env: dict[str, Any]) -> None:
    env["routes"] = PairRoutes({}, fail_at=1)
    res = _compare(_body())
    assert res["status"] == "original_incomplete"
    assert res["original"]["result_type"] == "partial"
    assert res["candidate"] is None and res["saving_seconds"] is None
    assert res["routing_calls"] == 2 and len(env["routes"].calls) == 2  # no candidate calls


def test_candidate_failure_keeps_complete_fresh_original(env: dict[str, Any]) -> None:
    env["routes"] = PairRoutes({}, fail_at=4)  # 2nd leg of the candidate
    res = _compare(_body())
    assert res["status"] == "candidate_incomplete"
    assert res["original"]["result_type"] == "complete"
    assert res["candidate"] is None and res["saving_seconds"] is None
    assert res["routing_calls"] == 5


def test_place_details_shared_once_per_place(env: dict[str, Any]) -> None:
    _compare(_body())
    calls = env["places"].calls
    assert sorted(calls) == sorted(
        [("city_dublin", "city"), ("A", "stop"), ("B", "stop"), ("C", "stop"), ("D", "stop")]
    )


@pytest.mark.asyncio
async def test_routing_budget_refuses_extra_calls() -> None:
    inner = PairRoutes({})
    budget = RoutingBudget(inner, 2)
    kw = {
        "origin_lat": 53.34,
        "origin_lng": -6.30,
        "dest_lat": 53.34,
        "dest_lng": -6.20,
        "mode": "transit",
        "depart_at": _NOW,
    }
    await budget.fetch_leg(**kw)
    await budget.fetch_leg(**kw)
    with pytest.raises(RoutingBudgetExceededError):
        await budget.fetch_leg(**kw)
    assert len(inner.calls) == 2


def test_compare_has_its_own_allowance(env: dict[str, Any]) -> None:
    client = TestClient(app)
    body = _body("ACBD")
    for i in range(10):
        body["operation_id"] = f"c{i}"
        assert client.post("/api/v2/compare", json=body).status_code == 200
    assert client.post("/api/v2/compare", json=body).status_code == 429
    plan = _payload([_stop("a", "A"), _stop("b", "B")], date="2026-10-21", time_="09:00")
    assert client.post("/api/v2/plan", json=plan).status_code == 200


# --- deadline, solver bounding, cancellation --------------------------------------


@pytest.mark.asyncio
async def test_solver_bounded_by_deadline_and_slot_released_when_thread_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_semaphore.reset_gates()
    seen_limits: list[float] = []

    def slow_solver(places: Any, first: bool, last: bool, limit: float) -> list[int]:
        seen_limits.append(limit)
        time.sleep(0.4)
        return list(range(len(places)))

    monkeypatch.setattr(comparison, "optimise_order", slow_solver)
    stops = [PLACES[p] for p in "ABCD"]
    from app.services.engine import VerifiedStop

    vstops = [VerifiedStop(p.place_id, p.place_id, p.name, None, p.lat, p.lng) for p in stops]
    deadline = DeadlineScope(deadline_seconds=0.1)
    started = time.monotonic()
    with pytest.raises(DeadlineExceededError):
        await comparison.generate_candidate(
            vstops, fixed_first=True, fixed_last=True, deadline=deadline
        )
    assert time.monotonic() - started < 0.3  # cancellation is immediate for the caller
    assert seen_limits and seen_limits[0] <= 0.1  # solver limit capped by remaining time
    assert provider_semaphore.solver_slots_free() == 1  # thread still running holds its slot
    await asyncio.sleep(0.5)
    assert provider_semaphore.solver_slots_free() == 2  # released when the thread ended


def _stream(body: dict[str, Any]) -> list[dict[str, Any]]:
    resp = TestClient(app).post("/api/v2/compare/stream", json=body)
    assert resp.status_code == 200, resp.text
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_stream_identifies_both_routes(env: dict[str, Any]) -> None:
    events = _stream(_body())
    phases = [e["phase"] for e in events if e["type"] == "phase_start"]
    assert phases == ["verification", "candidate", "original_route", "alternative_route"]
    assert all(e["operation_id"] == "op-1" and e["input_revision"] == 3 for e in events)
    outcome = events[-1]["outcome"]
    assert (outcome["outcome_type"], outcome["result"]["status"]) == ("comparison", "recommended")


def test_deadline_during_alternative_never_recommends(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    env["routes"] = PairRoutes({}, hang_at=4)
    monkeypatch.setattr(plan_v2, "DeadlineScope", lambda: DeadlineScope(deadline_seconds=0.5))
    res = _stream(_body())[-1]["outcome"]["result"]
    assert res["status"] == "candidate_incomplete"
    assert res["original"]["result_type"] == "complete"
    assert res["candidate"] is None


def test_deadline_during_verification_is_a_timeout(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    env["places"] = FakePlaces(hang=True)
    monkeypatch.setattr(plan_v2, "DeadlineScope", lambda: DeadlineScope(deadline_seconds=0.2))
    outcome = _stream(_body())[-1]["outcome"]
    assert (outcome["outcome_type"], outcome["phase"]) == ("timeout", "verification")
    assert env["routes"].calls == []


@pytest.mark.asyncio
async def test_disconnect_stops_further_comparison_calls() -> None:
    routes = PairRoutes({}, hang_at=3)  # first candidate leg hangs
    disconnect = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    req = ComparisonRequest.model_validate(_body())
    stream = plan_v2.PlanStream(
        req,
        departure_utc=_NOW + timedelta(days=1),
        places=FakePlaces(),
        routes=routes,
        ctx=OperationContext(operation_id="op-1", input_revision=3),
        deadline=DeadlineScope(),
        receive=receive,
    )
    seen: list[dict[str, Any]] = []

    async def consume() -> None:
        async for chunk in stream.events():
            seen.append(json.loads(chunk))

    task = asyncio.create_task(consume())
    while len(routes.calls) < 4:
        await asyncio.sleep(0.01)
    disconnect.set()
    await asyncio.wait_for(task, 1)
    await asyncio.sleep(0.05)
    assert len(routes.calls) == 4  # nothing scheduled after the disconnect
    assert all(e["type"] != "terminal" for e in seen)


def test_comparison_budget_is_exactly_two_times_n_minus_one(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    limits: list[int] = []
    real = plan_v2.RoutingBudget

    def recording(inner: Any, limit: int) -> RoutingBudget:
        limits.append(limit)
        return real(inner, limit)

    monkeypatch.setattr(plan_v2, "RoutingBudget", recording)
    _compare(_body())
    assert limits == [6]  # N=4 -> 2(N-1)
