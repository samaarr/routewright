"""POST /api/plan — the single v1 endpoint.

Takes a city, ordered stops, start time, and mode. Returns a flat timeline.
Reordering on the frontend just re-POSTs the new order; this endpoint is
stateless.

Days 5-6: geocode_cached + stay_defaults wired in. Legs are still 15-min
stubs — Routes API replaces them in Days 7-8.
"""

from datetime import timedelta
from typing import Literal
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.request import PlanRequest
from app.models.response import LegItem, Plan, StopItem
from app.services.geocache import geocode_cached
from app.services.geocoder import GeocodedPlace, GeocoderError
from app.services.stay_defaults import lookup_stay_minutes

router = APIRouter(prefix="/api", tags=["plan"])


@router.post("/plan", response_model=Plan)
async def plan(req: PlanRequest) -> Plan:
    """Generate a timeline from the user's ordered stops.

    Phase 1: geocode every stop (cache-first via SQLite).
    Phase 2: build timeline — real names/coords from geocoder, stay
             durations from type table or user override, legs still stubbed.
    """
    # Phase 1: geocode all stops sequentially before building the timeline
    # so that leg to_name can use the resolved name of the next stop.
    # Parallelising with asyncio.gather is a straightforward Day 7-8 upgrade
    # once we have real latency data; the cache absorbs repeated lookups.
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

    # Phase 2: build alternating Stop / Leg timeline.
    timeline: list[StopItem | LegItem] = []
    cursor = req.start_time

    for i, (stop, place) in enumerate(zip(req.stops, places)):
        stay_source: Literal["user", "default"]
        if stop.stay_minutes is not None:
            stay = stop.stay_minutes
            stay_source = "user"
        else:
            stay, _ = lookup_stay_minutes(place.primary_type, place.types)
            stay_source = "default"

        arrive_at = cursor
        depart_at = cursor + timedelta(minutes=stay)

        timeline.append(
            StopItem(
                query=stop.query,
                name=place.name,
                lat=place.lat,
                lng=place.lng,
                arrive_at=arrive_at,
                depart_at=depart_at,
                stay_minutes=stay,
                stay_source=stay_source,
                map_url=_search_url(stop.query, req.city),
            )
        )

        if i < len(req.stops) - 1:
            leg_depart = depart_at
            leg_arrive = depart_at + timedelta(minutes=15)
            timeline.append(
                LegItem(
                    from_name=place.name,
                    to_name=places[i + 1].name,
                    mode=req.mode,
                    duration_seconds=15 * 60,
                    depart_at=leg_depart,
                    arrive_at=leg_arrive,
                    summary=f"Fixture: 15 min via {req.mode}",
                    map_url=_dir_url(stop.query, req.stops[i + 1].query, req.city, req.mode),
                )
            )
            cursor = leg_arrive
        else:
            cursor = depart_at

    return Plan(
        generated_at=req.start_time,
        city=req.city,
        mode=req.mode,
        timeline=timeline,
        overview_map_url=_overview_url([s.query for s in req.stops], req.city),
    )


def _search_url(query: str, city: str) -> str:
    """Build a Maps search URL for a single place."""
    q = quote_plus(f"{query}, {city}")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def _dir_url(origin: str, destination: str, city: str, mode: str) -> str:
    """Build a Maps directions URL for a single leg."""
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
