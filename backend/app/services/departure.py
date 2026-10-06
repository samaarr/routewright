"""Departure time resolver: DepartureInput -> UTC-aware datetime (D14, D29, D40).

Clock-change handling:
- Skipped local time (clocks jump forward): rejected; never shifted.
- Repeated local time (clocks fall back): ``occurrence`` is required and means
  chronological order — 1 = the earlier instant, 2 = the later instant.
  Standard/summer labels are deliberately not used: which occurrence is
  "summer time" differs by location (e.g. Europe/Dublin's legal standard time
  is the summer offset).
- ``occurrence`` supplied for an ordinary, unambiguous time is rejected as a
  stale or invalid client claim rather than silently ignored.

Range: the Routes API's documented window — not more than 7 days in the past
or 100 days in the future; walking/driving must start in the future (past
departure times are accepted only for transit). The same check applies to a
refresh's planned departure (``unsupported_departure_reason``).

All failures raise DepartureError subclasses, mapped by the router to 422.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.request import MAX_FUTURE_DAYS, DepartureInput, TransportMode

_MAX_PAST_DAYS = 7


class DepartureError(ValueError):
    """Base class: the departure input cannot be converted safely."""

    code = "departure_invalid"


class InvalidDepartureDateError(DepartureError):
    """The local date/time is not a real calendar date/time."""

    code = "departure_invalid_date"


class NonExistentDepartureError(DepartureError):
    """The requested local time falls in a spring-forward gap."""

    code = "departure_nonexistent"


class AmbiguousDepartureError(DepartureError):
    """The local time occurs twice and no occurrence was chosen."""

    code = "departure_ambiguous"


class OccurrenceNotApplicableError(DepartureError):
    """An occurrence was supplied for a time that occurs only once."""

    code = "departure_occurrence_not_applicable"


class DepartureOutOfRangeError(DepartureError):
    """The departure is outside the supported planning window."""

    code = "departure_out_of_range"


def resolve_departure(
    dep: DepartureInput,
    *,
    mode: TransportMode = "transit",
    now: datetime | None = None,
    check_range: bool = True,
) -> datetime:
    """Convert a destination-local DepartureInput to a UTC-aware datetime.

    ``check_range=False`` (refresh): the trip's original departure is not
    routed again, so only its clock-change validity is checked; the refresh
    checks its planned departure instead.
    """
    try:
        year, month, day = (int(p) for p in dep.local_date.split("-"))
        hour, minute = (int(p) for p in dep.local_time.split(":"))
        dt_naive = datetime(year, month, day, hour, minute)
    except ValueError as exc:
        raise InvalidDepartureDateError(
            f"{dep.local_date} {dep.local_time} is not a valid date and time."
        ) from exc
    tz = ZoneInfo(dep.timezone)

    # Skipped time: a fold=0 round trip through UTC lands on a different wall time.
    dt0 = dt_naive.replace(tzinfo=tz, fold=0)
    if dt0.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != dt_naive:
        raise NonExistentDepartureError(
            f"{dep.local_date} {dep.local_time} does not exist in {dep.timezone}: "
            "the clocks skip that time. Choose another time."
        )

    # Repeated time: fold=0 and fold=1 give different UTC offsets.
    dt1 = dt_naive.replace(tzinfo=tz, fold=1)
    repeated = dt0.utcoffset() != dt1.utcoffset()
    if repeated and dep.occurrence is None:
        raise AmbiguousDepartureError(
            f"{dep.local_date} {dep.local_time} occurs twice in {dep.timezone}. "
            "Choose the first (earlier) or second (later) occurrence."
        )
    if not repeated and dep.occurrence is not None:
        raise OccurrenceNotApplicableError(
            f"{dep.local_date} {dep.local_time} occurs only once in {dep.timezone}; "
            "remove the occurrence choice."
        )

    # Python's fold=0 is the chronologically earlier instant, fold=1 the later.
    local = dt1 if dep.occurrence == 2 else dt0
    utc = local.astimezone(timezone.utc)
    problem = unsupported_departure_reason(utc, mode, now) if check_range else None
    if problem:
        raise DepartureOutOfRangeError(f"The departure {problem}.")
    return utc


def unsupported_departure_reason(
    utc: datetime, mode: TransportMode, now: datetime | None = None
) -> str | None:
    """Why the Routes API cannot schedule a departure at ``utc``, or None.

    Routes API (computeRoutes ``departureTime``, verified 2026-10-06): past
    times are allowed only for TRANSIT; transit is available up to 7 days in
    the past and 100 days in the future. Callers explain the problem; they
    never substitute the current time.
    """
    current = now or datetime.now(timezone.utc)
    if utc < current - timedelta(days=_MAX_PAST_DAYS):
        return f"must not be more than {_MAX_PAST_DAYS} days in the past"
    if utc > current + timedelta(days=MAX_FUTURE_DAYS):
        return f"must not be more than {MAX_FUTURE_DAYS} days in the future"
    if mode != "transit" and utc < current:
        return "must be in the future for walking and driving"
    return None


class PlannedDepartureError(DepartureError):
    """A refresh's planned departure cannot be used (D21).

    The refresh never falls back to the current time; the user is told why
    and can plan the day again instead.
    """

    code = "planned_departure_unsupported"


class DepartureTimezoneMismatchError(DepartureError):
    """The submitted departure zone differs from the verified city's zone."""

    code = "departure_timezone_mismatch"

    def __init__(self, submitted: str, resolved: str) -> None:
        super().__init__(
            f"The departure was entered for {submitted}, but the selected city is in "
            f"{resolved}. Re-enter the departure time for the selected city."
        )
        self.submitted = submitted
        self.resolved = resolved
