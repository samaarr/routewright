"""Production adapter implementations for the planning engine.

GoogleRoutesAdapter wraps directions.fetch_leg() under the RoutesAdapter
Protocol so the engine can be tested with deterministic fakes.
"""

from datetime import datetime
from urllib.parse import quote_plus

from app.core.provider_semaphore import get_provider_semaphore
from app.models.request import TransportMode
from app.services import directions
from app.services.engine import RoutingResult
from app.services.errors import NoRouteError, ProviderTemporaryError


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
