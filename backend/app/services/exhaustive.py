"""Experimental exhaustive optimiser for exactly four destinations (2026-10-08).

Approved as an experiment that supersedes the one-candidate comparison rules
only within this flow. It evaluates every visiting order of four distinct
destinations and picks the one whose last visit ends earliest.

Model (all instants UTC-aware; local time only for display and hours):

    a_1 = T0                         every order starts AT its first destination
    d_i = a_i + s_{p_i}              fixed stay per destination (by instance)
    a_{i+1} = G(p_i, p_{i+1}, d_i)   Google-backed arrival (incl. final walk)
    C(p) = a_4 + s_{p_4}             completion: end of the last visit
    E(p) = C(p) - T0

Assumptions, stated to the user before running:
- Travel TO the first destination is excluded: each order begins at its
  own first destination at T0. Orders therefore differ in where the day
  starts, which a real traveller would have to reach first.
- Endpoints are unrestricted; existing pins do not apply.
- Stays are the explicit values sent by the client (the current plan's
  resolved durations) and move with their destination; nothing is defaulted
  by position.
- Opening hours are assessed and reported as warnings but never reject,
  penalise or reorder a candidate.
- No automatic changes to departure time, stays or destinations.

Ranking among complete orders only: earliest C(p); exact ties by
straight-line path length D(p) (haversine, compared at millimetre
precision — a tie-breaker, not transit distance or proof of least
backtracking); then the original order; then instance-ID order.

Budgets: 24 orders x 3 legs = 72 routing calls at most (RoutingBudget counts
every issued call, failed or not; no retries, no cross-candidate caching).
The original order is one of the 24, never recalculated separately. Legs of
an order run sequentially; orders run one after another.

Failure handling: ``no_route`` / ``arrival_unknown`` fail only that order and
the search continues. Cancellation, deadline, quota exhaustion, unavailable
usage controls / provider capacity and provider-wide errors interrupt the
whole search, which is then reported as incomplete.

This module reuses the shared engine (plan_sequential: sequential legs,
destination-arrival parsing, hours assessment, deadline/cancellation and call
accounting) and the existing RoutingBudget and haversine implementation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise, permutations
from typing import Literal

from app.core.deadline import DeadlineScope
from app.models.request import EXHAUSTIVE_STOP_COUNT, ExhaustiveRequest, TransportMode
from app.models.response import (
    FailedLeg,
    KnownStop,
    PlanFailureReason,
    PlannedLeg,
    UnknownStop,
    WinnerBasis,
)
from app.services.comparison import RoutingBudget
from app.services.engine import (
    OperationContext,
    ResolvedDurations,
    RoutesAdapter,
    VerifiedStop,
    plan_sequential,
)
from app.services.geo import haversine_km

ORDER_COUNT = 24
LEGS_PER_ORDER = EXHAUSTIVE_STOP_COUNT - 1
ROUTING_BUDGET = ORDER_COUNT * LEGS_PER_ORDER  # 72
DEADLINE_SECONDS = 240.0

# Failures that are specific to one order; the search continues.
CANDIDATE_FAILURES: frozenset[str] = frozenset({"no_route", "arrival_unknown"})

Timeline = list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]


class _Silent:
    """Per-candidate leg events are not streamed (24 timelines); the caller
    emits its own progress after each order."""

    async def emit(self, event: object) -> None:
        return None


@dataclass
class Evaluation:
    """Exact (unrounded) evaluation of one order."""

    order: tuple[VerifiedStop, ...]
    is_original: bool
    status: Literal["complete", "failed", "interrupted"]
    timeline: Timeline
    distance_m: float
    routing_calls: int
    completion_at: datetime | None = None
    elapsed_seconds: int | None = None
    failure_reason: PlanFailureReason | None = None
    failure_message: str | None = None

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(s.instance_id for s in self.order)


@dataclass
class SearchOutcome:
    evaluations: list[Evaluation] = field(default_factory=list)
    interruption_reason: PlanFailureReason | None = None
    routing_calls: int = 0

    @property
    def complete(self) -> list[Evaluation]:
        return [e for e in self.evaluations if e.status == "complete"]

    @property
    def failed(self) -> list[Evaluation]:
        return [e for e in self.evaluations if e.status == "failed"]

    @property
    def evaluated(self) -> int:
        return len(self.complete) + len(self.failed)

    @property
    def search_complete(self) -> bool:
        return self.interruption_reason is None and self.evaluated == ORDER_COUNT


def generate_orders(stops: Sequence[VerifiedStop]) -> list[tuple[VerifiedStop, ...]]:
    """All 24 orders: the original first, then the rest in permutation order."""
    if len(stops) != EXHAUSTIVE_STOP_COUNT:
        raise ValueError("generate_orders needs exactly 4 stops")
    original = tuple(stops)
    orders = [original] + [p for p in permutations(stops) if p != original]
    ids = {tuple(s.instance_id for s in o) for o in orders}
    assert len(orders) == ORDER_COUNT and len(ids) == ORDER_COUNT, "expected 24 unique orders"
    return orders


def resolve_experiment_stays(request: ExhaustiveRequest) -> ResolvedDurations:
    """Explicit stays by instance ID, as sent (validated non-null, 0-720)."""
    stays: dict[str, int] = {}
    for spec in request.stops:
        if spec.stay_minutes is None:  # the request model already rejects this
            raise ValueError("every stop needs an explicit stay")
        stays[spec.instance_id] = spec.stay_minutes
    return ResolvedDurations(durations=stays, sources=dict.fromkeys(stays, "user"))


def geographic_path_metres(order: Sequence[VerifiedStop]) -> float:
    """Straight-line path length through ``order`` (tie-break only)."""
    return sum(haversine_km(a.lat, a.lng, b.lat, b.lng) for a, b in pairwise(order)) * 1000.0


async def evaluate_order(
    order: tuple[VerifiedStop, ...],
    stays: ResolvedDurations,
    start_utc: datetime,
    *,
    mode: TransportMode,
    routes: RoutesAdapter,
    ctx: OperationContext,
    deadline: DeadlineScope,
    trip_timezone: str,
    is_original: bool,
) -> Evaluation:
    """Evaluate one order from ``start_utc`` with the shared sequential engine."""
    calls_before = ctx.routing_calls
    timeline: Timeline = await plan_sequential(
        list(order),
        stays,
        start_utc,
        mode,
        routes,
        _Silent(),
        ctx,
        deadline,
        trip_timezone,
        phase="exhaustive_search",
    )
    calls = ctx.routing_calls - calls_before
    distance = geographic_path_metres(order)
    failed = next((i for i in timeline if isinstance(i, FailedLeg)), None)
    if failed is not None:
        status: Literal["failed", "interrupted"] = (
            "failed" if failed.failure_reason in CANDIDATE_FAILURES else "interrupted"
        )
        return Evaluation(
            order=order,
            is_original=is_original,
            status=status,
            timeline=timeline,
            distance_m=distance,
            routing_calls=calls,
            failure_reason=failed.failure_reason,
            failure_message=failed.failure_message,
        )
    last = timeline[-1]
    if not isinstance(last, KnownStop) or last.instance_id != order[-1].instance_id:
        raise RuntimeError("complete timeline must end at the last destination")
    completion = last.depart_at  # arrival at the last stop plus its fixed stay
    return Evaluation(
        order=order,
        is_original=is_original,
        status="complete",
        timeline=timeline,
        distance_m=distance,
        routing_calls=calls,
        completion_at=completion,
        elapsed_seconds=int((completion - start_utc).total_seconds()),
    )


def _rank_key(e: Evaluation) -> tuple[datetime, float, int, tuple[str, ...]]:
    assert e.completion_at is not None
    return (e.completion_at, round(e.distance_m, 3), 0 if e.is_original else 1, e.ids)


def rank_complete_candidates(
    evaluations: Sequence[Evaluation],
) -> tuple[list[Evaluation], WinnerBasis | None]:
    """Complete orders best-first, and which criterion separated the winner."""
    ranked = sorted((e for e in evaluations if e.status == "complete"), key=_rank_key)
    if not ranked:
        return [], None
    if len(ranked) == 1:
        return ranked, "completion"
    a, b = _rank_key(ranked[0]), _rank_key(ranked[1])
    basis: WinnerBasis
    if a[0] != b[0]:
        basis = "completion"
    elif a[1] != b[1]:
        basis = "distance"
    elif a[2] != b[2]:
        basis = "original"
    else:
        basis = "instance_order"
    return ranked, basis


async def optimise_exhaustive_four(
    stops: Sequence[VerifiedStop],
    stays: ResolvedDurations,
    start_utc: datetime,
    *,
    mode: TransportMode,
    routes: RoutesAdapter,
    ctx: OperationContext,
    deadline: DeadlineScope,
    trip_timezone: str,
    on_progress: Callable[[SearchOutcome], Awaitable[None]] | None = None,
) -> SearchOutcome:
    """Evaluate all 24 orders sequentially; stop the search on interruption."""
    budget = RoutingBudget(routes, ROUTING_BUDGET)
    outcome = SearchOutcome()
    for index, order in enumerate(generate_orders(stops)):
        if ctx.is_cancelled():
            outcome.interruption_reason = "cancelled"
            break
        if deadline.expired():
            outcome.interruption_reason = "deadline_exceeded"
            break
        evaluation = await evaluate_order(
            order,
            stays,
            start_utc,
            mode=mode,
            routes=budget,
            ctx=ctx,
            deadline=deadline,
            trip_timezone=trip_timezone,
            is_original=index == 0,
        )
        outcome.evaluations.append(evaluation)
        outcome.routing_calls = budget.calls
        if evaluation.status == "interrupted":
            outcome.interruption_reason = evaluation.failure_reason
            break
        if on_progress is not None:
            await on_progress(outcome)
    outcome.routing_calls = budget.calls
    return outcome
