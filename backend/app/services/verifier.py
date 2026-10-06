"""Server-side verification of the selected city and stops before routing (D13, D37, D40, D41, D45).

Order of work (each step blocks everything after it, so a failure costs no
routing calls and no further Places calls):

1. City: Place Details by its selected ID; zone resolved offline from the
   provider-confirmed coordinates. No UTC/browser/first-stop fallback.
2. Departure zone: the submitted zone must equal the city's resolved zone.
3. Stops, in input order: one Place Details lookup per DISTINCT place ID,
   shared by repeated visits; each stop's zone resolved offline and required
   to equal the city's zone.

Lookups are sequential rather than concurrent: the first failure identifies
one specific selection deterministically and no further calls are spent.
Submitted names/coordinates are display hints and are never used.
The city is always looked up with the city mask (it needs ``viewport`` for
D44 area warnings, which the stop mask does not request), so a city that is
also a stop costs one city lookup plus one stop lookup.
"""

from dataclasses import dataclass

from app.core.deadline import DeadlineScope
from app.models.request import ItineraryRequest
from app.services.area import Viewport
from app.services.departure import DepartureTimezoneMismatchError
from app.services.engine import OperationContext, PlacesAdapter, VerifiedStop
from app.services.errors import PlaceRole, TimezoneConflictError, TimezoneUnresolvedError
from app.services.place_details import PlaceDetails
from app.services.tz import resolve_timezone
from app.services.venue_hours import VenueHours, parse_venue_hours


@dataclass(frozen=True)
class VerifiedCity:
    place_id: str
    name: str
    lat: float
    lng: float
    timezone: str
    viewport: Viewport | None = None


@dataclass(frozen=True)
class VerifiedItinerary:
    city: VerifiedCity
    stops: list[VerifiedStop]

    @property
    def timezone(self) -> str:
        return self.city.timezone


async def verify_itinerary(
    req: ItineraryRequest,
    places: PlacesAdapter,
    ctx: OperationContext,
    deadline: DeadlineScope,
    from_stop: int = 0,
) -> VerifiedItinerary:
    """Verify city, departure zone and stops. Makes no routing calls.

    Raises:
        PlaceVerificationError, ProviderTemporaryError, QuotaExceededError,
        ProviderCapacityError: from the Places adapter.
        TimezoneUnresolvedError, TimezoneConflictError,
        DepartureTimezoneMismatchError: zone checks.
        DeadlineExceededError: the overall deadline expired, including while
            a lookup was in flight.

    ``from_stop`` > 0 (refresh, D37): only stops from that index onward are
    looked up and returned; the city and departure zone are still verified.
    """
    details: dict[tuple[str, PlaceRole], PlaceDetails] = {}

    async def lookup(place_id: str, role: PlaceRole) -> PlaceDetails:
        key = (place_id, role)
        if key not in details:
            ctx.record_places_call()
            details[key] = await deadline.bound(places.fetch_details(place_id, role=role))
        return details[key]

    # 1. City.
    city_id = req.city.place_id
    city_details = await lookup(city_id, "city")
    city_tz = resolve_timezone(city_details.lat, city_details.lng)
    if city_tz is None:
        raise TimezoneUnresolvedError(role="city", name=city_details.name)
    city = VerifiedCity(
        city_id,
        city_details.name,
        city_details.lat,
        city_details.lng,
        city_tz,
        city_details.viewport,
    )

    # 2. Departure zone must match before any stop lookups are spent.
    if req.departure.timezone != city_tz:
        raise DepartureTimezoneMismatchError(req.departure.timezone, city_tz)

    # 3. Stops.
    hours_by_place: dict[str, VenueHours | None] = {}
    verified: list[VerifiedStop] = []
    for spec in req.stops[from_stop:]:
        pid = spec.selection.place_id
        d = await lookup(pid, "stop")
        stop_tz = resolve_timezone(d.lat, d.lng)
        if stop_tz is None:
            raise TimezoneUnresolvedError(role="stop", name=d.name, instance_id=spec.instance_id)
        if stop_tz != city_tz:
            raise TimezoneConflictError(
                d.name, detected_tz=stop_tz, expected_tz=city_tz, instance_id=spec.instance_id
            )
        if pid not in hours_by_place:
            hours_by_place[pid] = parse_venue_hours(
                d.regular_hours_raw, d.current_hours_raw, d.fetched_at, city_tz
            )
        verified.append(
            VerifiedStop(
                instance_id=spec.instance_id,
                place_id=pid,
                name=d.name,
                address=None,
                lat=d.lat,
                lng=d.lng,
                hours=hours_by_place[pid],
                primary_type=d.primary_type,
                types=tuple(d.types),
            )
        )
    return VerifiedItinerary(city=city, stops=verified)
