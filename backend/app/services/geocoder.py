"""Place data types shared by the hours logic and the local optimiser.

Historically this module also held the v1 Text Search (New) geocoder used by
the legacy /api/plan and /api/optimise endpoints. Those endpoints were
retired on 2026-10-06 and the Text Search client with them, so the app no
longer issues Text Search requests. v2 identifies places by place_id via
Autocomplete and Place Details (see place_details.py).

Day numbering in OpeningPeriod follows Google's convention: Sunday=0 ..
Saturday=6. Missing hours (None) mean unknown — never inferred as closed.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OpeningPeriod:
    """One open→close interval from regularOpeningHours.periods.

    Day numbering: Sunday=0, Monday=1, ..., Saturday=6 (Google convention).
    close_day / close_minutes are None for 24-hour places (no close in the
    API response).  Periods that span midnight have close_day > open_day
    (or close_day=0 when open_day=6 for the Saturday→Sunday wrap).
    """

    open_day: int  # 0=Sunday .. 6=Saturday
    open_minutes: int  # minutes since midnight on open_day
    close_day: int | None  # None → 24 h (no close field in API)
    close_minutes: int | None


@dataclass(frozen=True)
class GeocodedPlace:
    """Result of a single geocode call.

    `primary_type` is None when the Places API omits the field (common for
    generic establishments). `types` falls back to [] if the API omits it.
    Both are handled gracefully by `stay_defaults.lookup_stay_minutes`.

    `opening_hours` is None when the API returns no regularOpeningHours for
    the place (common for homes, offices, transit stops, etc.).  Downstream
    code must treat None as "unknown" and never display it as "closed".
    """

    place_id: str
    name: str
    lat: float
    lng: float
    primary_type: str | None
    types: list[str] = field(default_factory=list)
    opening_hours: list[OpeningPeriod] | None = None
