"""Tests for opening-hours parsing, status computation, and cache round-trip.

All status tests use 2026-05-25 (Monday) as the trip date.
  datetime(2026, 5, 25).weekday() == 0 (Monday) → Google day 1.
  datetime(2026, 5, 24).weekday() == 6 (Sunday)  → Google day 0.
  datetime(2026, 5, 23).weekday() == 5 (Saturday) → Google day 6.

Trip timezone: UTC+1 (Dublin IST) — chosen to verify that
compute_hours_status uses local hour/minute, not UTC.
"""

from datetime import datetime, timedelta, timezone

from app.models.response import HoursDetail
from app.services.geocoder import OpeningPeriod
from app.services.hours import compute_hours_status, is_disqualifying_for_optimisation

# Trip timezone — UTC+1 (Dublin IST used in tests for concreteness).
_IST = timezone(timedelta(hours=1))


# Helpers
def _monday(hour: int, minute: int = 0) -> datetime:
    """2026-05-25 (Monday) at HH:MM in IST."""
    return datetime(2026, 5, 25, hour, minute, tzinfo=_IST)


def _saturday(hour: int, minute: int = 0) -> datetime:
    """2026-05-23 (Saturday) at HH:MM in IST."""
    return datetime(2026, 5, 23, hour, minute, tzinfo=_IST)


def _sunday(hour: int, minute: int = 0) -> datetime:
    """2026-05-24 (Sunday) at HH:MM in IST."""
    return datetime(2026, 5, 24, hour, minute, tzinfo=_IST)


def _period(
    od: int, oh: int, om: int = 0, cd: int | None = None, ch: int | None = None, cm: int = 0
) -> OpeningPeriod:
    """Shorthand for building an OpeningPeriod."""
    return OpeningPeriod(
        open_day=od,
        open_minutes=oh * 60 + om,
        close_day=cd,
        close_minutes=(ch * 60 + cm) if ch is not None else None,
    )


# ---------------------------------------------------------------------------
# Hours status computation
# ---------------------------------------------------------------------------


_TZ = "Europe/Dublin"  # UTC+1 in May 2026 — matches _IST used in helper datetimes


def test_status_unknown_when_no_hours() -> None:
    status, detail = compute_hours_status(None, _monday(10), _monday(11), _TZ)
    assert status == "unknown"
    assert detail is None


def test_status_open_24h_place() -> None:
    """24-hour place always returns 'open' with no detail."""
    hours = [OpeningPeriod(open_day=0, open_minutes=0, close_day=None, close_minutes=None)]
    status, detail = compute_hours_status(hours, _monday(3), _monday(4), _TZ)
    assert status == "open"
    assert detail is None


def test_status_open_within_hours() -> None:
    """Arrive 10:00, depart 11:00, place open Mon 09:00-17:00."""
    hours = [_period(1, 9, 0, 1, 17)]
    status, detail = compute_hours_status(hours, _monday(10), _monday(11), _TZ)
    assert status == "open"
    assert isinstance(detail, HoursDetail)
    assert detail.closes_at == "17:00"


def test_status_closed_on_arrival() -> None:
    """Arrive 08:00, place opens Mon 09:00-17:00."""
    hours = [_period(1, 9, 0, 1, 17)]
    status, detail = compute_hours_status(hours, _monday(8), _monday(9), _TZ)
    assert status == "closed_on_arrival"
    assert isinstance(detail, HoursDetail)
    assert detail.opens_at == "09:00"


def test_status_closed_on_arrival_provides_next_open() -> None:
    """Closed on a Sunday; next open is Monday 09:00."""
    hours = [_period(1, 9, 0, 1, 17)]  # only Monday hours
    status, detail = compute_hours_status(hours, _sunday(14), _sunday(15), _TZ)
    assert status == "closed_on_arrival"
    assert detail is not None
    assert detail.opens_at == "09:00"


def test_status_closes_during_visit() -> None:
    """Arrive 16:00, depart 18:00, close 17:00 — closes during the stay."""
    hours = [_period(1, 9, 0, 1, 17)]
    status, detail = compute_hours_status(hours, _monday(16), _monday(18), _TZ)
    assert status == "closes_during_visit"
    assert isinstance(detail, HoursDetail)
    assert detail.closes_at == "17:00"


def test_status_closes_soon() -> None:
    """Arrive 16:40, depart 16:55, close 17:00 — open but closes within 30 min."""
    hours = [_period(1, 9, 0, 1, 17)]
    status, detail = compute_hours_status(hours, _monday(16, 40), _monday(16, 55), _TZ)
    assert status == "closes_soon"
    assert isinstance(detail, HoursDetail)
    assert detail.closes_at == "17:00"


def test_status_priority_closes_during_visit_beats_closes_soon() -> None:
    """closes_during_visit takes priority even if arrival is also within 30 min of close."""
    hours = [_period(1, 9, 0, 1, 17)]
    # Arrive 16:45, depart 17:30 — visit crosses close at 17:00
    status, detail = compute_hours_status(hours, _monday(16, 45), _monday(17, 30), _TZ)
    assert status == "closes_during_visit"
    assert detail is not None
    assert detail.closes_at == "17:00"


def test_status_midnight_spanning_period() -> None:
    """Saturday 22:00 - Sunday 02:00: arrive Saturday 23:00, depart Saturday 23:30."""
    hours = [_period(6, 22, 0, 0, 2)]  # Sat 22:00 - Sun 02:00
    status, detail = compute_hours_status(hours, _saturday(23), _saturday(23, 30), _TZ)
    assert status == "open"
    assert detail is not None
    assert detail.closes_at == "02:00"


def test_status_saturday_night_arrives_sunday() -> None:
    """Period Sat 22:00 - Sun 02:00: arrive Sunday 01:00 (within the period)."""
    hours = [_period(6, 22, 0, 0, 2)]  # Sat 22:00 - Sun 02:00
    status, detail = compute_hours_status(hours, _sunday(1), _sunday(1, 30), _TZ)
    assert status == "open"
    assert detail is not None
    assert detail.closes_at == "02:00"


def test_status_multi_interval_correct_period_selected() -> None:
    """Arrive during lunch gap → closed; arrives at dinner → open."""
    hours = [
        _period(1, 12, 0, 1, 14),  # Mon lunch  12:00-14:00
        _period(1, 18, 0, 1, 23),  # Mon dinner 18:00-23:00
    ]
    # Arrive at 15:00 (gap between lunch and dinner)
    s, d = compute_hours_status(hours, _monday(15), _monday(15, 30), _TZ)
    assert s == "closed_on_arrival"
    assert d is not None
    assert d.opens_at == "18:00"

    # Arrive at 19:00 (during dinner)
    s2, d2 = compute_hours_status(hours, _monday(19), _monday(19, 30), _TZ)
    assert s2 == "open"
    assert d2 is not None
    assert d2.closes_at == "23:00"


# ---------------------------------------------------------------------------
# UTC-arrival regression tests (BST timezone)
# ---------------------------------------------------------------------------


def test_status_open_utc_arrival_bst_city() -> None:
    """Monmouth regression: UTC 07:47 = BST 08:47, opens Mon 08:00 local — must be 'open'.

    This is the exact false-positive that was reported: _to_week_minutes was reading
    the UTC hour (7) instead of the local hour (8), missing the active period.
    """
    from datetime import timezone as _timezone

    hours = [_period(1, 8, 0, 1, 18)]  # Mon 08:00-18:00
    arrive = datetime(2026, 5, 25, 7, 47, tzinfo=_timezone.utc)  # 08:47 BST
    depart = datetime(2026, 5, 25, 8, 47, tzinfo=_timezone.utc)  # 09:47 BST
    status, detail = compute_hours_status(hours, arrive, depart, "Europe/London")
    assert status == "open"
    assert detail is not None
    assert detail.closes_at == "18:00"


def test_status_closed_on_arrival_utc_arrival_bst_city() -> None:
    """Black Pig: UTC 08:45 = BST 09:45, opens Mon 10:00 local — must be closed_on_arrival."""
    from datetime import timezone as _timezone

    hours = [_period(1, 10, 0, 1, 17)]  # Mon 10:00-17:00
    arrive = datetime(2026, 5, 25, 8, 45, tzinfo=_timezone.utc)  # 09:45 BST
    depart = datetime(2026, 5, 25, 9, 45, tzinfo=_timezone.utc)  # 10:45 BST
    status, detail = compute_hours_status(hours, arrive, depart, "Europe/London")
    assert status == "closed_on_arrival"
    assert detail is not None
    assert detail.opens_at == "10:00"


# ---------------------------------------------------------------------------
# Arrival exactly at closing time (D42 boundary)
# ---------------------------------------------------------------------------


def test_status_arrival_exactly_at_closing() -> None:
    """Arriving at precisely the close time is treated as closed_on_arrival.

    The active-period condition is p_open <= arrive_abs < p_close (strict less-than),
    so the place is no longer open at the close minute itself.
    """
    hours = [_period(1, 9, 0, 1, 17)]  # Mon 09:00-17:00
    # Arrive exactly at 17:00
    status, detail = compute_hours_status(hours, _monday(17), _monday(17, 30), _TZ)
    assert status == "closed_on_arrival"
    # Next opening is Monday 09:00 (next week — only Monday hours available)
    assert detail is not None
    assert detail.opens_at == "09:00"


# ---------------------------------------------------------------------------
# hours_source propagation (D43)
# ---------------------------------------------------------------------------


def test_hours_source_none_by_default() -> None:
    """hours_source defaults to None when not supplied."""
    hours = [_period(1, 9, 0, 1, 17)]
    _, detail = compute_hours_status(hours, _monday(10), _monday(11), _TZ)
    assert detail is not None
    assert detail.hours_source is None


def test_hours_source_weekly_propagated_open() -> None:
    """hours_source='weekly' propagates to HoursDetail for an open stop."""
    hours = [_period(1, 9, 0, 1, 17)]
    _, detail = compute_hours_status(hours, _monday(10), _monday(11), _TZ, hours_source="weekly")
    assert detail is not None
    assert detail.hours_source == "weekly"


def test_hours_source_weekly_propagated_closed_on_arrival() -> None:
    """hours_source='weekly' propagates to HoursDetail for closed_on_arrival."""
    hours = [_period(1, 9, 0, 1, 17)]
    _, detail = compute_hours_status(hours, _monday(8), _monday(9), _TZ, hours_source="weekly")
    assert detail is not None
    assert detail.hours_source == "weekly"


def test_hours_source_weekly_propagated_closes_during_visit() -> None:
    """hours_source='weekly' propagates to HoursDetail for closes_during_visit."""
    hours = [_period(1, 9, 0, 1, 17)]
    _, detail = compute_hours_status(hours, _monday(16), _monday(18), _TZ, hours_source="weekly")
    assert detail is not None
    assert detail.hours_source == "weekly"


def test_hours_source_date_specific_propagated() -> None:
    """hours_source='date_specific' propagates (reserved for currentOpeningHours)."""
    hours = [_period(1, 9, 0, 1, 17)]
    _, detail = compute_hours_status(
        hours, _monday(10), _monday(11), _TZ, hours_source="date_specific"
    )
    assert detail is not None
    assert detail.hours_source == "date_specific"


def test_hours_source_not_in_detail_for_24h_place() -> None:
    """24-hour place returns (open, None) — no HoursDetail even with hours_source."""
    hours = [OpeningPeriod(open_day=0, open_minutes=0, close_day=None, close_minutes=None)]
    status, detail = compute_hours_status(hours, _monday(3), _monday(4), _TZ, hours_source="weekly")
    assert status == "open"
    assert detail is None  # 24h places never carry detail


# ---------------------------------------------------------------------------
# is_disqualifying_for_optimisation (D42, D24)
# ---------------------------------------------------------------------------


def test_disqualifying_closed_on_arrival_positive_stay() -> None:
    """closed_on_arrival + positive stay → disqualifying (D42)."""
    assert is_disqualifying_for_optimisation("closed_on_arrival", stay_minutes=60) is True


def test_not_disqualifying_closed_on_arrival_zero_stay() -> None:
    """closed_on_arrival + zero stay → warning only (D24 — zero-minute anchor stop)."""
    assert is_disqualifying_for_optimisation("closed_on_arrival", stay_minutes=0) is False


def test_not_disqualifying_closes_during_visit() -> None:
    """closes_during_visit → warning only, not disqualifying (D42)."""
    assert is_disqualifying_for_optimisation("closes_during_visit", stay_minutes=90) is False


def test_not_disqualifying_closes_soon() -> None:
    assert is_disqualifying_for_optimisation("closes_soon", stay_minutes=60) is False


def test_not_disqualifying_open() -> None:
    assert is_disqualifying_for_optimisation("open", stay_minutes=60) is False


def test_not_disqualifying_unknown() -> None:
    """Unknown hours never block optimisation — absence of data is not a conflict."""
    assert is_disqualifying_for_optimisation("unknown", stay_minutes=60) is False
