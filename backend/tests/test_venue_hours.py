"""Tests for v2 opening-hours parsing and assessment (D24, D42, D43).

Raw inputs mirror the Place Details (New) JSON shapes for regularOpeningHours
and currentOpeningHours. Dates: 2026-10-19 is a Monday (Google day 1).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services.hours import hours_eligibility
from app.services.venue_hours import assess_hours, parse_venue_hours

_TZ = "Europe/Dublin"
_ZONE = ZoneInfo(_TZ)
# Fetched on Monday 2026-10-19 → date-specific coverage 19th..25th inclusive.
_FETCHED = datetime(2026, 10, 19, 8, 0, tzinfo=_ZONE)


def _local(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=_ZONE)


def _pt(day: int, hour: int, minute: int = 0, d: date | None = None, **extra: Any) -> dict:
    point: dict[str, Any] = {"day": day, "hour": hour, "minute": minute, **extra}
    if d is not None:
        point["date"] = {"year": d.year, "month": d.month, "day": d.day}
    return point


def _weekly_daily(open_h: int, close_h: int) -> dict:
    return {"periods": [{"open": _pt(g, open_h), "close": _pt(g, close_h)} for g in range(7)]}


def _current(days: list[date], open_h: int, close_h: int, **extra: Any) -> dict:
    periods = []
    for d in days:
        g = (d.weekday() + 1) % 7
        periods.append({"open": _pt(g, open_h, d=d), "close": _pt(g, close_h, d=d)})
    return {"periods": periods, **extra}


_ALWAYS_OPEN = {"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}
_WEEK = [date(2026, 10, 19) + timedelta(days=i) for i in range(7)]


def _assess(regular: Any, current: Any, arrive: datetime, depart: datetime):  # type: ignore[no-untyped-def]
    hours = parse_venue_hours(regular, current, _FETCHED, _TZ)
    return assess_hours(hours, arrive, depart, _TZ)


# --- source selection --------------------------------------------------------


def test_date_specific_closure_overrides_weekly_opening() -> None:
    """Weekly says open Wednesday; current hours (a holiday) have no Wednesday period."""
    days = [d for d in _WEEK if d != date(2026, 10, 21)]
    current = _current(days, 9, 17, specialDays=[{"date": {"year": 2026, "month": 10, "day": 21}}])
    status, detail = _assess(_weekly_daily(9, 17), current, _local(21, 10), _local(21, 11))
    assert status == "closed_on_arrival"
    assert detail.hours_source == "date_specific"
    assert detail.special_day is True
    assert detail.coverage_start == date(2026, 10, 19)
    assert detail.coverage_end == date(2026, 10, 25)
    assert detail.exceptions_unconfirmed is False


def test_visit_outside_coverage_uses_qualified_weekly() -> None:
    """2026-10-28 is beyond the 7-day window: weekly data, explicitly qualified."""
    current = _current(_WEEK, 9, 17)
    status, detail = _assess(_weekly_daily(9, 17), current, _local(28, 10), _local(28, 11))
    assert status == "open"
    assert detail.hours_source == "weekly"
    assert detail.exceptions_unconfirmed is True
    assert detail.coverage_start is None


def test_visit_crossing_coverage_end_falls_back_to_weekly() -> None:
    current = _current(_WEEK, 9, 23)
    status, detail = _assess(_weekly_daily(0, 23), current, _local(25, 22), _local(26, 1))
    assert detail.hours_source == "weekly"
    assert status == "closes_during_visit"


def test_only_current_hours_outside_coverage_is_unknown() -> None:
    status, detail = _assess(None, _current(_WEEK, 9, 17), _local(30, 10), _local(30, 11))
    assert status == "unknown"
    assert detail.unknown_reason == "outside_coverage"


def test_missing_hours_unknown_not_closed() -> None:
    status, detail = _assess(None, None, _local(21, 10), _local(21, 11))
    assert status == "unknown"
    assert detail.unknown_reason == "missing"


# --- malformed vs documented always-open --------------------------------------


def test_documented_always_open_shape_retained() -> None:
    status, detail = _assess(_ALWAYS_OPEN, None, _local(21, 3), _local(21, 5))
    assert status == "open"
    assert detail.always_open is True
    assert detail.hours_source == "weekly"


def test_date_specific_always_open_shape_retained() -> None:
    status, detail = _assess(None, _ALWAYS_OPEN, _local(21, 3), _local(21, 5))
    assert status == "open"
    assert detail.always_open is True
    assert detail.hours_source == "date_specific"


def test_missing_close_outside_documented_shape_is_malformed() -> None:
    """A period without close that is not Sunday 00:00 is NOT treated as 24 hours."""
    raw = {"periods": [{"open": _pt(1, 9)}]}
    status, detail = _assess(raw, None, _local(19, 10), _local(19, 11))
    assert status == "unknown"
    assert detail.unknown_reason == "malformed"


def test_two_open_only_periods_are_malformed() -> None:
    raw = {"periods": [{"open": _pt(0, 0)}, {"open": _pt(1, 0)}]}
    status, detail = _assess(raw, None, _local(19, 10), _local(19, 11))
    assert status == "unknown"
    assert detail.unknown_reason == "malformed"


def test_out_of_range_hour_is_malformed() -> None:
    raw = {"periods": [{"open": _pt(1, 9), "close": _pt(1, 25)}]}
    status, detail = _assess(raw, None, _local(19, 10), _local(19, 11))
    assert status == "unknown"
    assert detail.unknown_reason == "malformed"


def test_malformed_current_hours_fall_back_to_weekly() -> None:
    bad_current = {"periods": [{"open": _pt(3, 9), "close": _pt(3, 17)}]}  # no dates
    status, detail = _assess(_weekly_daily(9, 17), bad_current, _local(21, 10), _local(21, 11))
    assert status == "open"
    assert detail.hours_source == "weekly"


# --- boundaries --------------------------------------------------------------


def test_arrival_exactly_at_closing_is_closed() -> None:
    status, detail = _assess(_weekly_daily(9, 17), None, _local(21, 17), _local(21, 18))
    assert status == "closed_on_arrival"
    assert detail.opens_at == "09:00"


def test_finishing_exactly_at_closing_is_allowed() -> None:
    status, detail = _assess(_weekly_daily(9, 17), None, _local(21, 16), _local(21, 17))
    assert status == "open"
    assert detail.closes_at == "17:00"


def test_closes_during_visit() -> None:
    status, detail = _assess(_weekly_daily(9, 17), None, _local(21, 16), _local(21, 17, 30))
    assert status == "closes_during_visit"
    assert detail.closes_at == "17:00"


def test_overnight_period_open_after_midnight() -> None:
    """Friday 20:00 → Saturday 02:00 (Google days 5 → 6); arrive Saturday 01:00."""
    raw = {"periods": [{"open": _pt(5, 20), "close": _pt(6, 2)}]}
    status, detail = _assess(raw, None, _local(24, 1), _local(24, 1, 30))
    assert status == "open"
    assert detail.closes_at == "02:00"


def test_week_boundary_saturday_to_sunday() -> None:
    """Saturday 22:00 → Sunday 03:00 (6 → 0). Sunday 01:00 open; staying to 04:00 overruns."""
    raw = {"periods": [{"open": _pt(6, 22), "close": _pt(0, 3)}]}
    assert _assess(raw, None, _local(25, 1), _local(25, 2))[0] == "open"
    assert _assess(raw, None, _local(25, 1), _local(25, 4))[0] == "closes_during_visit"


def test_contiguous_periods_merge_across_midnight() -> None:
    """Back-to-back daily 00:00–24:00 periods: a visit across midnight is not flagged."""
    raw = {"periods": [{"open": _pt(g, 0), "close": _pt((g + 1) % 7, 0)} for g in range(7)]}
    status, _ = _assess(raw, None, _local(21, 23), _local(22, 1))
    assert status == "open"


def test_truncated_close_reports_no_closing_time() -> None:
    """A close clipped to the data window is not a real closing time."""
    d0, d6 = _WEEK[0], _WEEK[6]
    current = {
        "periods": [
            {
                "open": _pt(1, 9, d=d0),
                "close": _pt(0, 23, 59, d=d6, truncated=True),
            }
        ]
    }
    status, detail = _assess(None, current, _local(25, 23, 40), _local(25, 23, 50))
    assert status == "open"
    assert detail.closes_at is None


def test_closed_on_arrival_vs_zero_minute_vs_closing_during_visit() -> None:
    weekly = _weekly_daily(9, 17)
    closed, _ = _assess(weekly, None, _local(21, 18), _local(21, 19))
    assert hours_eligibility(closed, 60) == "disqualifying"
    zero, _ = _assess(weekly, None, _local(21, 18), _local(21, 18))
    assert zero == "closed_on_arrival"
    assert hours_eligibility(zero, 0) == "warning"
    during, _ = _assess(weekly, None, _local(21, 16), _local(21, 18))
    assert hours_eligibility(during, 120) == "warning"
    unknown, _ = _assess(None, None, _local(21, 16), _local(21, 18))
    assert hours_eligibility(unknown, 60) == "warning"


def test_utc_inputs_are_assessed_in_trip_timezone() -> None:
    """16:30 UTC in October is 17:30 IST — after a 17:00 close."""
    arrive = datetime(2026, 10, 21, 16, 30, tzinfo=timezone.utc)
    status, _ = _assess(_weekly_daily(9, 17), None, arrive, arrive)
    assert status == "closed_on_arrival"


def test_closes_soon_uses_real_elapsed_time_across_spring_forward() -> None:
    """Dublin, Sun 2027-03-28: clocks jump 01:00 GMT → 02:00 IST.

    Arriving 00:50 GMT at a venue closing 02:15 IST is 25 real minutes before
    closing (wall-clock difference would wrongly say 85 minutes).
    """
    raw = {"periods": [{"open": _pt(0, 0), "close": _pt(0, 2, 15)}]}
    hours = parse_venue_hours(raw, None, _FETCHED, _TZ)
    arrive = datetime(2027, 3, 28, 0, 50, tzinfo=timezone.utc)
    status, detail = assess_hours(hours, arrive, arrive, _TZ)
    assert status == "closes_soon"
    assert detail.closes_at == "02:15"


def test_visit_across_fall_back_finishes_before_real_closing() -> None:
    """Dublin, Sun 2026-10-25: 02:00 IST → 01:00 GMT. 00:30 IST + 2h30 real time
    ends at 02:00 GMT, exactly at a 02:00 closing — allowed."""
    raw = {"periods": [{"open": _pt(6, 20), "close": _pt(0, 2)}]}
    hours = parse_venue_hours(raw, None, _FETCHED, _TZ)
    arrive = datetime(2026, 10, 24, 23, 30, tzinfo=timezone.utc)  # 00:30 IST
    depart = arrive + timedelta(minutes=150)  # 02:00 GMT
    assert assess_hours(hours, arrive, depart, _TZ)[0] == "open"
    assert assess_hours(hours, arrive, depart + timedelta(minutes=1), _TZ)[0] == (
        "closes_during_visit"
    )


def test_next_opening_on_another_day_carries_its_date() -> None:
    status, detail = _assess(_weekly_daily(9, 17), None, _local(21, 18), _local(21, 19))
    assert status == "closed_on_arrival"
    assert (detail.opens_at, detail.opens_on) == ("09:00", date(2026, 10, 22))
    same_day, d2 = _assess(_weekly_daily(9, 17), None, _local(21, 8), _local(21, 9))
    assert same_day == "closed_on_arrival" and d2.opens_on is None
