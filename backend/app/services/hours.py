"""Opening-hours status computation for plan stops.

Given a stop's opening_hours (from geocoding) and its planned arrive_at /
depart_at datetimes, returns a status and optional machine-readable detail.

Timezone contract:
    arrive_at and depart_at MUST be in the trip city's local timezone.
    RouteWright plans a single day in a single city, so the client submits
    start_time in the city's local timezone and all derived datetimes share
    it.  Per-venue timezone lookup is NOT performed — see geocoder.py for the
    full assumption documentation.

Day convention (Google Places API):
    Sunday=0, Monday=1, Tuesday=2, Wednesday=3,
    Thursday=4, Friday=5, Saturday=6.

Python weekday() returns Monday=0 ... Sunday=6.
Conversion: google_day = (python_weekday + 1) % 7
"""

from datetime import datetime

from app.models.response import HoursDetail, HoursStatus
from app.services.geocoder import OpeningPeriod

# Minutes in a full week — used to normalise across the Sunday/Saturday boundary.
_WEEK_MINUTES = 7 * 24 * 60

# A place is flagged "closes_soon" when it shuts within this many minutes of
# the planned arrival (AND stays open for the full visit).
CLOSES_SOON_THRESHOLD = 30


def _to_week_minutes(dt: datetime) -> int:
    """Minutes since Sunday 0:00 in dt's local timezone."""
    google_day = (dt.weekday() + 1) % 7  # Mon(0)→1 … Sun(6)→0
    return google_day * 1440 + dt.hour * 60 + dt.minute


def _fmt_hm(minutes_since_midnight: int) -> str:
    """Return 'HH:MM' for a minutes-since-midnight value."""
    minutes_since_midnight = minutes_since_midnight % 1440
    return f"{minutes_since_midnight // 60:02d}:{minutes_since_midnight % 60:02d}"


def _period_open_abs(p: OpeningPeriod) -> int:
    return p.open_day * 1440 + p.open_minutes


def _period_close_abs(p: OpeningPeriod) -> int:
    """Close time as absolute week-minutes, with Saturday→Sunday wrap applied."""
    assert p.close_day is not None and p.close_minutes is not None
    close = p.close_day * 1440 + p.close_minutes
    open_ = _period_open_abs(p)
    if close < open_:  # crosses Sunday midnight (e.g. Sat 23:00 → Sun 02:00)
        close += _WEEK_MINUTES
    return close


def compute_hours_status(
    opening_hours: list[OpeningPeriod] | None,
    arrive_at: datetime,
    depart_at: datetime,
) -> tuple[HoursStatus, HoursDetail | None]:
    """Compute the hours status for a stop at its planned arrival time.

    Returns (status, detail) where detail carries machine-readable time facts
    for the frontend to compose into display text.

    Status values:
        "open"                — open on arrival, stays open through the visit
        "closed_on_arrival"   — closed when you arrive (detail.opens_at = next opening)
        "closes_during_visit" — open on arrival but closes before depart_at
        "closes_soon"         — open on arrival, closes within CLOSES_SOON_THRESHOLD
                                minutes of arrival (but not during the visit)
        "unknown"             — no hours data (opening_hours is None)

    All times in HoursDetail are HH:MM in the same timezone as arrive_at.
    """
    if not opening_hours:
        return "unknown", None

    # 24-hour place: any period with no close field.
    if any(p.close_day is None for p in opening_hours):
        return "open", None

    arrive_abs = _to_week_minutes(arrive_at)
    depart_abs = _to_week_minutes(depart_at)
    # Visits that cross midnight: depart_abs rolls back to a smaller number.
    if depart_abs < arrive_abs:
        depart_abs += _WEEK_MINUTES

    # Find the period active at arrive_abs.
    active_open = active_close = -1
    for p in opening_hours:
        if p.close_day is None or p.close_minutes is None:
            continue  # 24h guard (already handled above)
        p_open = _period_open_abs(p)
        p_close = _period_close_abs(p)

        if p_open <= arrive_abs < p_close:
            active_open, active_close = p_open, p_close
            break

        # Handle the Saturday->Sunday boundary: arrive is early Sunday (arrive_abs
        # ~0-120) but the active period started Saturday night (p_open ~9900+,
        # p_close = p_open + duration after WEEK_MINUTES normalisation ~10020+).
        shifted = arrive_abs + _WEEK_MINUTES
        if p_open <= shifted < p_close:
            arrive_abs = shifted
            depart_abs += _WEEK_MINUTES
            active_open, active_close = p_open, p_close
            break

    if active_open == -1:
        # Closed at arrival — find the soonest upcoming open time this week.
        next_open_abs: int | None = None
        for p in opening_hours:
            if p.close_day is None:
                continue
            p_open = _period_open_abs(p)
            # If this period has already opened this week, look at next week's occurrence.
            if p_open <= arrive_abs:
                p_open += _WEEK_MINUTES
            if next_open_abs is None or p_open < next_open_abs:
                next_open_abs = p_open

        opens_at = _fmt_hm(next_open_abs) if next_open_abs is not None else None
        return "closed_on_arrival", HoursDetail(opens_at=opens_at)

    # Place is open on arrival.
    close_str = _fmt_hm(active_close)

    if depart_abs > active_close:
        # Stay crosses the closing time.
        return "closes_during_visit", HoursDetail(closes_at=close_str)

    if active_close - arrive_abs <= CLOSES_SOON_THRESHOLD:
        # Closes within the threshold after arrival, but stay ends before close.
        return "closes_soon", HoursDetail(closes_at=close_str)

    return "open", HoursDetail(closes_at=close_str)
