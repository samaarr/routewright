"""Google Routes API client for single-leg directions.

Calls the modern Routes API (computeRoutes), not the legacy Directions API.
The legacy API still works but Google has marked it for deprecation.

Reference:
    https://developers.google.com/maps/documentation/routes/compute_route_directions
    https://developers.google.com/maps/documentation/routes/transit-route

Key facts that shape this module:
    - Endpoint: POST https://routes.googleapis.com/directions/v2:computeRoutes
    - Auth via X-Goog-Api-Key header (not query param)
    - Field mask REQUIRED via X-Goog-FieldMask header
    - travelMode is uppercase: DRIVE, WALK, BICYCLE, TRANSIT
    - departureTime is RFC3339 string
    - duration in the response is a string like "300s" (seconds + "s" suffix)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from app.core.config import settings

ROUTES_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Mode mapping: our internal mode names → Routes API mode names.
_MODE_MAP: dict[str, str] = {
    "transit": "TRANSIT",
    "walking": "WALK",
    "driving": "DRIVE",
}

# Field mask: only what we use. Keeps SKU costs at the Pro tier minimum and
# response payloads small. Order matters in transit responses (legs.steps
# are returned only if transit-specific fields are requested).
_FIELD_MASK_COMMON = (
    "routes.duration,routes.distanceMeters,routes.legs.startLocation,routes.legs.endLocation"
)
_FIELD_MASK_TRANSIT = (
    _FIELD_MASK_COMMON
    + ",routes.legs.steps.transitDetails.stopDetails.departureTime"
    + ",routes.legs.steps.transitDetails.transitLine.name"
    + ",routes.legs.steps.transitDetails.transitLine.nameShort"
    + ",routes.legs.steps.transitDetails.transitLine.vehicle.type"
    + ",routes.legs.steps.travelMode"
)


@dataclass(frozen=True)
class LegResult:
    """Single-leg directions outcome.

    `summary` is the human-readable line shown in the UI ("Take the 47 bus,
    18 min" or "18 min walk"). `transit_line` is non-None only for transit
    legs that returned schedule details.
    """

    duration_seconds: int
    distance_meters: int
    depart_at: datetime
    arrive_at: datetime
    summary: str
    transit_line: str | None = None


class DirectionsError(Exception):
    """Raised when the Routes API call fails or returns no usable route."""


async def fetch_leg(
    origin_lat: float,
    origin_lng: float,
    destination_lat: float,
    destination_lng: float,
    depart_at: datetime,
    mode: Literal["transit", "walking", "driving"],
    client: httpx.AsyncClient | None = None,
) -> LegResult:
    """Fetch a single leg from the Routes API.

    The caller passes an httpx.AsyncClient when batching multiple legs
    concurrently; if None, a one-shot client is created.

    Raises DirectionsError if the API returns no route or an HTTP error.
    """
    if mode not in _MODE_MAP:
        raise DirectionsError(f"unsupported mode: {mode}")

    body = _build_request_body(
        origin_lat, origin_lng, destination_lat, destination_lng, depart_at, mode
    )
    field_mask = _FIELD_MASK_TRANSIT if mode == "transit" else _FIELD_MASK_COMMON
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": field_mask,
    }

    if client is None:
        async with httpx.AsyncClient(timeout=10.0) as one_shot:
            response = await one_shot.post(ROUTES_ENDPOINT, json=body, headers=headers)
    else:
        response = await client.post(ROUTES_ENDPOINT, json=body, headers=headers)

    if response.status_code != 200:
        raise DirectionsError(f"Routes API returned {response.status_code}: {response.text[:200]}")

    return _parse_response(response.json(), depart_at, mode)


def _build_request_body(
    origin_lat: float,
    origin_lng: float,
    destination_lat: float,
    destination_lng: float,
    depart_at: datetime,
    mode: str,
) -> dict[str, Any]:
    """Construct the JSON body. Kept pure for testability."""
    # Routes API requires UTC and RFC3339 with 'Z'. Convert defensively.
    if depart_at.tzinfo is None:
        depart_at = depart_at.replace(tzinfo=timezone.utc)
    depart_iso = depart_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    body: dict[str, Any] = {
        "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
        "destination": {
            "location": {"latLng": {"latitude": destination_lat, "longitude": destination_lng}}
        },
        "travelMode": _MODE_MAP[mode],
        "departureTime": depart_iso,
    }

    # `routingPreference: TRAFFIC_AWARE` is valid only for DRIVE / TWO_WHEELER.
    # The API rejects it with an error for TRANSIT and WALK.
    if mode == "driving":
        body["routingPreference"] = "TRAFFIC_AWARE"

    return body


def _parse_response(response_json: dict[str, Any], depart_at: datetime, mode: str) -> LegResult:
    """Parse a Routes API JSON response into a LegResult.

    The response shape is documented at
    https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes
    """
    routes = response_json.get("routes") or []
    if not routes:
        raise DirectionsError("Routes API returned no routes")

    route = routes[0]
    duration_str = route.get("duration", "0s")
    # Format is "<seconds>s" — e.g. "180s". Defensive parse.
    duration_seconds = _parse_duration(duration_str)
    distance_meters = int(route.get("distanceMeters", 0))
    arrive_at = depart_at + timedelta(seconds=duration_seconds)

    transit_line = None
    summary = _format_duration(duration_seconds)

    if mode == "transit":
        transit_line = _extract_transit_line_name(route)
        if transit_line:  # noqa: SIM108  (if/else clearer than ternary here)
            summary = f"Take the {transit_line}, {summary}"
        else:
            summary = f"{summary} (transit)"
    elif mode == "walking":
        summary = f"{summary} walk"
    else:
        summary = f"{summary} drive"

    return LegResult(
        duration_seconds=duration_seconds,
        distance_meters=distance_meters,
        depart_at=depart_at,
        arrive_at=arrive_at,
        summary=summary,
        transit_line=transit_line,
    )


def _parse_duration(duration_str: str) -> int:
    """Parse Google's duration format ('300s') to integer seconds."""
    if not duration_str:
        return 0
    s = duration_str.strip()
    if s.endswith("s"):
        s = s[:-1]
    try:
        # Float because Google sometimes returns e.g. "300.5s"
        return int(float(s))
    except ValueError:
        return 0


def _format_duration(seconds: int) -> str:
    """Format seconds as 'X min' or 'X hr Y min'."""
    minutes = max(1, seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"{hours} hr"
    return f"{hours} hr {mins} min"


def _extract_transit_line_name(route: dict[str, Any]) -> str | None:
    """Find the first transit step's line name in a route response.

    A transit leg may also contain WALK steps (to/from the stop). We pick
    the first TRANSIT step's line. Returns None if no transit step found.
    """
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            if step.get("travelMode") != "TRANSIT":
                continue
            details = step.get("transitDetails") or {}
            line = details.get("transitLine") or {}
            # Prefer the short name (e.g. "47") over the long name.
            short = line.get("nameShort")
            full = line.get("name")
            return short or full
    return None
