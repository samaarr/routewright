"""Domain errors for planning operations.

Distinct from HTTP exceptions — the router layer translates these into
appropriate HTTP responses with structured error codes.
"""

from typing import Literal

PlaceRole = Literal["city", "stop"]


class PlaceVerificationError(Exception):
    """A selected place is invalid or unresolvable; the user must reselect it.

    Only raised for confirmed selection problems (unknown/obsolete ID, moved or
    permanently closed place, provider identity mismatch, unusable location).
    Transient provider failures raise ProviderTemporaryError instead, so the
    user is never told a valid place is invalid.

    Attributes:
        place_id: The submitted provider place ID.
        role: Whether the city or a stop failed verification.
        reason: Machine-readable cause, e.g. "not_found", "moved".
        moved_place_id: Provider-reported replacement ID, surfaced for the
            user to choose — never substituted automatically.
    """

    def __init__(
        self,
        place_id: str,
        *,
        reason: str,
        role: PlaceRole = "stop",
        moved_place_id: str | None = None,
    ) -> None:
        super().__init__(f"Place {place_id!r} could not be verified: {reason}")
        self.place_id = place_id
        self.reason = reason
        self.role = role
        self.moved_place_id = moved_place_id


class ProviderTemporaryError(Exception):
    """A Google API call failed transiently (5xx, network timeout, etc.)."""


class NoRouteError(Exception):
    """The routing provider returned no valid route for a leg.

    Attributes:
        from_name: Origin place display name.
        to_name: Destination place display name.
    """

    def __init__(self, from_name: str, to_name: str) -> None:
        super().__init__(f"No route from {from_name!r} to {to_name!r}")
        self.from_name = from_name
        self.to_name = to_name


class QuotaExceededError(Exception):
    """A provider quota or the shared daily provider budget was exhausted."""


class ProviderCapacityError(Exception):
    """Provider admission was busy or usage control was unavailable.

    The call was not sent. Distinct from quota exhaustion so the user is not
    told the daily allowance is spent when the server was merely busy.
    """


class UsageControlUnavailableError(ProviderCapacityError):
    """The shared usage counter store could not be reached (fail-closed)."""


class TimezoneConflictError(Exception):
    """A stop's coordinates resolve to a different timezone than the trip timezone.

    All stops in a single ItineraryRequest must share one IANA timezone (D41).

    Attributes:
        stop_name: Display name of the conflicting stop.
        detected_tz: Timezone derived from the stop's coordinates.
        expected_tz: The selected city's timezone (the trip timezone).
    """

    def __init__(
        self,
        stop_name: str,
        *,
        detected_tz: str,
        expected_tz: str,
        instance_id: str | None = None,
    ) -> None:
        super().__init__(
            f"Stop {stop_name!r} is in timezone {detected_tz!r}, "
            f"but the trip timezone is {expected_tz!r}. "
            "All stops must share one timezone."
        )
        self.stop_name = stop_name
        self.detected_tz = detected_tz
        self.expected_tz = expected_tz
        self.instance_id = instance_id


class TimezoneUnresolvedError(Exception):
    """A verified location's IANA timezone could not be resolved offline (D40-41).

    Calculation is blocked; there is no UTC, browser or client-zone fallback.
    """

    def __init__(self, *, role: PlaceRole, name: str, instance_id: str | None = None) -> None:
        super().__init__(f"Could not resolve the timezone for {role} {name!r}.")
        self.role = role
        self.name = name
        self.instance_id = instance_id
