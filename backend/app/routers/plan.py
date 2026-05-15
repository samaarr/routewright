"""POST /api/plan — the single v1 endpoint.

Takes a city, ordered stops, start time, and mode. Returns a flat timeline.
Reordering on the frontend just re-POSTs the new order; this endpoint is
stateless.

Days 3-8 will replace the fixture body with the real geocoder → chain →
Routes API pipeline.
"""

from datetime import timedelta
from urllib.parse import quote_plus

from fastapi import APIRouter

from app.models.request import PlanRequest
from app.models.response import LegItem, Plan, StopItem

router = APIRouter(prefix="/api", tags=["plan"])


@router.post("/plan", response_model=Plan)
async def plan(req: PlanRequest) -> Plan:
    """Generate a timeline from the user's ordered stops.

    **Stubbed** until day 7. Returns a deterministic fixture that mirrors
    the real shape so the frontend can wire against it from day 1.
    """
    return _fixture_plan(req)


def _fixture_plan(req: PlanRequest) -> Plan:
    """Deterministic fixture timeline. Echoes the user-supplied order with
    naive 15-minute legs and the user-supplied (or 60-min default) stay
    durations.
    """
    timeline: list[StopItem | LegItem] = []
    cursor = req.start_time

    for i, stop in enumerate(req.stops):
        stay = stop.stay_minutes if stop.stay_minutes is not None else 60
        stay_source = "user" if stop.stay_minutes is not None else "default"

        arrive_at = cursor
        depart_at = cursor + timedelta(minutes=stay)

        timeline.append(
            StopItem(
                query=stop.query,
                name=stop.query,  # real geocoder fills this in later
                lat=0.0,
                lng=0.0,
                arrive_at=arrive_at,
                depart_at=depart_at,
                stay_minutes=stay,
                stay_source=stay_source,
                map_url=_search_url(stop.query, req.city),
            )
        )

        # Append a leg if this isn't the last stop.
        if i < len(req.stops) - 1:
            leg_depart = depart_at
            leg_arrive = depart_at + timedelta(minutes=15)
            next_query = req.stops[i + 1].query
            timeline.append(
                LegItem(
                    from_name=stop.query,
                    to_name=next_query,
                    mode=req.mode,
                    duration_seconds=15 * 60,
                    depart_at=leg_depart,
                    arrive_at=leg_arrive,
                    summary=f"Fixture: 15 min via {req.mode}",
                    map_url=_dir_url(stop.query, next_query, req.city, req.mode),
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
