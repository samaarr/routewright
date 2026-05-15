"""Shared pytest fixtures."""

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.directions import LegResult
from app.services.geocoder import GeocodedPlace


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI test client. Stateless, no setup needed in week 1."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Geocoder mock — used by all /api/plan tests to avoid real network calls.
# Patches app.routers.plan.geocode_cached with an async function that returns
# predictable GeocodedPlace objects keyed by normalised query string.
#
# All three test stops exercise explicit entries in the stay-defaults table:
#   Trinity College  → tourist_attraction → 60 min
#   Temple Bar       → tourist_attraction → 60 min
#   Guinness Storehouse → brewery        → 90 min
# ---------------------------------------------------------------------------

_MOCK_PLACES: dict[str, GeocodedPlace] = {
    "trinity college": GeocodedPlace(
        place_id="ChIJ_TC",
        name="Trinity College Dublin",
        lat=53.3440,
        lng=-6.2546,
        primary_type="tourist_attraction",
        types=["tourist_attraction", "point_of_interest", "establishment"],
    ),
    "temple bar": GeocodedPlace(
        place_id="ChIJ_TB",
        name="Temple Bar",
        lat=53.3454,
        lng=-6.2672,
        primary_type="tourist_attraction",
        types=["tourist_attraction", "bar", "point_of_interest"],
    ),
    "guinness storehouse": GeocodedPlace(
        place_id="ChIJ_GS",
        name="Guinness Storehouse",
        lat=53.3418,
        lng=-6.2867,
        primary_type="brewery",
        types=["brewery", "tourist_attraction", "point_of_interest"],
    ),
}

_FALLBACK_PLACE = GeocodedPlace(
    place_id="ChIJ_FALLBACK",
    name="Unknown Place",
    lat=1.0,
    lng=1.0,
    primary_type="tourist_attraction",
    types=["tourist_attraction"],
)


@pytest.fixture
def mock_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch fetch_leg in the plan router with a predictable 20-min result.

    Uses 20 min (not 15) so any test that accidentally runs against the old
    15-min stub will fail immediately — it acts as a canary.
    """

    async def _fake_fetch_leg(
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        depart_at: datetime,
        mode: str,
        client: object = None,
    ) -> LegResult:
        return LegResult(
            duration_seconds=20 * 60,
            distance_meters=2000,
            depart_at=depart_at,
            arrive_at=depart_at + timedelta(seconds=20 * 60),
            summary=f"Mock: 20 min via {mode}",
            transit_line=None,
        )

    monkeypatch.setattr("app.routers.plan.fetch_leg", _fake_fetch_leg)


@pytest.fixture
def mock_geocode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch geocode_cached in the plan router with predictable test data."""

    async def _fake(
        query: str,
        city: str,
        db_path: str,
        ttl_days: int,
        client: object = None,
    ) -> GeocodedPlace:
        return _MOCK_PLACES.get(query.strip().lower(), _FALLBACK_PLACE)

    monkeypatch.setattr("app.routers.plan.geocode_cached", _fake)
