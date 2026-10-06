"""Offline IANA timezone lookup from lat/lng via timezonefinder.

TimezoneFinder reads its bundled data on __init__ and is thread-safe for
reads.  Instantiate once here; plan, optimise and the v2 verifier share it.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()


def resolve_timezone(lat: float, lng: float) -> str | None:
    """Return the IANA zone at the coordinates, or None if unresolvable.

    No fallback of any kind (D40): callers must block on None. A name that
    the local tz database cannot load is also treated as unresolvable.
    """
    tz = _tf.timezone_at(lat=lat, lng=lng)
    if tz is None:
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return tz


def destination_timezone(lat: float, lng: float, fallback: str) -> str:
    """Legacy v1 lookup with a fallback zone. Not used by the v2 engine.

    Falls back to `fallback` when the lookup returns None (ocean/null-island),
    and ultimately to 'UTC' if fallback is also absent.
    """
    tz = _tf.timezone_at(lat=lat, lng=lng)
    return tz if tz is not None else (fallback or "UTC")
