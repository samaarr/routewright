"""POST /api/optimise — distance-optimal stop reordering with hours awareness.

Stage 2: haversine cost + opening-hours soft constraints via OR-Tools time
dimension.  Geocodes stops cache-first, runs OR-Tools TSP, returns the
reordered stop list, path-length stats, and any infeasibility flags.
The caller re-POSTs the result to /api/plan for pricing.
"""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.limiter import limiter
from app.models.request import PlanRequest
from app.models.response import OptimisedStop, OptimiseResponse
from app.services.geocache import geocode_cached
from app.services.geocoder import GeocoderError
from app.services.optimise import build_haversine_matrix, optimise_order_with_hours
from app.services.stay_defaults import DEFAULT_STAY_MINUTES
from app.services.tz import destination_timezone

router = APIRouter(prefix="/api", tags=["optimise"])


def _path_km(matrix: list[list[float]], order: list[int]) -> float:
    return sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))


@router.post("/optimise", response_model=OptimiseResponse)
@limiter.limit("20/day")
async def optimise(request: Request, req: PlanRequest) -> OptimiseResponse:
    """Return stops in hours-aware haversine-optimal order with path-length stats.

    Geocodes stops (cache-first — nearly free after the first plan).  Opening
    hours are applied as soft constraints so the solver avoids arriving at
    closed venues; infeasibility_flags reports stops that remain violated.
    The optimised stop list is intended for re-POST to /api/plan.
    """
    places = []
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

    trip_timezone = destination_timezone(places[0].lat, places[0].lng, req.timezone)
    stays = [
        s.stay_minutes if s.stay_minutes is not None else DEFAULT_STAY_MINUTES for s in req.stops
    ]

    n = len(places)
    matrix = build_haversine_matrix(places)
    original_order = list(range(n))
    optimised_idx, flags = optimise_order_with_hours(
        places,
        stays,
        req.start_time,
        trip_timezone,
        fixed_first=req.fixed_first,
        fixed_last=req.fixed_last,
    )

    return OptimiseResponse(
        stops=[
            OptimisedStop(
                query=req.stops[i].query,
                name=places[i].name,
                stay_minutes=req.stops[i].stay_minutes,
            )
            for i in optimised_idx
        ],
        original_km=round(_path_km(matrix, original_order), 2),
        optimised_km=round(_path_km(matrix, optimised_idx), 2),
        infeasibility_flags=flags,
    )
