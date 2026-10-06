"""Backend-controlled city/place suggestions and explicit selection (D13, D26, D34-D36, D38).

Endpoints (all POST, JSON, same combined per-IP allowance):
    /api/v2/suggest/cities   city suggestions ("(cities)" types)
    /api/v2/suggest/places   place suggestions biased to the selected city
    /api/v2/select/city      verify the chosen city: name, coords, timezone, viewport
    /api/v2/select/place     coordinates for the chosen place (map pin, area and
                             timezone preview); concludes the autocomplete session

Suggestions are never auto-selected: the browser must send the chosen ID to a
select endpoint. A successful search with nothing to show returns 200 with
``status: "no_matches"``; that is distinct from invalid input (422), the per-IP
search limit (429 ``rate_limit_exceeded``), the shared provider budget
(429 ``quota_exceeded``), unavailable usage control (503), busy capacity (503)
and provider failure (503 ``provider_unavailable``). No automatic retries.

Limits: D36's 30/minute and 100/day per verified IP (trusted-proxy rules,
shared Redis counters in production) are shared by all four endpoints.
Counting selections in the same bucket is an interim choice because D36 leaves
selection limits unspecified; it introduces no new numeric limit.

Coordinates returned by a select lookup are written to the minimal cache
(place ID + coordinates only, D38). A place selection WITHOUT a session token
(e.g. re-validating an earlier choice) is served from that cache when an
unexpired entry exists; with a session token the lookup is always made, since
it is what concludes the autocomplete session.
"""

from collections.abc import Awaitable, Callable
from typing import Any, NoReturn, TypeVar

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.limiter import (
    SELECTION_SEARCH_LIMITS,
    SELECTION_SEARCH_SCOPE,
    limiter,
    request_cost,
)
from app.core.opmetrics import OperationMetrics, OperationType
from app.models.request import PlaceSuggestionQuery, SelectionRequest, SuggestionQuery
from app.models.response import (
    SelectedCity,
    SelectedPlace,
    SuggestionItem,
    SuggestionsResponse,
    ViewportOut,
)
from app.services import geocache
from app.services.adapter import GooglePlacesAdapter, GoogleSuggestionAdapter
from app.services.area import Viewport
from app.services.autocomplete import InvalidQueryError, Suggestion
from app.services.errors import (
    PlaceVerificationError,
    ProviderCapacityError,
    ProviderTemporaryError,
    QuotaExceededError,
    UsageControlUnavailableError,
)
from app.services.tz import resolve_timezone

router = APIRouter(prefix="/api/v2", tags=["selection"])

_R = TypeVar("_R")


async def _measured(operation: OperationType, run: Callable[[], Awaitable[_R]]) -> _R:
    """One aggregate metrics line per selection request (no query text, IDs or IPs)."""
    metrics = OperationMetrics(operation, "json")
    metrics.activate()
    try:
        result = await run()
    except HTTPException as exc:
        detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
        metrics.finish(
            "rejected" if exc.status_code == 422 else "error", str(detail.get("error", "other"))
        )
        raise
    except Exception:
        metrics.finish("error", "internal_error")
        raise
    metrics.finish(result.status if isinstance(result, SuggestionsResponse) else "ok")
    return result


def suggestion_adapter() -> GoogleSuggestionAdapter:
    return GoogleSuggestionAdapter()


def places_adapter() -> GooglePlacesAdapter:
    return GooglePlacesAdapter()


def _fail(status: int, code: str, message: str, **extra: object) -> NoReturn:
    headers = None
    if status == 503:
        headers = {"Retry-After": "60" if code == "usage_control_unavailable" else "2"}
    if code == "quota_exceeded":
        headers = {"Retry-After": "86400"}
    detail: dict[str, object] = {"error": code, "message": message}
    detail.update({k: v for k, v in extra.items() if v is not None})
    raise HTTPException(status_code=status, detail=detail, headers=headers)


def _provider_failure(exc: Exception) -> NoReturn:
    if isinstance(exc, InvalidQueryError):
        _fail(422, "invalid_query", "That search could not be processed. Try different text.")
    if isinstance(exc, QuotaExceededError):
        _fail(429, "quota_exceeded", "The daily search allowance has been used up.")
    if isinstance(exc, UsageControlUnavailableError):
        _fail(503, "usage_control_unavailable", "Search is unavailable right now.")
    if isinstance(exc, ProviderCapacityError):
        _fail(503, "provider_capacity", "Search is busy. Try again shortly.")
    if isinstance(exc, PlaceVerificationError):
        _fail(
            422,
            "place_invalid",
            "That place could not be confirmed. Choose another suggestion.",
            reason=exc.reason,
            moved_place_id=exc.moved_place_id,
        )
    if isinstance(exc, ProviderTemporaryError):
        _fail(503, "provider_unavailable", "Search is temporarily unavailable.")
    raise exc


def _response(items: list[Suggestion]) -> SuggestionsResponse:
    return SuggestionsResponse(
        status="ok" if items else "no_matches",
        suggestions=[
            SuggestionItem(
                place_id=s.place_id, primary_text=s.primary_text, secondary_text=s.secondary_text
            )
            for s in items
        ],
    )


async def _remember(place_id: str, lat: float, lng: float) -> None:
    try:
        await geocache.put_coordinates(
            place_id, lat, lng, settings.cache_db_path, settings.cache_ttl_days
        )
    except Exception:  # cache is an optimisation; never fail a selection on it
        return


@router.post("/suggest/cities", response_model=SuggestionsResponse)
@limiter.shared_limit(SELECTION_SEARCH_LIMITS, scope=SELECTION_SEARCH_SCOPE, cost=request_cost)
async def suggest_cities(request: Request, body: SuggestionQuery) -> SuggestionsResponse:
    return await _measured("suggest_city", lambda: _suggest_cities(body))


async def _suggest_cities(body: SuggestionQuery) -> SuggestionsResponse:
    try:
        items = await suggestion_adapter().suggest(
            body.query, kind="city", session_token=body.session_token, bias=None
        )
    except Exception as exc:
        _provider_failure(exc)
    return _response(items)


@router.post("/suggest/places", response_model=SuggestionsResponse)
@limiter.shared_limit(SELECTION_SEARCH_LIMITS, scope=SELECTION_SEARCH_SCOPE, cost=request_cost)
async def suggest_places(request: Request, body: PlaceSuggestionQuery) -> SuggestionsResponse:
    return await _measured("suggest_place", lambda: _suggest_places(body))


async def _suggest_places(body: PlaceSuggestionQuery) -> SuggestionsResponse:
    v = body.city_viewport
    bias = Viewport(v.low_lat, v.low_lng, v.high_lat, v.high_lng) if v else None
    try:
        items = await suggestion_adapter().suggest(
            body.query, kind="place", session_token=body.session_token, bias=bias
        )
    except Exception as exc:
        _provider_failure(exc)
    return _response(items)


@router.post("/select/city", response_model=SelectedCity)
@limiter.shared_limit(SELECTION_SEARCH_LIMITS, scope=SELECTION_SEARCH_SCOPE, cost=request_cost)
async def select_city(request: Request, body: SelectionRequest) -> SelectedCity:
    return await _measured("select_city", lambda: _select_city(body))


async def _select_city(body: SelectionRequest) -> SelectedCity:
    try:
        d = await places_adapter().fetch_details(
            body.place_id, role="city", session_token=body.session_token
        )
    except Exception as exc:
        _provider_failure(exc)
    tz = resolve_timezone(d.lat, d.lng)
    if tz is None:
        _fail(
            422,
            "timezone_unresolved",
            f"The timezone for {d.name} could not be determined. Select another city.",
        )
    await _remember(d.place_id, d.lat, d.lng)
    vp = d.viewport
    return SelectedCity(
        place_id=d.place_id,
        name=d.name,
        secondary_text=d.formatted_address,
        lat=d.lat,
        lng=d.lng,
        timezone=tz,
        viewport=ViewportOut(
            low_lat=vp.low_lat, low_lng=vp.low_lng, high_lat=vp.high_lat, high_lng=vp.high_lng
        )
        if vp
        else None,
    )


@router.post("/select/place", response_model=SelectedPlace)
@limiter.shared_limit(SELECTION_SEARCH_LIMITS, scope=SELECTION_SEARCH_SCOPE, cost=request_cost)
async def select_place(request: Request, body: SelectionRequest) -> SelectedPlace:
    return await _measured("select_place", lambda: _select_place(body))


async def _select_place(body: SelectionRequest) -> SelectedPlace:
    if body.session_token is None:
        cached = await geocache.get_coordinates(
            body.place_id, settings.cache_db_path, settings.cache_ttl_days
        )
        if cached is not None:
            return SelectedPlace(
                place_id=cached.place_id,
                lat=cached.lat,
                lng=cached.lng,
                timezone=resolve_timezone(cached.lat, cached.lng),
                source="cache",
            )
    try:
        loc = await places_adapter().fetch_selected_location(
            body.place_id, session_token=body.session_token
        )
    except Exception as exc:
        _provider_failure(exc)
    await _remember(loc.place_id, loc.lat, loc.lng)
    return SelectedPlace(
        place_id=loc.place_id,
        lat=loc.lat,
        lng=loc.lng,
        secondary_text=loc.formatted_address,
        timezone=resolve_timezone(loc.lat, loc.lng),
        source="provider",
    )
