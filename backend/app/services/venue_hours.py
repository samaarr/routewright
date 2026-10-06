"""Opening-hours parsing and assessment for the v2 planning engine (D24, D42, D43).

Source data comes from Place Details (New), fetched per operation:

- ``currentOpeningHours`` — documented as "the hours of operation for the next
  seven days (including today) incorporating any special opening hours".
  Points carry a calendar ``date``; ``truncated`` marks a point clipped to the
  edge of that seven-day window (the real open/close lies outside it).
- ``regularOpeningHours`` — "hours of operation for a place on a typical
  schedule". Weekday-based, no dates, no holiday exceptions.

Rules applied here:

- Date-specific hours are used only when the whole visit falls inside the
  documented coverage window (local date of the fetch + 6 days). Coverage is
  never inferred from the periods themselves.
- Otherwise weekly hours are used, flagged ``exceptions_unconfirmed``.
- Always-open is recognised ONLY in Google's documented shape: a single period
  opening day 0 at 00:00 with no ``close``. Any other missing close is
  malformed, and malformed or absent data is "unknown" — never open, never
  closed.
- Within date-specific coverage a date with no periods is a known closure
  (this is how explicit closed dates appear). Missing data never is.
- Arriving exactly at closing time is closed; finishing exactly at closing is
  allowed. Periods are expanded to concrete local datetimes and merged when
  contiguous, so overnight and Saturday->Sunday periods need no special cases.

Times are compared as wall-clock times in the trip timezone (venue hours are
wall-clock). Across a DST transition this can be off by the transition offset
for the affected hour; v1 accepts that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.models.response import HoursDetail, HoursStatus, HoursUnknownReason

# Documented coverage of currentOpeningHours: today plus the next six days.
DATE_SPECIFIC_COVERAGE_DAYS = 7

# Matches app.services.hours.CLOSES_SOON_THRESHOLD (v1) so both paths agree.
CLOSES_SOON_MINUTES = 30

_WEEK_MINUTES = 7 * 24 * 60


class _MalformedHoursError(ValueError):
    """Provider hours data present but not in a documented, usable shape."""


@dataclass(frozen=True)
class WeeklyPeriod:
    """One regularOpeningHours period. Google days: Sunday=0 .. Saturday=6."""

    open_day: int
    open_minutes: int
    close_day: int
    close_minutes: int


@dataclass(frozen=True)
class WeeklyHours:
    always_open: bool
    periods: tuple[WeeklyPeriod, ...]


@dataclass(frozen=True)
class DatedPeriod:
    """One currentOpeningHours period as local wall-clock datetimes."""

    open_at: datetime
    close_at: datetime
    close_truncated: bool


@dataclass(frozen=True)
class DateSpecificHours:
    coverage_start: date
    coverage_end: date  # inclusive
    always_open: bool
    periods: tuple[DatedPeriod, ...]
    special_days: frozenset[date]


@dataclass(frozen=True)
class VenueHours:
    """Request-scoped hours for one place. Never persisted (D38)."""

    weekly: WeeklyHours | None
    date_specific: DateSpecificHours | None
    # True when some hours data was present but unusable; distinguishes
    # "malformed" from "missing" when nothing usable remains.
    had_malformed: bool = False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _int_field(point: dict[str, Any], key: str, lo: int, hi: int) -> int:
    # proto3 JSON may omit zero-valued fields, so absent means 0.
    value = point.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise _MalformedHoursError(f"{key} out of range")
    return value


def _point_clock(point: Any) -> tuple[int, int, int]:
    if not isinstance(point, dict):
        raise _MalformedHoursError("point is not an object")
    return (
        _int_field(point, "day", 0, 6),
        _int_field(point, "hour", 0, 23),
        _int_field(point, "minute", 0, 59),
    )


def _point_date(point: dict[str, Any]) -> date:
    raw = point.get("date")
    if not isinstance(raw, dict):
        raise _MalformedHoursError("date-specific point has no date")
    try:
        return date(int(raw["year"]), int(raw["month"]), int(raw["day"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise _MalformedHoursError("invalid date") from exc


def _periods(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        raise _MalformedHoursError("hours is not an object")
    periods = raw.get("periods")
    if not isinstance(periods, list) or not periods:
        raise _MalformedHoursError("no periods")
    if not all(isinstance(p, dict) for p in periods):
        raise _MalformedHoursError("period is not an object")
    return periods


def _is_documented_always_open(periods: list[dict[str, Any]]) -> bool:
    if len(periods) != 1 or "close" in periods[0]:
        return False
    return _point_clock(periods[0].get("open")) == (0, 0, 0)


def _parse_weekly(raw: Any) -> WeeklyHours:
    periods = _periods(raw)
    if _is_documented_always_open(periods):
        return WeeklyHours(always_open=True, periods=())
    parsed: list[WeeklyPeriod] = []
    for p in periods:
        if "close" not in p:
            raise _MalformedHoursError("missing close outside the documented always-open shape")
        o_day, o_h, o_m = _point_clock(p.get("open"))
        c_day, c_h, c_m = _point_clock(p.get("close"))
        parsed.append(WeeklyPeriod(o_day, o_h * 60 + o_m, c_day, c_h * 60 + c_m))
    return WeeklyHours(always_open=False, periods=tuple(parsed))


def _parse_date_specific(raw: Any, fetched_local_date: date) -> DateSpecificHours:
    periods = _periods(raw)
    coverage_end = fetched_local_date + timedelta(days=DATE_SPECIFIC_COVERAGE_DAYS - 1)
    special: set[date] = set()
    for sd in raw.get("specialDays") or []:
        if isinstance(sd, dict):
            try:
                special.add(_point_date(sd))
            except _MalformedHoursError:
                continue  # informational only; a bad entry must not discard hours
    if _is_documented_always_open(periods):
        return DateSpecificHours(fetched_local_date, coverage_end, True, (), frozenset(special))
    parsed: list[DatedPeriod] = []
    for p in periods:
        open_pt, close_pt = p.get("open"), p.get("close")
        if not isinstance(open_pt, dict) or not isinstance(close_pt, dict):
            raise _MalformedHoursError("date-specific period needs open and close")
        _, o_h, o_m = _point_clock(open_pt)
        _, c_h, c_m = _point_clock(close_pt)
        open_at = datetime.combine(_point_date(open_pt), datetime.min.time()).replace(
            hour=o_h, minute=o_m
        )
        close_at = datetime.combine(_point_date(close_pt), datetime.min.time()).replace(
            hour=c_h, minute=c_m
        )
        if close_at <= open_at:
            raise _MalformedHoursError("close not after open")
        parsed.append(DatedPeriod(open_at, close_at, close_pt.get("truncated") is True))
    return DateSpecificHours(
        fetched_local_date, coverage_end, False, tuple(parsed), frozenset(special)
    )


def parse_venue_hours(
    regular_raw: Any,
    current_raw: Any,
    fetched_at: datetime,
    trip_timezone: str,
) -> VenueHours | None:
    """Parse Place Details hours fields. Returns None when neither is present.

    ``fetched_at`` (aware) anchors the date-specific coverage window to the
    local date the provider data was retrieved in the trip timezone.
    """
    malformed = False
    weekly: WeeklyHours | None = None
    current: DateSpecificHours | None = None
    if regular_raw is not None:
        try:
            weekly = _parse_weekly(regular_raw)
        except _MalformedHoursError:
            malformed = True
    if current_raw is not None:
        fetched_local = fetched_at.astimezone(ZoneInfo(trip_timezone)).date()
        try:
            current = _parse_date_specific(current_raw, fetched_local)
        except _MalformedHoursError:
            malformed = True
    if weekly is None and current is None and not malformed:
        return None
    return VenueHours(weekly=weekly, date_specific=current, had_malformed=malformed)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Interval:
    open_at: datetime
    close_at: datetime
    close_truncated: bool = False


def _weekly_intervals(weekly: WeeklyHours, first: date, last: date) -> list[_Interval]:
    out: list[_Interval] = []
    d = first
    while d <= last:
        google_day = (d.weekday() + 1) % 7  # Python Mon=0 -> Google Mon=1
        for p in weekly.periods:
            if p.open_day != google_day:
                continue
            open_abs = p.open_day * 1440 + p.open_minutes
            close_abs = p.close_day * 1440 + p.close_minutes
            if close_abs <= open_abs:  # wraps past Saturday -> Sunday
                close_abs += _WEEK_MINUTES
            open_at = datetime.combine(d, datetime.min.time()) + timedelta(minutes=p.open_minutes)
            out.append(_Interval(open_at, open_at + timedelta(minutes=close_abs - open_abs)))
        d += timedelta(days=1)
    return out


def _merge(intervals: list[_Interval]) -> list[_Interval]:
    merged: list[_Interval] = []
    for iv in sorted(intervals, key=lambda i: i.open_at):
        if merged and iv.open_at <= merged[-1].close_at:
            last = merged[-1]
            if iv.close_at > last.close_at:
                merged[-1] = _Interval(last.open_at, iv.close_at, iv.close_truncated)
        else:
            merged.append(iv)
    return merged


def _hm(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _classify(
    intervals: list[_Interval], arrive: datetime, depart: datetime, base: HoursDetail
) -> tuple[HoursStatus, HoursDetail]:
    merged = _merge(intervals)
    active = next((iv for iv in merged if iv.open_at <= arrive < iv.close_at), None)
    if active is None:
        upcoming = [iv.open_at for iv in merged if iv.open_at > arrive]
        opens_at = _hm(min(upcoming)) if upcoming else None
        return "closed_on_arrival", base.model_copy(update={"opens_at": opens_at})
    if active.close_truncated:
        # Real closing time lies beyond the data window: open for the visit,
        # but no closing time can be stated.
        return "open", base
    detail = base.model_copy(update={"closes_at": _hm(active.close_at)})
    if depart > active.close_at:
        return "closes_during_visit", detail
    if active.close_at - arrive <= timedelta(minutes=CLOSES_SOON_MINUTES):
        return "closes_soon", detail
    return "open", detail


def _unknown(reason: HoursUnknownReason) -> tuple[HoursStatus, HoursDetail]:
    return "unknown", HoursDetail(unknown_reason=reason)


def assess_hours(
    hours: VenueHours | None,
    arrive_at: datetime,
    depart_at: datetime,
    trip_timezone: str,
) -> tuple[HoursStatus, HoursDetail]:
    """Assess a visit [arrive_at, depart_at] (aware datetimes) against venue hours."""
    if hours is None:
        return _unknown("missing")
    tz = ZoneInfo(trip_timezone)
    arrive = arrive_at.astimezone(tz).replace(tzinfo=None)
    depart = depart_at.astimezone(tz).replace(tzinfo=None)

    ds = hours.date_specific
    if ds is not None and ds.coverage_start <= arrive.date() and depart.date() <= ds.coverage_end:
        base = HoursDetail(
            hours_source="date_specific",
            coverage_start=ds.coverage_start,
            coverage_end=ds.coverage_end,
            special_day=arrive.date() in ds.special_days or depart.date() in ds.special_days,
        )
        if ds.always_open:
            return "open", base.model_copy(update={"always_open": True})
        intervals = [_Interval(p.open_at, p.close_at, p.close_truncated) for p in ds.periods]
        return _classify(intervals, arrive, depart, base)

    wk = hours.weekly
    if wk is not None:
        base = HoursDetail(hours_source="weekly", exceptions_unconfirmed=True)
        if wk.always_open:
            return "open", base.model_copy(update={"always_open": True})
        first = arrive.date() - timedelta(days=1)  # a period may have opened yesterday
        last = depart.date() + timedelta(days=1)
        return _classify(_weekly_intervals(wk, first, last), arrive, depart, base)

    if ds is not None:
        return _unknown("outside_coverage")
    return _unknown("malformed" if hours.had_malformed else "missing")
