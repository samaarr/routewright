"""Distance-based route optimiser — Stage 1: haversine, no time windows.

build_haversine_matrix: N×N symmetric km matrix, pure Python.
optimise_order: OR-Tools TSP returning the visiting order that minimises
    total haversine path length.

Stage 2 adds time-window constraints (opening hours).
Stage 3 wires user-facing fixed_first/fixed_last pinning and the UI button.
"""

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.services.geo import haversine_km
from app.services.geocoder import GeocodedPlace

# Feature gate — enforced by the caller (endpoint), not here.
# optimise_order works for any N; the cap is a product/billing decision.
OPTIMISE_MAX_STOPS = 10

_SCALE = 1000  # km → integer; keeps 3 decimal places of precision
_TIME_LIMIT_SECONDS = 2


def build_haversine_matrix(places: list[GeocodedPlace]) -> list[list[float]]:
    """Return an N×N symmetric matrix of haversine_km distances."""
    n = len(places)
    return [
        [haversine_km(places[i].lat, places[i].lng, places[j].lat, places[j].lng) for j in range(n)]
        for i in range(n)
    ]


def optimise_order(
    places: list[GeocodedPlace],
    fixed_first: bool = False,
    fixed_last: bool = False,
) -> list[int]:
    """Return an index permutation that minimises the total haversine path.

    Uses OR-Tools single-vehicle TSP over the haversine distance matrix.
    Returns the original order [0, 1, ..., n-1] unchanged when len < 3.

    fixed_first / fixed_last pin stop 0 or stop n-1 to their position.
    Both default to False; Stage 3 wires these to user-facing UI controls.

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
    params.time_limit.seconds = _TIME_LIMIT_SECONDS

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
