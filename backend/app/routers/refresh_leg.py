"""POST /api/refresh-leg — refresh a single leg with current-time routing.

Avoids re-geocoding all stops when the user just wants up-to-date
directions for one segment. The client already has coordinates from
the plan response, so no geocoding happens here — one Routes API call.

The departure time is always datetime.now(UTC), making the result
meaningful: "if I left right now, how long would this leg take?"
"""

import math
from datetime import datetime, timezone
from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.limiter import REFRESH_LIMITS, limiter, request_cost
from app.core.provider_semaphore import get_provider_semaphore
from app.models.request import TransportMode
from app.models.response import LegItem
from app.services.directions import DirectionsError, fetch_leg

router = APIRouter(prefix="/api", tags=["refresh-leg"])


class RefreshLegRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_lat: float = Field(..., ge=-90.0, le=90.0)
    from_lng: float = Field(..., ge=-180.0, le=180.0)
    from_name: str = Field(..., min_length=1, max_length=200)
    to_lat: float = Field(..., ge=-90.0, le=90.0)
    to_lng: float = Field(..., ge=-180.0, le=180.0)
    to_name: str = Field(..., min_length=1, max_length=200)
    mode: TransportMode
    city: str = Field(..., min_length=1, max_length=120)

    @field_validator("from_lat", "from_lng", "to_lat", "to_lng")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("coordinate must be a finite number")
        return v

    @field_validator("from_name", "to_name", "city", mode="before")
    @classmethod
    def strip_and_reject_blank(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


@router.post("/refresh-leg", response_model=LegItem)
@limiter.limit(REFRESH_LIMITS, cost=request_cost)
async def refresh_leg(request: Request, req: RefreshLegRequest) -> LegItem:
    """Fetch a single leg using the current wall-clock time as departure.

    Returns a LegItem in the same shape as the items in a Plan.timeline,
    so the client can splice it in without reshaping.
    """
    depart_at = datetime.now(timezone.utc)

    try:
        async with get_provider_semaphore():
            result = await fetch_leg(
                origin_lat=req.from_lat,
                origin_lng=req.from_lng,
                destination_lat=req.to_lat,
                destination_lng=req.to_lng,
                depart_at=depart_at,
                mode=req.mode,
            )
    except DirectionsError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch route: {req.from_name} → {req.to_name}",
        ) from exc

    return LegItem(
        from_name=req.from_name,
        to_name=req.to_name,
        mode=req.mode,
        duration_seconds=result.duration_seconds,
        distance_meters=result.distance_meters,
        depart_at=depart_at,
        arrive_at=result.arrive_at,
        summary=result.summary,
        map_url=_dir_url(req.from_name, req.to_name, req.city, req.mode),
    )


def _dir_url(origin: str, destination: str, city: str, mode: str) -> str:
    o = quote_plus(f"{origin}, {city}")
    d = quote_plus(f"{destination}, {city}")
    return f"https://www.google.com/maps/dir/?api=1&origin={o}&destination={d}&travelmode={mode}"
