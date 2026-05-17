"""POST /api/plan — the single v1 endpoint.

Takes a city, ordered stops, start time, and mode. Returns a flat timeline.
Reordering on the frontend just re-POSTs the new order; this endpoint is
stateless.

Day 7-8: stub legs replaced with real parallel Routes API calls via
asyncio.gather. See CLAUDE.md "Known v1 limitations" for the pre-chain
approximation used to enable parallel fetching.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.limiter import limiter
from app.models.request import PlanRequest
from app.models.response import LegItem, Plan, StopItem
from app.models.response import Warning as PlanWarning
from app.services.directions import DirectionsError, fetch_leg
from app.services.geocache import geocode_cached
from app.services.geocoder import GeocodedPlace, GeocoderError
from app.services.stay_defaults import lookup_stay_minutes

router = APIRouter(prefix="/api", tags=["plan"])

_FALLBACK_LEG_SECONDS = 15 * 60

# Words that appear in both neighbourhood names and venue names; triggers a
# disambiguation warning when the geocoder returns a food/drink place type.
_AMBIGUOUS_NEIGHBOURHOOD_TOKENS = {"bar", "quarter", "village", "yard"}
_FOOD_PLACE_TYPES = {"bar", "pub", "restaurant", "cafe", "bakery", "meal_takeaway", "night_club", "food"}


@router.post("/plan", response_model=Plan)
@limiter.limit("20/day")
async def plan(request: Request, req: PlanRequest) -> Plan:
    """Generate a timeline from the user's ordered stops.

    Phase 1: geocode every stop (cache-first via SQLite).
    Phase 2: resolve stay_minutes for all stops from type table or user override.
    Phase 3: pre-chain — compute leg departure times using stay durations only
             (zero leg travel time assumed) to enable parallel fetching.
    Phase 4: asyncio.gather all Routes API leg fetches in parallel.
    Phase 5: assemble final timeline with real leg durations; degrade
             gracefully on any leg failure.
    """
    # Phase 1: geocode all stops sequentially (cache-first).
    places: list[GeocodedPlace] = []
    for stop in req.stops:
        try:
            place = await geocode_cached(
                stop.query,
                req.city,
                settings.cache_db_path,
                settings.cache_ttl_days,
            )
        except GeocoderError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Could not geocode stop: {stop.query!r}",
            ) from exc
        places.append(place)

    # Post-geocode warnings — checked before any routing.
    warnings: list[PlanWarning] = []
    for i in range(len(places) - 1):
        if places[i].place_id == places[i + 1].place_id:
            warnings.append(
                PlanWarning(
                    severity="warning",
                    message=(
                        f"Stop {i + 1} and stop {i + 2} both resolve to the same "
                        f"location ({places[i].name}). The leg between them will "
                        "have near-zero duration."
                    ),
                    affects_stop_index=i,
                )
            )
    for stop, place in zip(req.stops, places):
        tokens = {t.lower().strip("',.-") for t in stop.query.split()}
        if (
            tokens & _AMBIGUOUS_NEIGHBOURHOOD_TOKENS
            and place.primary_type in _FOOD_PLACE_TYPES
        ):
            warnings.append(
                PlanWarning(
                    severity="info",
                    message=(
                        f"'{stop.query}' resolved to a {place.primary_type} "
                        f"({place.name}). If you meant the neighbourhood, try "
                        "adding a street or landmark for clarity."
                    ),
                    affects_stop_index=None,
                )
            )

    # Phase 2: resolve stay_minutes for every stop.
    # First and last stops are anchors — default stay is 0 so the chain starts
    # and ends cleanly. Middle stops use the type-lookup table. A user-supplied
    # stay_minutes always wins regardless of position.
    stays: list[int] = []
    stay_sources: list[Literal["user", "default"]] = []
    n_stops = len(req.stops)
    for i, (stop, place) in enumerate(zip(req.stops, places)):
        if stop.stay_minutes is not None:
            stays.append(stop.stay_minutes)
            stay_sources.append("user")
        elif i == 0 or i == n_stops - 1:
            stays.append(0)
            stay_sources.append("default")
        else:
            minutes, _ = lookup_stay_minutes(place.primary_type, place.types)
            stays.append(minutes)
            stay_sources.append("default")

    # Phase 3: pre-chain — compute each leg's departure time from stays alone,
    # treating leg travel time as 0. This lets us fan out all leg fetches
    # simultaneously in Phase 4. See CLAUDE.md for accuracy trade-off.
    n_legs = len(req.stops) - 1
    leg_depart_times: list[datetime] = []
    pre_cursor = req.start_time
    for stay in stays[:n_legs]:
        pre_cursor = pre_cursor + timedelta(minutes=stay)
        leg_depart_times.append(pre_cursor)

    # Phase 4: fetch all legs in parallel; collect exceptions instead of raising.
    leg_tasks = [
        fetch_leg(
            origin_lat=places[i].lat,
            origin_lng=places[i].lng,
            destination_lat=places[i + 1].lat,
            destination_lng=places[i + 1].lng,
            depart_at=leg_depart_times[i],
            mode=req.mode,
        )
        for i in range(n_legs)
    ]
    raw_results: list[Any] = list(await asyncio.gather(*leg_tasks, return_exceptions=True))

    # Phase 5: walk forward with real leg durations; degrade any failed leg.
    timeline: list[StopItem | LegItem] = []
    cursor = req.start_time

    for i, (stop, place) in enumerate(zip(req.stops, places)):
        arrive_at = cursor
        depart_at = cursor + timedelta(minutes=stays[i])

        timeline.append(
            StopItem(
                query=stop.query,
                name=place.name,
                lat=place.lat,
                lng=place.lng,
                arrive_at=arrive_at,
                depart_at=depart_at,
                stay_minutes=stays[i],
                stay_source=stay_sources[i],
                map_url=_search_url(stop.query, req.city),
            )
        )

        if i < n_legs:
            result = raw_results[i]
            leg_depart = depart_at

            if isinstance(result, Exception):
                warnings.append(
                    PlanWarning(
                        severity="warning",
                        message=(
                            f"Could not fetch route: {place.name} → {places[i + 1].name}. "
                            "Showing estimated time."
                        ),
                        affects_stop_index=i,
                    )
                )
                duration_sec = _FALLBACK_LEG_SECONDS
                summary = "Route unavailable — check Google Maps"
                distance: int | None = None
            else:
                duration_sec = result.duration_seconds
                summary = result.summary
                distance = result.distance_meters

            leg_arrive = leg_depart + timedelta(seconds=duration_sec)
            timeline.append(
                LegItem(
                    from_name=place.name,
                    to_name=places[i + 1].name,
                    mode=req.mode,
                    duration_seconds=duration_sec,
                    distance_meters=distance,
                    depart_at=leg_depart,
                    arrive_at=leg_arrive,
                    summary=summary,
                    map_url=_dir_url(stop.query, req.stops[i + 1].query, req.city, req.mode),
                )
            )
            cursor = leg_arrive

    return Plan(
        generated_at=req.start_time,
        city=req.city,
        mode=req.mode,
        timeline=timeline,
        overview_map_url=_overview_url([s.query for s in req.stops], req.city),
        warnings=warnings,
    )


def _search_url(query: str, city: str) -> str:
    q = quote_plus(f"{query}, {city}")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def _dir_url(origin: str, destination: str, city: str, mode: str) -> str:
    o = quote_plus(f"{origin}, {city}")
    d = quote_plus(f"{destination}, {city}")
    return f"https://www.google.com/maps/dir/?api=1&origin={o}&destination={d}&travelmode={mode}"


def _overview_url(queries: list[str], city: str) -> str:
    """Driving-mode multi-waypoint URL for spatial overview.

    Note: even in transit/walking mode for legs, the overview is driving.
    Google Maps' public URL spec only supports waypoints in driving mode.
    """
    if len(queries) < 2:
        return _search_url(queries[0] if queries else city, city)
    origin = quote_plus(f"{queries[0]}, {city}")
    destination = quote_plus(f"{queries[-1]}, {city}")
    middle = queries[1:-1]
    url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={origin}&destination={destination}&travelmode=driving"
    )
    if middle:
        waypoints = "|".join(quote_plus(f"{q}, {city}") for q in middle)
        url += f"&waypoints={waypoints}"
    return url
