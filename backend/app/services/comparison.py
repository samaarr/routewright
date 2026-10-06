"""Step 8 comparison helpers: one local candidate, budgets and eligibility.

Decisions 3-12, 15-20, 24, 42-43. The orchestration (verification, the two
sequential itinerary calculations and result assembly) lives in
``routers/plan_v2.execute_compare``; this module holds the parts that must be
independently testable:

- ``generate_candidate``: the EXISTING distance-only OR-Tools optimiser
  (``optimise.optimise_order``; haversine, not transit time) run once in the
  bounded solver slot. Its time limit is min(2 s, remaining deadline), so the
  worker thread always ends promptly; the slot is released when the thread
  ends. Pins apply to whichever stop instances hold the first/last positions
  when the comparison starts (D16, D17). No further candidates are searched.
- ``RoutingBudget``: hard cap of 2(N-1) routing calls per comparison (D5,
  D10). Calls are counted when issued; failed/cancelled calls stay counted.
- ``journey_seconds``: total journey time = sum over legs of (arrival -
  planned departure), so waiting for the first vehicle and transfers are
  included. A transit arrival is the last ride's scheduled arrival plus the
  documented staticDuration of the final walk to the destination
  (directions._extract_scheduled_times); if that is undocumented the leg
  fails as arrival_unknown, so no comparison is made on invented times.
- ``decide``: recommend only when both runs are complete, the candidate has
  no hours-disqualifying visit (known closure on arrival with a positive
  stay), pins and durations are intact, and the exact saving is >= 300 s.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import pairwise
from typing import Literal

from fastapi import HTTPException

from app.core.config import settings
from app.core.deadline import DeadlineExceededError, DeadlineScope
from app.core.provider_semaphore import run_in_solver_slot
from app.models.request import TransportMode
from app.models.response import FailedLeg, KnownStop, PlannedLeg, UnknownStop
from app.services.engine import RoutesAdapter, RoutingResult, VerifiedStop
from app.services.errors import ProviderCapacityError
from app.services.geo import HasLatLng, haversine_km
from app.services.hours import hours_eligibility
from app.services.optimise import optimise_order

SAVING_THRESHOLD_SECONDS = 300
SOLVER_MAX_SECONDS = 2.0

Timeline = list[KnownStop | PlannedLeg | FailedLeg | UnknownStop]


class CandidateIntegrityError(RuntimeError):
    """The local search returned something that is not a valid reordering."""


class RoutingBudgetExceededError(RuntimeError):
    """Defensive: a comparison tried to exceed its 2(N-1) routing calls."""


def path_km(points: Sequence[HasLatLng], order: Sequence[int]) -> float:
    return sum(
        haversine_km(points[a].lat, points[a].lng, points[b].lat, points[b].lng)
        for a, b in pairwise(order)
    )


def check_candidate(order: list[int], n: int, fixed_first: bool, fixed_last: bool) -> None:
    if sorted(order) != list(range(n)):
        raise CandidateIntegrityError("candidate is not a permutation of the stops")
    if fixed_first and order[0] != 0:
        raise CandidateIntegrityError("candidate moved the pinned first stop")
    if fixed_last and order[-1] != n - 1:
        raise CandidateIntegrityError("candidate moved the pinned last stop")


async def generate_candidate(
    stops: Sequence[VerifiedStop],
    *,
    fixed_first: bool,
    fixed_last: bool,
    deadline: DeadlineScope,
) -> list[int]:
    """Run the existing distance optimiser once, bounded by the deadline."""
    n = len(stops)
    deadline.check()
    limit = min(SOLVER_MAX_SECONDS, deadline.remaining_seconds())
    if limit <= 0:
        raise DeadlineExceededError("No time left for the local search")
    solve = partial(optimise_order, list(stops), fixed_first, fixed_last, limit)
    try:
        order = await deadline.bound(
            run_in_solver_slot(
                solve,
                wait_seconds=min(settings.provider_wait_seconds, deadline.remaining_seconds()),
            )
        )
    except HTTPException as exc:  # solver capacity busy
        raise ProviderCapacityError("Optimisation capacity is busy") from exc
    check_candidate(order, n, fixed_first, fixed_last)
    return order


class RoutingBudget:
    """Wraps a RoutesAdapter and refuses calls beyond ``limit``."""

    def __init__(self, inner: RoutesAdapter, limit: int) -> None:
        self.inner = inner
        self.limit = limit
        self.calls = 0

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
        if self.calls >= self.limit:
            raise RoutingBudgetExceededError(f"routing budget of {self.limit} calls exhausted")
        self.calls += 1
        return await self.inner.fetch_leg(
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            mode=mode,
            depart_at=depart_at,
        )


def is_complete(timeline: Timeline) -> bool:
    return not any(isinstance(i, FailedLeg | UnknownStop) for i in timeline)


def journey_seconds(timeline: Timeline) -> int:
    """Total elapsed journey time: the sum of each leg's ``journey_seconds``
    (arrival minus planned departure) — the same value the UI shows per leg."""
    return sum(i.journey_seconds for i in timeline if isinstance(i, PlannedLeg))


def disqualified_stops(timeline: Timeline) -> list[str]:
    """Instance IDs with a known closure on arrival for a positive stay (D42)."""
    return [
        i.instance_id
        for i in timeline
        if isinstance(i, KnownStop)
        and hours_eligibility(i.hours_status, i.stay_minutes) == "disqualifying"
    ]


def durations_by_instance(timeline: Timeline) -> dict[str, int]:
    return {i.instance_id: i.stay_minutes for i in timeline if isinstance(i, KnownStop)}


Decision = Literal["recommended", "not_faster", "hours_ineligible"]


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    original_seconds: int
    candidate_seconds: int
    saving_seconds: int
    ineligible: list[str]


def decide(original: Timeline, candidate: Timeline) -> Verdict:
    """Decide on two COMPLETE timelines (callers handle incomplete ones)."""
    if not (is_complete(original) and is_complete(candidate)):
        raise ValueError("decide() needs two complete itineraries")
    if durations_by_instance(original) != durations_by_instance(candidate):
        raise CandidateIntegrityError("visit durations changed between orders")
    orig_s, cand_s = journey_seconds(original), journey_seconds(candidate)
    saving = orig_s - cand_s
    ineligible = disqualified_stops(candidate)
    if ineligible:
        decision: Decision = "hours_ineligible"
    elif saving >= SAVING_THRESHOLD_SECONDS:  # exact seconds, before any rounding
        decision = "recommended"
    else:
        decision = "not_faster"
    return Verdict(decision, orig_s, cand_s, saving, ineligible)
