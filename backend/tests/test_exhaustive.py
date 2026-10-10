"""Experimental exhaustive four-stop optimiser (2026-10-08).

Deterministic fakes only: a counting places fake and a scripted routes fake
(travel time can depend on the pair and the departure instant), plus the
HTTP-level Routes mock from test_final_walk for the final-walk case. No
network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.main import app
from app.models.request import ExhaustiveRequest
from app.models.response import ExhaustiveResult, KnownStop, PlannedLeg, UnknownStop
from app.routers import plan_v2
from app.services import adapter as adapter_module
from app.services import directions, exhaustive
from app.services.adapter import GoogleRoutesAdapter
from app.services.engine import OperationContext, RoutingResult, VerifiedStop
from app.services.errors import (
    NoRouteError,
    ProviderCapacityError,
    ProviderTemporaryError,
    QuotaExceededError,
)
from tests.test_compare_v2 import LNG, _geo
from tests.test_final_walk import MockGoogleRoutes
from tests.test_plan_v2_verified import _NOW, PLACES, FakePlaces, _payload, _stop, _weekly

T0 = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)  # 09:00 Europe/Dublin
STAYS = {"a": 10, "c": 20, "b": 30, "d": 40}  # nonzero at every position on purpose


@pytest.fixture(autouse=True)
def geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    for pid, lng in LNG.items():
        monkeypatch.setitem(PLACES, pid, _geo(pid, lng))
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)


def _pid(lng: float) -> str:
    return next(p for p, v in LNG.items() if abs(v - lng) < 1e-9)


Minutes = Callable[[str, str, datetime], float]


def _by_distance(a: str, b: str, t: datetime) -> float:
    return round(abs(LNG[a] - LNG[b]) * 1000)  # A->C 20 min, A->D 120 min


class Routes:
    """Scripted RoutesAdapter: records (from, to, depart_at) for every call."""

    def __init__(
        self,
        minutes: Minutes = _by_distance,
        fail: Callable[[str, str, datetime, int], Exception | None] | None = None,
        hook: Callable[[int], Any] | None = None,
    ) -> None:
        self.minutes = minutes
        self.fail = fail
        self.hook = hook
        self.calls: list[tuple[str, str, datetime]] = []

    async def fetch_leg(self, **kw: Any) -> RoutingResult:
        a, b, t = _pid(kw["origin_lng"]), _pid(kw["dest_lng"]), kw["depart_at"]
        self.calls.append((a, b, t))
        if self.hook is not None:
            res = self.hook(len(self.calls))
            if asyncio.iscoroutine(res):
                await res
        exc = self.fail(a, b, t, len(self.calls)) if self.fail else None
        if exc is not None:
            raise exc
        seconds = int(self.minutes(a, b, t) * 60)
        return RoutingResult(
            duration_seconds=seconds,
            distance_meters=1000,
            arrive_at=t + timedelta(seconds=seconds),
            summary="Bus",
            map_url="https://example.invalid/route",
        )


def _req(order: str = "ACBD", stays: dict[str, int] | None = None, **kw: Any) -> ExhaustiveRequest:
    s = STAYS if stays is None else stays
    body = _payload(
        [_stop(p.lower(), p, s[p.lower()]) for p in order], date="2026-10-21", time_="09:00"
    )
    body.update(kw)
    return ExhaustiveRequest.model_validate(body)


class Events:
    def __init__(self) -> None:
        self.items: list[Any] = []

    async def emit(self, event: object) -> None:
        self.items.append(event)


async def _run(
    routes: Routes,
    req: ExhaustiveRequest | None = None,
    places: FakePlaces | None = None,
    ctx: OperationContext | None = None,
    deadline: DeadlineScope | None = None,
    departure: datetime = T0,
) -> tuple[ExhaustiveResult, FakePlaces, Events]:
    places = places or FakePlaces()
    events = Events()
    result = await plan_v2.execute_exhaustive(
        req or _req(),
        departure_utc=departure,
        places=places,
        routes=routes,
        emitter=events,
        ctx=ctx or OperationContext(operation_id="op-x", input_revision=3),
        deadline=deadline or DeadlineScope(deadline_seconds=exhaustive.DEADLINE_SECONDS),
    )
    return result, places, events


def _stops(timeline: list[Any]) -> list[KnownStop]:
    return [i for i in timeline if isinstance(i, KnownStop)]


# --- orders, budget, shared verification ------------------------------------------


def _verified(order: str = "ACBD") -> list[VerifiedStop]:
    return [VerifiedStop(p.lower(), p, f"Place {p}", None, 53.34, LNG[p]) for p in order]


def test_generate_orders_is_24_unique_with_original_first() -> None:
    stops = _verified()
    orders = exhaustive.generate_orders(stops)
    assert len(orders) == 24
    assert len({tuple(s.instance_id for s in o) for o in orders}) == 24
    assert orders[0] == tuple(stops)
    assert orders.count(tuple(stops)) == 1


@pytest.mark.asyncio
async def test_all_success_uses_exactly_72_calls_and_verifies_once() -> None:
    routes = Routes()
    result, places, events = await _run(routes)
    assert len(routes.calls) == 72 == result.routing_calls == result.routing_budget
    assert sorted(places.calls) == sorted(
        [("city_dublin", "city"), ("A", "stop"), ("C", "stop"), ("B", "stop"), ("D", "stop")]
    )
    assert result.status == "all_complete" and result.search_complete
    assert (result.evaluated_orders, result.complete_orders, result.failed_orders) == (24, 24, 0)
    assert result.message == "Earliest completion among all 24 evaluated stop orders."
    assert sum(c.is_original for c in result.candidates) == 1
    assert [c.order for c in result.candidates].count(["a", "c", "b", "d"]) == 1
    assert result.winner_plan is not None
    progress = [
        e.evaluated for e in events.items if getattr(e, "type", "") == "exhaustive_progress"
    ]
    assert progress == list(range(1, 25))


@pytest.mark.asyncio
async def test_same_start_instant_fixed_stays_and_sequential_departures() -> None:
    result, _, _ = await _run(Routes())
    for cand in result.candidates:
        stops = _stops(cand.timeline)
        assert stops[0].arrive_at == T0  # every order starts AT its first destination
        assert {s.instance_id: s.stay_minutes for s in stops} == STAYS  # endpoints keep stays
        items = cand.timeline
        for prev, leg, nxt in zip(items[0::2], items[1::2], items[2::2], strict=False):
            assert isinstance(prev, KnownStop) and isinstance(leg, PlannedLeg)
            assert leg.depart_at == prev.arrive_at + timedelta(minutes=STAYS[prev.instance_id])
            assert isinstance(nxt, KnownStop) and nxt.arrive_at == leg.arrive_at
        last = stops[-1]
        assert cand.completion_at == last.arrive_at + timedelta(minutes=last.stay_minutes)
        assert cand.elapsed_seconds == int((cand.completion_at - T0).total_seconds())


# --- ranking -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_longer_geographic_order_can_win_through_earlier_completion() -> None:
    fast = {("B", "A"), ("A", "D"), ("D", "C")}  # long hops, one direction only

    def minutes(a: str, b: str, t: datetime) -> float:
        return 5 if (a, b) in fast else 60

    result, _, _ = await _run(Routes(minutes))
    winner = result.winner
    assert winner is not None and result.winner_basis == "completion"
    assert winner.order == ["b", "a", "d", "c"]
    shortest = min(c.distance_m for c in result.candidates)
    assert winner.distance_m > shortest
    later = [c for c in result.candidates if c.distance_m == shortest]
    assert all(c.completion_at > winner.completion_at for c in later)


@pytest.mark.asyncio
async def test_time_dependent_responses_change_the_winner() -> None:
    def minutes(a: str, b: str, t: datetime) -> float:
        if (a, b) == ("B", "D"):
            return 5 if t.hour < 10 else 90
        if (a, b) == ("C", "B"):
            return 5 if t.hour >= 12 else 90
        return 30

    zero = dict.fromkeys(STAYS, 0)
    early, _, _ = await _run(Routes(minutes), _req(stays=zero), departure=T0)
    late, _, _ = await _run(Routes(minutes), _req(stays=zero), departure=T0.replace(hour=13))

    def pairs(order: list[str]) -> set[tuple[str, str]]:
        return set(pairwise(order))

    assert early.winner and late.winner and early.winner.order != late.winner.order
    assert ("b", "d") in pairs(early.winner.order)
    assert ("c", "b") in pairs(late.winner.order)


def _ev(
    ids: str, completion_min: int, distance: float, original: bool = False
) -> exhaustive.Evaluation:
    order = tuple(VerifiedStop(i, i.upper(), i, None, 53.0, -6.0) for i in ids)
    return exhaustive.Evaluation(
        order=order,
        is_original=original,
        status="complete",
        timeline=[],
        distance_m=distance,
        routing_calls=3,
        completion_at=T0 + timedelta(minutes=completion_min),
    )


def test_ranking_completion_then_distance_then_original_then_instance_ids() -> None:
    rank = exhaustive.rank_complete_candidates
    ranked, basis = rank([_ev("abcd", 100, 1000), _ev("bacd", 90, 9000)])
    assert ranked[0].ids == tuple("bacd") and basis == "completion"
    ranked, basis = rank([_ev("abcd", 90, 5000), _ev("bacd", 90, 4000)])
    assert ranked[0].ids == tuple("bacd") and basis == "distance"
    ranked, basis = rank([_ev("dcba", 90, 4000), _ev("abcd", 90, 4000, original=True)])
    assert ranked[0].ids == tuple("abcd") and basis == "original"
    ranked, basis = rank([_ev("dcba", 90, 4000), _ev("bacd", 90, 4000)])
    assert ranked[0].ids == tuple("bacd") and basis == "instance_order"
    # Float noise below a millimetre is not a distance difference.
    ranked, basis = rank([_ev("dcba", 90, 4000.0000001), _ev("bacd", 90, 4000.0)])
    assert basis == "instance_order"


@pytest.mark.asyncio
async def test_equal_completion_prefers_shorter_path_then_original() -> None:
    same = Routes(lambda a, b, t: 30)
    result, _, _ = await _run(same)  # original ACBD is the monotone (shortest) path
    assert result.winner and result.winner.order == ["a", "c", "b", "d"]
    assert result.winner_basis == "original"  # DBCA has the same length
    result, _, _ = await _run(Routes(lambda a, b, t: 30), _req("CABD"))
    assert result.winner and result.winner.order == ["a", "c", "b", "d"]
    assert result.winner_basis == "instance_order"  # ACBD vs DBCA: instance IDs decide
    assert result.saving_seconds == 0  # equal completion: exact zero, not invented


# --- hours, failures, interruptions --------------------------------------------------


@pytest.mark.asyncio
async def test_closed_venue_warns_without_disqualifying(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline, _, _ = await _run(Routes())
    monkeypatch.setitem(PLACES, "A", _geo("A", LNG["A"], regular_hours_raw=_weekly(20, 22)))
    result, _, _ = await _run(Routes())
    assert result.status == "all_complete" and result.complete_orders == 24
    assert result.winner and baseline.winner and result.winner.order == baseline.winner.order
    assert any(w.affects_instance_id == "a" for w in result.hours_warnings)
    stop_a = next(s for s in _stops(result.winner.timeline) if s.instance_id == "a")
    assert stop_a.hours_status == "closed_on_arrival"


@pytest.mark.asyncio
async def test_failed_candidates_are_never_treated_as_complete() -> None:
    def fail(a: str, b: str, t: datetime, n: int) -> Exception | None:
        return NoRouteError(a, b) if (a, b) == ("A", "C") else None

    routes = Routes(fail=fail)
    result, _, _ = await _run(routes)
    failed = [c for c in result.candidates if c.status == "failed"]
    assert len(failed) == 6  # orders with A immediately followed by C
    assert all(("a", "c") in set(pairwise(c.order)) for c in failed)
    for c in failed:
        assert c.completion_at is None and c.elapsed_seconds is None
        assert c.failure_reason == "no_route"
        assert isinstance(c.timeline[-1], UnknownStop) or c.order[-1] == "c"
    assert result.status == "some_failed" and result.search_complete
    assert (
        result.message == "Earliest completion among 18 completed orders; 6 could not be evaluated."
    )
    assert result.winner and ("a", "c") not in set(pairwise(result.winner.order))
    assert result.original and result.original.status == "failed"
    assert result.saving_seconds is None  # no saving against an incomplete original
    assert result.winner_plan is not None
    assert len(routes.calls) == result.routing_calls < 72


@pytest.mark.asyncio
async def test_deadline_interrupts_and_never_claims_exhaustive_success() -> None:
    def fail(a: str, b: str, t: datetime, n: int) -> Exception | None:
        return DeadlineExceededError("time up") if n == 10 else None

    routes = Routes(fail=fail)
    result, _, _ = await _run(routes)
    assert result.status == "interrupted" and not result.search_complete
    assert result.interruption_reason == "deadline_exceeded"
    assert result.evaluated_orders == 3 and len(routes.calls) == 10
    assert result.message == "Search incomplete: evaluated 3 of 24 orders."
    assert result.winner is not None and result.winner_plan is None  # best so far, not acceptable
    assert result.candidates[-1].status == "interrupted"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (QuotaExceededError("budget"), "quota_exceeded"),
        (ProviderCapacityError("usage control unavailable"), "provider_capacity"),
        (ProviderTemporaryError("down"), "provider_temporary"),
    ],
)
async def test_provider_wide_failures_stop_the_search(exc: Exception, reason: str) -> None:
    routes = Routes(fail=lambda a, b, t, n: exc if n == 5 else None)
    result, _, _ = await _run(routes)
    assert len(routes.calls) == 5  # no further calls, no retries
    assert result.status == "interrupted" and result.interruption_reason == reason
    assert result.winner_plan is None


@pytest.mark.asyncio
async def test_cancellation_stops_further_calls() -> None:
    ctx = OperationContext(operation_id="op-x", input_revision=3)
    routes = Routes(hook=lambda n: ctx.cancel() if n == 4 else None)
    result, _, _ = await _run(routes, ctx=ctx)
    assert len(routes.calls) == 4
    assert result.status == "interrupted" and result.interruption_reason == "cancelled"


@pytest.mark.asyncio
async def test_saving_is_exact_seconds_against_the_original() -> None:
    def minutes(a: str, b: str, t: datetime) -> float:
        return _by_distance(a, b, t) + (ord(a) * 7 % 59) / 60  # leg-specific odd seconds

    result, _, _ = await _run(Routes(minutes), _req("ADCB"))
    assert result.original and result.winner
    assert result.original.completion_at and result.winner.completion_at
    expected = int((result.original.completion_at - result.winner.completion_at).total_seconds())
    assert result.saving_seconds == expected > 0
    assert expected % 60 != 0  # computed before any display rounding


# --- final walk through the real Routes parser ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("walk", [0, 300])
async def test_final_walk_and_final_stay_count_in_completion(
    monkeypatch: pytest.MonkeyPatch, walk: int
) -> None:
    mock = MockGoogleRoutes({}, default=(0, 600, walk))
    real = directions.fetch_leg

    async def via_mock(**kw: Any) -> directions.LegResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock.handler)) as client:
            return await real(**kw, client=client)

    monkeypatch.setattr(adapter_module.directions, "fetch_leg", via_mock)
    result, _, _ = await _run(GoogleRoutesAdapter())  # type: ignore[arg-type]
    assert len(mock.requests) == 72
    total_stays = sum(STAYS.values()) * 60
    for cand in result.candidates:
        # three legs of 10-minute rides plus the documented final walk, plus every stay
        assert cand.elapsed_seconds == total_stays + 3 * (600 + walk)


# --- endpoint --------------------------------------------------------------------------

TESTER = "198.51.100.23"


@pytest.fixture
def tester(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client on the configured tester allowlist (peer identity)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_whitelist_ips", TESTER)
    return TestClient(app, client=(TESTER, 4321))


def _body(order: str = "ACBD", **kw: Any) -> dict[str, Any]:
    body = _payload(
        [_stop(p.lower(), p, STAYS[p.lower()]) for p in order], date="2026-10-21", time_="09:00"
    )
    body.update(kw)
    return body


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["stops"].pop(),  # 3 stops
        lambda b: b["stops"][1]["selection"].update(place_id="A"),  # duplicate destination
        lambda b: b["stops"][2].pop("stay_minutes"),  # missing explicit stay
        lambda b: b.update(fixed_first=True),  # pins do not apply
    ],
)
def test_endpoint_rejects_invalid_experiment_requests(
    mutate: Callable[[dict[str, Any]], Any],
) -> None:
    body = _body()
    mutate(body)
    resp = TestClient(app).post("/api/v2/optimise-exhaustive/stream", json=body)
    assert resp.status_code == 422


def test_stream_reports_progress_and_terminal_result(
    monkeypatch: pytest.MonkeyPatch, tester: TestClient
) -> None:
    routes = Routes()
    seen: dict[str, float] = {}
    real_scope = plan_v2.DeadlineScope

    def scope(**kw: Any) -> DeadlineScope:
        seen["deadline"] = kw.get("deadline_seconds", 60.0)
        return real_scope(**kw)

    monkeypatch.setattr(plan_v2, "DeadlineScope", scope)
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: FakePlaces())
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    resp = tester.post("/api/v2/optimise-exhaustive/stream", json=_body())
    assert resp.status_code == 200
    events = [json.loads(line) for line in resp.text.splitlines()]
    assert events[0]["phases"] == ["verification", "exhaustive_search"]
    progress = [e["evaluated"] for e in events if e["type"] == "exhaustive_progress"]
    assert progress == list(range(1, 25))
    outcome = events[-1]["outcome"]
    assert outcome["outcome_type"] == "exhaustive"
    assert outcome["result"]["status"] == "all_complete"
    assert outcome["result"]["deadline_seconds"] == 240 and seen["deadline"] == 240
    assert len(routes.calls) == 72


def test_shares_the_comparison_rate_limit_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    client = TestClient(app)
    past = _body()
    past["departure"]["local_date"] = "2020-01-01"  # rejected before any provider call
    for _ in range(settings.max_requests_per_ip_per_minute):
        assert client.post("/api/v2/compare/stream", json=past).status_code == 422
    assert client.post("/api/v2/optimise-exhaustive/stream", json=past).status_code == 429


@pytest.mark.asyncio
async def test_disconnect_stops_the_search_mid_flight() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang(n: int) -> None:
        if n == 5:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    routes = Routes(hook=hang)
    disconnect = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    stream = plan_v2.PlanStream(
        _req(),
        departure_utc=T0,
        places=FakePlaces(),
        routes=routes,
        ctx=OperationContext(operation_id="op-x", input_revision=1),
        deadline=DeadlineScope(deadline_seconds=exhaustive.DEADLINE_SECONDS),
        receive=receive,
    )
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for chunk in stream.events():
            received.append(json.loads(chunk))

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 5)
    disconnect.set()
    await asyncio.wait_for(task, 5)
    await asyncio.wait_for(cancelled.wait(), 5)  # the in-flight call was cancelled
    assert len(routes.calls) == 5
    assert all(e["type"] != "terminal" for e in received)


# --- tester allowlist (experiment only; fails closed) ---------------------------------


class _NoProvider:
    """Any provider use is a test failure: rejection must happen first."""

    async def fetch_details(self, *a: Any, **kw: Any) -> Any:
        raise AssertionError("provider called")

    async def fetch_leg(self, **kw: Any) -> Any:
        raise AssertionError("provider called")


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: _NoProvider())
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: _NoProvider())


def _allow(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_whitelist_ips", value)


@pytest.mark.parametrize("allowlist", ["", " , ", "0.0.0.0/0,not-an-ip", "203.0.113.200"])
def test_experiment_fails_closed_for_non_testers(
    monkeypatch: pytest.MonkeyPatch, no_provider: None, allowlist: str
) -> None:
    _allow(monkeypatch, allowlist)
    client = TestClient(app, client=(TESTER, 4321))
    resp = client.post("/api/v2/optimise-exhaustive/stream", json=_body())
    assert resp.status_code == 403
    assert resp.json()["detail"]["error"] == "experiment_not_available"
    assert client.get("/api/v2/experiments").json() == {"exhaustive_four": False}


def test_rejection_precedes_departure_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow(monkeypatch, "")
    past = _body()
    past["departure"]["local_date"] = "2020-01-01"
    client = TestClient(app, client=(TESTER, 1))
    resp = client.post("/api/v2/optimise-exhaustive/stream", json=past)
    assert resp.status_code == 403  # not 422: the departure is never evaluated


def test_other_flows_are_not_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow(monkeypatch, "")
    past = _body()
    past["departure"]["local_date"] = "2020-01-01"
    client = TestClient(app, client=(TESTER, 1))
    assert client.post("/api/v2/compare/stream", json=past).status_code == 422  # reached validation
    assert client.post("/api/v2/plan", json=past).status_code == 422


def test_tester_by_peer_with_ipv6_normalisation(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow(monkeypatch, "2001:DB8:0::23")
    client = TestClient(app, client=("2001:db8::23", 1))
    assert client.get("/api/v2/experiments").json() == {"exhaustive_four": True}


@pytest.fixture
def railway(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "client_ip_source", "railway")
    monkeypatch.setattr(settings, "railway_environment_id", "env-1")
    monkeypatch.setattr(settings, "railway_tcp_proxy_domain", "")
    monkeypatch.setattr(settings, "trusted_proxy_ips", "")


EDGE_HEADERS = {"x-railway-edge": "railway/europe-west4", "x-railway-request-id": "r1"}
GLOBAL_TESTER = "93.184.216.34"  # Railway mode accepts only globally routable addresses


def test_tester_identified_by_verified_railway_edge_header(
    monkeypatch: pytest.MonkeyPatch, railway: None
) -> None:
    _allow(monkeypatch, GLOBAL_TESTER)
    client = TestClient(app, client=("10.250.0.7", 1))  # Railway internal peer
    ok = client.get("/api/v2/experiments", headers={"x-real-ip": GLOBAL_TESTER, **EDGE_HEADERS})
    assert ok.json() == {"exhaustive_four": True}


@pytest.mark.parametrize(
    "headers",
    [
        {"x-real-ip": GLOBAL_TESTER},  # forged: no edge markers
        {"x-forwarded-for": GLOBAL_TESTER, **EDGE_HEADERS},  # forwarded headers ignored
        {"x-real-ip": f"{GLOBAL_TESTER}, 1.1.1.1", **EDGE_HEADERS},  # malformed
    ],
)
def test_forged_identity_headers_never_grant_tester_access(
    monkeypatch: pytest.MonkeyPatch, railway: None, no_provider: None, headers: dict[str, str]
) -> None:
    _allow(monkeypatch, GLOBAL_TESTER)
    client = TestClient(app, client=("10.250.0.7", 1))
    assert client.get("/api/v2/experiments", headers=headers).json() == {"exhaustive_four": False}
    resp = client.post("/api/v2/optimise-exhaustive/stream", json=_body(), headers=headers)
    assert resp.status_code == 403
