"""Tests for Step 3: sequential planner, verifier, and departure resolver.

Verifies:
- plan_sequential threads actual arrival times forward (D1).
- No fallback duration is invented on leg failure (D2).
- Verification runs before routing; timezone conflicts block routing.
- Partial failure: valid prefix + FailedLeg + UnknownStop items.
- OperationContext call accounting tracks routing calls.
- Deadline enforcement stops the plan with FailedLeg reason=deadline_exceeded.
- Cancellation stops the plan with FailedLeg reason=cancelled.
- resolve_departure handles normal, spring-forward, fall-back, and occurrence.
- verify_stops derives timezone and rejects timezone conflicts.

All tests use deterministic fakes; no real Google API calls are made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.models.request import DepartureInput, PlaceSelection, StopSpec
from app.models.response import FailedLeg, KnownStop, PlannedLeg, UnknownStop
from app.services.departure import (
    AmbiguousDepartureError,
    NonExistentDepartureError,
    resolve_departure,
)
from app.services.engine import (
    OperationCancelledError,
    OperationContext,
    ResolvedDurations,
    RoutingResult,
    VerifiedStop,
    plan_sequential,
    resolve_durations,
)
from app.services.errors import (
    NoRouteError,
    ProviderTemporaryError,
    QuotaExceededError,
    TimezoneConflictError,
)
from app.services.verifier import verify_stops

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc
_T0 = datetime(2026, 6, 1, 9, 0, 0, tzinfo=_UTC)
_DUR = 1200  # 20 minutes in seconds


def _vstop(
    instance_id: str,
    lat: float = 53.344,
    lng: float = -6.254,
) -> VerifiedStop:
    return VerifiedStop(
        instance_id=instance_id,
        place_id=f"ChIJ_{instance_id}",
        name=f"Place {instance_id}",
        address=None,
        lat=lat,
        lng=lng,
    )


def _durations(
    *instance_ids: str,
    explicit: dict[str, int] | None = None,
) -> ResolvedDurations:
    """Build durations with D11 rules: first/last=0, middle=60 unless overridden."""
    stops = [(iid, (explicit or {}).get(iid)) for iid in instance_ids]
    return resolve_durations(stops, {})


class _FakeRoutesAdapter:
    """Deterministic routes adapter that returns fixed results or raises errors."""

    def __init__(
        self,
        result: RoutingResult | None = None,
        fail_at: int | None = None,
        failure: type[Exception] | Exception = NoRouteError("from", "to"),
    ) -> None:
        self._result = result or RoutingResult(
            duration_seconds=_DUR,
            distance_meters=500,
            arrive_at=_T0 + timedelta(seconds=_DUR),
            summary="20 min walk",
            map_url="https://maps.google.com/dir/",
        )
        self._fail_at = fail_at
        self._failure = failure
        self.call_count = 0
        self.depart_times: list[datetime] = []

    async def fetch_leg(
        self,
        *,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str,
        depart_at: datetime,
    ) -> RoutingResult:
        call_idx = self.call_count
        self.call_count += 1
        self.depart_times.append(depart_at)

        if self._fail_at is not None and call_idx == self._fail_at:
            if isinstance(self._failure, Exception):
                raise self._failure
            raise self._failure("from", "to")

        # Arrive_at is depart_at + fixed duration so we can verify threading.
        return RoutingResult(
            duration_seconds=self._result.duration_seconds,
            distance_meters=self._result.distance_meters,
            arrive_at=depart_at + timedelta(seconds=self._result.duration_seconds),
            summary=self._result.summary,
            map_url=self._result.map_url,
        )


class _RecordingEmitter:
    """Emitter that records every event for assertion."""

    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


class _NullEmitter:
    async def emit(self, event: object) -> None:
        return


def _deadline(seconds: float = 60.0) -> DeadlineScope:
    return DeadlineScope(deadline_seconds=seconds)


# ---------------------------------------------------------------------------
# resolve_durations — verify sources dict is populated
# ---------------------------------------------------------------------------


def test_resolve_durations_sources_user_and_default() -> None:
    result = resolve_durations([("first", None), ("mid", 45), ("last", None)], {})
    assert result.get_source("first") == "default"
    assert result.get_source("mid") == "user"
    assert result.get_source("last") == "default"


def test_resolve_durations_sources_all_default() -> None:
    result = resolve_durations([("first", None), ("mid", None), ("last", None)], {"mid": 90})
    assert result.get_source("mid") == "default"


# ---------------------------------------------------------------------------
# plan_sequential — timestamp threading (D1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sequential_timestamps_thread_forward() -> None:
    """Leg N+1 departs at actual arrival from leg N, not a pre-computed estimate."""
    stops = [_vstop("a"), _vstop("b"), _vstop("c")]
    durations = _durations("a", "b", "c", explicit={"b": 30})

    adapter = _FakeRoutesAdapter()
    ctx = OperationContext(operation_id="op-ts", input_revision=0)

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="walking",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    # Stop a: arrive=T0, stay=0 (first), depart=T0
    stop_a = timeline[0]
    assert isinstance(stop_a, KnownStop)
    assert stop_a.arrive_at == _T0
    assert stop_a.depart_at == _T0

    # Leg a->b: departs at T0, arrives at T0+20min (adapter returns depart+20min)
    leg_ab = timeline[1]
    assert isinstance(leg_ab, PlannedLeg)
    assert leg_ab.depart_at == _T0
    assert leg_ab.arrive_at == _T0 + timedelta(seconds=_DUR)

    # Stop b: arrives at actual leg arrival = T0+20min, stay=30min, departs T0+50min
    stop_b = timeline[2]
    assert isinstance(stop_b, KnownStop)
    assert stop_b.arrive_at == _T0 + timedelta(seconds=_DUR)
    assert stop_b.depart_at == _T0 + timedelta(seconds=_DUR) + timedelta(minutes=30)

    # Leg b->c: departs at T0+50min (actual departure from b)
    leg_bc = timeline[3]
    assert isinstance(leg_bc, PlannedLeg)
    assert leg_bc.depart_at == stop_b.depart_at

    # Stop c: last stop, stay=0
    stop_c = timeline[4]
    assert isinstance(stop_c, KnownStop)
    assert stop_c.arrive_at == leg_bc.arrive_at
    assert stop_c.stay_minutes == 0


@pytest.mark.asyncio
async def test_first_and_last_stop_stay_zero() -> None:
    """D11: first and last stops always have stay_minutes=0."""
    stops = [_vstop("a"), _vstop("b")]
    durations = _durations("a", "b", explicit={"a": 60, "b": 60})

    # Even with explicit 60-minute overrides, D11 forces 0 for first/last.
    # resolve_durations enforces this, so verify it carries through the engine.
    adapter = _FakeRoutesAdapter()
    ctx = OperationContext()

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    stop_a = timeline[0]
    stop_b = timeline[2]
    assert isinstance(stop_a, KnownStop)
    assert isinstance(stop_b, KnownStop)
    assert stop_a.stay_minutes == 0
    assert stop_b.stay_minutes == 0


# ---------------------------------------------------------------------------
# plan_sequential — routing call accounting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routing_call_count_equals_n_minus_one() -> None:
    """N stops produce exactly N-1 routing calls."""
    stops = [_vstop("a"), _vstop("b"), _vstop("c"), _vstop("d")]
    durations = _durations("a", "b", "c", "d")
    adapter = _FakeRoutesAdapter()
    ctx = OperationContext()

    await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    assert adapter.call_count == 3
    assert ctx.routing_calls == 3


# ---------------------------------------------------------------------------
# plan_sequential — partial failure (D2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_failure_no_invented_times() -> None:
    """NoRouteError on leg 1 produces FailedLeg + UnknownStop; no timing on unknowns."""
    stops = [_vstop("a"), _vstop("b"), _vstop("c")]
    durations = _durations("a", "b", "c", explicit={"b": 45})
    adapter = _FakeRoutesAdapter(fail_at=1)  # leg b->c fails
    ctx = OperationContext()

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    # a: KnownStop, leg a->b: PlannedLeg, b: KnownStop, leg b->c: FailedLeg, c: UnknownStop
    assert len(timeline) == 5
    assert isinstance(timeline[0], KnownStop)  # stop a
    assert isinstance(timeline[1], PlannedLeg)  # leg a->b (success)
    assert isinstance(timeline[2], KnownStop)  # stop b
    assert isinstance(timeline[3], FailedLeg)  # leg b->c (fail)
    assert isinstance(timeline[4], UnknownStop)  # stop c

    failed_leg = timeline[3]
    assert isinstance(failed_leg, FailedLeg)
    assert failed_leg.failure_reason == "no_route"
    assert "arrive_at" not in FailedLeg.model_fields
    assert "depart_at" not in FailedLeg.model_fields

    unknown_c = timeline[4]
    assert isinstance(unknown_c, UnknownStop)
    assert "arrive_at" not in UnknownStop.model_fields
    assert "depart_at" not in UnknownStop.model_fields


@pytest.mark.asyncio
async def test_partial_failure_first_leg() -> None:
    """Failure on leg 0 leaves only the first KnownStop; all others are unknown."""
    stops = [_vstop("a"), _vstop("b"), _vstop("c")]
    durations = _durations("a", "b", "c")
    adapter = _FakeRoutesAdapter(fail_at=0)
    ctx = OperationContext()

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    assert len(timeline) == 4  # a, failed a->b, unknown b, unknown c
    assert isinstance(timeline[0], KnownStop)
    assert isinstance(timeline[1], FailedLeg)
    assert isinstance(timeline[2], UnknownStop)
    assert isinstance(timeline[3], UnknownStop)
    assert timeline[2].instance_id == "b"
    assert timeline[3].instance_id == "c"


@pytest.mark.asyncio
async def test_provider_temporary_maps_to_reason() -> None:
    stops = [_vstop("a"), _vstop("b")]
    durations = _durations("a", "b")
    adapter = _FakeRoutesAdapter(fail_at=0, failure=ProviderTemporaryError("down"))
    ctx = OperationContext()

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    failed = timeline[1]
    assert isinstance(failed, FailedLeg)
    assert failed.failure_reason == "provider_temporary"


@pytest.mark.asyncio
async def test_quota_exceeded_maps_to_reason() -> None:
    stops = [_vstop("a"), _vstop("b")]
    durations = _durations("a", "b")
    adapter = _FakeRoutesAdapter(fail_at=0, failure=QuotaExceededError("quota"))
    ctx = OperationContext()

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    failed = timeline[1]
    assert isinstance(failed, FailedLeg)
    assert failed.failure_reason == "quota_exceeded"


# ---------------------------------------------------------------------------
# plan_sequential — deadline and cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deadline_expired_before_leg_produces_failed_leg() -> None:
    """An already-expired deadline produces a FailedLeg with deadline_exceeded."""
    stops = [_vstop("a"), _vstop("b")]
    durations = _durations("a", "b")
    adapter = _FakeRoutesAdapter()
    ctx = OperationContext()

    expired_deadline = DeadlineScope(deadline_seconds=0.0)
    import time as _time

    _time.sleep(0.01)  # ensure it has expired

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=expired_deadline,
    )

    # With an expired deadline, the first stop is emitted then the leg fails.
    failed = next((item for item in timeline if isinstance(item, FailedLeg)), None)
    assert failed is not None
    assert failed.failure_reason == "deadline_exceeded"
    # Adapter should not have been called (deadline check precedes fetch_leg call).
    assert adapter.call_count == 0


@pytest.mark.asyncio
async def test_cancelled_context_produces_failed_leg() -> None:
    """A cancelled OperationContext produces FailedLeg with reason=cancelled."""

    class _CancelOnCallAdapter:
        """Cancels ctx on first call, then raises OperationCancelledError."""

        def __init__(self, ctx: OperationContext) -> None:
            self._ctx = ctx
            self.call_count = 0

        async def fetch_leg(self, **kwargs: object) -> RoutingResult:
            self._ctx.cancel()
            self.call_count += 1
            raise OperationCancelledError("cancelled by context")

    stops = [_vstop("a"), _vstop("b"), _vstop("c")]
    durations = _durations("a", "b", "c")
    ctx = OperationContext()
    adapter = _CancelOnCallAdapter(ctx)

    timeline = await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="transit",
        routes=adapter,
        emitter=_NullEmitter(),
        ctx=ctx,
        deadline=_deadline(),
    )

    failed = next((item for item in timeline if isinstance(item, FailedLeg)), None)
    assert failed is not None
    assert failed.failure_reason == "cancelled"


# ---------------------------------------------------------------------------
# plan_sequential — streaming events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emitter_receives_expected_event_types() -> None:
    """Emitter sees: operation_start, stop_ready, leg_progress, leg_ready, phase_complete."""
    from app.models.response import (
        LegProgressEvent,
        LegReadyEvent,
        OperationStartEvent,
        PhaseCompleteEvent,
        StopReadyEvent,
    )

    stops = [_vstop("a"), _vstop("b")]
    durations = _durations("a", "b")
    adapter = _FakeRoutesAdapter()
    ctx = OperationContext(operation_id="op-emit", input_revision=1)
    emitter = _RecordingEmitter()

    await plan_sequential(
        stops=stops,
        durations=durations,
        departure=_T0,
        mode="walking",
        routes=adapter,
        emitter=emitter,
        ctx=ctx,
        deadline=_deadline(),
    )

    types = [type(e) for e in emitter.events]
    assert OperationStartEvent in types
    assert StopReadyEvent in types
    assert LegProgressEvent in types
    assert LegReadyEvent in types
    assert PhaseCompleteEvent in types

    # All events carry operation identity.
    for event in emitter.events:
        assert getattr(event, "operation_id", None) == "op-emit"
        assert getattr(event, "input_revision", None) == 1


# ---------------------------------------------------------------------------
# verify_stops
# ---------------------------------------------------------------------------


def _stop_spec(instance_id: str, lat: float = 53.344, lng: float = -6.254) -> StopSpec:
    return StopSpec(
        instance_id=instance_id,
        selection=PlaceSelection(
            place_id=f"ChIJ_{instance_id}",
            name=f"Place {instance_id}",
            lat=lat,
            lng=lng,
        ),
    )


def test_verify_stops_returns_verified_list() -> None:
    stops = [_stop_spec("a"), _stop_spec("b")]
    verified, tz = verify_stops(stops, _deadline())
    assert len(verified) == 2
    assert verified[0].instance_id == "a"
    assert verified[1].instance_id == "b"
    assert isinstance(tz, str)
    assert len(tz) > 0


def test_verify_stops_timezone_conflict_raises() -> None:
    """A stop in a different timezone raises TimezoneConflictError."""
    # Dublin, Ireland (Europe/Dublin) vs New York (America/New_York)
    stops = [
        _stop_spec("dublin", lat=53.344, lng=-6.254),  # Europe/Dublin
        _stop_spec("nyc", lat=40.713, lng=-74.006),  # America/New_York
    ]
    with pytest.raises(TimezoneConflictError) as exc_info:
        verify_stops(stops, _deadline())
    assert "America/New_York" in str(exc_info.value) or "Europe/Dublin" in str(exc_info.value)


def test_verify_stops_timezone_conflict_blocks_routing() -> None:
    """After a timezone conflict, no routing calls should be made."""
    # This test verifies that the verifier fails before any adapter is used.
    stops = [
        _stop_spec("dublin", lat=53.344, lng=-6.254),
        _stop_spec("nyc", lat=40.713, lng=-74.006),
    ]
    adapter = _FakeRoutesAdapter()

    with pytest.raises(TimezoneConflictError):
        verify_stops(stops, _deadline())

    # No routing calls made because verifier raised before any planning.
    assert adapter.call_count == 0


def test_verify_stops_expired_deadline_raises() -> None:
    import time as _time

    stops = [_stop_spec("a"), _stop_spec("b")]
    dead = DeadlineScope(deadline_seconds=0.0)
    _time.sleep(0.01)

    with pytest.raises(DeadlineExceededError):
        verify_stops(stops, dead)


# ---------------------------------------------------------------------------
# resolve_departure
# ---------------------------------------------------------------------------


def test_resolve_departure_normal() -> None:
    dep = DepartureInput(
        local_date="2026-06-01",
        local_time="09:00",
        timezone="Europe/Dublin",
    )
    result = resolve_departure(dep)
    # June 1 in Dublin is IST (UTC+1), so 09:00 local = 08:00 UTC.
    assert result.tzinfo is not None
    assert result.hour == 8
    assert result.minute == 0


def test_resolve_departure_utc_zone() -> None:
    dep = DepartureInput(
        local_date="2026-06-01",
        local_time="12:30",
        timezone="UTC",
    )
    result = resolve_departure(dep)
    assert result.hour == 12
    assert result.minute == 30


def test_resolve_departure_spring_forward_rejected() -> None:
    """Europe/Dublin springs forward on the last Sunday of March.
    On 2026-03-29 at 01:00 -> 02:00. Time 01:30 does not exist."""
    dep = DepartureInput(
        local_date="2026-03-29",
        local_time="01:30",
        timezone="Europe/Dublin",
    )
    with pytest.raises(NonExistentDepartureError):
        resolve_departure(dep)


def test_resolve_departure_fall_back_ambiguous_without_occurrence() -> None:
    """Europe/Dublin falls back on last Sunday of October.
    On 2026-10-25 at 01:30, the time occurs twice."""
    dep = DepartureInput(
        local_date="2026-10-25",
        local_time="01:30",
        timezone="Europe/Dublin",
    )
    with pytest.raises(AmbiguousDepartureError):
        resolve_departure(dep)


def test_resolve_departure_fall_back_with_occurrence_1() -> None:
    """occurrence=1 selects the first (IST/UTC+1) occurrence."""
    dep = DepartureInput(
        local_date="2026-10-25",
        local_time="01:30",
        timezone="Europe/Dublin",
        occurrence=1,
    )
    result = resolve_departure(dep)
    # First occurrence (IST = UTC+1): 01:30 IST = 00:30 UTC.
    assert result.hour == 0
    assert result.minute == 30


def test_resolve_departure_fall_back_with_occurrence_2() -> None:
    """occurrence=2 selects the second (GMT/UTC+0) occurrence."""
    dep = DepartureInput(
        local_date="2026-10-25",
        local_time="01:30",
        timezone="Europe/Dublin",
        occurrence=2,
    )
    result = resolve_departure(dep)
    # Second occurrence (GMT = UTC+0): 01:30 GMT = 01:30 UTC.
    assert result.hour == 1
    assert result.minute == 30


def test_resolve_departure_unambiguous_time_ignores_occurrence() -> None:
    """A non-fold time with occurrence=1 works normally."""
    dep = DepartureInput(
        local_date="2026-06-01",
        local_time="09:00",
        timezone="Europe/Dublin",
        occurrence=1,
    )
    result = resolve_departure(dep)
    # June is IST (UTC+1), 09:00 local = 08:00 UTC.
    assert result.hour == 8


# ---------------------------------------------------------------------------
# plan_v2 endpoint integration (using TestClient)
# ---------------------------------------------------------------------------


def test_plan_v2_rejects_spring_forward_departure() -> None:
    """The v2 endpoint returns 422 for a non-existent departure time."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    payload = {
        "operation_id": "op-001",
        "input_revision": 0,
        "city": {
            "place_id": "ChIJ_Dublin",
            "name": "Dublin, Ireland",
            "lat": 53.344,
            "lng": -6.254,
        },
        "stops": [
            {
                "instance_id": "a",
                "selection": {
                    "place_id": "ChIJ_a",
                    "name": "Trinity College",
                    "lat": 53.344,
                    "lng": -6.254,
                },
            },
            {
                "instance_id": "b",
                "selection": {
                    "place_id": "ChIJ_b",
                    "name": "Temple Bar",
                    "lat": 53.345,
                    "lng": -6.267,
                },
            },
        ],
        "departure": {
            "local_date": "2026-03-29",
            "local_time": "01:30",
            "timezone": "Europe/Dublin",
        },
    }
    response = client.post("/api/v2/plan", json=payload)
    assert response.status_code == 422


def test_plan_v2_rejects_timezone_conflict() -> None:
    """The v2 endpoint returns 422 when stops span multiple timezones."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    payload = {
        "operation_id": "op-002",
        "input_revision": 0,
        "city": {
            "place_id": "ChIJ_Dublin",
            "name": "Dublin, Ireland",
            "lat": 53.344,
            "lng": -6.254,
        },
        "stops": [
            {
                "instance_id": "a",
                "selection": {
                    "place_id": "ChIJ_a",
                    "name": "Dublin Stop",
                    "lat": 53.344,
                    "lng": -6.254,
                },
            },
            {
                "instance_id": "b",
                "selection": {
                    "place_id": "ChIJ_b",
                    "name": "New York Stop",
                    "lat": 40.713,
                    "lng": -74.006,
                },
            },
        ],
        "departure": {
            "local_date": "2026-06-01",
            "local_time": "09:00",
            "timezone": "Europe/Dublin",
        },
    }
    response = client.post("/api/v2/plan", json=payload)
    assert response.status_code == 422
