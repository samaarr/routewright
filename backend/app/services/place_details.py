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
    location, types, viewport,
    formattedAddress                   → Essentials
    displayName, primaryType,
    businessStatus                     → Pro
    regularOpeningHours,
    currentOpeningHours                → Enterprise
A request is billed at the highest tier of any requested field. Masks per
purpose (see DetailsPurpose):
    stop_verification → Enterprise (hours are required for D42/D43)
    city              → Pro (displayName); viewport adds no tier
    stop_selection    → Essentials (id, location, formattedAddress)

Autocomplete sessions: a Place Details call that carries the session token of
the Autocomplete requests concludes the session (``sessionToken`` query
parameter). It is still billed by its own field-mask SKU. See autocomplete.py
for what a session does and does not save.

Rich details are request-scoped. Only place ID + coordinates may be persisted,
via geocache.put_coordinates (D38).
"""

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.provider_accounting import ProviderCallKind
from app.services.area import Viewport, parse_viewport
from app.services.errors import (
    PlaceRole,
    PlaceVerificationError,
    ProviderTemporaryError,
    QuotaExceededError,
)

PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

DetailsPurpose = Literal["stop_verification", "city", "stop_selection"]

# Stop verification needs identity, location, type (stay defaults), relocation
# status and both hours sources. No address, photos, ratings or reviews.
STOP_FIELD_MASK = (
    "id,displayName,location,primaryType,types,businessStatus,movedPlaceId,"
    "regularOpeningHours,currentOpeningHours"
)
# City selection and verification: identity, name, address context, location
# (offline timezone) and viewport (D44 outside-area warnings). Shared by both
# so a selected city is verified with the same fields it was chosen with.
CITY_FIELD_MASK = "id,displayName,formattedAddress,location,viewport"
# Stop selection only needs coordinates (area warning, timezone preview, map
# pin) and address context. The name shown is the suggestion's own text; the
# provider name is confirmed at plan time by stop verification.
STOP_SELECTION_FIELD_MASK = "id,location,formattedAddress"

_MASKS: dict[DetailsPurpose, str] = {
    "stop_verification": STOP_FIELD_MASK,
    "city": CITY_FIELD_MASK,
    "stop_selection": STOP_SELECTION_FIELD_MASK,
}
_KINDS: dict[DetailsPurpose, ProviderCallKind] = {
    "stop_verification": "place_details_enterprise",
    "city": "place_details_pro",
    "stop_selection": "place_details_essentials",
}

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
    formatted_address: str | None = None
    viewport: Viewport | None = None


@dataclass(frozen=True)
class SelectedLocation:
    """Result of a stop-selection lookup (Essentials fields only)."""

    place_id: str
    lat: float
    lng: float
    formatted_address: str | None
    fetched_at: datetime


def field_mask_for(purpose: DetailsPurpose) -> str:
    return _MASKS[purpose]


def call_kind_for(purpose: DetailsPurpose) -> ProviderCallKind:
    return _KINDS[purpose]


def role_for(purpose: DetailsPurpose) -> PlaceRole:
    return "city" if purpose == "city" else "stop"


_SESSION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def valid_session_token(token: str) -> bool:
    return bool(_SESSION_TOKEN_RE.fullmatch(token))


def validate_place_id(place_id: str, role: PlaceRole) -> None:
    if not _PLACE_ID_RE.fullmatch(place_id):
        raise PlaceVerificationError(place_id, reason="invalid_id", role=role)


async def _get_details_json(
    place_id: str,
    *,
    purpose: DetailsPurpose,
    session_token: str | None,
    client: httpx.AsyncClient | None,
) -> Any:
    role = role_for(purpose)
    validate_place_id(place_id, role)
    url = PLACE_DETAILS_URL.format(place_id=place_id)
    headers = {
        "X-Goog-Api-Key": settings.google_maps_api_key,
        "X-Goog-FieldMask": field_mask_for(purpose),
    }
    params = {"sessionToken": session_token} if session_token else None
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=10.0) as one_shot:
                response = await one_shot.get(url, headers=headers, params=params)
        else:
            response = await client.get(url, headers=headers, params=params)
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
        return response.json()
    except ValueError as exc:
        raise ProviderTemporaryError("Provider returned an unreadable response") from exc


async def fetch_place_details(
    place_id: str,
    *,
    purpose: DetailsPurpose,
    session_token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> PlaceDetails:
    """Issue one verification Place Details request (stop_verification or city).

    The caller handles budget/admission.

    Raises:
        PlaceVerificationError: the selection is confirmed invalid.
        ProviderTemporaryError: network/provider failure; the place may be fine.
        QuotaExceededError: provider-side quota (HTTP 429).
    """
    payload = await _get_details_json(
        place_id, purpose=purpose, session_token=session_token, client=client
    )
    return parse_place_details(payload, place_id, role_for(purpose))


async def fetch_selected_location(
    place_id: str,
    *,
    session_token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> SelectedLocation:
    """Essentials lookup for a stop the user just selected (concludes a session)."""
    payload = await _get_details_json(
        place_id, purpose="stop_selection", session_token=session_token, client=client
    )
    if not isinstance(payload, dict):
        raise ProviderTemporaryError("Provider returned an unreadable response")
    if payload.get("id") != place_id:
        raise PlaceVerificationError(place_id, reason="identity_changed", role="stop")
    lat, lng = _location(payload, place_id, "stop")
    address = payload.get("formattedAddress")
    return SelectedLocation(
        place_id=place_id,
        lat=lat,
        lng=lng,
        formatted_address=address if isinstance(address, str) and address else None,
        fetched_at=datetime.now(timezone.utc),
    )


def _location(payload: dict[str, Any], requested_id: str, role: PlaceRole) -> tuple[float, float]:
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
    return lat, lng


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

    lat, lng = _location(payload, requested_id, role)
    address = payload.get("formattedAddress")

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
        formatted_address=address if isinstance(address, str) and address else None,
        viewport=parse_viewport(payload.get("viewport")),
    )
