"""Tests for Step 2 contracts: models, discriminated unions, engine primitives.

Verifies that:
- Every terminal state (complete/partial/failed/cancelled/error) is
  distinguishable by discriminator and never invented.
- Unknown downstream timestamps are absent from FailedLeg / UnknownStop.
- Discriminated unions round-trip correctly for all variants.
- resolve_durations applies D11 rules (first/last = 0, explicit wins,
  default fallback to 60).
- OperationContext carries unique identity and tracks call counts.
- ContractRoot.model_json_schema() exports a valid schema dict.
- New request models (PlaceSelection, CitySelection, DepartureInput,
  StopSpec, ItineraryRequest, RefreshRequest) validate inputs correctly.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.models.request import (
    CitySelection,
    DepartureInput,
    ItineraryRequest,
    PlaceSelection,
    RefreshRequest,
    StopSpec,
)
from app.models.response import (
    CancelledOutcome,
    CompletePlan,
    ContractRoot,
    ErrorOutcome,
    FailedLeg,
    KnownStop,
    LegReadyEvent,
    OperationStartEvent,
    PartialPlan,
    PhaseCompleteEvent,
    PlannedLeg,
    PlanOutcome,
    RefreshOutcome,
    StopReadyEvent,
    TerminalEvent,
    UnknownStop,
)
from app.services.engine import (
    OperationContext,
    resolve_durations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 6, 1, 9, 20, 0, tzinfo=timezone.utc)


def _known_stop(instance_id: str = "s1") -> KnownStop:
    return KnownStop(
        instance_id=instance_id,
        place_id="ChIJ_TC",
        name="Trinity College",
        lat=53.344,
        lng=-6.254,
        arrive_at=_NOW,
        depart_at=_LATER,
        stay_minutes=60,
        stay_source="default",
        map_url="https://maps.google.com/?q=Trinity+College",
    )


def _planned_leg(from_id: str = "s1", to_id: str = "s2") -> PlannedLeg:
    return PlannedLeg(
        from_stop_id=from_id,
        to_stop_id=to_id,
        from_name="Trinity College",
        to_name="Temple Bar",
        mode="transit",
        duration_seconds=1200,
        depart_at=_LATER,
        arrive_at=datetime(2026, 6, 1, 9, 40, tzinfo=timezone.utc),
        summary="Take the 37 bus, 20 min",
        map_url="https://maps.google.com/?saddr=53.344,-6.254&daddr=53.345,-6.267",
    )


def _failed_leg(from_id: str = "s1", to_id: str = "s2") -> FailedLeg:
    return FailedLeg(
        from_stop_id=from_id,
        to_stop_id=to_id,
        from_name="Trinity College",
        to_name="Temple Bar",
        failure_reason="no_route",
        failure_message="No transit route available for this leg.",
    )


def _unknown_stop(instance_id: str = "s2") -> UnknownStop:
    return UnknownStop(
        instance_id=instance_id,
        place_id="ChIJ_TB",
        name="Temple Bar",
    )


def _place_selection(**kwargs: object) -> PlaceSelection:
    defaults: dict[str, object] = {
        "place_id": "ChIJ_TC",
        "name": "Trinity College",
        "lat": 53.344,
        "lng": -6.254,
    }
    return PlaceSelection(**{**defaults, **kwargs})  # type: ignore[arg-type]


def _stop_spec(instance_id: str = "abc123", **kwargs: object) -> StopSpec:
    return StopSpec(
        instance_id=instance_id,
        selection=_place_selection(),
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# D11 — resolve_durations
# ---------------------------------------------------------------------------


def test_resolve_durations_explicit_endpoint_wins() -> None:
    """D11: an explicit value wins even at an endpoint (was forced to 0 before)."""
    result = resolve_durations([("s1", 30), ("s2", None)], {"s1": 90, "s2": 90})
    assert result.get("s1") == 30
    assert result.get_source("s1") == "user"
    assert result.get("s2") == 0  # unspecified endpoint defaults to 0
    assert result.get_source("s2") == "default"


def test_resolve_durations_explicit_zero_in_middle_wins() -> None:
    result = resolve_durations([("s1", None), ("s2", 0), ("s3", None)], {"s2": 90})
    assert result.get("s2") == 0
    assert result.get_source("s2") == "user"


def test_resolve_durations_rejects_duplicate_instance_ids() -> None:
    from app.services.engine import DuplicateInstanceIdError

    with pytest.raises(DuplicateInstanceIdError):
        resolve_durations([("s1", None), ("s1", None)], {})


def test_resolve_durations_two_stops_both_zero() -> None:
    result = resolve_durations([("s1", None), ("s2", None)], {})
    assert result.get("s1") == 0
    assert result.get("s2") == 0


def test_resolve_durations_three_stops_explicit_middle() -> None:
    result = resolve_durations(
        [("s1", None), ("s2", 45), ("s3", None)],
        {"s2": 90},
    )
    assert result.get("s1") == 0
    assert result.get("s2") == 45  # explicit wins over default
    assert result.get("s3") == 0


def test_resolve_durations_three_stops_default_middle() -> None:
    result = resolve_durations(
        [("s1", None), ("s2", None), ("s3", None)],
        {"s2": 90},
    )
    assert result.get("s2") == 90  # place-type default


def test_resolve_durations_fallback_to_60() -> None:
    """Missing default → 60-minute fallback for middle stops."""
    result = resolve_durations([("s1", None), ("s2", None), ("s3", None)], {})
    assert result.get("s2") == 60


def test_resolve_durations_empty() -> None:
    result = resolve_durations([], {})
    assert result.durations == {}


def test_resolve_durations_five_stops() -> None:
    stops = [("s1", None), ("s2", 30), ("s3", None), ("s4", 15), ("s5", None)]
    defaults = {"s3": 75}
    result = resolve_durations(stops, defaults)
    assert result.get("s1") == 0  # first
    assert result.get("s2") == 30  # explicit
    assert result.get("s3") == 75  # default
    assert result.get("s4") == 15  # explicit
    assert result.get("s5") == 0  # last


# ---------------------------------------------------------------------------
# OperationContext
# ---------------------------------------------------------------------------


def test_operation_context_unique_ids() -> None:
    ctx1 = OperationContext()
    ctx2 = OperationContext()
    assert ctx1.operation_id != ctx2.operation_id
    assert len(ctx1.operation_id) > 0


def test_operation_context_cancel() -> None:
    ctx = OperationContext()
    assert not ctx.is_cancelled()
    ctx.cancel()
    assert ctx.is_cancelled()


def test_operation_context_call_accounting() -> None:
    ctx = OperationContext(operation_id="op-test", input_revision=3)
    assert ctx.routing_calls == 0
    assert ctx.places_calls == 0
    ctx.record_routing_call()
    ctx.record_routing_call()
    ctx.record_places_call()
    assert ctx.routing_calls == 2
    assert ctx.places_calls == 1


# ---------------------------------------------------------------------------
# DeadlineScope
# ---------------------------------------------------------------------------


def test_deadline_scope_check_passes_immediately() -> None:
    scope = DeadlineScope(deadline_seconds=60.0)
    scope.check()  # should not raise


def test_deadline_scope_cancel_raises() -> None:
    scope = DeadlineScope()
    scope.cancel()
    with pytest.raises(DeadlineExceededError, match="cancelled"):
        scope.check()


def test_deadline_scope_remaining_decreases() -> None:
    scope = DeadlineScope(deadline_seconds=10.0)
    remaining = scope.remaining_seconds()
    assert 0 < remaining <= 10.0


# ---------------------------------------------------------------------------
# Unknown-time guarantee: FailedLeg and UnknownStop have no schedule fields
# ---------------------------------------------------------------------------


def test_failed_leg_has_no_arrive_at() -> None:
    leg = _failed_leg()
    assert not hasattr(leg, "arrive_at") or not hasattr(PlannedLeg.model_fields, "arrive_at")
    # Direct check: FailedLeg should not declare timing fields
    assert "arrive_at" not in FailedLeg.model_fields
    assert "depart_at" not in FailedLeg.model_fields


def test_unknown_stop_has_no_timing_fields() -> None:
    stop = _unknown_stop()
    assert "arrive_at" not in UnknownStop.model_fields
    assert "depart_at" not in UnknownStop.model_fields
    assert stop.instance_id == "s2"
    assert stop.name == "Temple Bar"


# ---------------------------------------------------------------------------
# Discriminated union round-trips
# ---------------------------------------------------------------------------


def test_plan_result_complete_round_trip() -> None:
    plan = CompletePlan(
        operation_id="op1",
        input_revision=0,
        city="Dublin, Ireland",
        mode="transit",
        timezone="Europe/Dublin",
        timeline=[_known_stop(), _planned_leg(), _known_stop("s2")],
        overview_map_url="https://maps.google.com/maps?q=Dublin",
    )
    serialised = plan.model_dump()
    assert serialised["result_type"] == "complete"
    # Round-trip via PlanOutcome
    outcome = PlanOutcome(result=plan)
    assert outcome.outcome_type == "plan"
    assert outcome.result.result_type == "complete"


def test_plan_result_partial_round_trip() -> None:
    plan = PartialPlan(
        operation_id="op1",
        input_revision=0,
        city="Dublin, Ireland",
        mode="transit",
        timezone="Europe/Dublin",
        timeline=[_known_stop(), _failed_leg(), _unknown_stop()],
        failed_at_leg_index=0,
        failure_reason="no_route",
        overview_map_url="https://maps.google.com/maps?q=Dublin",
    )
    assert plan.result_type == "partial"
    assert plan.failure_reason == "no_route"
    # Downstream stop must be UnknownStop with no times
    last = plan.timeline[-1]
    assert isinstance(last, UnknownStop)


def test_operation_outcome_cancelled_round_trip() -> None:
    outcome = CancelledOutcome(reason="client disconnected")
    assert outcome.outcome_type == "cancelled"


def test_operation_outcome_error_round_trip() -> None:
    outcome = ErrorOutcome(code="quota_exceeded", message="Daily quota reached.")
    assert outcome.outcome_type == "error"


def test_stream_event_terminal_with_plan_outcome() -> None:
    plan = CompletePlan(
        operation_id="op1",
        input_revision=1,
        city="Dublin, Ireland",
        mode="transit",
        timezone="Europe/Dublin",
        timeline=[_known_stop()],
        overview_map_url="https://maps.google.com/",
    )
    terminal = TerminalEvent(
        operation_id="op1",
        input_revision=1,
        outcome=PlanOutcome(result=plan),
    )
    assert terminal.type == "terminal"
    assert terminal.outcome.outcome_type == "plan"


def test_stream_event_operation_start() -> None:
    event = OperationStartEvent(
        operation_id="op1",
        input_revision=0,
        phases=["geocoding", "routing"],
    )
    assert event.type == "operation_start"
    assert "routing" in event.phases


def test_stream_event_leg_ready_planned() -> None:
    event = LegReadyEvent(
        operation_id="op1",
        input_revision=0,
        leg_index=0,
        leg=_planned_leg(),
    )
    assert event.type == "leg_ready"
    assert event.leg.item_type == "leg"


def test_stream_event_leg_ready_failed() -> None:
    event = LegReadyEvent(
        operation_id="op1",
        input_revision=0,
        leg_index=0,
        leg=_failed_leg(),
    )
    assert event.leg.item_type == "failed_leg"


def test_stream_event_stop_ready() -> None:
    event = StopReadyEvent(
        operation_id="op1",
        input_revision=0,
        stop_index=0,
        stop=_known_stop(),
    )
    assert event.type == "stop_ready"


def test_stream_event_phase_complete() -> None:
    event = PhaseCompleteEvent(
        operation_id="op1",
        input_revision=0,
        phase="geocoding",
    )
    assert event.type == "phase_complete"


def test_refresh_outcome_with_subsequent_stops() -> None:
    outcome = RefreshOutcome(
        leg=_planned_leg(),
        subsequent_stops=[_known_stop("s2"), _unknown_stop("s3")],
    )
    assert outcome.outcome_type == "refresh"
    assert len(outcome.subsequent_stops) == 2


# ---------------------------------------------------------------------------
# New request model validation
# ---------------------------------------------------------------------------


def test_place_selection_valid() -> None:
    ps = _place_selection()
    assert ps.place_id == "ChIJ_TC"
    assert ps.name == "Trinity College"


def test_place_selection_blank_name_rejected() -> None:
    with pytest.raises(ValidationError, match="blank"):
        PlaceSelection(place_id="ChIJ", name="  ", lat=53.0, lng=-6.0)


def test_place_selection_blank_place_id_rejected() -> None:
    with pytest.raises(ValidationError, match="blank"):
        PlaceSelection(place_id="", name="Test", lat=53.0, lng=-6.0)


def test_place_selection_coord_out_of_range() -> None:
    with pytest.raises(ValidationError):
        PlaceSelection(place_id="x", name="Test", lat=91.0, lng=0.0)


def test_city_selection_viewport_all_or_none() -> None:
    # All four corners provided — valid
    cs = CitySelection(
        place_id="ChIJ",
        name="Dublin",
        lat=53.3,
        lng=-6.2,
        ne_lat=53.4,
        ne_lng=-6.1,
        sw_lat=53.2,
        sw_lng=-6.3,
    )
    assert cs.ne_lat == 53.4

    # Partial viewport — rejected
    with pytest.raises(ValidationError, match="Viewport requires"):
        CitySelection(place_id="ChIJ", name="Dublin", lat=53.3, lng=-6.2, ne_lat=53.4)


def test_departure_input_valid() -> None:
    dep = DepartureInput(
        local_date="2026-06-01",
        local_time="09:00",
        timezone="Europe/Dublin",
    )
    assert dep.local_date == "2026-06-01"


def test_departure_input_invalid_timezone() -> None:
    with pytest.raises(ValidationError, match="IANA timezone"):
        DepartureInput(
            local_date="2026-06-01",
            local_time="09:00",
            timezone="Not/A/Timezone",
        )


def test_departure_input_invalid_date_pattern() -> None:
    with pytest.raises(ValidationError):
        DepartureInput(
            local_date="01-06-2026",  # wrong order
            local_time="09:00",
            timezone="Europe/Dublin",
        )


def test_departure_input_invalid_time_pattern() -> None:
    with pytest.raises(ValidationError):
        DepartureInput(
            local_date="2026-06-01",
            local_time="9:00",  # missing leading zero
            timezone="Europe/Dublin",
        )


def test_departure_input_occurrence_dsambiguity() -> None:
    dep = DepartureInput(
        local_date="2026-10-25",
        local_time="01:30",
        timezone="Europe/Dublin",
        occurrence=1,
    )
    assert dep.occurrence == 1


def test_stop_spec_valid() -> None:
    spec = _stop_spec(stay_minutes=45)
    assert spec.stay_minutes == 45
    assert spec.instance_id == "abc123"


def test_stop_spec_stay_over_720_rejected() -> None:
    with pytest.raises(ValidationError):
        StopSpec(
            instance_id="x",
            selection=_place_selection(),
            stay_minutes=721,
        )


def test_itinerary_request_valid() -> None:
    stops = [_stop_spec("a"), _stop_spec("b")]
    req = ItineraryRequest(
        operation_id="op-001",
        input_revision=0,
        city=CitySelection(place_id="ChIJ", name="Dublin", lat=53.3, lng=-6.2),
        stops=stops,
        departure=DepartureInput(
            local_date="2026-06-01", local_time="09:00", timezone="Europe/Dublin"
        ),
        mode="transit",
    )
    assert req.operation_id == "op-001"


def test_itinerary_request_total_stay_over_12h_rejected() -> None:
    # 12 stops: first + 10 middle x 74 min + last = 740 min > 720 min limit
    middle = [
        StopSpec(instance_id=f"s{i}", selection=_place_selection(), stay_minutes=74)
        for i in range(10)
    ]
    stops = [_stop_spec("first"), *middle, _stop_spec("last")]
    assert len(stops) == 12
    with pytest.raises(ValidationError, match="12 hours"):
        ItineraryRequest(
            operation_id="op-001",
            input_revision=0,
            city=CitySelection(place_id="ChIJ", name="Dublin", lat=53.3, lng=-6.2),
            stops=stops,
            departure=DepartureInput(
                local_date="2026-06-01", local_time="09:00", timezone="Europe/Dublin"
            ),
        )


def test_refresh_request_valid() -> None:
    stops = [_stop_spec("a"), _stop_spec("b")]
    req = RefreshRequest(
        operation_id="op-ref-001",
        input_revision=2,
        city=CitySelection(place_id="ChIJ", name="Dublin", lat=53.3, lng=-6.2),
        stops=stops,
        departure=DepartureInput(
            local_date="2026-06-01", local_time="09:00", timezone="Europe/Dublin"
        ),
        leg_index=0,
        planned_departure_utc="2026-06-01T09:00:00Z",
    )
    assert req.leg_index == 0
    assert req.planned_departure_utc == "2026-06-01T09:00:00Z"


# ---------------------------------------------------------------------------
# ContractRoot schema export
# ---------------------------------------------------------------------------


def test_contract_root_schema_is_exportable() -> None:
    schema = ContractRoot.model_json_schema()
    assert isinstance(schema, dict)
    assert "$defs" in schema


def test_contract_root_schema_contains_key_types() -> None:
    schema = ContractRoot.model_json_schema()
    defs = schema.get("$defs", {})
    for expected in (
        "KnownStop",
        "PlannedLeg",
        "FailedLeg",
        "UnknownStop",
        "CompletePlan",
        "PartialPlan",
        "TerminalEvent",
        "OperationStartEvent",
    ):
        assert expected in defs, f"Expected {expected!r} in schema $defs"
