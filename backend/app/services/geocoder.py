"""Google Places API (New) client for geocoding stop queries.

Calls Text Search (New), not the legacy Places API. Key facts:
    - Endpoint: POST https://places.googleapis.com/v1/places:searchText
    - Auth via X-Goog-Api-Key header (not query param)
    - Field mask REQUIRED via X-Goog-FieldMask header — omitting returns an error
    - maxResultCount: 1 keeps response small and billing minimal
    - primaryType may be absent for generic places — always handle None
    - types array is ordered most-specific-first per Google's schema

Billing tier: Pro (~5K free requests/month as of March 2025). The Pro tier
is unavoidable because we request primaryType; dropping it would save cost
but break stay_defaults lookup accuracy.

Opening hours:
    regularOpeningHours.periods is requested and parsed into OpeningPeriod
    objects stored on GeocodedPlace.  Day numbering follows Google's convention:
    Sunday=0, Monday=1, ..., Saturday=6.  A period with close_day=None means
    the place is open 24 hours.  Missing hours (None) means unknown — never
    inferred as closed.

Timezone assumption:
    Opening hours from the Places API use the venue's LOCAL time.
    RouteWright plans a single day in a single city, so all venues share the
    trip-city timezone.  The caller is responsible for supplying datetimes in
    the city's local timezone when computing hours status (see hours.py).
    Per-venue timezone lookup is NOT performed.
"""

import dataclasses
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# Minimum field mask for our use case. Each field here is deliberate:
#   id                    — cache key and stable identifier
#   displayName           — human-readable name for the UI
#   location              — lat/lng for Routes API calls
#   primaryType           — primary lookup key for stay_defaults
#   types                 — fallback array for stay_defaults when primaryType misses
#   regularOpeningHours   — weekly open/close periods for hours-status display
#                           Adds regularOpeningHours to the Pro-tier billing SKU
#                           (already required for primaryType) — no tier change.
_FIELD_MASK = (
    "places.id,places.displayName,places.location,"
    "places.primaryType,places.types,places.regularOpeningHours"
)


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


class GeocoderError(Exception):
    """Raised when the Places API call fails or returns no usable result."""


async def geocode(
    query: str,
    city: str,
    client: httpx.AsyncClient | None = None,
) -> GeocodedPlace:
    """Resolve a stop query to a geocoded place via the Places API (New).

    Appends `city` to the query string (e.g. "Trinity College, Dublin, Ireland")
    to constrain the search geographically without requiring a separate
    city-geocode call.

    Raises GeocoderError if the API returns a non-200 status or zero results.
    """
    body = _build_request_body(query, city)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    if client is None:
        async with httpx.AsyncClient(timeout=10.0) as one_shot:
            response = await one_shot.post(PLACES_ENDPOINT, json=body, headers=headers)
    else:
        response = await client.post(PLACES_ENDPOINT, json=body, headers=headers)

    if response.status_code != 200:
        raise GeocoderError(f"Places API returned {response.status_code}: {response.text[:200]}")

    return _parse_response(response.json(), query)


def _build_request_body(query: str, city: str) -> dict[str, Any]:
    """Construct the JSON request body. Pure function for testability."""
    return {
        "textQuery": f"{query}, {city}",
        "maxResultCount": 1,
    }


def _parse_opening_hours(raw: Any) -> list[OpeningPeriod] | None:
    """Parse regularOpeningHours from a Places API place object.

    Returns None on missing or malformed data — never raises, never crashes.
    Returns None (not []) when no parseable periods are found, so callers can
    distinguish "unknown" from an empty list.

    Google's day convention: Sunday=0, Monday=1, ..., Saturday=6.
    24-hour places: single period with open={day:0, hour:0, minute:0} and
    no close field — parsed as close_day=None, close_minutes=None.
    """
    try:
        periods_raw = (raw or {}).get("periods") or []
        if not periods_raw:
            return None

        result: list[OpeningPeriod] = []
        for period in periods_raw:
            open_pt = period.get("open") or {}
            close_pt = period.get("close")  # absent for 24-hour places

            open_day = int(open_pt.get("day", 0))
            open_minutes = int(open_pt.get("hour", 0)) * 60 + int(open_pt.get("minute", 0))

            if close_pt is None:
                result.append(
                    OpeningPeriod(
                        open_day=open_day,
                        open_minutes=open_minutes,
                        close_day=None,
                        close_minutes=None,
                    )
                )
            else:
                close_day = int(close_pt.get("day", open_day))
                close_minutes = int(close_pt.get("hour", 0)) * 60 + int(close_pt.get("minute", 0))
                result.append(
                    OpeningPeriod(
                        open_day=open_day,
                        open_minutes=open_minutes,
                        close_day=close_day,
                        close_minutes=close_minutes,
                    )
                )

        return result if result else None
    except Exception:
        return None


def opening_hours_to_json_list(periods: list[OpeningPeriod]) -> list[dict[str, Any]]:
    """Serialise a list of OpeningPeriod to a JSON-safe list of dicts."""
    return [dataclasses.asdict(p) for p in periods]


def opening_hours_from_json_list(data: list[dict[str, Any]]) -> list[OpeningPeriod]:
    """Deserialise a list of dicts back into OpeningPeriod objects."""
    return [OpeningPeriod(**d) for d in data]


def _parse_response(response_json: dict[str, Any], original_query: str) -> GeocodedPlace:
    """Parse a Places API Text Search response into a GeocodedPlace.

    Raises GeocoderError if the places array is empty (no match found).
    """
    places = response_json.get("places") or []
    if not places:
        raise GeocoderError(f"place not found: {original_query!r}")

    place = places[0]

    place_id: str = place.get("id", "")
    name: str = (place.get("displayName") or {}).get("text", original_query)
    location: dict[str, Any] = place.get("location") or {}
    lat: float = float(location.get("latitude", 0.0))
    lng: float = float(location.get("longitude", 0.0))
    primary_type: str | None = place.get("primaryType") or None
    types: list[str] = place.get("types") or []
    opening_hours = _parse_opening_hours(place.get("regularOpeningHours"))

    return GeocodedPlace(
        place_id=place_id,
        name=name,
        lat=lat,
        lng=lng,
        primary_type=primary_type,
        types=types,
        opening_hours=opening_hours,
    )
