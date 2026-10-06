"""Departure time resolver: DepartureInput -> UTC-aware datetime.

Handles the two DST edge cases:
- Spring-forward gap: the requested local time does not exist (e.g. clocks
  skip from 01:00 directly to 02:00). Rejected with a clear message.
- Fall-back fold: the same local time occurs twice. Requires occurrence=1
  (first/standard) or occurrence=2 (second/summer) to disambiguate.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.models.request import DepartureInput


class NonExistentDepartureError(ValueError):
    """The requested local time falls in a spring-forward gap."""


class AmbiguousDepartureError(ValueError):
    """The requested local time is ambiguous during a fall-back clock change."""


def resolve_departure(dep: DepartureInput) -> datetime:
    """Convert a DepartureInput to a UTC-aware datetime.

    Raises:
        NonExistentDepartureError: If the time is in a spring-forward gap.
        AmbiguousDepartureError: If the time is in a fall-back fold and
            ``occurrence`` was not supplied.
    """
    year, month, day = (int(p) for p in dep.local_date.split("-"))
    hour, minute = (int(p) for p in dep.local_time.split(":"))
    tz = ZoneInfo(dep.timezone)
    dt_naive = datetime(year, month, day, hour, minute)

    # Detect spring-forward gap first: convert fold=0 to UTC and back.
    # If the round-trip gives a different local time, the original time is in
    # the skipped hour and does not exist.
    dt0 = dt_naive.replace(tzinfo=tz, fold=0)
    dt_utc0 = dt0.astimezone(timezone.utc)
    dt_roundtrip = dt_utc0.astimezone(tz).replace(tzinfo=None)
    if dt_roundtrip != dt_naive:
        raise NonExistentDepartureError(
            f"The time {dep.local_date} {dep.local_time} does not exist in "
            f"{dep.timezone} (spring-forward clock change)."
        )

    # Detect fall-back ambiguity: fold=0 and fold=1 have different UTC offsets,
    # meaning the same wall-clock time occurs twice.
    dt1 = dt_naive.replace(tzinfo=tz, fold=1)
    is_fold = dt0.utcoffset() != dt1.utcoffset()

    if is_fold and dep.occurrence is None:
        raise AmbiguousDepartureError(
            f"The time {dep.local_date} {dep.local_time} is ambiguous in "
            f"{dep.timezone} (fall-back clock change). "
            "Supply occurrence=1 (first/standard) or occurrence=2 (second/summer)."
        )

    # Build the local datetime with the correct fold value.
    fold = 1 if dep.occurrence == 2 else 0
    dt_local = dt_naive.replace(tzinfo=tz, fold=fold)
    return dt_local.astimezone(timezone.utc)
