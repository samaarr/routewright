"""Stop verification: validate submitted selections and derive the trip timezone.

Called before any routing calls (D45). Invalid selections stop the operation
without consuming routing quota. All stops must share one IANA timezone (D29);
a conflict raises TimezoneConflictError which the router maps to 422.
"""

from app.core.deadline import DeadlineScope
from app.models.request import StopSpec
from app.services.engine import VerifiedStop
from app.services.errors import TimezoneConflictError
from app.services.tz import destination_timezone


def verify_stops(
    stops: list[StopSpec],
    deadline: DeadlineScope,
) -> tuple[list[VerifiedStop], str]:
    """Validate stop selections and derive the trip timezone.

    For each stop, derives the IANA timezone offline from its submitted
    coordinates. All stops must share one timezone (D29). The first stop's
    timezone becomes the trip timezone.

    Args:
        stops: Ordered list of stop specifications from the ItineraryRequest.
        deadline: Active operation deadline -- checked before each stop.

    Returns:
        Tuple of (verified_stops, trip_timezone_str).

    Raises:
        TimezoneConflictError: Any stop resolves to a different timezone than
            the first stop.
        DeadlineExceededError: Deadline exceeded before all stops are verified.
    """
    deadline.check()

    verified: list[VerifiedStop] = []
    trip_tz: str | None = None

    for spec in stops:
        deadline.check()
        sel = spec.selection

        # Offline timezone lookup from coordinates -- no network call (D29).
        tz = destination_timezone(sel.lat, sel.lng, "UTC")

        if trip_tz is None:
            trip_tz = tz
        elif tz != trip_tz:
            raise TimezoneConflictError(
                stop_name=sel.name,
                detected_tz=tz,
                expected_tz=trip_tz,
            )

        verified.append(
            VerifiedStop(
                instance_id=spec.instance_id,
                place_id=sel.place_id,
                name=sel.name,
                address=None,  # PlaceSelection carries no address field
                lat=sel.lat,
                lng=sel.lng,
            )
        )

    return verified, trip_tz or "UTC"
