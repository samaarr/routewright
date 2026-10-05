"""Tests for route optimiser — Stage 1 (haversine) and Stage 2 (hours-aware).

Stage 1: pure distance via OR-Tools TSP.
Stage 2: opening-hours soft constraints via OR-Tools time dimension.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.geocoder import GeocodedPlace, OpeningPeriod
from app.services.optimise import (
    OPTIMISE_MAX_STOPS,
    build_haversine_matrix,
    optimise_order,
    optimise_order_with_hours,
)


def _place(name: str, lat: float, lng: float) -> GeocodedPlace:
    return GeocodedPlace(
        place_id=f"id_{name.replace(' ', '_')}",
        name=name,
        lat=lat,
        lng=lng,
        primary_type="tourist_attraction",
        types=["tourist_attraction"],
    )


def _path_km(places: list[GeocodedPlace], order: list[int]) -> float:
    """Sum of haversine distances along the given order."""
    m = build_haversine_matrix(places)
    return sum(m[order[i]][order[i + 1]] for i in range(len(order) - 1))


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Dublin Howth route — same coords as test_backtrack.py
_HOWTH = [
    _place("Trinity", 53.3438, -6.2546),
    _place("Bonobo Smithfield", 53.3504, -6.2746),
    _place("Howth", 53.3728, -6.0588),
    _place("Mema's", 53.3532, -6.2604),
    _place("Strand View", 53.3835, -6.1483),
]

# London 11-stop route: alternates far-west / far-east to create a zigzag
# that an optimiser can obviously improve.
_LONDON = [
    _place("Heathrow", 51.4700, -0.4543),  # far west
    _place("Shoreditch", 51.5228, -0.0785),  # east
    _place("Kew Gardens", 51.4785, -0.2944),  # west
    _place("Canary Wharf", 51.5054, -0.0235),  # far east
    _place("Notting Hill", 51.5130, -0.2018),  # central-west
    _place("Greenwich", 51.4769, 0.0005),  # southeast
    _place("Islington", 51.5362, -0.1010),  # north-east
    _place("Hammersmith", 51.4921, -0.2220),  # west
    _place("Bethnal Green", 51.5285, -0.0547),  # east
    _place("Richmond", 51.4613, -0.3068),  # southwest
    _place("Hackney", 51.5450, -0.0553),  # northeast
]

# Geocode mock data for the endpoint integration test
_MOCK_PLACES: dict[str, GeocodedPlace] = {
    "trinity college": _place("Trinity College Dublin", 53.3440, -6.2546),
    "temple bar": _place("Temple Bar", 53.3454, -6.2672),
    "guinness storehouse": _place("Guinness Storehouse", 53.3418, -6.2867),
}
_FALLBACK = _place("Unknown", 53.3440, -6.2546)


async def _fake_geocode(
    query: str,
    city: str,
    db_path: str,
    ttl_days: int,
    client: object = None,
) -> GeocodedPlace:
    return _MOCK_PLACES.get(query.strip().lower(), _FALLBACK)


# ---------------------------------------------------------------------------
# build_haversine_matrix
# ---------------------------------------------------------------------------


def test_matrix_is_square_symmetric_zero_diagonal() -> None:
    n = len(_HOWTH)
    m = build_haversine_matrix(_HOWTH)
    assert len(m) == n
    assert all(len(row) == n for row in m)
    for i in range(n):
        assert m[i][i] == 0.0
        for j in range(n):
            assert abs(m[i][j] - m[j][i]) < 1e-9


def test_matrix_off_diagonal_positive() -> None:
    m = build_haversine_matrix(_HOWTH)
    for i, row in enumerate(m):
        for j, val in enumerate(row):
            if i != j:
                assert val > 0.0


# ---------------------------------------------------------------------------
# optimise_order: edge cases
# ---------------------------------------------------------------------------


def test_one_stop_unchanged() -> None:
    assert optimise_order([_place("A", 0.0, 0.0)]) == [0]


def test_two_stops_unchanged() -> None:
    places = [_place("A", 0.0, 0.0), _place("B", 1.0, 1.0)]
    assert optimise_order(places) == [0, 1]


def test_result_is_valid_permutation() -> None:
    n = len(_HOWTH)
    assert sorted(optimise_order(_HOWTH)) == list(range(n))


def test_already_efficient_order_not_worsened() -> None:
    """Three collinear stops: optimal order must not produce a longer path."""
    places = [
        _place("West", 51.5, -0.3),
        _place("Centre", 51.5, -0.1),
        _place("East", 51.5, 0.1),
    ]
    original_km = _path_km(places, [0, 1, 2])
    optimised_km = _path_km(places, optimise_order(places))
    assert optimised_km <= original_km + 1e-6


# ---------------------------------------------------------------------------
# optimise_order: improvement on backtrack routes
# ---------------------------------------------------------------------------


def test_howth_optimised_path_shorter() -> None:
    """OR-Tools must find an order with shorter total haversine path."""
    original_km = _path_km(_HOWTH, list(range(len(_HOWTH))))
    optimised_km = _path_km(_HOWTH, optimise_order(_HOWTH))
    assert optimised_km < original_km, (
        f"optimised ({optimised_km:.2f} km) must be shorter than original ({original_km:.2f} km)"
    )


def test_london_11_stop_optimised_path_shorter() -> None:
    """Zigzag London route: OR-Tools must produce a materially shorter path."""
    original_km = _path_km(_LONDON, list(range(len(_LONDON))))
    optimised_km = _path_km(_LONDON, optimise_order(_LONDON))
    assert optimised_km < original_km, (
        f"optimised ({optimised_km:.2f} km) must be shorter than original ({original_km:.2f} km)"
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_optimise_max_stops_constant() -> None:
    assert 8 <= OPTIMISE_MAX_STOPS <= 12


# ---------------------------------------------------------------------------
# /api/optimise endpoint
# ---------------------------------------------------------------------------


def test_optimise_endpoint_returns_reordered_stops(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoint returns stops in optimised order with before/after km stats."""
    monkeypatch.setattr("app.routers.optimise.geocode_cached", _fake_geocode)

    payload = {
        "city": "Dublin, Ireland",
        "stops": [
            {"query": "Trinity College"},
            {"query": "Temple Bar"},
            {"query": "Guinness Storehouse"},
        ],
        "start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "mode": "transit",
    }
    resp = client.post("/api/optimise", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    stops = data["stops"]
    assert len(stops) == 3
    assert all("query" in s and "name" in s for s in stops)
    assert "original_km" in data
    assert "optimised_km" in data
    assert data["optimised_km"] <= data["original_km"] + 1e-3


def test_optimise_endpoint_two_stops_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two stops: order unchanged (nothing to optimise)."""
    monkeypatch.setattr("app.routers.optimise.geocode_cached", _fake_geocode)

    payload = {
        "city": "Dublin, Ireland",
        "stops": [
            {"query": "Trinity College"},
            {"query": "Temple Bar"},
        ],
        "start_time": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "mode": "transit",
    }
    resp = client.post("/api/optimise", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["stops"]) == 2
    assert data["stops"][0]["query"] == "Trinity College"
    assert data["stops"][1]["query"] == "Temple Bar"


# ---------------------------------------------------------------------------
# Stage 2: hours-aware optimiser
# ---------------------------------------------------------------------------

# Monday 2026-06-01 09:00 UTC = 10:00 BST — all test places in "Europe/London"
_S2_START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
_S2_TZ = "Europe/London"

# Monday period helpers
# Google day: 0=Sun, 1=Mon … 6=Sat
_MON_ALL_DAY = OpeningPeriod(open_day=1, open_minutes=0, close_day=1, close_minutes=1439)
_MON_AFTERNOON = OpeningPeriod(open_day=1, open_minutes=840, close_day=1, close_minutes=1200)
# opens Mon 14:00 BST = 840 min, closes Mon 20:00 BST = 1200 min

# Slightly spread around central London — distance differences are intentionally small
# so hours penalties (50 km-eq) dominate over travel cost (~0.5 km)
_CLOSE_CLUSTER = [
    _place("Museum", 51.5194, -0.1270),
    _place("Park", 51.5202, -0.1265),
    _place("Café", 51.5198, -0.1260),
    _place("Gallery", 51.5190, -0.1255),
]

# Sunday 2026-05-31 09:00 UTC = 10:00 BST — for "all-closed" tests
_S2_START_SUN = datetime(2026, 5, 31, 9, 0, tzinfo=timezone.utc)


def _place_with_hours(
    name: str, lat: float, lng: float, periods: list[OpeningPeriod]
) -> GeocodedPlace:
    return GeocodedPlace(
        place_id=f"id_{name.replace(' ', '_')}",
        name=name,
        lat=lat,
        lng=lng,
        primary_type="tourist_attraction",
        types=["tourist_attraction"],
        opening_hours=periods,
    )


def test_s2_unknown_hours_no_flags_no_penalty() -> None:
    """Stops with no hours data (unknown) produce no flags.

    Without hours constraints the result must equal Stage 1's pure-distance order.
    """
    order_s1 = optimise_order(_HOWTH)
    order_s2, flags = optimise_order_with_hours(
        _HOWTH,
        stays=[60] * len(_HOWTH),
        start_time=_S2_START,
        city_timezone=_S2_TZ,
    )
    assert sorted(order_s2) == list(range(len(_HOWTH)))
    assert flags == []
    assert order_s2 == order_s1, "No-hours result must match Stage 1"


def test_s2_closed_on_arrival_stop_not_first() -> None:
    """A stop closed in the morning is pushed out of the lead position.

    Museum only opens Mon 14:00 BST (840 min).  Trip starts 10:00 BST.
    Arrival penalty (50 km-equivalent per 60 min) vastly exceeds intra-cluster
    travel cost (~0.1 km), so the solver avoids placing Museum first.
    """
    places = [
        _place_with_hours("Museum", 51.5194, -0.1270, [_MON_AFTERNOON]),  # closed until 14:00
        _place("Park", 51.5202, -0.1265),
        _place("Café", 51.5198, -0.1260),
    ]
    order, _flags = optimise_order_with_hours(
        places,
        stays=[60, 60, 60],
        start_time=_S2_START,
        city_timezone=_S2_TZ,
    )
    assert order[0] != 0, "Museum (closed at 10:00 BST) must not be the first stop"


def test_s2_all_closed_all_flagged() -> None:
    """When every stop is closed on Sunday, all appear in infeasibility_flags."""
    # All stops only open Monday; trip runs on Sunday.
    sunday_places = [
        _place_with_hours(f"Stop{i}", 51.5194 + i * 0.001, -0.127, [_MON_ALL_DAY]) for i in range(4)
    ]
    order, flags = optimise_order_with_hours(
        sunday_places,
        stays=[60] * 4,
        start_time=_S2_START_SUN,
        city_timezone=_S2_TZ,
    )
    assert sorted(order) == [0, 1, 2, 3]
    assert len(flags) == 4, "Every stop closed on Sunday must be flagged"
    assert all(f.issue == "closed_on_arrival" for f in flags)


def test_s2_closes_during_visit_flagged_when_stay_too_long() -> None:
    """A stop where the stay overruns closing time is flagged closes_during_visit.

    n=2 → passthrough (order=[0,1]).  LateCloser is first; trip starts 10:00 BST.
    Stop open Mon 08:00–11:30 BST.  Stay = 180 min → depart 13:00 BST > 11:30 close.
    """
    closes_1130 = OpeningPeriod(open_day=1, open_minutes=480, close_day=1, close_minutes=690)
    # Mon 08:00 BST (480 min) → Mon 11:30 BST (690 min)
    late_closer = _place_with_hours("LateCloser", 51.5200, -0.1270, [closes_1130])
    other = _place("Other", 51.5205, -0.1265)

    _order, flags = optimise_order_with_hours(
        [late_closer, other],
        stays=[180, 60],
        start_time=_S2_START,
        city_timezone=_S2_TZ,
    )
    assert len(flags) == 1
    assert flags[0].stop_name == "LateCloser"
    assert flags[0].issue == "closes_during_visit"


def test_s2_open_all_trip_no_flags() -> None:
    """Stops confirmed open throughout the trip produce no infeasibility flags."""
    all_open = [
        _place_with_hours(f"Stop{i}", 51.5194 + i * 0.001, -0.127, [_MON_ALL_DAY]) for i in range(4)
    ]
    _order, flags = optimise_order_with_hours(
        all_open,
        stays=[60] * 4,
        start_time=_S2_START,
        city_timezone=_S2_TZ,
    )
    assert flags == []


def test_s2_stage1_regression_no_hours() -> None:
    """Without hours data, Stage 2 matches Stage 1 on the zigzag London route."""
    order_s1 = optimise_order(_LONDON)
    order_s2, flags = optimise_order_with_hours(
        _LONDON,
        stays=[60] * len(_LONDON),
        start_time=_S2_START,
        city_timezone=_S2_TZ,
    )
    assert sorted(order_s2) == list(range(len(_LONDON)))
    assert flags == []
    assert order_s2 == order_s1, "No-hours Stage 2 must produce same order as Stage 1"
