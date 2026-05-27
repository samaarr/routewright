"""Offline IANA timezone lookup from lat/lng via timezonefinder.

TimezoneFinder reads its bundled data on __init__ and is thread-safe for
reads.  Instantiate once here; both plan and optimise routers import
destination_timezone from this module so a single object is shared.
"""

from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()


def destination_timezone(lat: float, lng: float, fallback: str) -> str:
    """Return the IANA timezone for the given coordinates.

    Uses offline timezonefinder data — no network call.  Falls back to
    `fallback` when the lookup returns None (ocean/null-island), and
    ultimately to 'UTC' if fallback is also absent.
    """
    tz = _tf.timezone_at(lat=lat, lng=lng)
    return tz if tz is not None else (fallback or "UTC")
