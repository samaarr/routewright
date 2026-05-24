"""Geodesic distance utilities and conservative backtrack detection.

haversine_km: standard great-circle distance between two lat/lng points.
detect_backtrack_hint: single-stop backtrack detection, advisory only.
"""

import math

from app.models.response import RouteHint
from app.services.geocoder import GeocodedPlace

# A single relocation must reduce the haversine path length by at least
# this fraction before a hint is emitted.  Set at 0.10 (deliberately
# sensitive / minimal-guard) to observe raw behaviour on real routes
# before deciding which guards to reinstate.
BACKTRACK_HINT_THRESHOLD = 0.10


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
    """Return an advisory hint if one stop is a clear spatial backtrack.

    Minimal-guard mode: no start/end anchoring (any stop can be flagged),
    no median-leg guard, threshold at 10%.  The median-leg guard was removed
    because a large backtrack inflates the median, making the ratio test
    self-defeating for exactly the cases it should catch.

    Conditions — ALL must hold:
    1. At least 4 stops.
    2. A single relocation of ANY stop (including first and last) reduces
       the haversine path length by >= BACKTRACK_HINT_THRESHOLD.

    When two relocations give equal improvement, the one whose flagged stop
    has the longest adjacent leg is preferred (most visually obvious backtrack).

    Returns None in the common case (efficient route or below threshold).
    """
    n = len(places)
    if n < 4:
        return None

    base_order = list(range(n))
    current_total = _path_length(places, base_order)
    if current_total == 0.0:
        return None

    # Leg lengths used for tie-breaking and for choosing the highlighted leg.
    leg_lengths = [
        haversine_km(
            places[i].lat,
            places[i].lng,
            places[i + 1].lat,
            places[i + 1].lng,
        )
        for i in range(n - 1)
    ]

    best_improvement = 0.0
    best_candidates: list[tuple[int, int]] = []  # (flagged_idx, insert_before_idx)

    for move_i in range(n):  # all stops are candidates — no anchoring
        remaining = [j for j in base_order if j != move_i]
        # range(len(remaining)) tries every position except appending to the
        # very end, so remaining[insert_pos] is always a valid "before" stop.
        for insert_pos in range(len(remaining)):
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
        # Guard for edge stops: no leg before index 0, no leg after index n-1.
        legs = []
        if flagged > 0:
            legs.append(leg_lengths[flagged - 1])
        if flagged < n - 1:
            legs.append(leg_lengths[flagged])
        return max(legs) if legs else 0.0

    best_flagged_idx, best_insert_before = max(best_candidates, key=lambda c: max_adj_leg(c[0]))

    # The leg to highlight on the map: whichever adjacent leg is longer.
    flagged = best_flagged_idx
    leg_in = leg_lengths[flagged - 1] if flagged > 0 else 0.0
    leg_out = leg_lengths[flagged] if flagged < n - 1 else 0.0
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
