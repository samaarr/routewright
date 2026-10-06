"""Shared planning engine: protocols, value objects, and the duration resolver.

All I/O is injected through Protocol interfaces (PlacesAdapter, RoutesAdapter,
ProgressEmitter) so planning logic can be tested with deterministic fakes that
never touch the network.

plan_sequential implements ordinary sequential planning, including opening-
hours assessment of each known stop. compare_orders and refresh_suffix remain
stubs until the comparison and refresh stages.
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
    PhaseStartEvent,
    PlanFailureReason,
    PlannedLeg,
    StopReadyEvent,
    UnknownStop,
)
from app.services.errors import (
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
) -> list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]:
    """Sequential leg planner (D1, D2) with opening-hours assessment (D42, D43).

    Computes each leg using the actual preceding arrival time. On routing
    failure produces a valid prefix + FailedLeg + UnknownStop items.
    No fallback durations are invented for failed legs.

    Args:
        stops: Verified stop list from the verifier.
        durations: Resolved stay durations (D11 rules applied).
        departure: UTC-aware departure datetime for the first stop.
        mode: Transport mode for all legs.
        routes: Routing adapter (injected -- real or fake).
        emitter: Progress emitter (injected -- streaming or no-op).
        ctx: Operation context carrying identity and call counters.
        deadline: Active 60-second deadline scope. Each routing await is
            bounded by its remaining time, not just checked between calls.
        trip_timezone: Verified IANA zone; hours are assessed in it.

    Returns:
        Flat timeline of KnownStop / PlannedLeg / FailedLeg / UnknownStop.
        A FailedLeg terminates the valid prefix; all subsequent stops are
        UnknownStop with no timing fields.
    """
    n = len(stops)
    n_legs = n - 1
    timeline: list[KnownStop | PlannedLeg | FailedLeg | UnknownStop] = []
    cursor = departure  # Threads actual arrival forward after each leg.

    completed_legs = 0
    await emitter.emit(
        PhaseStartEvent(
            operation_id=ctx.operation_id,
            input_revision=ctx.input_revision,
            phase="routing",
        )
    )

    for i, stop in enumerate(stops):
        stay_min = durations.get(stop.instance_id)
        arrive_at = cursor
        depart_at = cursor + timedelta(minutes=stay_min)
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
                stop_index=i,
                stop=known_stop,
            )
        )

        if i >= n_legs:
            # Last stop: no leg follows.
            continue

        next_stop = stops[i + 1]

        await emitter.emit(
            LegProgressEvent(
                operation_id=ctx.operation_id,
                input_revision=ctx.input_revision,
                leg_index=i,
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
                    leg_index=i,
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
                leg_index=i,
                leg=planned_leg,
                completed_legs=completed_legs,
                total_legs=n_legs,
            )
        )

    await emitter.emit(
        PhaseCompleteEvent(
            operation_id=ctx.operation_id,
            input_revision=ctx.input_revision,
            phase="routing",
        )
    )

    return timeline


# ---------------------------------------------------------------------------
# Engine entry points (stubs -- implemented in Steps 6 and 7)
# ---------------------------------------------------------------------------


async def compare_orders(
    original: list[VerifiedStop],
    alternative: list[VerifiedStop],
    durations: ResolvedDurations,
    departure: datetime,
    mode: TransportMode,
    routes: RoutesAdapter,
    emitter: ProgressEmitter,
    ctx: OperationContext,
    deadline: DeadlineScope,
) -> tuple[
    list[KnownStop | PlannedLeg | FailedLeg | UnknownStop],
    list[KnownStop | PlannedLeg | FailedLeg | UnknownStop],
]:
    """Comparison planner -- implemented in Step 7."""
    raise NotImplementedError("compare_orders: implemented in Step 7")


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
) -> list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]:
    """Refresh planner -- implemented in Step 6."""
    raise NotImplementedError("refresh_suffix: implemented in Step 6")
