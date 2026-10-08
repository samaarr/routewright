"""POST /api/v2/plan and /api/v2/plan/stream -- verified sequential planning.

Both endpoints run the same orchestration (``execute_plan``):

1. Departure syntax, calendar validity, clock-change handling and supported
   range — no provider calls (D14, D29). Failures are HTTP 422 before any
   response body or stream starts.
2. Verification phase: Place Details for the city, departure-zone match, then
   stops (D13, D37, D40, D41, D45). Any failure makes ZERO routing calls.
3. Fixed stay durations from the original order and verified place types (D11).
4. Routing phase: each leg departs at the previous stop's actual arrival plus
   its fixed stay; a failed leg keeps the valid prefix and leaves the rest
   unknown (D1, D2). Known stops get opening-hours assessment (D24, D42, D43);
   every verified stop gets an outside-area check against the city viewport
   (D25, D44).

One 60-second DeadlineScope starts when the request handler starts and bounds
verification, admission waits and every in-flight provider await (D19, D23).

Streaming transport (/plan/stream): newline-delimited JSON (one StreamEvent
per line, ``application/x-ndjson``) over the same POST — no jobs, polling or
retries. Events: operation_start → phase_start/phase_complete (verification,
routing) → stop_ready / leg_progress / leg_ready → exactly one terminal event
(complete or partial plan, timeout, error). A client cancels by aborting the
request; the server detects the disconnect, cancels the producer task (which
cancels in-flight provider calls and releases admission slots) and makes no
further calls. Calls already sent remain counted. Errors before the response
starts are ordinary HTTP errors; after headers are sent they are typed
terminal events.

Provider calls per plan: 1 city lookup + 1 per distinct stop place, then at
most N-1 routing calls; all through the shared budget and accounting seam.
The legacy /api/plan endpoint is unchanged and stays available for callers.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NoReturn
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.types import Message

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.core.limiter import OPTIMISE_LIMITS, PLAN_LIMITS, REFRESH_LIMITS, limiter, request_cost
from app.core.opmetrics import OperationMetrics, OperationType
from app.models.request import (
    ComparisonRequest,
    ExhaustiveRequest,
    ItineraryRequest,
    RefreshRequest,
)
from app.models.response import (
    CandidateEvaluation,
    ComparisonOutcome,
    ComparisonResult,
    CompletePlan,
    ErrorDetails,
    ErrorOutcome,
    ExhaustiveOutcome,
    ExhaustiveProgressEvent,
    ExhaustiveResult,
    FailedLeg,
    KnownStop,
    OperationOutcome,
    OperationStartEvent,
    PartialPlan,
    PhaseCompleteEvent,
    PhaseName,
    PhaseStartEvent,
    PlannedLeg,
    PlanOutcome,
    PlanResult,
    RefreshComplete,
    RefreshOutcome,
    RefreshPartial,
    RefreshResult,
    TerminalEvent,
    TimeoutOutcome,
    UnknownStop,
    Warning,
    WarningSeverity,
)
from app.services import exhaustive
from app.services.adapter import GooglePlacesAdapter, GoogleRoutesAdapter
from app.services.area import (
    AREA_UNAVAILABLE_MESSAGE,
    OUTSIDE_AREA_MESSAGE,
    area_status,
)
from app.services.comparison import (
    CandidateIntegrityError,
    RoutingBudget,
    decide,
    generate_candidate,
    is_complete,
    path_km,
)
from app.services.departure import (
    DepartureError,
    PlannedDepartureError,
    resolve_departure,
    unsupported_departure_reason,
)
from app.services.engine import (
    DuplicateInstanceIdError,
    OperationCancelledError,
    OperationContext,
    PlacesAdapter,
    ProgressEmitter,
    RoutesAdapter,
    VerifiedStop,
    place_type_defaults,
    plan_sequential,
    refresh_suffix,
    resolve_durations,
)
from app.services.errors import (
    PlaceVerificationError,
    ProviderCapacityError,
    ProviderTemporaryError,
    QuotaExceededError,
    TimezoneConflictError,
    TimezoneUnresolvedError,
    UsageControlUnavailableError,
)
from app.services.hours import hours_eligibility
from app.services.verifier import VerifiedItinerary, verify_itinerary

log = logging.getLogger("routewright.plan_v2")

router = APIRouter(prefix="/api/v2", tags=["plan_v2"])

NDJSON_MEDIA_TYPE = "application/x-ndjson"
# A full 12-stop plan emits ~45 events; the bound only matters if the client
# stops reading, in which case the producer blocks instead of growing memory.
MAX_QUEUED_EVENTS = 64
# Extra time the stream waits for the producer's own terminal event after the
# operation deadline before synthesising a timeout terminal itself.
TERMINAL_GRACE_SECONDS = 2.0
# Both v2 planning endpoints share one per-IP counter (existing plan limits);
# refresh has its own allowance with the existing refresh limits (D21).
_PLAN_V2_SCOPE = "plan-v2"
_REFRESH_V2_SCOPE = "refresh-v2"
# Comparisons use the existing optimise limits with their own allowance.
_COMPARE_V2_SCOPE = "compare-v2"


class _NullEmitter:
    async def emit(self, event: object) -> None:
        return


# Indirection so tests can inject deterministic adapters without monkeypatching
# provider modules.
def places_adapter() -> PlacesAdapter:
    return GooglePlacesAdapter()


def routes_adapter() -> RoutesAdapter:
    return GoogleRoutesAdapter()


def _now() -> datetime:
    """Clock for the departure-range check (patched in tests)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Failure mapping (shared by the JSON and streaming endpoints)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanFailure:
    status: int
    code: str
    message: str
    details: ErrorDetails | None = None
    headers: dict[str, str] | None = None


def describe_failure(exc: BaseException) -> PlanFailure | None:
    """Map a domain exception to a user-safe failure, or None if unexpected."""
    if isinstance(exc, PlaceVerificationError):
        return PlanFailure(
            422,
            "place_invalid",
            "A selected place could not be verified. Please select it again.",
            ErrorDetails(
                role=exc.role,
                reason=exc.reason,
                place_id=exc.place_id,
                moved_place_id=exc.moved_place_id,
            ),
        )
    if isinstance(exc, ProviderTemporaryError):
        return PlanFailure(
            503, "place_temporary", "Place verification is temporarily unavailable. Try again."
        )
    if isinstance(exc, QuotaExceededError):
        return PlanFailure(
            429,
            "quota_exceeded",
            "The daily provider allowance has been reached. Try again tomorrow.",
        )
    if isinstance(exc, UsageControlUnavailableError):
        return PlanFailure(
            503,
            "usage_control_unavailable",
            "Usage checks are unavailable, so no requests were sent. Try again shortly.",
            ErrorDetails(retry_after_seconds=60),
            {"Retry-After": "60"},
        )
    if isinstance(exc, ProviderCapacityError):
        return PlanFailure(
            503,
            "provider_capacity",
            "The service is busy. Try again shortly.",
            ErrorDetails(retry_after_seconds=2),
            {"Retry-After": "2"},
        )
    if isinstance(exc, TimezoneUnresolvedError):
        return PlanFailure(
            422,
            "timezone_unresolved",
            f"The timezone for {exc.name} could not be determined. "
            + ("Select another city." if exc.role == "city" else "Select another place."),
            ErrorDetails(
                role=exc.role, instance_ids=[exc.instance_id] if exc.instance_id else None
            ),
        )
    if isinstance(exc, TimezoneConflictError):
        return PlanFailure(
            422,
            "timezone_conflict",
            f"{exc.stop_name} is in {exc.detected_tz}, but this trip is in "
            f"{exc.expected_tz}. Trips must stay within one timezone.",
            ErrorDetails(role="stop", instance_ids=[exc.instance_id] if exc.instance_id else None),
        )
    if isinstance(exc, DepartureError):
        return PlanFailure(422, exc.code, str(exc))
    if isinstance(exc, DuplicateInstanceIdError):
        return PlanFailure(
            422, "duplicate_instance_id", "Each stop must have a unique instance_id."
        )
    if isinstance(exc, DeadlineExceededError | OperationCancelledError):
        return PlanFailure(503, "deadline_exceeded", "The request took too long. Try again.")
    return None


def _with_instance_ids(failure: PlanFailure, req: ItineraryRequest) -> PlanFailure:
    d = failure.details
    if d is None or d.role != "stop" or d.instance_ids is not None or d.place_id is None:
        return failure
    ids = [s.instance_id for s in req.stops if s.selection.place_id == d.place_id]
    return PlanFailure(
        failure.status,
        failure.code,
        failure.message,
        d.model_copy(update={"instance_ids": ids}),
        failure.headers,
    )


def _raise_http(failure: PlanFailure) -> NoReturn:
    detail: dict[str, Any] = {"error": failure.code, "message": failure.message}
    if failure.details is not None:
        detail.update(failure.details.model_dump(exclude_none=True))
    raise HTTPException(status_code=failure.status, detail=detail, headers=failure.headers)


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------


def _overview_url(lats_lngs: list[tuple[float, float]]) -> str:
    """Multi-stop overview URL using coordinate pairs (driving mode for overview)."""
    if len(lats_lngs) < 2:
        lat, lng = lats_lngs[0]
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    origin_lat, origin_lng = lats_lngs[0]
    dest_lat, dest_lng = lats_lngs[-1]
    middle = lats_lngs[1:-1]
    url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(f'{origin_lat},{origin_lng}')}"
        f"&destination={quote_plus(f'{dest_lat},{dest_lng}')}"
        f"&travelmode=driving"
    )
    if middle:
        waypoints = "|".join(quote_plus(f"{lat},{lng}") for lat, lng in middle)
        url += f"&waypoints={waypoints}"
    return url


def _hours_warnings(timeline: list[Any], first_stop_index: int = 0) -> list[Warning]:
    """Warnings for the user's own order. Nothing is dropped or reordered.

    ``first_stop_index`` is the global index of the first stop item in
    ``timeline`` (k+1 for a refresh suffix).
    """
    warnings: list[Warning] = []
    stop_index = first_stop_index - 1
    for item in timeline:
        if item.item_type in ("stop", "unknown_stop"):
            stop_index += 1
        if not isinstance(item, KnownStop):
            continue
        status, detail = item.hours_status, item.hours_detail
        severity: WarningSeverity
        if hours_eligibility(status, item.stay_minutes) == "ok":
            continue
        weekly_note = (
            " Based on the usual weekly schedule; holiday or special hours are not confirmed."
            if detail is not None and detail.exceptions_unconfirmed
            else ""
        )
        if status == "closed_on_arrival":
            opens = ""
            if detail and detail.opens_at:
                when = f" on {detail.opens_on.isoformat()}" if detail.opens_on else ""
                opens = f" It opens at {detail.opens_at}{when}."
            if item.stay_minutes > 0:
                message = f"{item.name} appears to be closed when you arrive.{opens}"
                code, severity = "hours_closed_on_arrival", "warning"
            else:
                message = (
                    f"{item.name} appears to be closed at this time. As a pass-through "
                    f"stop it may still be reachable, but access is not confirmed.{opens}"
                )
                code, severity = "hours_closed_zero_minute", "warning"
        elif status == "closes_during_visit":
            closes = detail.closes_at if detail else None
            message = (
                f"{item.name} closes at {closes}, before your {item.stay_minutes}-minute "
                "visit ends. The full visit may not fit."
            )
            code, severity = "hours_closes_during_visit", "warning"
        else:  # unknown
            message = f"Opening hours for {item.name} could not be checked."
            code, severity = "hours_unknown", "info"
        warnings.append(
            Warning(
                severity=severity,
                message=message + weekly_note,
                affects_stop_index=stop_index,
                affects_instance_id=item.instance_id,
                code=code,
            )
        )
    return warnings


def _area_warnings(
    itinerary: VerifiedItinerary,
    first_stop_index: int = 0,
    skip_first: bool = False,
    stops: list[VerifiedStop] | None = None,
) -> list[Warning]:
    """D44: compare every verified stop (known or unknown timing) with the viewport.

    For a refresh, ``itinerary.stops`` starts at stop k (global index
    ``first_stop_index``), which belongs to the unchanged prefix and is skipped.
    ``stops`` overrides the order (a comparison candidate).
    """
    viewport = itinerary.city.viewport
    if viewport is None:
        return [Warning(severity="info", message=AREA_UNAVAILABLE_MESSAGE, code="area_unavailable")]
    return [
        Warning(
            severity="warning",
            message=OUTSIDE_AREA_MESSAGE,
            affects_stop_index=first_stop_index + i,
            affects_instance_id=stop.instance_id,
            code="outside_city_area",
        )
        for i, stop in enumerate(itinerary.stops if stops is None else stops)
        if not (skip_first and i == 0) and area_status(viewport, stop.lat, stop.lng) == "outside"
    ]


async def execute_plan(
    req: ItineraryRequest,
    *,
    departure_utc: datetime,
    places: PlacesAdapter,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
) -> PlanResult:
    """Verify, resolve durations and route. Raises domain errors before routing."""
    op, rev = ctx.operation_id, ctx.input_revision
    await emitter.emit(
        OperationStartEvent(operation_id=op, input_revision=rev, phases=["verification", "routing"])
    )
    await emitter.emit(PhaseStartEvent(operation_id=op, input_revision=rev, phase="verification"))
    itinerary = await verify_itinerary(req, places, ctx, deadline)
    await emitter.emit(
        PhaseCompleteEvent(operation_id=op, input_revision=rev, phase="verification")
    )

    durations = resolve_durations(
        [(s.instance_id, s.stay_minutes) for s in req.stops],
        place_type_defaults(itinerary.stops),
    )
    timeline = await plan_sequential(
        stops=itinerary.stops,
        durations=durations,
        departure=departure_utc,
        mode=req.mode,
        routes=routes,
        emitter=emitter,
        ctx=ctx,
        deadline=deadline,
        trip_timezone=itinerary.timezone,
    )

    return _assemble_plan(req, itinerary, itinerary.stops, timeline)


def _assemble_plan(
    req: ItineraryRequest,
    itinerary: VerifiedItinerary,
    ordered: list[VerifiedStop],
    timeline: list[KnownStop | PlannedLeg | FailedLeg | UnknownStop],
) -> PlanResult:
    """CompletePlan/PartialPlan for ``timeline`` computed over ``ordered`` stops."""
    overview_url = _overview_url([(v.lat, v.lng) for v in ordered])
    warnings = _hours_warnings(timeline) + _area_warnings(itinerary, stops=ordered)
    failed = next(
        ((i, item) for i, item in enumerate(timeline) if isinstance(item, FailedLeg)), None
    )
    if failed is None:
        return CompletePlan(
            operation_id=req.operation_id,
            input_revision=req.input_revision,
            city=itinerary.city.name,
            mode=req.mode,
            timezone=itinerary.timezone,
            timeline=timeline,
            overview_map_url=overview_url,
            warnings=warnings,
        )
    failed_idx, failed_leg = failed
    leg_index = sum(1 for item in timeline[:failed_idx] if isinstance(item, PlannedLeg))
    return PartialPlan(
        operation_id=req.operation_id,
        input_revision=req.input_revision,
        city=itinerary.city.name,
        mode=req.mode,
        timezone=itinerary.timezone,
        timeline=timeline,
        failed_at_leg_index=leg_index,
        failure_reason=failed_leg.failure_reason,
        overview_map_url=overview_url,
        warnings=warnings,
    )


async def execute_refresh(
    req: RefreshRequest,
    *,
    places: PlacesAdapter,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
) -> RefreshResult:
    """Refresh from leg k at its planned departure (D21). Verifies only the
    city, departure zone and stops k..N-1 (D37); routes at most N-1-k legs."""
    k = req.leg_index
    op, rev = ctx.operation_id, ctx.input_revision
    await emitter.emit(
        OperationStartEvent(operation_id=op, input_revision=rev, phases=["verification", "routing"])
    )
    await emitter.emit(PhaseStartEvent(operation_id=op, input_revision=rev, phase="verification"))
    itinerary = await verify_itinerary(req, places, ctx, deadline, from_stop=k)
    await emitter.emit(
        PhaseCompleteEvent(operation_id=op, input_revision=rev, phase="verification")
    )

    # Durations resolved from the ORIGINAL full order (D11); only suffix
    # stops need place-type defaults, prefix stops are not recomputed.
    durations = resolve_durations(
        [(s.instance_id, s.stay_minutes) for s in req.stops],
        place_type_defaults(itinerary.stops),
    )
    suffix = await refresh_suffix(
        itinerary.stops,
        durations,
        k,
        req.planned_departure,
        req.mode,
        routes,
        emitter,
        ctx,
        deadline,
        itinerary.timezone,
    )
    warnings = _hours_warnings(suffix, first_stop_index=k + 1) + _area_warnings(
        itinerary, first_stop_index=k, skip_first=True
    )
    failed = next(((i, item) for i, item in enumerate(suffix) if isinstance(item, FailedLeg)), None)
    if failed is None:
        return RefreshComplete(
            operation_id=op,
            input_revision=rev,
            leg_index=k,
            planned_departure=req.planned_departure,
            timezone=itinerary.timezone,
            suffix=suffix,
            warnings=warnings,
        )
    failed_idx, failed_leg = failed
    routed = sum(1 for item in suffix[:failed_idx] if isinstance(item, PlannedLeg))
    return RefreshPartial(
        operation_id=op,
        input_revision=rev,
        leg_index=k,
        planned_departure=req.planned_departure,
        timezone=itinerary.timezone,
        suffix=suffix,
        warnings=warnings,
        failed_at_leg_index=k + routed,
        failure_reason=failed_leg.failure_reason,
    )


_COMPARISON_MESSAGES = {
    "no_different_order": "No different order found by the current search.",
    "recommended": (
        "A different order is estimated to save at least 5 minutes of travel for this "
        "departure. It is an estimate, not a guarantee."
    ),
    "not_faster": (
        "The other order checked is not at least 5 minutes faster, so your order is kept."
    ),
    "hours_ineligible": (
        "The other order checked would arrive at a venue while it appears closed, so your "
        "order is kept."
    ),
    "original_incomplete": (
        "Your current order could not be fully recalculated, so the comparison stopped. "
        "Your previous plan is unchanged."
    ),
    "candidate_incomplete": (
        "The other order could not be fully calculated, so no change is suggested. Your "
        "current order was recalculated."
    ),
}


async def execute_compare(
    req: ComparisonRequest,
    *,
    departure_utc: datetime,
    places: PlacesAdapter,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
) -> ComparisonResult:
    """Step 8: one local candidate compared with a fresh original (D3-D12, D15-D20).

    Verified place details are fetched once and shared by both orders (D37);
    nothing is stored across requests (D10). Routing calls are capped at
    2(N-1) by RoutingBudget; none are made when the order is unchanged (D9).
    """
    op, rev = ctx.operation_id, ctx.input_revision
    phases: list[PhaseName] = ["verification", "candidate", "original_route", "alternative_route"]
    await emitter.emit(OperationStartEvent(operation_id=op, input_revision=rev, phases=phases))
    await emitter.emit(PhaseStartEvent(operation_id=op, input_revision=rev, phase="verification"))
    itinerary = await verify_itinerary(req, places, ctx, deadline)
    await emitter.emit(
        PhaseCompleteEvent(operation_id=op, input_revision=rev, phase="verification")
    )
    stops = itinerary.stops
    n = len(stops)
    original_ids = [s.instance_id for s in stops]
    # Fixed durations from the ORIGINAL order, carried by instance (D11).
    durations = resolve_durations(
        [(s.instance_id, s.stay_minutes) for s in req.stops], place_type_defaults(stops)
    )

    await emitter.emit(PhaseStartEvent(operation_id=op, input_revision=rev, phase="candidate"))
    order = await generate_candidate(
        stops, fixed_first=req.fixed_first, fixed_last=req.fixed_last, deadline=deadline
    )
    await emitter.emit(PhaseCompleteEvent(operation_id=op, input_revision=rev, phase="candidate"))
    candidate_ids = [original_ids[i] for i in order]
    common = {
        "operation_id": op,
        "input_revision": rev,
        "original_order": original_ids,
        "fixed_first": req.fixed_first,
        "fixed_last": req.fixed_last,
        "original_distance_km": round(path_km(stops, list(range(n))), 3),
        "candidate_distance_km": round(path_km(stops, order), 3),
    }
    if candidate_ids == original_ids:  # by stop-instance identity
        return ComparisonResult(
            **common,
            status="no_different_order",
            message=_COMPARISON_MESSAGES["no_different_order"],
            routing_calls=0,
        )

    budget = RoutingBudget(routes, 2 * (n - 1))
    original_tl = await plan_sequential(
        stops,
        durations,
        departure_utc,
        req.mode,
        budget,
        emitter,
        ctx,
        deadline,
        itinerary.timezone,
        phase="original_route",
    )
    original_plan = _assemble_plan(req, itinerary, stops, original_tl)
    if not is_complete(original_tl):
        return ComparisonResult(
            **common,
            candidate_order=candidate_ids,
            status="original_incomplete",
            message=_COMPARISON_MESSAGES["original_incomplete"],
            original=original_plan,
            routing_calls=budget.calls,
        )

    candidate_stops = [stops[i] for i in order]
    candidate_tl = await plan_sequential(
        candidate_stops,
        durations,
        departure_utc,
        req.mode,
        budget,
        emitter,
        ctx,
        deadline,
        itinerary.timezone,
        phase="alternative_route",
    )
    if not is_complete(candidate_tl):
        return ComparisonResult(
            **common,
            candidate_order=candidate_ids,
            status="candidate_incomplete",
            message=_COMPARISON_MESSAGES["candidate_incomplete"],
            original=original_plan,
            routing_calls=budget.calls,
        )

    verdict = decide(original_tl, candidate_tl)
    candidate_plan = _assemble_plan(req, itinerary, candidate_stops, candidate_tl)
    if verdict.decision == "recommended" and not isinstance(candidate_plan, CompletePlan):
        raise CandidateIntegrityError("recommended candidate is not complete")
    return ComparisonResult(
        **common,
        candidate_order=candidate_ids,
        status=verdict.decision,
        message=_COMPARISON_MESSAGES[verdict.decision],
        original=original_plan,
        candidate=candidate_plan
        if verdict.decision == "recommended" and isinstance(candidate_plan, CompletePlan)
        else None,
        original_seconds=verdict.original_seconds,
        candidate_seconds=verdict.candidate_seconds,
        saving_seconds=verdict.saving_seconds,
        ineligible_instance_ids=verdict.ineligible,
        routing_calls=budget.calls,
    )


# ---------------------------------------------------------------------------
# Experimental exhaustive search over four stops (2026-10-08)
# ---------------------------------------------------------------------------


def _exhaustive_message(search: exhaustive.SearchOutcome) -> str:
    total = exhaustive.ORDER_COUNT
    if not search.search_complete:
        return f"Search incomplete: evaluated {search.evaluated} of {total} orders."
    done, failed = len(search.complete), len(search.failed)
    if failed == 0:
        return f"Earliest completion among all {total} evaluated stop orders."
    if done == 0:
        return f"No order could be completed; {failed} could not be evaluated."
    return f"Earliest completion among {done} completed orders; {failed} could not be evaluated."


def _candidate_model(e: exhaustive.Evaluation) -> CandidateEvaluation:
    return CandidateEvaluation(
        order=list(e.ids),
        is_original=e.is_original,
        status=e.status,
        completion_at=e.completion_at,
        elapsed_seconds=e.elapsed_seconds,
        distance_m=round(e.distance_m),
        failure_reason=e.failure_reason,
        failure_message=e.failure_message,
        timeline=e.timeline,
        routing_calls=e.routing_calls,
    )


async def execute_exhaustive(
    req: ExhaustiveRequest,
    *,
    departure_utc: datetime,
    places: PlacesAdapter,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
) -> ExhaustiveResult:
    """Verify the city and four stops once, then evaluate all 24 orders.

    Verification errors (invalid selection, timezone conflict, temporary
    place failure) are raised before any routing, as for planning. The
    search itself never raises for routing problems: it returns an explicit
    result whose ``status`` says whether every order was evaluated.
    """
    op, rev = ctx.operation_id, ctx.input_revision
    await emitter.emit(
        OperationStartEvent(
            operation_id=op, input_revision=rev, phases=["verification", "exhaustive_search"]
        )
    )
    await emitter.emit(PhaseStartEvent(operation_id=op, input_revision=rev, phase="verification"))
    itinerary = await verify_itinerary(req, places, ctx, deadline)
    await emitter.emit(
        PhaseCompleteEvent(operation_id=op, input_revision=rev, phase="verification")
    )
    stops = itinerary.stops
    stays = exhaustive.resolve_experiment_stays(req)

    async def progress(search: exhaustive.SearchOutcome) -> None:
        await emitter.emit(
            ExhaustiveProgressEvent(
                operation_id=op,
                input_revision=rev,
                evaluated=search.evaluated,
                complete=len(search.complete),
                failed=len(search.failed),
                total=exhaustive.ORDER_COUNT,
            )
        )

    await emitter.emit(
        PhaseStartEvent(operation_id=op, input_revision=rev, phase="exhaustive_search")
    )
    search = await exhaustive.optimise_exhaustive_four(
        stops,
        stays,
        departure_utc,
        mode=req.mode,
        routes=routes,
        ctx=ctx,
        deadline=deadline,
        trip_timezone=itinerary.timezone,
        on_progress=progress,
    )
    await emitter.emit(
        PhaseCompleteEvent(operation_id=op, input_revision=rev, phase="exhaustive_search")
    )

    ranked, basis = exhaustive.rank_complete_candidates(search.evaluations)
    winner = ranked[0] if ranked else None
    original = search.evaluations[0] if search.evaluations else None
    saving = None
    if winner and original and original.status == "complete":
        assert original.completion_at is not None and winner.completion_at is not None
        saving = int((original.completion_at - winner.completion_at).total_seconds())
    winner_plan = None
    if winner is not None and search.search_complete:
        assembled = _assemble_plan(req, itinerary, list(winner.order), winner.timeline)
        if not isinstance(assembled, CompletePlan):
            raise RuntimeError("a complete winner must assemble into a complete plan")
        winner_plan = assembled
    if search.search_complete:
        status = "all_complete" if not search.failed else "some_failed"
    else:
        status = "interrupted"
    return ExhaustiveResult(
        operation_id=op,
        input_revision=rev,
        status=status,
        message=_exhaustive_message(search),
        search_complete=search.search_complete,
        requested_orders=exhaustive.ORDER_COUNT,
        evaluated_orders=search.evaluated,
        complete_orders=len(search.complete),
        failed_orders=len(search.failed),
        interruption_reason=search.interruption_reason,
        start_at=departure_utc,
        original_order=[s.instance_id for s in stops],
        original=_candidate_model(original) if original else None,
        winner=_candidate_model(winner) if winner else None,
        winner_basis=basis,
        winner_plan=winner_plan,
        saving_seconds=saving,
        hours_warnings=_hours_warnings(winner.timeline) if winner else [],
        candidates=[_candidate_model(e) for e in search.evaluations],
        routing_calls=search.routing_calls,
        routing_budget=exhaustive.ROUTING_BUDGET,
        deadline_seconds=int(exhaustive.DEADLINE_SECONDS),
    )


# ---------------------------------------------------------------------------
# Aggregate operational metrics (Step 9, D46): bounded categories only
# ---------------------------------------------------------------------------

_COMPARISON_CATEGORY = {
    "no_different_order": "no_different_order",
    "recommended": "compared",  # result categories deliberately not split (D46)
    "not_faster": "compared",
    "hours_ineligible": "compared",
    "original_incomplete": "incomplete",
    "candidate_incomplete": "incomplete",
}


def _result_category(result: object) -> tuple[str, str | None]:
    if isinstance(result, CompletePlan | RefreshComplete):
        return "complete", None
    if isinstance(result, PartialPlan | RefreshPartial):
        if result.failure_reason == "deadline_exceeded":
            return "timeout", "deadline_exceeded"
        return "partial", result.failure_reason
    if isinstance(result, ExhaustiveResult):
        # Like comparisons, results are not split by outcome (D46).
        if result.status == "interrupted":
            return "incomplete", result.interruption_reason
        return "compared", None
    if isinstance(result, ComparisonResult):
        failure = None
        if result.status == "original_incomplete" and isinstance(result.original, PartialPlan):
            failure = result.original.failure_reason
        return _COMPARISON_CATEGORY[result.status], failure
    return "error", "other"


def _outcome_category(outcome: OperationOutcome) -> tuple[str, str | None]:
    if isinstance(outcome, PlanOutcome | RefreshOutcome | ComparisonOutcome | ExhaustiveOutcome):
        return _result_category(outcome.result)
    if isinstance(outcome, TimeoutOutcome):
        return "timeout", "deadline_exceeded"
    if isinstance(outcome, ErrorOutcome):
        return "error", outcome.code
    return "cancelled", None


def _failure_category(exc: BaseException) -> tuple[str, str | None]:
    if isinstance(exc, HTTPException):
        detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("error", "other"))
        return ("rejected" if exc.status_code == 422 else "error"), code
    if isinstance(exc, DeadlineExceededError):
        return "timeout", "deadline_exceeded"
    failure = describe_failure(exc)
    if failure is None:
        return "error", "internal_error"
    return ("rejected" if failure.status == 422 else "error"), failure.code


async def _measured(
    operation: OperationType,
    stop_count: int,
    run: Callable[[], Awaitable[Any]],
) -> Any:
    """Run a JSON endpoint body and emit exactly one metrics line."""
    metrics = OperationMetrics(operation, "json", stop_count)
    metrics.activate()
    try:
        result = await run()
    except BaseException as exc:
        metrics.finish(*_failure_category(exc))
        raise
    metrics.finish(*_result_category(result))
    return result


def _validated_departure(req: ItineraryRequest) -> datetime:
    try:
        return resolve_departure(req.departure, mode=req.mode, now=_now())
    except DepartureError as exc:
        failure = describe_failure(exc)
        assert failure is not None
        _raise_http(failure)


def _validated_refresh(req: RefreshRequest) -> None:
    """Pre-stream checks: no provider calls, HTTP 422 on failure (D21).

    The planned departure is never replaced with the current time. If the
    provider cannot schedule it, the user is told why.
    """
    try:
        trip_departure = resolve_departure(
            req.departure, mode=req.mode, now=_now(), check_range=False
        )
        planned = req.planned_departure
        if planned < trip_departure:
            raise PlannedDepartureError(
                "The selected journey's planned departure is earlier than the trip's "
                "departure, so it does not belong to this plan. Plan the day again."
            )
        problem = unsupported_departure_reason(planned, req.mode, _now())
        if problem:
            raise PlannedDepartureError(
                f"This journey's planned departure {problem}, so it can't be refreshed "
                "for that time. Plan the day again with a new departure time."
            )
    except DepartureError as exc:
        failure = describe_failure(exc)
        assert failure is not None
        _raise_http(failure)


# ---------------------------------------------------------------------------
# JSON endpoint
# ---------------------------------------------------------------------------


@router.post("/plan", response_model=PlanResult)
@limiter.shared_limit(PLAN_LIMITS, scope=_PLAN_V2_SCOPE, cost=request_cost)
async def plan_v2(request: Request, req: ItineraryRequest) -> PlanResult:
    """Verify selections, then plan sequentially; one JSON response."""
    result: PlanResult = await _measured("plan", len(req.stops), lambda: _plan_json(req))
    return result


async def _plan_json(req: ItineraryRequest) -> PlanResult:
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    departure_utc = _validated_departure(req)
    try:
        return await execute_plan(
            req,
            departure_utc=departure_utc,
            places=places_adapter(),
            routes=routes_adapter(),
            emitter=_NullEmitter(),
            ctx=ctx,
            deadline=deadline,
        )
    except Exception as exc:
        failure = describe_failure(exc)
        if failure is None:
            raise
        _raise_http(_with_instance_ids(failure, req))


# ---------------------------------------------------------------------------
# Streaming endpoint
# ---------------------------------------------------------------------------


def _stream_operation(req: ItineraryRequest) -> OperationType:
    if isinstance(req, ComparisonRequest):
        return "compare"
    if isinstance(req, RefreshRequest):
        return "refresh"
    return "plan"


class _QueueEmitter:
    """Forwards engine events into the bounded stream queue; tracks the phase."""

    def __init__(self, queue: "asyncio.Queue[Any]") -> None:
        self.queue = queue
        self.phase: PhaseName = "verification"

    async def emit(self, event: object) -> None:
        if isinstance(event, PhaseStartEvent):
            self.phase = event.phase
        await self.queue.put(event)


Receive = Callable[[], Awaitable[Message]]

# Queued by the disconnect watcher so a consumer blocked on an empty queue
# wakes immediately instead of sleeping until the deadline.
_DISCONNECTED = object()


class PlanStream:
    """One streamed planning operation: a producer task feeding a bounded queue.

    ``events()`` is the response body iterator. Whatever ends it — terminal
    event, client disconnect, generator close — its ``finally`` cancels and
    awaits the producer and watcher tasks, so nothing outlives the response.
    """

    def __init__(
        self,
        req: ItineraryRequest,
        *,
        departure_utc: datetime | None = None,
        places: PlacesAdapter,
        routes: RoutesAdapter,
        ctx: OperationContext,
        deadline: DeadlineScope,
        receive: Receive | None,
        metrics: OperationMetrics | None = None,
    ) -> None:
        """Plan stream for an ItineraryRequest (needs ``departure_utc``), or a
        refresh/comparison stream for a RefreshRequest/ComparisonRequest."""
        self.req = req
        self.departure_utc = departure_utc
        self.places = places
        self.routes = routes
        self.ctx = ctx
        self.deadline = deadline
        self.receive = receive
        self.queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
        self.emitter = _QueueEmitter(self.queue)
        self.disconnected = False
        self.metrics = metrics

    def _terminal(self, outcome: OperationOutcome) -> TerminalEvent:
        return TerminalEvent(
            operation_id=self.ctx.operation_id,
            input_revision=self.ctx.input_revision,
            outcome=outcome,
        )

    def _timeout(self, partial: PartialPlan | RefreshPartial | None = None) -> TimeoutOutcome:
        return TimeoutOutcome(
            phase=self.emitter.phase,
            message=(
                "Routing took too long; the timetable stops at the last confirmed leg."
                if partial is not None
                else "This took too long and was stopped. Try again."
            ),
            partial=partial,
        )

    async def _produce(self) -> None:
        outcome: OperationOutcome
        if self.metrics is not None:
            self.metrics.activate()  # provider calls in this task count toward it
        try:
            result: PlanResult | RefreshResult | ComparisonResult | ExhaustiveResult
            if isinstance(self.req, ExhaustiveRequest):
                assert self.departure_utc is not None
                result = await execute_exhaustive(
                    self.req,
                    departure_utc=self.departure_utc,
                    places=self.places,
                    routes=self.routes,
                    emitter=self.emitter,
                    ctx=self.ctx,
                    deadline=self.deadline,
                )
            elif isinstance(self.req, ComparisonRequest):
                assert self.departure_utc is not None
                result = await execute_compare(
                    self.req,
                    departure_utc=self.departure_utc,
                    places=self.places,
                    routes=self.routes,
                    emitter=self.emitter,
                    ctx=self.ctx,
                    deadline=self.deadline,
                )
            elif isinstance(self.req, RefreshRequest):
                result = await execute_refresh(
                    self.req,
                    places=self.places,
                    routes=self.routes,
                    emitter=self.emitter,
                    ctx=self.ctx,
                    deadline=self.deadline,
                )
            else:
                assert self.departure_utc is not None
                result = await execute_plan(
                    self.req,
                    departure_utc=self.departure_utc,
                    places=self.places,
                    routes=self.routes,
                    emitter=self.emitter,
                    ctx=self.ctx,
                    deadline=self.deadline,
                )
            if (
                isinstance(result, PartialPlan | RefreshPartial)
                and result.failure_reason == "deadline_exceeded"
            ):
                outcome = self._timeout(result)
            elif isinstance(result, RefreshComplete | RefreshPartial):
                outcome = RefreshOutcome(result=result)
            elif isinstance(result, ComparisonResult):
                outcome = ComparisonOutcome(result=result)
            elif isinstance(result, ExhaustiveResult):
                outcome = ExhaustiveOutcome(result=result)
            else:
                outcome = PlanOutcome(result=result)
        except asyncio.CancelledError:
            if self.metrics is not None:
                self.metrics.finish("cancelled")
            raise
        except DeadlineExceededError:
            outcome = self._timeout()
        except Exception as exc:
            failure = describe_failure(exc)
            if failure is None:
                log.error("plan_stream_failed exception_type=%s", type(exc).__name__)
                outcome = ErrorOutcome(
                    code="internal_error", message="Planning failed unexpectedly. Try again."
                )
            else:
                failure = _with_instance_ids(failure, self.req)
                outcome = ErrorOutcome(
                    code=failure.code, message=failure.message, details=failure.details
                )
        if self.metrics is not None:
            self.metrics.finish(*_outcome_category(outcome))
        await self.queue.put(self._terminal(outcome))

    async def _watch_disconnect(self, producer: "asyncio.Task[None]") -> None:
        assert self.receive is not None
        while True:
            message = await self.receive()
            if message["type"] == "http.disconnect":
                self.disconnected = True
                producer.cancel()
                with contextlib.suppress(asyncio.QueueFull):
                    # A full queue already has events that will wake the consumer.
                    self.queue.put_nowait(_DISCONNECTED)
                return

    async def events(self) -> AsyncIterator[bytes]:
        producer = asyncio.create_task(self._produce())
        watcher = asyncio.create_task(self._watch_disconnect(producer)) if self.receive else None
        try:
            while True:
                timeout = self.deadline.remaining_seconds() + TERMINAL_GRACE_SECONDS
                try:
                    event = await asyncio.wait_for(self.queue.get(), timeout=timeout)
                except TimeoutError:
                    producer.cancel()
                    if self.metrics is not None:
                        self.metrics.finish("timeout", "deadline_exceeded")
                    event = self._terminal(self._timeout())
                if event is _DISCONNECTED or self.disconnected:
                    return
                yield (event.model_dump_json() + "\n").encode()
                if isinstance(event, TerminalEvent):
                    return
        finally:
            producer.cancel()
            if watcher is not None:
                watcher.cancel()
            await asyncio.gather(producer, *([watcher] if watcher else []), return_exceptions=True)


@router.post("/plan/stream")
@limiter.shared_limit(PLAN_LIMITS, scope=_PLAN_V2_SCOPE, cost=request_cost)
async def plan_v2_stream(request: Request, req: ItineraryRequest) -> StreamingResponse:
    """Streamed planning. Validation/rate-limit errors are HTTP errors; everything
    after the response starts is reported as stream events."""
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    metrics = OperationMetrics(_stream_operation(req), "stream", len(req.stops))
    try:
        departure_utc = _validated_departure(req)
    except HTTPException as exc:
        metrics.finish(*_failure_category(exc))
        raise
    stream = PlanStream(
        req,
        departure_utc=departure_utc,
        places=places_adapter(),
        routes=routes_adapter(),
        ctx=ctx,
        deadline=deadline,
        receive=request.receive,
        metrics=metrics,
    )
    return StreamingResponse(
        stream.events(),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Refresh endpoints (D21, Step 7)
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=RefreshResult)
@limiter.shared_limit(REFRESH_LIMITS, scope=_REFRESH_V2_SCOPE, cost=request_cost)
async def refresh_v2(request: Request, req: RefreshRequest) -> RefreshResult:
    """Recompute the timetable from leg k at its planned departure; one JSON response."""
    result: RefreshResult = await _measured("refresh", len(req.stops), lambda: _refresh_json(req))
    return result


async def _refresh_json(req: RefreshRequest) -> RefreshResult:
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    _validated_refresh(req)
    try:
        return await execute_refresh(
            req,
            places=places_adapter(),
            routes=routes_adapter(),
            emitter=_NullEmitter(),
            ctx=ctx,
            deadline=deadline,
        )
    except Exception as exc:
        failure = describe_failure(exc)
        if failure is None:
            raise
        _raise_http(_with_instance_ids(failure, req))


@router.post("/refresh/stream")
@limiter.shared_limit(REFRESH_LIMITS, scope=_REFRESH_V2_SCOPE, cost=request_cost)
async def refresh_v2_stream(request: Request, req: RefreshRequest) -> StreamingResponse:
    """Streamed suffix refresh: same events, deadline, cancellation and error
    semantics as planning; the terminal outcome is a RefreshOutcome."""
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    metrics = OperationMetrics("refresh", "stream", len(req.stops))
    try:
        _validated_refresh(req)
    except HTTPException as exc:
        metrics.finish(*_failure_category(exc))
        raise
    stream = PlanStream(
        req,
        places=places_adapter(),
        routes=routes_adapter(),
        ctx=ctx,
        deadline=deadline,
        receive=request.receive,
        metrics=metrics,
    )
    return StreamingResponse(
        stream.events(),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Comparison endpoints (Step 8)
# ---------------------------------------------------------------------------


@router.post("/compare", response_model=ComparisonResult)
@limiter.shared_limit(OPTIMISE_LIMITS, scope=_COMPARE_V2_SCOPE, cost=request_cost)
async def compare_v2(request: Request, req: ComparisonRequest) -> ComparisonResult:
    """Compare the current order with one local candidate; one JSON response."""
    result: ComparisonResult = await _measured(
        "compare", len(req.stops), lambda: _compare_json(req)
    )
    return result


async def _compare_json(req: ComparisonRequest) -> ComparisonResult:
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    departure_utc = _validated_departure(req)
    try:
        return await execute_compare(
            req,
            departure_utc=departure_utc,
            places=places_adapter(),
            routes=routes_adapter(),
            emitter=_NullEmitter(),
            ctx=ctx,
            deadline=deadline,
        )
    except Exception as exc:
        failure = describe_failure(exc)
        if failure is None:
            raise
        _raise_http(_with_instance_ids(failure, req))


@router.post("/compare/stream")
@limiter.shared_limit(OPTIMISE_LIMITS, scope=_COMPARE_V2_SCOPE, cost=request_cost)
async def compare_v2_stream(request: Request, req: ComparisonRequest) -> StreamingResponse:
    """Streamed comparison: phases verification, candidate, original_route,
    alternative_route; terminal ComparisonOutcome (or timeout/error)."""
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    metrics = OperationMetrics(_stream_operation(req), "stream", len(req.stops))
    try:
        departure_utc = _validated_departure(req)
    except HTTPException as exc:
        metrics.finish(*_failure_category(exc))
        raise
    stream = PlanStream(
        req,
        departure_utc=departure_utc,
        places=places_adapter(),
        routes=routes_adapter(),
        ctx=ctx,
        deadline=deadline,
        receive=request.receive,
        metrics=metrics,
    )
    return StreamingResponse(
        stream.events(),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Experimental exhaustive endpoint (2026-10-08)
# ---------------------------------------------------------------------------


@router.post("/optimise-exhaustive/stream")
@limiter.shared_limit(OPTIMISE_LIMITS, scope=_COMPARE_V2_SCOPE, cost=request_cost)
async def optimise_exhaustive_stream(request: Request, req: ExhaustiveRequest) -> StreamingResponse:
    """Experimental: evaluate all 24 orders of exactly four stops.

    Shares the comparison rate-limit scope. Its own 240-second deadline covers
    verification, capacity waits and routing (existing 60-second operations
    are unchanged); at most 72 routing calls. Phases: verification,
    exhaustive_search; progress events after each order; terminal
    ExhaustiveOutcome (or timeout/error). One open stream holds one admission
    slot for up to 240 s.
    """
    deadline = DeadlineScope(deadline_seconds=exhaustive.DEADLINE_SECONDS)
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)
    metrics = OperationMetrics("compare_exhaustive", "stream", len(req.stops))
    try:
        departure_utc = _validated_departure(req)
    except HTTPException as exc:
        metrics.finish(*_failure_category(exc))
        raise
    stream = PlanStream(
        req,
        departure_utc=departure_utc,
        places=places_adapter(),
        routes=routes_adapter(),
        ctx=ctx,
        deadline=deadline,
        receive=request.receive,
        metrics=metrics,
    )
    return StreamingResponse(
        stream.events(),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"X-Accel-Buffering": "no"},
    )
