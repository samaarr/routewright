"""Tests for destination-timezone derivation from geocoded coordinates.

Verifies _destination_timezone returns the correct IANA zone from lat/lng,
with correct fallback chain (coords -> browser zone -> UTC), and that
compute_hours_status uses the derived zone (not the test machine's zone).
"""

from datetime import datetime
from datetime import timezone as _tz

import pytest

from app.routers.plan import _destination_timezone
from app.services.geocoder import OpeningPeriod
from app.services.hours import compute_hours_status

# ---------------------------------------------------------------------------
# Coordinate derivation
# ---------------------------------------------------------------------------


def test_london_coords_return_europe_london() -> None:
    assert _destination_timezone(51.5074, -0.1278, "UTC") == "Europe/London"


def test_tokyo_coords_return_asia_tokyo() -> None:
    assert _destination_timezone(35.6762, 139.6503, "UTC") == "Asia/Tokyo"


def test_nyc_coords_return_america_new_york() -> None:
    assert _destination_timezone(40.7128, -74.0060, "UTC") == "America/New_York"


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


class _NullFinder:
    """Stub that always returns None — simulates ocean/null-island coords."""

    def timezone_at(self, *, lat: float, lng: float) -> None:
        return None


def test_fallback_to_browser_zone_when_lookup_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ocean/null-island coords return None -> use browser-supplied zone."""
    from app.routers import plan as _plan

    monkeypatch.setattr(_plan, "_tf", _NullFinder())
    assert _destination_timezone(0.0, 0.0, "Europe/Dublin") == "Europe/Dublin"


def test_fallback_to_utc_when_both_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """If coord lookup returns None AND browser zone is empty, use 'UTC'."""
    from app.routers import plan as _plan

    monkeypatch.setattr(_plan, "_tf", _NullFinder())
    assert _destination_timezone(0.0, 0.0, "") == "UTC"


# ---------------------------------------------------------------------------
# Far-timezone correctness: Tokyo trip evaluated in Asia/Tokyo
# ---------------------------------------------------------------------------


def _period(
    od: int, oh: int, om: int = 0, cd: int | None = None, ch: int | None = None, cm: int = 0
) -> OpeningPeriod:
    return OpeningPeriod(
        open_day=od,
        open_minutes=oh * 60 + om,
        close_day=cd,
        close_minutes=(ch * 60 + cm) if ch is not None else None,
    )


def test_tokyo_venue_evaluated_in_asia_tokyo_not_browser_zone() -> None:
    """UTC 00:47 = JST 09:47 (UTC+9). Venue opens Mon 09:00 JST -> 'open'.

    If the wrong zone (e.g. UTC or Europe/London) were used, the UTC hour (0)
    would miss the 09:00 opening period and falsely return closed_on_arrival.
    Asia/Tokyo (UTC+9) is derived from coords; no browser-zone input involved.
    """
    # Monday 2026-05-25 00:47 UTC = 09:47 JST
    arrive_utc = datetime(2026, 5, 25, 0, 47, tzinfo=_tz.utc)
    depart_utc = datetime(2026, 5, 25, 1, 47, tzinfo=_tz.utc)

    # Venue open Mon 09:00-18:00 JST (Google day 1)
    hours = [_period(1, 9, 0, 1, 18)]

    # Derive timezone from Tokyo coordinates (mimics plan.py's derivation)
    tz_name = _destination_timezone(35.6762, 139.6503, "UTC")
    assert tz_name == "Asia/Tokyo"

    status, detail = compute_hours_status(hours, arrive_utc, depart_utc, tz_name)
    assert status == "open"
    assert detail is not None
    assert detail.closes_at == "18:00"


def test_tokyo_venue_closed_correctly_in_asia_tokyo() -> None:
    """UTC 23:47 (Sun) = Mon 08:47 JST. Venue opens Mon 09:00 JST -> closed."""
    # Sunday 2026-05-24 23:47 UTC = Monday 2026-05-25 08:47 JST
    arrive_utc = datetime(2026, 5, 24, 23, 47, tzinfo=_tz.utc)
    depart_utc = datetime(2026, 5, 25, 0, 47, tzinfo=_tz.utc)

    hours = [_period(1, 9, 0, 1, 18)]  # Mon 09:00-18:00 JST

    tz_name = _destination_timezone(35.6762, 139.6503, "UTC")
    assert tz_name == "Asia/Tokyo"

    status, detail = compute_hours_status(hours, arrive_utc, depart_utc, tz_name)
    assert status == "closed_on_arrival"
    assert detail is not None
    assert detail.opens_at == "09:00"
