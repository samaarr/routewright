"""Shared planning engine: protocols, value objects, and the duration resolver.

All I/O is injected through Protocol interfaces (PlacesAdapter, RoutesAdapter,
ProgressEmitter) so planning logic can be tested with deterministic fakes that
never touch the network.

plan_sequential (ordinary planning) and refresh_suffix (D21 suffix refresh)
share one sequential routing loop, including opening-hours assessment of each
known stop. The Step 8 comparison (services/comparison.py) runs it twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.models.request import TransportMode
from app.models.response import (
    FailedLeg,
    KnownStop,
    LegProgressEvent,
    LegReadyEvent,
    PhaseCompleteEvent,
    PhaseName,
    PhaseStartEvent,
    PlanFailureReason,
    PlannedLeg,
    StopReadyEvent,
    UnknownStop,
)
from app.services.errors import (
    ArrivalUnknownError,
    NoRouteError,
    PlaceRole,
    ProviderCapacityError,
    ProviderTemporaryError,
    QuotaExceededError,
)
from app.services.place_details import PlaceDetails
from app.services.stay_defaults import lookup_stay_minutes
from app.services.venue_hours import VenueHours, assess_hours

# ---------------------------------------------------------------------------
# Engine-layer exceptions
# ---------------------------------------------------------------------------


class OperationCancelledError(Exception):
    """Raised when the operation scope is cancelled (client disconnect)."""


class OperationTimeoutError(Exception):
    """Raised when the 60-second operation deadline is exceeded."""


# ---------------------------------------------------------------------------
# Routing result — returned by RoutesAdapter, assembled into PlannedLeg by engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingResult:
    """Raw result from a single routing call.

    The engine augments this with stop identity fields (from_stop_id,
    to_stop_id, names) to construct a PlannedLeg.
    """

    duration_seconds: int
    distance_meters: int | None
    arrive_at: datetime
    summary: str
    map_url: str


# ---------------------------------------------------------------------------
# Adapter protocols — inject real Google clients or deterministic fakes
# ---------------------------------------------------------------------------


@runtime_checkable
class PlacesAdapter(Protocol):
    """Fetches provider-confirmed details for one selected place ID."""

    async def fetch_details(self, place_id: str, *, role: PlaceRole) -> PlaceDetails:
        """Return details or raise PlaceVerificationError / ProviderTemporaryError /
        QuotaExceededError / ProviderCapacityError."""
        ...  # pragma: no cover


@runtime_checkable
class RoutesAdapter(Protocol):
    """Fetches routing data for a single origin->destination leg."""

    async def fetch_leg(
        self,
        *,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: TransportMode,
        depart_at: datetime,
    ) -> RoutingResult:
        """Return a RoutingResult or raise NoRouteError / ProviderTemporaryError."""
        ...  # pragma: no cover


@runtime_checkable
class ProgressEmitter(Protocol):
    """Emits incremental streaming events during a planning operation."""

    async def emit(self, event: object) -> None:
        """Fire-and-forget: emit without blocking the planning loop."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedStop:
    """A stop whose identity and coordinates the Places provider confirmed.

    name/lat/lng come from the provider, never from the submitted selection.
    hours is request-scoped provider data (None = no hours returned).
    """

    instance_id: str
    place_id: str
    name: str
    address: str | None
    lat: float
    lng: float
    hours: VenueHours | None = None
    primary_type: str | None = None
    types: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedDurations:
    """Stay durations keyed by instance_id, ready for the sequential leg loop.

    First and last stops always have 0-minute stays (D11). Middle stops use
    the explicit user value when provided; otherwise the place-type default.
    The ``sources`` dict records whether each duration came from a user
    override or the default table (used to populate KnownStop.stay_source).
    """

    durations: dict[str, int]
    sources: dict[str, Literal["user", "default"]] = field(default_factory=dict)

    def get(self, instance_id: str) -> int:
        return self.durations.get(instance_id, 0)

    def get_source(self, instance_id: str) -> Literal["user", "default"]:
        return self.sources.get(instance_id, "default")


# ---------------------------------------------------------------------------
# Operation context — identity, cancellation, call accounting
# ---------------------------------------------------------------------------


@dataclass
class OperationContext:
    """Shared state for a single plan / comparison / refresh operation.

    Carries operation identity (echoed on every streaming event, used to
    reject stale responses), cancellation flag, and call-accounting counters.
    """

    operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    input_revision: int = 0
    _cancelled: bool = field(default=False, init=False)
    _routing_calls: int = field(default=0, init=False)
    _places_calls: int = field(default=0, init=False)

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def record_routing_call(self) -> None:
        self._routing_calls += 1

    def record_places_call(self) -> None:
        self._places_calls += 1

    @property
    def routing_calls(self) -> int:
        return self._routing_calls

    @property
    def places_calls(self) -> int:
        return self._places_calls


# ---------------------------------------------------------------------------
# Duration resolver (D11)
# ---------------------------------------------------------------------------


class DuplicateInstanceIdError(ValueError):
    """Two stops share an instance_id; durations could not be keyed safely."""


def place_type_defaults(stops: list[VerifiedStop]) -> dict[str, int]:
    """Place-type default stay per instance_id from provider-verified types.

    Uses the existing stay_defaults table (primaryType first, then the types
    array). Repeated visits to one place get the same default but remain
    separate entries keyed by their own instance_id.
    """
    return {s.instance_id: lookup_stay_minutes(s.primary_type, list(s.types))[0] for s in stops}


def resolve_durations(
    stops: list[tuple[str, int | None]],
    defaults: dict[str, int],
) -> ResolvedDurations:
    """Resolve fixed stay durations once, from the ORIGINAL input order (D11).

    Rules:
    1. An explicit user value wins at every position, including the first and
       last stops and an explicit zero.
    2. Otherwise the original first and last stops default to 0 minutes.
    3. Otherwise middle stops use the place-type default from ``defaults``
       (stay_defaults table); 60 min only if a default is absent.

    The result is keyed by stop-instance ID so it can be carried unchanged
    through later reordering/comparison without re-applying positional rules.

    Args:
        stops: Ordered ``(instance_id, explicit_stay_minutes_or_None)``.
        defaults: Place-type default minutes per ``instance_id``.

    Raises:
        DuplicateInstanceIdError: an instance_id appears more than once.
    """
    if not stops:
        return ResolvedDurations(durations={})

    result: dict[str, int] = {}
    source_map: dict[str, Literal["user", "default"]] = {}
    n = len(stops)

    for i, (instance_id, explicit) in enumerate(stops):
        if instance_id in result:
            raise DuplicateInstanceIdError(f"duplicate instance_id {instance_id!r}")
        if explicit is not None:
            result[instance_id] = explicit
            source_map[instance_id] = "user"
        elif i == 0 or i == n - 1:
            result[instance_id] = 0
            source_map[instance_id] = "default"
        else:
            result[instance_id] = defaults.get(instance_id, 60)
            source_map[instance_id] = "default"

    return ResolvedDurations(durations=result, sources=source_map)


# ---------------------------------------------------------------------------
# Map URL helpers (engine-internal)
# ---------------------------------------------------------------------------


def _maps_search_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"


# ---------------------------------------------------------------------------
# Sequential planner (Step 3)
# ---------------------------------------------------------------------------


async def _route_sequence(
    stops: list[VerifiedStop],
    durations: ResolvedDurations,
    *,
    start: datetime,
    first_stop_known: bool,
    index_offset: int,
    mode: TransportMode,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
    trip_timezone: str,
    phase: PhaseName = "routing",
) -> list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]:
    """Shared sequential routing loop for planning, refresh and comparison.

    Each leg departs at the actual arrival of the previous leg plus the next
    stop's fixed stay (D1). On the first failed leg the loop stops: a
    FailedLeg is recorded and every later stop becomes an UnknownStop with no
    timing or hours (D2). Each routing await is bounded by the remaining
    deadline.

    ``first_stop_known=True`` (planning): ``start`` is the arrival at
    stops[0], which is emitted as a KnownStop. ``first_stop_known=False``
    (refresh): stops[0] belongs to the unchanged prefix; ``start`` is the
    planned departure of the first leg and stops[0] is not emitted.
    ``index_offset`` makes stop/leg indices in events global.
    """
    n = len(stops)
    n_legs = n - 1
    timeline: list[KnownStop | PlannedLeg | FailedLeg | UnknownStop] = []
    cursor = start  # Threads actual arrival forward after each leg.

    completed_legs = 0
    await emitter.emit(
        PhaseStartEvent(
            operation_id=ctx.operation_id,
            input_revision=ctx.input_revision,
            phase=phase,
        )
    )

    for i, stop in enumerate(stops):
        stay_min = durations.get(stop.instance_id)
        arrive_at = cursor
        depart_at = cursor + timedelta(minutes=stay_min)
        if i == 0 and not first_stop_known:
            # Refresh: the origin stop is part of the confirmed prefix; the
            # first leg leaves at its planned departure (never "now", D21).
            depart_at = start
        else:
            await _emit_known_stop(
                stop,
                arrive_at,
                depart_at,
                stay_min,
                durations,
                trip_timezone,
                timeline,
                emitter,
                ctx,
                index_offset + i,
            )

        if i >= n_legs:
            # Last stop: no leg follows.
            continue

        next_stop = stops[i + 1]

        await emitter.emit(
            LegProgressEvent(
                operation_id=ctx.operation_id,
                input_revision=ctx.input_revision,
                leg_index=index_offset + i,
                total_legs=n_legs,
            )
        )

        failure_reason: PlanFailureReason | None = None
        failure_message: str | None = None

        try:
            # Check deadline and cancellation before each network call so that
            # an expired deadline produces a FailedLeg rather than an exception.
            deadline.check()
            if ctx.is_cancelled():
                raise OperationCancelledError("Operation was cancelled")
            ctx.record_routing_call()
            result = await deadline.bound(
                routes.fetch_leg(
                    origin_lat=stop.lat,
                    origin_lng=stop.lng,
                    dest_lat=next_stop.lat,
                    dest_lng=next_stop.lng,
                    mode=mode,
                    depart_at=depart_at,
                )
            )
        except NoRouteError:
            failure_reason = "no_route"
            failure_message = f"No {mode} route found from {stop.name!r} to {next_stop.name!r}."
        except ArrivalUnknownError:
            failure_reason = "arrival_unknown"
            failure_message = (
                "The routing response didn't include enough timing to know when you'd arrive."
            )
        except ProviderTemporaryError:
            failure_reason = "provider_temporary"
            failure_message = "Routing service temporarily unavailable."
        except QuotaExceededError:
            failure_reason = "quota_exceeded"
            failure_message = "The daily routing allowance has been reached."
        except ProviderCapacityError:
            failure_reason = "provider_capacity"
            failure_message = "The routing service is busy. Try again shortly."
        except DeadlineExceededError:
            failure_reason = "deadline_exceeded"
            failure_message = "Operation deadline exceeded during routing."
        except OperationCancelledError:
            failure_reason = "cancelled"
            failure_message = "Operation was cancelled."

        if failure_reason is not None:
            failed_leg = FailedLeg(
                from_stop_id=stop.instance_id,
                to_stop_id=next_stop.instance_id,
                from_name=stop.name,
                to_name=next_stop.name,
                failure_reason=failure_reason,
                failure_message=failure_message,
            )
            timeline.append(failed_leg)

            await emitter.emit(
                LegReadyEvent(
                    operation_id=ctx.operation_id,
                    input_revision=ctx.input_revision,
                    leg_index=index_offset + i,
                    leg=failed_leg,
                    completed_legs=completed_legs,
                    total_legs=n_legs,
                )
            )

            # All remaining stops have unknown timing.
            for j in range(i + 1, n):
                timeline.append(
                    UnknownStop(
                        instance_id=stops[j].instance_id,
                        place_id=stops[j].place_id,
                        name=stops[j].name,
                    )
                )
            break

        # Success: thread the actual arrival forward as the next stop's cursor.
        planned_leg = PlannedLeg(
            from_stop_id=stop.instance_id,
            to_stop_id=next_stop.instance_id,
            from_name=stop.name,
            to_name=next_stop.name,
            mode=mode,
            duration_seconds=result.duration_seconds,
            # Same definition everywhere (display, totals, comparison savings).
            journey_seconds=int((result.arrive_at - depart_at).total_seconds()),
            distance_meters=result.distance_meters,
            depart_at=depart_at,
            arrive_at=result.arrive_at,
            summary=result.summary,
            map_url=result.map_url,
        )
        timeline.append(planned_leg)
        cursor = result.arrive_at  # Key: use actual arrival for next leg departure.
        completed_legs += 1

        await emitter.emit(
            LegReadyEvent(
                operation_id=ctx.operation_id,
                input_revision=ctx.input_revision,
                leg_index=index_offset + i,
                leg=planned_leg,
                completed_legs=completed_legs,
                total_legs=n_legs,
            )
        )

    await emitter.emit(
        PhaseCompleteEvent(
            operation_id=ctx.operation_id,
            input_revision=ctx.input_revision,
            phase=phase,
        )
    )

    return timeline


async def _emit_known_stop(
    stop: VerifiedStop,
    arrive_at: datetime,
    depart_at: datetime,
    stay_min: int,
    durations: ResolvedDurations,
    trip_timezone: str,
    timeline: list[KnownStop | PlannedLeg | FailedLeg | UnknownStop],
    emitter: ProgressEmitter,
    ctx: OperationContext,
    stop_index: int,
) -> None:
    # Assessed against this stop's actual computed arrival/departure.
    hours_status, hours_detail = assess_hours(stop.hours, arrive_at, depart_at, trip_timezone)
    known_stop = KnownStop(
        instance_id=stop.instance_id,
        place_id=stop.place_id,
        name=stop.name,
        address=stop.address,
        lat=stop.lat,
        lng=stop.lng,
        arrive_at=arrive_at,
        depart_at=depart_at,
        stay_minutes=stay_min,
        stay_source=durations.get_source(stop.instance_id),
        map_url=_maps_search_url(stop.lat, stop.lng),
        hours_status=hours_status,
        hours_detail=hours_detail,
    )
    timeline.append(known_stop)
    await emitter.emit(
        StopReadyEvent(
            operation_id=ctx.operation_id,
            input_revision=ctx.input_revision,
            stop_index=stop_index,
            stop=known_stop,
        )
    )


async def plan_sequential(
    stops: list[VerifiedStop],
    durations: ResolvedDurations,
    departure: datetime,
    mode: TransportMode,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
    trip_timezone: str,
    phase: PhaseName = "routing",
) -> list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]:
    """Sequential planner (D1, D2) with opening-hours assessment (D42, D43).

    The first stop is reached at ``departure``; every later timestamp comes
    from actual routed arrivals plus fixed stays. Returns a flat timeline of
    KnownStop / PlannedLeg / FailedLeg / UnknownStop; at most N-1 routing calls.
    """
    return await _route_sequence(
        stops,
        durations,
        start=departure,
        first_stop_known=True,
        index_offset=0,
        mode=mode,
        routes=routes,
        emitter=emitter,
        ctx=ctx,
        deadline=deadline,
        trip_timezone=trip_timezone,
        phase=phase,
    )


# ---------------------------------------------------------------------------
# Engine entry points
# ---------------------------------------------------------------------------


async def refresh_suffix(
    stops: list[VerifiedStop],
    durations: ResolvedDurations,
    leg_index: int,
    planned_departure: datetime,
    mode: TransportMode,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
    trip_timezone: str,
) -> list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]:
    """Recompute the timetable from leg ``leg_index`` onward (D21).

    ``stops`` are the verified stops k..N-1 (stop k is the origin of leg k and
    stays in the caller's unchanged prefix). Leg k departs at
    ``planned_departure`` — the selected leg's planned departure, never the
    current time. Later legs depart at actual arrivals plus the preserved
    fixed stays, and downstream hours are re-assessed. At most N-1-k routing
    calls. On failure, refreshed results so far are kept and later times are
    unknown; no earlier downstream timestamps are reused.

    Returns the suffix: leg k, stop k+1, leg k+1, ... (no item for stop k).
    """
    return await _route_sequence(
        stops,
        durations,
        start=planned_departure,
        first_stop_known=False,
        index_offset=leg_index,
        mode=mode,
        routes=routes,
        emitter=emitter,
        ctx=ctx,
        deadline=deadline,
        trip_timezone=trip_timezone,
    )
