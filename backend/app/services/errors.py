"""Domain errors for planning operations.

Distinct from HTTP exceptions — the router layer translates these into
appropriate HTTP responses with structured error codes.
"""


class PlaceVerificationError(Exception):
    """A required place could not be verified before routing begins.

    Attributes:
        place_name: Display label for the unresolvable place.
        is_temporary: True if the failure is transient (network / provider
            unavailable); False if the selection itself is invalid (stale
            place_id, deleted venue, etc.).
    """

    def __init__(self, place_name: str, *, is_temporary: bool = False) -> None:
        super().__init__(place_name)
        self.place_name = place_name
        self.is_temporary = is_temporary


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
    """A Google API quota limit was hit during the operation."""


class TimezoneConflictError(Exception):
    """A stop's coordinates resolve to a different timezone than the trip timezone.

    All stops in a single ItineraryRequest must share one IANA timezone (D29).

    Attributes:
        stop_name: Display name of the conflicting stop.
        detected_tz: Timezone derived from the stop's coordinates.
        expected_tz: Timezone derived from the first stop (the trip timezone).
    """

    def __init__(self, stop_name: str, *, detected_tz: str, expected_tz: str) -> None:
        super().__init__(
            f"Stop {stop_name!r} is in timezone {detected_tz!r}, "
            f"but the trip timezone is {expected_tz!r}. "
            "All stops must share one timezone."
        )
        self.stop_name = stop_name
        self.detected_tz = detected_tz
        self.expected_tz = expected_tz
