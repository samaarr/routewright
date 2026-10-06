"""Distance-based route optimiser — Stage 1 + Stage 2.

Stage 1 (optimise_order): haversine cost only, no time windows.
Stage 2 (optimise_order_with_hours): adds opening-hours soft constraints via
    OR-Tools time dimension.  Penalties make the solver prefer schedules that
    respect opening hours; a complete order is always returned.  Stops that
    remain violated after optimisation are reported as InfeasibilityFlags.

Stage 3 wires user-facing fixed_first/fixed_last pinning and the UI button.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.models.response import InfeasibilityFlag
from app.services.geo import HasLatLng, haversine_km
from app.services.geocoder import GeocodedPlace
from app.services.hours import compute_hours_status

# Feature gate — enforced by the caller (endpoint), not here.
OPTIMISE_MAX_STOPS = 10

_SCALE = 1000  # km → integer metres; keeps 3 decimal places of precision
_TIME_LIMIT_SECONDS = 2
_HORIZON_MINUTES = 1440  # 24-hour planning horizon
_WEEK_MINUTES = 7 * 24 * 60

# Stage 2 soft-penalty calibration.
# Each coefficient is cost-units-per-minute-of-violation in the time dimension.
# _SCALE / 60 makes 60 minutes of violation equivalent to 1 km of extra distance.
CLOSED_ON_ARRIVAL_PENALTY_KM: int = 50  # strong: door is shut
CLOSES_DURING_VISIT_PENALTY_KM: int = 5  # soft: fact to surface
_COEFF_CLOSED_ON_ARRIVAL = round(CLOSED_ON_ARRIVAL_PENALTY_KM * _SCALE / 60)
_COEFF_CLOSES_DURING_VISIT = round(CLOSES_DURING_VISIT_PENALTY_KM * _SCALE / 60)


def build_haversine_matrix(places: Sequence[HasLatLng]) -> list[list[float]]:
    """Return an N×N symmetric matrix of haversine_km distances."""
    n = len(places)
    return [
        [haversine_km(places[i].lat, places[i].lng, places[j].lat, places[j].lng) for j in range(n)]
        for i in range(n)
    ]


def optimise_order(
    places: Sequence[HasLatLng],
    fixed_first: bool = False,
    fixed_last: bool = False,
    time_limit_seconds: float = _TIME_LIMIT_SECONDS,
) -> list[int]:
    """Return an index permutation that minimises the total haversine path.

    Uses OR-Tools single-vehicle TSP over the haversine distance matrix.
    Returns the original order [0, 1, ..., n-1] unchanged when len < 3.

    fixed_first / fixed_last pin stop 0 or stop n-1 to their position.
    Both default to False; Stage 3 wires these to user-facing UI controls.

    ``time_limit_seconds`` bounds the OR-Tools search (the v2 comparison
    passes min(2 s, remaining operation deadline)), so the worker thread
    always finishes promptly even if the awaiting request was cancelled.

    Open-path formulation: a virtual dummy depot (index n) with zero-cost
    arcs to/from all real stops lets the solver find the best start and end
    without penalising the real path.  Fixed endpoints replace the dummy
    with the pinned real node on that side.
    """
    n = len(places)
    if n < 3:
        return list(range(n))

    matrix = build_haversine_matrix(places)
    int_matrix = [[round(d * _SCALE) for d in row] for row in matrix]

    # Dummy depot: index n, zero cost on all arcs to/from it.
    # Not needed when both endpoints are pinned (start=0, end=n-1 directly).
    dummy = n
    need_dummy = not (fixed_first and fixed_last)
    n_nodes = n + 1 if need_dummy else n
    start_node = 0 if fixed_first else dummy
    end_node = (n - 1) if fixed_last else dummy

    manager = pywrapcp.RoutingIndexManager(n_nodes, 1, [start_node], [end_node])
    routing = pywrapcp.RoutingModel(manager)

    def _dist(from_idx: int, to_idx: int) -> int:
        fi: int = manager.IndexToNode(from_idx)
        ti: int = manager.IndexToNode(to_idx)
        if fi == dummy or ti == dummy:
            return 0
        return int_matrix[fi][ti]

    cb_idx = routing.RegisterTransitCallback(_dist)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    whole = int(time_limit_seconds)
    params.time_limit.seconds = whole
    params.time_limit.nanos = int((time_limit_seconds - whole) * 1e9)

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return list(range(n))

    skip: set[int] = {dummy} if need_dummy else set()
    idx = routing.Start(0)
    order: list[int] = []
    while not routing.IsEnd(idx):
        node = manager.IndexToNode(idx)
        if node not in skip:
            order.append(node)
        idx = solution.Value(routing.NextVar(idx))
    end = manager.IndexToNode(routing.End(0))
    if end not in skip:
        order.append(end)

    return order


# ---------------------------------------------------------------------------
# Stage 2: hours-aware soft constraints
# ---------------------------------------------------------------------------


def _period_open_abs(open_day: int, open_minutes: int) -> int:
    return open_day * 1440 + open_minutes


def _period_close_abs(open_abs: int, close_day: int, close_minutes: int) -> int:
    close = close_day * 1440 + close_minutes
    if close < open_abs:
        close += _WEEK_MINUTES
    return close


def _start_week_minutes(dt_local: datetime) -> int:
    google_day = (dt_local.weekday() + 1) % 7  # Mon(0)→1 … Sun(6)→0
    return google_day * 1440 + dt_local.hour * 60 + dt_local.minute


def _opening_offsets(
    place: GeocodedPlace,
    start_abs: int,
) -> tuple[int | None, int | None]:
    """Return (opens_offset, closes_offset) in minutes relative to start_time.

    Both None → no constraint (unknown hours or 24-hour open).
    opens_offset ≤ 0 → already open at start_time (no lower-bound penalty needed).
    closes_offset is always > 0 when returned.
    """
    if not place.opening_hours:
        return None, None
    if any(p.close_day is None for p in place.opening_hours):
        return None, None  # 24-hour place

    best_opens: int | None = None
    best_closes: int | None = None

    for p in place.opening_hours:
        if p.close_day is None or p.close_minutes is None:
            continue
        p_open = _period_open_abs(p.open_day, p.open_minutes)
        p_close = _period_close_abs(p_open, p.close_day, p.close_minutes)

        opens_off = p_open - start_abs
        closes_off = p_close - start_abs

        # Shift expired periods (closed before start) to next-week occurrence
        if closes_off <= 0:
            opens_off += _WEEK_MINUTES
            closes_off += _WEEK_MINUTES

        # Already open at start — return immediately (lowest opens_off)
        if opens_off <= 0 < closes_off:
            return opens_off, closes_off

        # Opens within our planning horizon
        if 0 < opens_off <= _HORIZON_MINUTES and (best_opens is None or opens_off < best_opens):
            best_opens = opens_off
            best_closes = closes_off

    if best_opens is not None:
        return best_opens, best_closes
    return None, None


def _compute_flags(
    places: list[GeocodedPlace],
    stays: list[int],
    order: list[int],
    start_time: datetime,
    city_timezone: str,
    average_speed_kmh: float,
) -> list[InfeasibilityFlag]:
    """Simulate the chosen route and flag stops with residual hours violations."""
    flags: list[InfeasibilityFlag] = []
    current_time = start_time
    for i, idx in enumerate(order):
        if i > 0:
            prev = order[i - 1]
            travel_min = (
                haversine_km(places[prev].lat, places[prev].lng, places[idx].lat, places[idx].lng)
                / average_speed_kmh
                * 60
            )
            current_time = current_time + timedelta(minutes=travel_min + stays[prev])
        arrive = current_time
        depart = arrive + timedelta(minutes=stays[idx])
        status, _ = compute_hours_status(places[idx].opening_hours, arrive, depart, city_timezone)
        if status in ("closed_on_arrival", "closes_during_visit"):
            flags.append(InfeasibilityFlag(stop_index=i, stop_name=places[idx].name, issue=status))
    return flags


def optimise_order_with_hours(
    places: list[GeocodedPlace],
    stays: list[int],
    start_time: datetime,
    city_timezone: str = "UTC",
    average_speed_kmh: float = 25.0,
    fixed_first: bool = False,
    fixed_last: bool = False,
) -> tuple[list[int], list[InfeasibilityFlag]]:
    """Return (order, flags) minimising haversine path with soft opening-hours constraints.

    OR-Tools TSP with a time dimension.  Arc time = travel_minutes(i→j) + stays[i].
    Opening hours impose soft bounds on the cumulative arrival time at each stop:
      • opens_offset   → SetCumulVarSoftLowerBound (COEFF_CLOSED_ON_ARRIVAL)
      • closes_offset−stay → SetCumulVarSoftUpperBound (COEFF_CLOSES_DURING_VISIT)

    Unknown / 24-hour places receive no penalty.  The solver always returns a
    complete order; infeasibility_flags lists stops that remain violated after
    optimisation (computed by post-hoc route simulation).
    """
    n = len(places)
    if n < 3:
        order = list(range(n))
        return order, _compute_flags(
            places, stays, order, start_time, city_timezone, average_speed_kmh
        )

    try:
        tz = ZoneInfo(city_timezone)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")
    start_abs = _start_week_minutes(start_time.astimezone(tz))

    matrix = build_haversine_matrix(places)
    int_matrix = [[round(d * _SCALE) for d in row] for row in matrix]

    dummy = n
    need_dummy = not (fixed_first and fixed_last)
    n_nodes = n + 1 if need_dummy else n
    start_node = 0 if fixed_first else dummy
    end_node = (n - 1) if fixed_last else dummy

    manager = pywrapcp.RoutingIndexManager(n_nodes, 1, [start_node], [end_node])
    routing = pywrapcp.RoutingModel(manager)

    def _dist(from_idx: int, to_idx: int) -> int:
        fi: int = manager.IndexToNode(from_idx)
        ti: int = manager.IndexToNode(to_idx)
        if fi == dummy or ti == dummy:
            return 0
        return int_matrix[fi][ti]

    cb_dist = routing.RegisterTransitCallback(_dist)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_dist)

    def _time(from_idx: int, to_idx: int) -> int:
        fi: int = manager.IndexToNode(from_idx)
        ti: int = manager.IndexToNode(to_idx)
        if fi == dummy or ti == dummy:
            return 0
        travel_min = (
            haversine_km(places[fi].lat, places[fi].lng, places[ti].lat, places[ti].lng)
            / average_speed_kmh
            * 60
        )
        return round(travel_min + stays[fi])

    cb_time = routing.RegisterTransitCallback(_time)
    routing.AddDimension(cb_time, 0, _HORIZON_MINUTES, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    for i in range(n):
        opens_off, closes_off = _opening_offsets(places[i], start_abs)
        if opens_off is None or closes_off is None:
            continue
        node_idx = manager.NodeToIndex(i)
        if opens_off > 0:
            time_dim.SetCumulVarSoftLowerBound(node_idx, opens_off, _COEFF_CLOSED_ON_ARRIVAL)
        upper = closes_off - stays[i]
        if upper >= 0:
            time_dim.SetCumulVarSoftUpperBound(node_idx, upper, _COEFF_CLOSES_DURING_VISIT)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.time_limit.seconds = _TIME_LIMIT_SECONDS

    solution = routing.SolveWithParameters(params)
    if solution is None:
        order = list(range(n))
    else:
        skip: set[int] = {dummy} if need_dummy else set()
        idx_r = routing.Start(0)
        order = []
        while not routing.IsEnd(idx_r):
            node = manager.IndexToNode(idx_r)
            if node not in skip:
                order.append(node)
            idx_r = solution.Value(routing.NextVar(idx_r))
        end_node_val = manager.IndexToNode(routing.End(0))
        if end_node_val not in skip:
            order.append(end_node_val)

    return order, _compute_flags(places, stays, order, start_time, city_timezone, average_speed_kmh)
