"""POST /api/v2/plan -- sequential-engine planning endpoint.

Uses ItineraryRequest (pre-resolved place selections, destination-local
departure time with DST disambiguation, operation identity). Returns a
PlanResult (CompletePlan or PartialPlan).

Differences from /api/plan:
- Pre-resolved PlaceSelections instead of free-text queries (no geocoding).
- Sequential leg execution: each leg uses the actual preceding arrival time.
- No invented fallback duration on leg failure (D1, D2).
- Destination-local departure with DST handling (D14, D40-41).
- All stops must share one timezone (D29).
- 60-second overall deadline (D6).
"""

from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.core.limiter import PLAN_LIMITS, limiter, request_cost
from app.models.request import ItineraryRequest
from app.models.response import (
    CompletePlan,
    FailedLeg,
    PartialPlan,
    PlannedLeg,
    PlanResult,
)
from app.services.adapter import GoogleRoutesAdapter
from app.services.departure import (
    AmbiguousDepartureError,
    NonExistentDepartureError,
    resolve_departure,
)
from app.services.engine import (
    OperationCancelledError,
    OperationContext,
    plan_sequential,
    resolve_durations,
)
from app.services.errors import TimezoneConflictError
from app.services.verifier import verify_stops

router = APIRouter(prefix="/api/v2", tags=["plan_v2"])


class _NullEmitter:
    """No-op progress emitter -- streaming wired in Step 5."""

    async def emit(self, event: object) -> None:
        return


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


@router.post("/plan", response_model=PlanResult)
@limiter.limit(PLAN_LIMITS, cost=request_cost)
async def plan_v2(request: Request, req: ItineraryRequest) -> PlanResult:
    """Generate a timeline using the sequential planning engine.

    Verifies stop selections and departure time before any routing calls.
    A failed leg preserves the valid prefix and leaves downstream times
    unknown -- no fallback durations are invented (D1, D2).
    """
    deadline = DeadlineScope()

    # Resolve destination-local departure to UTC (D14, D40-41).
    try:
        departure_utc = resolve_departure(req.departure)
    except (NonExistentDepartureError, AmbiguousDepartureError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Verify stops and derive trip timezone (offline, no API calls) (D29, D45).
    try:
        verified_stops, trip_tz = verify_stops(req.stops, deadline)
    except TimezoneConflictError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DeadlineExceededError as exc:
        raise HTTPException(
            status_code=503, detail="Operation deadline exceeded during verification"
        ) from exc

    # Resolve stay durations (D11 rules: first/last = 0, explicit wins, 60-min fallback).
    stops_for_resolver = [(s.instance_id, s.stay_minutes) for s in req.stops]
    durations = resolve_durations(stops_for_resolver, {})

    # Run the sequential planner.
    ctx = OperationContext(
        operation_id=req.operation_id,
        input_revision=req.input_revision,
    )
    try:
        timeline = await plan_sequential(
            stops=verified_stops,
            durations=durations,
            departure=departure_utc,
            mode=req.mode,
            routes=GoogleRoutesAdapter(),
            emitter=_NullEmitter(),
            ctx=ctx,
            deadline=deadline,
        )
    except (OperationCancelledError, DeadlineExceededError) as exc:
        raise HTTPException(status_code=503, detail="Operation timed out or was cancelled") from exc

    # Build the result.
    overview_url = _overview_url([(v.lat, v.lng) for v in verified_stops])

    # Find the first FailedLeg in the timeline, if any.
    failed_items = [
        (timeline_idx, item)
        for timeline_idx, item in enumerate(timeline)
        if isinstance(item, FailedLeg)
    ]

    if failed_items:
        first_failed_timeline_idx, first_failed_leg = failed_items[0]
        # Count PlannedLeg items before the failure to get the leg index.
        leg_index = sum(
            1 for item in timeline[:first_failed_timeline_idx] if isinstance(item, PlannedLeg)
        )
        return PartialPlan(
            operation_id=req.operation_id,
            input_revision=req.input_revision,
            city=req.city.name,
            mode=req.mode,
            timezone=trip_tz,
            timeline=timeline,
            failed_at_leg_index=leg_index,
            failure_reason=first_failed_leg.failure_reason,
            overview_map_url=overview_url,
        )

    return CompletePlan(
        operation_id=req.operation_id,
        input_revision=req.input_revision,
        city=req.city.name,
        mode=req.mode,
        timezone=trip_tz,
        timeline=timeline,
        overview_map_url=overview_url,
    )
