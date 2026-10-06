"""POST /api/v2/plan -- verified sequential planning with opening-hours assessment.

Flow (one 60-second deadline covers all of it, including in-flight awaits):

1. Departure syntax, calendar validity, clock-change handling and supported
   range — no provider calls (D14, D29).
2. Server-side verification by Place Details: city, departure-zone match, then
   stops (D13, D37, D40, D41, D45). Any failure here returns a structured
   error and makes ZERO routing calls.
3. Fixed stay durations from the original order and provider-verified place
   types (D11).
4. Sequential routing: each leg departs at the previous stop's actual arrival
   plus its fixed stay; a failed leg keeps the valid prefix and leaves the
   rest unknown (D1, D2). Each known stop's hours are assessed against its
   actual visit (D24, D42, D43) and surfaced as warnings.

Provider calls for one plan: at most 1 (city, shared if it is also a stop)
+ distinct stop place IDs Place Details calls, then at most N-1 routing
calls. All go through the shared provider budget; no automatic retries.

The legacy /api/plan endpoint is unchanged and still serves the frontend.
"""

from datetime import datetime, timezone
from typing import Any, NoReturn
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.core.limiter import PLAN_LIMITS, limiter, request_cost
from app.models.request import ItineraryRequest
from app.models.response import (
    CompletePlan,
    FailedLeg,
    KnownStop,
    PartialPlan,
    PlannedLeg,
    PlanResult,
    Warning,
    WarningSeverity,
)
from app.services.adapter import GooglePlacesAdapter, GoogleRoutesAdapter
from app.services.departure import DepartureError, resolve_departure
from app.services.engine import (
    DuplicateInstanceIdError,
    OperationCancelledError,
    OperationContext,
    PlacesAdapter,
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
)
from app.services.hours import hours_eligibility
from app.services.verifier import verify_itinerary

router = APIRouter(prefix="/api/v2", tags=["plan_v2"])


class _NullEmitter:
    """No-op progress emitter -- HTTP streaming is wired in a later stage."""

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


def _fail(
    status: int, code: str, message: str, headers: dict[str, str] | None = None, **extra: Any
) -> NoReturn:
    detail: dict[str, Any] = {"error": code, "message": message}
    detail.update({k: v for k, v in extra.items() if v is not None})
    raise HTTPException(status_code=status, detail=detail, headers=headers)


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
            opens = f" It opens at {detail.opens_at}." if detail and detail.opens_at else ""
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


@router.post("/plan", response_model=PlanResult)
@limiter.limit(PLAN_LIMITS, cost=request_cost)
async def plan_v2(request: Request, req: ItineraryRequest) -> PlanResult:
    """Verify selections, then plan sequentially with opening-hours assessment."""
    deadline = DeadlineScope()
    ctx = OperationContext(operation_id=req.operation_id, input_revision=req.input_revision)

    # 1. Departure validity — before any provider call.
    try:
        departure_utc = resolve_departure(req.departure, mode=req.mode, now=_now())
    except DepartureError as exc:
        _fail(422, exc.code, str(exc))

    # 2. Verification — no routing calls happen unless this fully succeeds.
    def stop_ids_for(place_id: str) -> list[str]:
        return [s.instance_id for s in req.stops if s.selection.place_id == place_id]

    try:
        itinerary = await verify_itinerary(req, places_adapter(), ctx, deadline)
    except PlaceVerificationError as exc:
        _fail(
            422,
            "place_invalid",
            "A selected place could not be verified. Please select it again.",
            role=exc.role,
            reason=exc.reason,
            place_id=exc.place_id,
            instance_ids=stop_ids_for(exc.place_id) if exc.role == "stop" else None,
            moved_place_id=exc.moved_place_id,
        )
    except ProviderTemporaryError:
        _fail(
            503,
            "place_temporary",
            "Place verification is temporarily unavailable. Try again shortly.",
        )
    except QuotaExceededError:
        _fail(429, "quota_exceeded", "The daily provider allowance has been reached.")
    except ProviderCapacityError:
        _fail(
            503,
            "provider_capacity",
            "The service is busy. Try again shortly.",
            headers={"Retry-After": "2"},
        )
    except TimezoneUnresolvedError as exc:
        _fail(
            422,
            "timezone_unresolved",
            f"The timezone for {exc.name} could not be determined. "
            + ("Select another city." if exc.role == "city" else "Select another place."),
            role=exc.role,
            instance_ids=[exc.instance_id] if exc.instance_id else None,
        )
    except TimezoneConflictError as exc:
        _fail(
            422,
            "timezone_conflict",
            f"{exc.stop_name} is in {exc.detected_tz}, but this trip is in "
            f"{exc.expected_tz}. Trips must stay within one timezone.",
            role="stop",
            instance_ids=[exc.instance_id] if exc.instance_id else None,
        )
    except DepartureError as exc:  # zone mismatch, found after city verification
        _fail(422, exc.code, str(exc))
    except DeadlineExceededError:
        _fail(503, "deadline_exceeded", "The request took too long. Try again.")

    # 3. Fixed durations from the original order and verified place types.
    try:
        durations = resolve_durations(
            [(s.instance_id, s.stay_minutes) for s in req.stops],
            place_type_defaults(itinerary.stops),
        )
    except DuplicateInstanceIdError:
        _fail(422, "duplicate_instance_id", "Each stop must have a unique instance_id.")

    # 4. Sequential routing + hours.
    try:
        timeline = await plan_sequential(
            stops=itinerary.stops,
            durations=durations,
            departure=departure_utc,
            mode=req.mode,
            routes=routes_adapter(),
            emitter=_NullEmitter(),
            ctx=ctx,
            deadline=deadline,
            trip_timezone=itinerary.timezone,
        )
    except (OperationCancelledError, DeadlineExceededError):
        _fail(503, "deadline_exceeded", "The request took too long. Try again.")

    overview_url = _overview_url([(v.lat, v.lng) for v in itinerary.stops])
    warnings = _hours_warnings(timeline)

    failed = next(
        ((i, item) for i, item in enumerate(timeline) if isinstance(item, FailedLeg)), None
    )
    if failed is not None:
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
