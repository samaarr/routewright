"""POST /api/v2/plan -- verified sequential planning.

``execute_plan`` orchestrates:

1. Departure syntax, calendar validity, clock-change handling and supported
   range — no provider calls (D14, D29). Failures are HTTP 422.
2. Verification: Place Details for the city, departure-zone match, then stops
   (D13, D37, D40, D41, D45). Any failure makes ZERO routing calls.
3. Fixed stay durations from the original order and verified place types (D11).
4. Routing: each leg departs at the previous stop's actual arrival plus its
   fixed stay; a failed leg keeps the valid prefix and leaves the rest
   unknown (D1, D2). Known stops get opening-hours assessment (D24, D42, D43);
   every verified stop gets an outside-area check against the city viewport
   (D25, D44).

One 60-second DeadlineScope bounds verification, admission waits and every
in-flight provider await (D19, D23). Provider calls per plan: 1 city lookup +
1 per distinct stop place, then at most N-1 routing calls; all through the
shared budget and accounting seam. The legacy /api/plan endpoint is unchanged.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NoReturn
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.core.limiter import PLAN_LIMITS, limiter, request_cost
from app.models.request import ItineraryRequest
from app.models.response import (
    CompletePlan,
    ErrorDetails,
    FailedLeg,
    KnownStop,
    PartialPlan,
    PlannedLeg,
    PlanResult,
    Warning,
    WarningSeverity,
)
from app.services.adapter import GooglePlacesAdapter, GoogleRoutesAdapter
from app.services.area import (
    AREA_UNAVAILABLE_MESSAGE,
    OUTSIDE_AREA_MESSAGE,
    area_status,
)
from app.services.departure import DepartureError, resolve_departure
from app.services.engine import (
    DuplicateInstanceIdError,
    OperationCancelledError,
    OperationContext,
    PlacesAdapter,
    ProgressEmitter,
    RoutesAdapter,
    place_type_defaults,
    plan_sequential,
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

# v2 planning endpoints share one per-IP counter (existing plan limits).
_PLAN_V2_SCOPE = "plan-v2"


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


def _hours_warnings(timeline: list[Any]) -> list[Warning]:
    """Warnings for the user's own order. Nothing is dropped or reordered."""
    warnings: list[Warning] = []
    stop_index = -1
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


def _area_warnings(itinerary: VerifiedItinerary) -> list[Warning]:
    """D44: compare every verified stop (known or unknown timing) with the viewport."""
    viewport = itinerary.city.viewport
    if viewport is None:
        return [Warning(severity="info", message=AREA_UNAVAILABLE_MESSAGE, code="area_unavailable")]
    return [
        Warning(
            severity="warning",
            message=OUTSIDE_AREA_MESSAGE,
            affects_stop_index=i,
            affects_instance_id=stop.instance_id,
            code="outside_city_area",
        )
        for i, stop in enumerate(itinerary.stops)
        if area_status(viewport, stop.lat, stop.lng) == "outside"
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
    itinerary = await verify_itinerary(req, places, ctx, deadline)

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

    overview_url = _overview_url([(v.lat, v.lng) for v in itinerary.stops])
    warnings = _hours_warnings(timeline) + _area_warnings(itinerary)
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


def _validated_departure(req: ItineraryRequest) -> datetime:
    try:
        return resolve_departure(req.departure, mode=req.mode, now=_now())
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
