"""Tests for distance-based route optimiser — Stage 1 (haversine, no time windows).

No opening-hours constraints (Stage 2). No UI (Stage 3).
Pure distance optimisation via OR-Tools TSP.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.geocoder import GeocodedPlace
from app.services.optimise import (
    OPTIMISE_MAX_STOPS,
    build_haversine_matrix,
    optimise_order,
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
        "start_time": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
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
        "start_time": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
        "mode": "transit",
    }
    resp = client.post("/api/optimise", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["stops"]) == 2
    assert data["stops"][0]["query"] == "Trinity College"
    assert data["stops"][1]["query"] == "Temple Bar"
