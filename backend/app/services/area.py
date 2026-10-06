"""Outside-area checks against a city's provider-supplied viewport (D25, D44).

The viewport is Google's suggested map framing for the selected city — NOT an
administrative boundary. A stop outside it is still allowed (it only has to
pass the one-timezone rule); the user just sees "Outside the selected city's
suggested area." When no usable viewport is available the check is reported as
unavailable rather than guessed with an invented radius.

Boundary points count as inside. A viewport whose low longitude is greater
than its high longitude crosses the antimeridian (Google's documented
representation), so the longitude test wraps.
"""

import math
from dataclasses import dataclass
from typing import Any, Literal

AreaStatus = Literal["inside", "outside", "unavailable"]

OUTSIDE_AREA_MESSAGE = "Outside the selected city's suggested area."
AREA_UNAVAILABLE_MESSAGE = (
    "The suggested-area check is unavailable for the selected city, so stops "
    "were not compared against it."
)


@dataclass(frozen=True)
class Viewport:
    low_lat: float
    low_lng: float
    high_lat: float
    high_lng: float


def _finite_in(value: Any, lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f = float(value)
    return f if math.isfinite(f) and lo <= f <= hi else None


def parse_viewport(raw: Any) -> Viewport | None:
    """Parse a Places ``viewport`` ({low:{latitude,longitude}, high:{...}}).

    Returns None for anything missing or invalid (the check is then
    "unavailable"). Low latitude must not exceed high latitude.
    """
    if not isinstance(raw, dict):
        return None
    low, high = raw.get("low"), raw.get("high")
    if not isinstance(low, dict) or not isinstance(high, dict):
        return None
    values = (
        _finite_in(low.get("latitude"), -90, 90),
        _finite_in(low.get("longitude"), -180, 180),
        _finite_in(high.get("latitude"), -90, 90),
        _finite_in(high.get("longitude"), -180, 180),
    )
    if any(v is None for v in values):
        return None
    low_lat, low_lng, high_lat, high_lng = (float(v) for v in values)  # type: ignore[arg-type]
    if low_lat > high_lat:
        return None
    return Viewport(low_lat, low_lng, high_lat, high_lng)


def area_status(viewport: Viewport | None, lat: float, lng: float) -> AreaStatus:
    if viewport is None:
        return "unavailable"
    if not viewport.low_lat <= lat <= viewport.high_lat:
        return "outside"
    if viewport.low_lng <= viewport.high_lng:
        inside = viewport.low_lng <= lng <= viewport.high_lng
    else:  # crosses the antimeridian
        inside = lng >= viewport.low_lng or lng <= viewport.high_lng
    return "inside" if inside else "outside"
