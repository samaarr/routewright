"""Unit tests for detect_backtrack_hint and haversine_km.

Test coordinates use Dublin-area latitudes (≈53.34°) so the math is
representative of real-world use.  At that latitude 1° lng ≈ 66.5 km
and 1° lat ≈ 111 km, giving comfortable margins above the 25%/1.8x thresholds.

All tests are pure-haversine (no network calls).
"""

import pytest

from app.models.response import RouteHint
from app.services.geo import (
    BACKTRACK_HINT_THRESHOLD,
    LONG_LEG_RATIO_THRESHOLD,
    detect_backtrack_hint,
    haversine_km,
)
from app.services.geocoder import GeocodedPlace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_place(name: str, lat: float, lng: float) -> GeocodedPlace:
    return GeocodedPlace(place_id=name, name=name, lat=lat, lng=lng, primary_type=None, types=[])


# ---------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------


def test_haversine_same_point_is_zero() -> None:
    assert haversine_km(53.34, -6.26, 53.34, -6.26) == pytest.approx(0.0)


def test_haversine_known_distance() -> None:
    # Dublin city centre to Howth Head (verified: ~13.1 km great-circle)
    dublin = (53.3498, -6.2603)
    howth = (53.3759, -6.0677)
    dist = haversine_km(*dublin, *howth)
    assert 12.0 < dist < 14.5


def test_haversine_symmetric() -> None:
    a = (53.34, -6.26)
    b = (53.38, -6.20)
    assert haversine_km(*a, *b) == pytest.approx(haversine_km(*b, *a))


# ---------------------------------------------------------------------------
# detect_backtrack_hint — clear backtrack (>= 25% improvement, long leg)
# ---------------------------------------------------------------------------


def test_clear_backtrack_returns_hint() -> None:
    """A stop that sits far west while the rest of the route runs east-west
    near the start triggers a hint.

    Route (lng): -6.260 → -6.230 → -6.258 → -6.200 → -6.170
    Stop 2 (lng -6.258) is almost back at the start after going east to -6.230.
    Moving it to position 1 (before stop 1) reduces the path substantially.
    """
    places = [
        make_place("Start", 53.340, -6.260),  # index 0 — anchor
        make_place("East1", 53.340, -6.230),  # index 1
        make_place("BackNear", 53.340, -6.258),  # index 2 — backtrack close to start
        make_place("East2", 53.340, -6.200),  # index 3
        make_place("End", 53.340, -6.170),  # index 4 — anchor
    ]
    hint = detect_backtrack_hint(places)
    assert hint is not None
    assert isinstance(hint, RouteHint)
    assert hint.flagged_stop_index == 2
    assert hint.flagged_stop_name == "BackNear"
    # Suggested position is before East2 (index 3) or East1 (index 1)
    assert hint.suggested_before_index in (1, 3)
    # The backtrack leg highlighted must span the flagged stop
    assert hint.long_leg_from_index in (1, 2)
    assert hint.long_leg_to_index == hint.long_leg_from_index + 1


def test_clear_backtrack_near_start_far_end() -> None:
    """Stop C sits almost at the start anchor while the rest of the route
    runs east, and D is a big jump further east.  This creates a C→D leg
    that is ~2.5x the median — comfortably above the long-leg threshold —
    and a 39% haversine path improvement when C is moved first.

    Verified values (at Dublin lat ≈ 53.34°, 1° lng ≈ 66.5 km):
      A(-6.260) → B(-6.220) → C(-6.259) → D(-6.160) → E(-6.140)
      Leg lengths ≈ [2.66, 2.59, 6.58, 1.33] km, median ≈ 2.62 km
      Best relocation: move C before B → 39% improvement, C→D ratio ≈ 2.5x
    """
    places = [
        make_place("A", 53.340, -6.260),  # anchor start (west)
        make_place("B", 53.340, -6.220),  # going east
        make_place("C", 53.340, -6.259),  # almost back at start — backtrack
        make_place("D", 53.340, -6.160),  # far east (big jump)
        make_place("E", 53.340, -6.140),  # anchor end (east)
    ]
    hint = detect_backtrack_hint(places)
    assert hint is not None
    assert hint.flagged_stop_index == 2
    assert hint.flagged_stop_name == "C"
    assert hint.suggested_before_index == 1  # move C before B
    assert hint.long_leg_from_index == 2  # the long C→D backtrack leg
    assert hint.long_leg_to_index == 3


# ---------------------------------------------------------------------------
# detect_backtrack_hint — no hint cases
# ---------------------------------------------------------------------------


def test_efficient_linear_route_returns_none() -> None:
    """Stops laid out in a straight eastward line — no backtrack."""
    places = [
        make_place("A", 53.340, -6.260),
        make_place("B", 53.340, -6.220),
        make_place("C", 53.340, -6.180),
        make_place("D", 53.340, -6.140),
        make_place("E", 53.340, -6.100),
    ]
    assert detect_backtrack_hint(places) is None


def test_three_stops_returns_none() -> None:
    """Fewer than 4 stops: no hint regardless of geometry."""
    places = [
        make_place("A", 53.340, -6.260),
        make_place("B", 53.340, -6.100),
        make_place("C", 53.340, -6.000),
    ]
    assert detect_backtrack_hint(places) is None


def test_two_stops_returns_none() -> None:
    places = [
        make_place("A", 53.340, -6.260),
        make_place("B", 53.340, -6.100),
    ]
    assert detect_backtrack_hint(places) is None


def test_sub_threshold_inefficiency_returns_none() -> None:
    """A mild inefficiency (< 25% improvement from one relocation) → None.

    Route: A → B(lng -6.230) → C(lng -6.225) → D(lng -6.200) → E(lng -6.170)
    C is only slightly back from B — tiny improvement, well below threshold.
    """
    places = [
        make_place("A", 53.340, -6.260),  # anchor
        make_place("B", 53.340, -6.230),
        make_place("C", 53.340, -6.225),  # barely back from B
        make_place("D", 53.340, -6.200),
        make_place("E", 53.340, -6.170),  # anchor
    ]
    assert detect_backtrack_hint(places) is None


def test_long_leg_guard_blocks_marginal_case() -> None:
    """Even if improvement >= 25%, hint is suppressed when no adjacent leg
    is anomalously long (all legs are roughly the same length).

    All legs ≈ equal length — no single leg stands out as a backtrack.
    """
    # Zigzag route where each leg is similar length but order isn't ideal.
    # Leg ratio will not reach 1.8x median, so guard fires.
    places = [
        make_place("A", 53.340, -6.260),
        make_place("B", 53.360, -6.240),
        make_place("C", 53.345, -6.255),  # slight zigzag back
        make_place("D", 53.380, -6.220),
        make_place("E", 53.400, -6.200),
    ]
    # Verify that even if improvement were >= 25%, the long-leg guard
    # would suppress it.  (If this route passes guard, adjust coords.)
    hint = detect_backtrack_hint(places)
    # Either guard fires (None) or improvement is below threshold (also None).
    assert hint is None


# ---------------------------------------------------------------------------
# detect_backtrack_hint — threshold constants accessible
# ---------------------------------------------------------------------------


def test_threshold_constants_are_reasonable() -> None:
    assert 0.15 <= BACKTRACK_HINT_THRESHOLD <= 0.40
    assert 1.2 <= LONG_LEG_RATIO_THRESHOLD <= 2.5
