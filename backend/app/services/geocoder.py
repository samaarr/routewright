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
"""

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# Minimum field mask for our use case. Each field here is deliberate:
#   id            — cache key and stable identifier
#   displayName   — human-readable name for the UI
#   location      — lat/lng for Routes API calls
#   primaryType   — primary lookup key for stay_defaults
#   types         — fallback array for stay_defaults when primaryType misses
_FIELD_MASK = "places.id,places.displayName,places.location,places.primaryType,places.types"


@dataclass(frozen=True)
class GeocodedPlace:
    """Result of a single geocode call.

    `primary_type` is None when the Places API omits the field (common for
    generic establishments). `types` falls back to [] if the API omits it.
    Both are handled gracefully by `stay_defaults.lookup_stay_minutes`.
    """

    place_id: str
    name: str
    lat: float
    lng: float
    primary_type: str | None
    types: list[str] = field(default_factory=list)


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
        raise GeocoderError(
            f"Places API returned {response.status_code}: {response.text[:200]}"
        )

    return _parse_response(response.json(), query)


def _build_request_body(query: str, city: str) -> dict[str, Any]:
    """Construct the JSON request body. Pure function for testability."""
    return {
        "textQuery": f"{query}, {city}",
        "maxResultCount": 1,
    }


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

    return GeocodedPlace(
        place_id=place_id,
        name=name,
        lat=lat,
        lng=lng,
        primary_type=primary_type,
        types=types,
    )
