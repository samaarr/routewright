"""Google Place Details (New) client for server-side selection verification (D13, D37, D45).

Verified against the official docs (2026-10-06):
    - GET https://places.googleapis.com/v1/places/{PLACE_ID}
    - Auth via X-Goog-Api-Key; X-Goog-FieldMask is required. Place Details
      masks name fields directly (no ``places.`` prefix used by Text Search).
    - Obsolete IDs return NOT_FOUND (HTTP 404); truncated/modified IDs return
      an invalid-request error (HTTP 400).
    - A place that moved reports businessStatus=CLOSED_PERMANENTLY with
      movedPlaceId. We surface that ID; we never substitute it silently.
    - Always-open hours: one period opening day 0 00:00 with no close.

Billing (Place Details SKUs, per the field table in the docs):
    id, movedPlaceId                   → Essentials (IDs Only)
    location, types                    → Essentials
    displayName, primaryType,
    businessStatus                     → Pro
    regularOpeningHours,
    currentOpeningHours                → Enterprise
A request is billed at the highest tier of any requested field, so every
stop lookup is a **Place Details Enterprise** event because hours are
required for D42/D43. City lookups request no hours and bill as Pro.
NOTE: the legacy Text Search comment in geocoder.py claims requesting
regularOpeningHours keeps v1 geocoding in the Pro tier; current docs list
opening hours as Enterprise there too. That discrepancy is recorded in
IMPLEMENTATION_PROGRESS.md and is not resolved by this module.

Details are request-scoped. Nothing here writes to the persistent cache.
"""

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.services.errors import (
    PlaceRole,
    PlaceVerificationError,
    ProviderTemporaryError,
    QuotaExceededError,
)

PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

# Stop verification needs identity, location, type (stay defaults), relocation
# status and both hours sources. No address, photos, ratings or reviews.
STOP_FIELD_MASK = (
    "id,displayName,location,primaryType,types,businessStatus,movedPlaceId,"
    "regularOpeningHours,currentOpeningHours"
)
# City verification needs identity, name and location (timezone resolution).
# The viewport for D44 outside-area warnings is not requested until that
# warning is implemented.
CITY_FIELD_MASK = "id,displayName,location"

# Google place IDs are URL-safe tokens. Rejecting anything else before the
# call keeps arbitrary input out of the request path and costs no quota.
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")


@dataclass(frozen=True)
class PlaceDetails:
    """Provider-confirmed details for one place, valid for one operation."""

    place_id: str
    name: str
    lat: float
    lng: float
    primary_type: str | None = None
    types: list[str] = field(default_factory=list)
    regular_hours_raw: Any = None
    current_hours_raw: Any = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def field_mask_for(role: PlaceRole) -> str:
    return STOP_FIELD_MASK if role == "stop" else CITY_FIELD_MASK


def validate_place_id(place_id: str, role: PlaceRole) -> None:
    if not _PLACE_ID_RE.fullmatch(place_id):
        raise PlaceVerificationError(place_id, reason="invalid_id", role=role)


async def fetch_place_details(
    place_id: str,
    *,
    role: PlaceRole,
    client: httpx.AsyncClient | None = None,
) -> PlaceDetails:
    """Issue one Place Details request. The caller handles budget/admission.

    Raises:
        PlaceVerificationError: the selection is confirmed invalid.
        ProviderTemporaryError: network/provider failure; the place may be fine.
        QuotaExceededError: provider-side quota (HTTP 429).
    """
    validate_place_id(place_id, role)
    url = PLACE_DETAILS_URL.format(place_id=place_id)
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": field_mask_for(role),
    }
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10.0) as one_shot:
                response = await one_shot.get(url, headers=headers)
        else:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ProviderTemporaryError("Place verification temporarily unavailable") from exc

    if response.status_code == 404:
        raise PlaceVerificationError(place_id, reason="not_found", role=role)
    if response.status_code == 400:
        raise PlaceVerificationError(place_id, reason="invalid_id", role=role)
    if response.status_code == 429:
        raise QuotaExceededError("Places provider quota exceeded")
    if response.status_code != 200:
        # 401/403 (key or restriction problem) and 5xx are not the user's
        # selection being wrong; never report them as an invalid place.
        raise ProviderTemporaryError("Place verification temporarily unavailable")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderTemporaryError("Provider returned an unreadable response") from exc
    return parse_place_details(payload, place_id, role)


def parse_place_details(payload: Any, requested_id: str, role: PlaceRole) -> PlaceDetails:
    """Validate a Place Details payload against the requested identity."""
    if not isinstance(payload, dict):
        raise ProviderTemporaryError("Provider returned an unreadable response")

    moved = payload.get("movedPlaceId")
    if isinstance(moved, str) and moved:
        raise PlaceVerificationError(requested_id, reason="moved", role=role, moved_place_id=moved)
    if payload.get("businessStatus") == "CLOSED_PERMANENTLY":
        raise PlaceVerificationError(requested_id, reason="permanently_closed", role=role)

    # The provider must confirm the identity we asked for. A different ID is
    # not silently adopted; the user reselects.
    if payload.get("id") != requested_id:
        raise PlaceVerificationError(requested_id, reason="identity_changed", role=role)

    name = (payload.get("displayName") or {}).get("text")
    if not isinstance(name, str) or not name.strip():
        raise PlaceVerificationError(requested_id, reason="incomplete_details", role=role)

    location = payload.get("location") or {}
    try:
        lat = float(location["latitude"])
        lng = float(location["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlaceVerificationError(requested_id, reason="no_location", role=role) from exc
    if (
        not math.isfinite(lat)
        or not math.isfinite(lng)
        or not -90 <= lat <= 90
        or not -180 <= lng <= 180
        or (lat == 0.0 and lng == 0.0)
    ):
        raise PlaceVerificationError(requested_id, reason="no_location", role=role)

    primary = payload.get("primaryType")
    types = payload.get("types")
    return PlaceDetails(
        place_id=requested_id,
        name=name.strip(),
        lat=lat,
        lng=lng,
        primary_type=primary if isinstance(primary, str) and primary else None,
        types=[t for t in types if isinstance(t, str)] if isinstance(types, list) else [],
        regular_hours_raw=payload.get("regularOpeningHours"),
        current_hours_raw=payload.get("currentOpeningHours"),
    )
