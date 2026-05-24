"""Unit tests for detect_backtrack_hint and haversine_km.

Test coordinates use Dublin-area latitudes (≈53.34°) so the math is
representative of real-world use.  At that latitude 1° lng ≈ 66.5 km
and 1° lat ≈ 111 km.

All tests are pure-haversine (no network calls).

Algorithm state: minimal-guard mode — no start/end anchoring, no
median-leg guard, threshold 0.10.  The median-leg guard was removed
because a large backtrack inflates the median, blocking the very cases
the guard should catch (confirmed on the Howth diagnostic route).
"""

import pytest

from app.models.response import RouteHint
from app.services.geo import (
    BACKTRACK_HINT_THRESHOLD,
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
# detect_backtrack_hint — clear backtrack cases
# ---------------------------------------------------------------------------


def test_clear_backtrack_returns_hint() -> None:
    """A stop close to the start, visited after the route has moved east,
    is flagged as a backtrack.

    Route (lng): -6.260 → -6.230 → -6.258 → -6.200 → -6.170
    Stop 2 (lng -6.258) is almost back at the start after going east to -6.230.
    Moving it before stop 1 reduces the path substantially.
    """
    places = [
        make_place("Start", 53.340, -6.260),
        make_place("East1", 53.340, -6.230),
        make_place("BackNear", 53.340, -6.258),  # backtrack close to start
        make_place("East2", 53.340, -6.200),
        make_place("End", 53.340, -6.170),
    ]
    hint = detect_backtrack_hint(places)
    assert hint is not None
    assert isinstance(hint, RouteHint)
    assert hint.flagged_stop_index == 2
    assert hint.flagged_stop_name == "BackNear"
    assert hint.long_leg_from_index in (1, 2)
    assert hint.long_leg_to_index == hint.long_leg_from_index + 1


def test_clear_backtrack_near_start_far_end() -> None:
    """Stop C sits almost at the start while the rest of the route runs east,
    and D is a big jump further east — 39% haversine path improvement from
    moving C to position 1 (before B).

    Route (lng): -6.260 → -6.220 → -6.259 → -6.160 → -6.140
    """
    places = [
        make_place("A", 53.340, -6.260),
        make_place("B", 53.340, -6.220),
        make_place("C", 53.340, -6.259),  # almost back at start — backtrack
        make_place("D", 53.340, -6.160),  # big jump east
        make_place("E", 53.340, -6.140),
    ]
    hint = detect_backtrack_hint(places)
    assert hint is not None
    assert hint.flagged_stop_index == 2
    assert hint.flagged_stop_name == "C"
    assert hint.suggested_before_index == 1  # move C before B
    assert hint.long_leg_from_index == 2  # the long C→D leg
    assert hint.long_leg_to_index == 3


def test_howth_backtrack_returns_hint() -> None:
    """Real Dublin route: Howth is a large NE outlier visited between two
    central stops — a 41% haversine improvement exists.

    Previously blocked by the self-defeating median-leg guard (the two ~14 km
    Howth legs inflated the median to 10.9 km, pushing the 1.8x bar to 19.5 km
    — higher than the legs themselves).  With the guard removed this now fires.

    Coords: Trinity, Bonobo Smithfield, Howth, Mema's, Strand View.
    """
    places = [
        make_place("Trinity", 53.3438, -6.2546),
        make_place("Bonobo Smithfield", 53.3504, -6.2746),
        make_place("Howth", 53.3728, -6.0588),
        make_place("Mema's", 53.3532, -6.2604),
        make_place("Strand View", 53.3835, -6.1483),
    ]
    hint = detect_backtrack_hint(places)
    assert hint is not None
    assert hint.flagged_stop_index == 2  # Howth
    assert hint.flagged_stop_name == "Howth"
    # Suggested position: before Strand View (the best single-stop relocation)
    assert hint.suggested_before_index == 4
    assert hint.suggested_before_name == "Strand View"


def test_last_stop_can_be_flagged() -> None:
    """With anchoring removed, the last stop can be flagged.

    Far is geographically near the start (west) but placed last, creating a
    long backtrack leg at the end of the route (~48% improvement by moving it
    right after the start stop).

    Route (lng): -6.260 → -6.240 → -6.220 → -6.200 → -6.255(Far)
    """
    places = [
        make_place("A", 53.340, -6.260),  # start (west)
        make_place("B", 53.340, -6.240),
        make_place("C", 53.340, -6.220),
        make_place("D", 53.340, -6.200),  # eastmost middle stop
        make_place("Far", 53.340, -6.255),  # last stop — near A, should be earlier
    ]
    hint = detect_backtrack_hint(places)
    assert hint is not None
    assert hint.flagged_stop_index == 4  # last stop
    assert hint.flagged_stop_name == "Far"


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
    """A mild inefficiency (< 10% improvement from any single relocation) → None.

    Route: A → B(-6.230) → C(-6.225) → D(-6.200) → E(-6.170).
    All stops trend eastward with no significant backtrack.
    """
    places = [
        make_place("A", 53.340, -6.260),
        make_place("B", 53.340, -6.230),
        make_place("C", 53.340, -6.225),  # almost same position as B — not a backtrack
        make_place("D", 53.340, -6.200),
        make_place("E", 53.340, -6.170),
    ]
    assert detect_backtrack_hint(places) is None


# ---------------------------------------------------------------------------
# detect_backtrack_hint — threshold constant accessible
# ---------------------------------------------------------------------------


def test_threshold_constant_is_reasonable() -> None:
    assert 0.05 <= BACKTRACK_HINT_THRESHOLD <= 0.40
