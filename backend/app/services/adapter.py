"""Production adapter implementations for the planning engine.

GoogleRoutesAdapter wraps directions.fetch_leg() and GooglePlacesAdapter wraps
place_details.fetch_place_details() under the engine's Protocols so planning
can be tested with deterministic fakes.

Both go through the same bounded provider admission (semaphore) and the
shared fail-closed daily provider budget. The budget is consumed before each
request is sent and is not refunded if the call fails or is cancelled.
Admission/budget rejections are translated into typed engine errors so a
mid-plan rejection becomes a FailedLeg rather than an unstructured HTTP error.
"""

from datetime import datetime
from urllib.parse import quote_plus

from fastapi import HTTPException

from app.core.provider_semaphore import (
    USAGE_CONTROL_UNAVAILABLE_DETAIL,
    consume_provider_budget,
    get_provider_semaphore,
)
from app.models.request import TransportMode
from app.services import directions
from app.services.area import Viewport
from app.services.autocomplete import Suggestion, SuggestionKind, fetch_suggestions
from app.services.engine import RoutingResult
from app.services.errors import (
    NoRouteError,
    PlaceRole,
    ProviderCapacityError,
    ProviderTemporaryError,
    QuotaExceededError,
    UsageControlUnavailableError,
)
from app.services.place_details import (
    DetailsPurpose,
    PlaceDetails,
    SelectedLocation,
    call_kind_for,
    fetch_place_details,
    fetch_selected_location,
    validate_place_id,
)


def _admission_error(exc: HTTPException) -> Exception:
    """Map provider_semaphore's HTTP rejections onto engine error types."""
    if exc.status_code == 429:
        return QuotaExceededError("Daily provider budget exhausted")
    if exc.detail == USAGE_CONTROL_UNAVAILABLE_DETAIL:
        return UsageControlUnavailableError("Usage control unavailable")
    return ProviderCapacityError("Provider capacity busy")


def _dir_url_coords(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    mode: str,
) -> str:
    """Google Maps directions URL using coordinate pairs."""
    o = quote_plus(f"{origin_lat},{origin_lng}")
    d = quote_plus(f"{dest_lat},{dest_lng}")
    return f"https://www.google.com/maps/dir/?api=1&origin={o}&destination={d}&travelmode={mode}"


class GoogleRoutesAdapter:
    """Wraps directions.fetch_leg() as a RoutesAdapter for the planning engine.

    Raises NoRouteError when the Routes API returns no usable route.
    Raises ProviderTemporaryError on transient network / API errors.
    """

    async def fetch_leg(
        self,
        *,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: TransportMode,
        depart_at: datetime,
    ) -> RoutingResult:
        try:
            async with get_provider_semaphore():
                result = await directions.fetch_leg(
                    origin_lat=origin_lat,
                    origin_lng=origin_lng,
                    destination_lat=dest_lat,
                    destination_lng=dest_lng,
                    depart_at=depart_at,
                    mode=mode,
                )
        except HTTPException as exc:
            raise _admission_error(exc) from exc
        except directions.DirectionsError as exc:
            msg = str(exc).lower()
            if "no route" in msg:
                raise NoRouteError("", "") from exc
            raise ProviderTemporaryError(str(exc)) from exc

        return RoutingResult(
            duration_seconds=result.duration_seconds,
            distance_meters=result.distance_meters,
            arrive_at=result.arrive_at,
            summary=result.summary,
            map_url=_dir_url_coords(origin_lat, origin_lng, dest_lat, dest_lng, mode),
        )


class GooglePlacesAdapter:
    """Wraps Place Details (New) as a PlacesAdapter for the verifier.

    No automatic retries (D8). One call per invocation; the verifier is
    responsible for sharing lookups across duplicate place IDs (D37).
    """

    async def fetch_details(
        self, place_id: str, *, role: PlaceRole, session_token: str | None = None
    ) -> PlaceDetails:
        purpose: DetailsPurpose = "city" if role == "city" else "stop_verification"
        # Reject malformed IDs before admission so they cost no budget.
        validate_place_id(place_id, role)
        try:
            async with get_provider_semaphore():
                await consume_provider_budget(call_kind_for(purpose))
                return await fetch_place_details(
                    place_id, purpose=purpose, session_token=session_token
                )
        except HTTPException as exc:
            raise _admission_error(exc) from exc

    async def fetch_selected_location(
        self, place_id: str, *, session_token: str | None
    ) -> SelectedLocation:
        validate_place_id(place_id, "stop")
        try:
            async with get_provider_semaphore():
                await consume_provider_budget(call_kind_for("stop_selection"))
                return await fetch_selected_location(place_id, session_token=session_token)
        except HTTPException as exc:
            raise _admission_error(exc) from exc


class GoogleSuggestionAdapter:
    """Wraps Autocomplete (New) under shared admission + budget. No retries."""

    async def suggest(
        self,
        query: str,
        *,
        kind: SuggestionKind,
        session_token: str | None,
        bias: Viewport | None,
    ) -> list[Suggestion]:
        try:
            async with get_provider_semaphore():
                await consume_provider_budget("autocomplete")
                return await fetch_suggestions(
                    query, kind=kind, session_token=session_token, bias=bias
                )
        except HTTPException as exc:
            raise _admission_error(exc) from exc
