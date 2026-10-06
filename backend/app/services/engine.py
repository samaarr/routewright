"""Shared planning engine: protocols, value objects, and the duration resolver.

All I/O is injected through Protocol interfaces (PlacesAdapter, RoutesAdapter,
ProgressEmitter) so planning logic can be tested with deterministic fakes that
never touch the network.

plan_sequential is implemented in Step 3.
compare_orders and refresh_suffix remain stubs until Steps 7 and 6.
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
    HoursStatus,
    KnownStop,
    LegProgressEvent,
    LegReadyEvent,
    OperationStartEvent,
    PhaseCompleteEvent,
    PlanFailureReason,
    PlannedLeg,
    StopReadyEvent,
    UnknownStop,
)
from app.services.errors import NoRouteError, ProviderTemporaryError, QuotaExceededError

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
    """Verifies a place_id and returns confirmed coordinates."""

    async def verify_place(self, place_id: str, name: str) -> tuple[float, float]:
        """Return (lat, lng) or raise PlaceVerificationError."""
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
    """A stop whose coordinates have been confirmed by the Places adapter."""

    instance_id: str
    place_id: str
    name: str
    address: str | None
    lat: float
    lng: float
    hours_status: HoursStatus = "unknown"


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


def resolve_durations(
    stops: list[tuple[str, int | None]],
    defaults: dict[str, int],
) -> ResolvedDurations:
    """Apply D11 stay-duration rules for an ordered list of stops.

    Rules (in precedence order):
    1. First stop: 0 minutes always (departure point -- no visit counted).
    2. Last stop: 0 minutes always (arrival point -- no visit counted).
    3. Explicit user value wins over the place-type default.
    4. Otherwise: place-type default from ``defaults``, falling back to 60 min.

    Args:
        stops: Ordered list of ``(instance_id, explicit_stay_minutes_or_None)``.
        defaults: Place-type default minutes per ``instance_id``.

    Returns:
        ``ResolvedDurations`` with every ``instance_id`` in ``stops`` present.
    """
    if not stops:
        return ResolvedDurations(durations={})

    result: dict[str, int] = {}
    source_map: dict[str, Literal["user", "default"]] = {}
    n = len(stops)

    for i, (instance_id, explicit) in enumerate(stops):
        if i == 0 or i == n - 1:
            result[instance_id] = 0
            source_map[instance_id] = "default"
        elif explicit is not None:
            result[instance_id] = explicit
            source_map[instance_id] = "user"
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
) -> list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]:
    """Sequential leg planner (D1, D2).

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
        deadline: Active 60-second deadline scope.

    Returns:
        Flat timeline of KnownStop / PlannedLeg / FailedLeg / UnknownStop.
        A FailedLeg terminates the valid prefix; all subsequent stops are
        UnknownStop with no timing fields.
    """
    n = len(stops)
    n_legs = n - 1
    timeline: list[KnownStop | PlannedLeg | FailedLeg | UnknownStop] = []
    cursor = departure  # Threads actual arrival forward after each leg.

    await emitter.emit(
        OperationStartEvent(
            operation_id=ctx.operation_id,
            input_revision=ctx.input_revision,
            phases=["routing"],
        )
    )

    for i, stop in enumerate(stops):
        stay_min = durations.get(stop.instance_id)
        arrive_at = cursor
        depart_at = cursor + timedelta(minutes=stay_min)

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
            hours_status=stop.hours_status,
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
            result = await routes.fetch_leg(
                origin_lat=stop.lat,
                origin_lng=stop.lng,
                dest_lat=next_stop.lat,
                dest_lng=next_stop.lng,
                mode=mode,
                depart_at=depart_at,
            )
        except NoRouteError:
            failure_reason = "no_route"
            failure_message = f"No {mode} route found from {stop.name!r} to {next_stop.name!r}."
        except ProviderTemporaryError:
            failure_reason = "provider_temporary"
            failure_message = "Routing service temporarily unavailable."
        except QuotaExceededError:
            failure_reason = "quota_exceeded"
            failure_message = "API quota reached for this operation."
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

        await emitter.emit(
            LegReadyEvent(
                operation_id=ctx.operation_id,
                input_revision=ctx.input_revision,
                leg_index=i,
                leg=planned_leg,
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
