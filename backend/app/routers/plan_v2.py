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
from app.core.limiter import PLAN_LIMITS, REFRESH_LIMITS, limiter, request_cost
from app.models.request import ItineraryRequest, RefreshRequest
from app.models.response import (
    CompletePlan,
    ErrorDetails,
    ErrorOutcome,
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
    Warning,
    WarningSeverity,
)
from app.services.adapter import GooglePlacesAdapter, GoogleRoutesAdapter
from app.services.area import (
    AREA_UNAVAILABLE_MESSAGE,
    OUTSIDE_AREA_MESSAGE,
    area_status,
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
    itinerary: VerifiedItinerary, first_stop_index: int = 0, skip_first: bool = False
) -> list[Warning]:
    """D44: compare every verified stop (known or unknown timing) with the viewport.

    For a refresh, ``itinerary.stops`` starts at stop k (global index
    ``first_stop_index``), which belongs to the unchanged prefix and is skipped.
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
        for i, stop in enumerate(itinerary.stops)
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
    ) -> None:
        """Plan stream for an ItineraryRequest (needs ``departure_utc``), or a
        refresh stream for a RefreshRequest."""
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
        try:
            result: PlanResult | RefreshResult
            if isinstance(self.req, RefreshRequest):
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
            else:
                outcome = PlanOutcome(result=result)
        except asyncio.CancelledError:
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
    departure_utc = _validated_departure(req)
    stream = PlanStream(
        req,
        departure_utc=departure_utc,
        places=places_adapter(),
        routes=routes_adapter(),
        ctx=ctx,
        deadline=deadline,
        receive=request.receive,
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
    _validated_refresh(req)
    stream = PlanStream(
        req,
        places=places_adapter(),
        routes=routes_adapter(),
        ctx=ctx,
        deadline=deadline,
        receive=request.receive,
    )
    return StreamingResponse(
        stream.events(),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"X-Accel-Buffering": "no"},
    )
