"""Geodesic distance utilities and conservative backtrack detection.

haversine_km: standard great-circle distance between two lat/lng points.
detect_backtrack_hint: single-stop backtrack detection, advisory only.
"""

import math
from statistics import median

from app.models.response import RouteHint
from app.services.geocoder import GeocodedPlace

# A single relocation must reduce the haversine path length by at least
# this fraction before a hint is emitted. Deliberately conservative.
BACKTRACK_HINT_THRESHOLD = 0.25

# The leg into or out of the flagged stop must be at least this many times
# the median leg length. Guards against flagging marginal reshuffles in
# routes where all legs are similarly long.
LONG_LEG_RATIO_THRESHOLD = 1.8


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat / 2) ** 2 + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    return r * 2 * math.asin(math.sqrt(a))


def _path_length(places: list[GeocodedPlace], order: list[int]) -> float:
    """Sum of haversine_km for consecutive stops in the given index order."""
    return sum(
        haversine_km(
            places[order[i]].lat,
            places[order[i]].lng,
            places[order[i + 1]].lat,
            places[order[i + 1]].lng,
        )
        for i in range(len(order) - 1)
    )


def detect_backtrack_hint(places: list[GeocodedPlace]) -> RouteHint | None:
    """Return an advisory hint if one middle stop is a clear spatial backtrack.

    Conservative conditions — ALL must hold:
    1. At least 4 stops (otherwise no meaningful middle to consider).
    2. A single relocation of one middle stop reduces the haversine path
       length by >= BACKTRACK_HINT_THRESHOLD (25%).
    3. The flagged stop is adjacent to a leg that is >= LONG_LEG_RATIO_THRESHOLD
       (1.8x) the median leg length — avoids flagging near-uniform routes.

    First/last stops are treated as fixed anchors (not candidates for moving).
    When two relocations give equal improvement, the one whose flagged stop
    has the longest adjacent leg is preferred (most visually obvious backtrack).

    Returns None in the common case (efficient route or ambiguous hint).
    """
    n = len(places)
    if n < 4:
        return None

    base_order = list(range(n))
    current_total = _path_length(places, base_order)
    if current_total == 0.0:
        return None

    # Leg lengths in the current (user) order.
    leg_lengths = [
        haversine_km(
            places[i].lat,
            places[i].lng,
            places[i + 1].lat,
            places[i + 1].lng,
        )
        for i in range(n - 1)
    ]
    med = median(leg_lengths)

    best_improvement = 0.0
    # Collect all relocations within epsilon of best — break ties by max adj leg.
    best_candidates: list[tuple[int, int]] = []  # (flagged_idx, insert_before_idx)

    for move_i in range(1, n - 1):  # middle stops only — first/last are anchors
        remaining = [j for j in base_order if j != move_i]
        # Insert move_i before each position in remaining, excluding before the
        # first anchor (remaining[0]) and after the last anchor (remaining[-1]).
        for insert_pos in range(1, len(remaining)):
            new_order = [*remaining[:insert_pos], move_i, *remaining[insert_pos:]]
            new_total = _path_length(places, new_order)
            improvement = (current_total - new_total) / current_total
            if improvement > best_improvement + 1e-9:
                best_improvement = improvement
                best_candidates = [(move_i, remaining[insert_pos])]
            elif improvement > best_improvement - 1e-9 and improvement > 1e-9:
                best_candidates.append((move_i, remaining[insert_pos]))

    if best_improvement < BACKTRACK_HINT_THRESHOLD:
        return None

    def max_adj_leg(flagged: int) -> float:
        return max(leg_lengths[flagged - 1], leg_lengths[flagged])

    # Among equally-good candidates, prefer the one with the longest adjacent leg
    # — that stop is the most spatially obvious backtrack.
    best_flagged_idx, best_insert_before = max(best_candidates, key=lambda c: max_adj_leg(c[0]))

    # Long-leg guard: the flagged stop must sit next to a clearly anomalous leg.
    flagged = best_flagged_idx
    leg_in = leg_lengths[flagged - 1]
    leg_out = leg_lengths[flagged]
    if max(leg_in, leg_out) < med * LONG_LEG_RATIO_THRESHOLD:
        return None

    # The leg to highlight on the map: whichever of the two adjacent legs is longer.
    if leg_in >= leg_out:
        long_from, long_to = flagged - 1, flagged
    else:
        long_from, long_to = flagged, flagged + 1

    return RouteHint(
        flagged_stop_index=flagged,
        suggested_before_index=best_insert_before,
        flagged_stop_name=places[flagged].name,
        suggested_before_name=places[best_insert_before].name,
        long_leg_from_index=long_from,
        long_leg_to_index=long_to,
    )
