"""POST /api/optimise — distance-optimal stop reordering.

Stage 1: haversine cost, no time-window constraints (Stage 2), no UI (Stage 3).
Geocodes stops cache-first, runs OR-Tools TSP, returns the reordered stop list
plus path-length stats. The caller re-POSTs the result to /api/plan for pricing.
"""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.limiter import limiter
from app.models.request import PlanRequest
from app.models.response import OptimisedStop, OptimiseResponse
from app.services.geocache import geocode_cached
from app.services.geocoder import GeocoderError
from app.services.optimise import build_haversine_matrix, optimise_order

router = APIRouter(prefix="/api", tags=["optimise"])


def _path_km(matrix: list[list[float]], order: list[int]) -> float:
    return sum(matrix[order[i]][order[i + 1]] for i in range(len(order) - 1))


@router.post("/optimise", response_model=OptimiseResponse)
@limiter.limit("20/day")
async def optimise(request: Request, req: PlanRequest) -> OptimiseResponse:
    """Return stops in haversine-optimal order with before/after path lengths.

    Geocodes stops (cache-first — nearly free after the first plan).  The
    optimised stop list is intended for the frontend to re-POST to /api/plan,
    reusing the existing handleReorder flow to produce a priced timeline.
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

    n = len(places)
    matrix = build_haversine_matrix(places)
    original_order = list(range(n))
    optimised_idx = optimise_order(places)

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
    )
