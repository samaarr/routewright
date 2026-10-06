"""Request models for the v2 API (/api/v2/*).

The legacy v1 endpoints (/api/plan, /api/optimise, /api/refresh-leg) and
their request models were retired on 2026-10-06.
"""

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

TransportMode = Literal["transit", "walking", "driving"]

# Maximum how far into the future a departure may be (v2 departure range check).
MAX_FUTURE_DAYS = 100


class PlaceSelection(BaseModel):
    """A selected place identified by its Google place_id.

    The client selects the place (via suggestions or a previous plan response)
    before submitting. Only ``place_id`` is authoritative: the server fetches
    Place Details for it and routes with the provider-confirmed name and
    coordinates. ``name``/``lat``/``lng`` are client display hints and are
    never used for routing, timezone resolution or hours (D13, D45).
    """

    model_config = ConfigDict(extra="forbid")

    place_id: str = Field(..., min_length=1, max_length=300)
    name: str = Field(..., min_length=1, max_length=300)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)

    @field_validator("place_id", "name", mode="before")
    @classmethod
    def strip_and_reject_blank(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class CitySelection(PlaceSelection):
    """A resolved city with an optional map viewport (D26, D44).

    The viewport (north-east / south-west corners) is used by the map to
    fit the initial camera to the trip city. All four corners must be
    supplied together or all omitted.
    """

    ne_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    ne_lng: float | None = Field(default=None, ge=-180.0, le=180.0)
    sw_lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    sw_lng: float | None = Field(default=None, ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def viewport_all_or_none(self) -> Self:
        viewport_fields = (self.ne_lat, self.ne_lng, self.sw_lat, self.sw_lng)
        provided = [f for f in viewport_fields if f is not None]
        if provided and len(provided) != 4:
            raise ValueError("Viewport requires all four corners (ne_lat, ne_lng, sw_lat, sw_lng)")
        return self


class StopSpec(BaseModel):
    """One stop in an ItineraryRequest: stable identity + explicit place selection.

    instance_id is client-assigned and stable across edits and reorders (D11).
    It is the key used to preserve per-stop duration overrides when the user
    drags a stop to a new position in the list.
    """

    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Client-assigned stable identifier for this stop instance.",
    )
    selection: PlaceSelection
    stay_minutes: int | None = Field(
        default=None,
        ge=0,
        le=720,
        description="Explicit stay override. None means use the place-type default.",
    )


class DepartureInput(BaseModel):
    """Destination-local departure time with explicit DST disambiguation (D14).

    A local date + time + IANA timezone is used instead of a UTC datetime
    so that "start at 09:00" is preserved correctly across DST transitions.
    When clocks fall back, the 01:00–02:00 hour occurs twice; occurrence
    disambiguates which instance the user intends (1 = first / standard,
    2 = second / summer). It is required if and only if the departure lands
    in a fold; the server rejects it for times that occur only once.

    ``timezone`` must equal the zone the server resolves offline from the
    verified city; a mismatch is rejected rather than trusted (D40, D41).
    """

    model_config = ConfigDict(extra="forbid")

    local_date: str = Field(
        ...,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="ISO 8601 date in the trip city's local timezone, e.g. '2026-06-01'.",
    )
    local_time: str = Field(
        ...,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="24-hour clock time, e.g. '09:00'.",
    )
    timezone: str = Field(
        ...,
        description="IANA timezone for the trip city, e.g. 'Europe/Dublin'.",
    )
    occurrence: Literal[1, 2] | None = Field(
        default=None,
        description=(
            "Repeated-time choice in chronological order: 1 = earlier instant, "
            "2 = later instant. Required only when the local time occurs twice."
        ),
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return v


class ItineraryRequest(BaseModel):
    """Input for the new itinerary-planning endpoints (Step 3+)."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Client-generated UUID identifying this operation (D12).",
    )
    input_revision: int = Field(
        ...,
        ge=0,
        description="Monotonic counter incremented on each form edit (D12).",
    )
    city: CitySelection
    stops: list[StopSpec] = Field(
        ...,
        min_length=2,
        max_length=12,
        description="Stops in user-chosen order.",
    )
    departure: DepartureInput
    mode: TransportMode = Field(default="transit")
    fixed_first: bool = Field(default=False)
    fixed_last: bool = Field(default=False)

    @model_validator(mode="after")
    def bound_itinerary(self) -> Self:
        from app.core.config import settings

        if len(self.stops) > settings.max_stops_per_request:
            raise ValueError("Too many stops")
        if sum(s.stay_minutes or 0 for s in self.stops) > 12 * 60:
            raise ValueError("Total explicit visits must not exceed 12 hours")
        # Durations are keyed by instance_id (D11); repeated provider place IDs
        # are allowed (distinct visits), repeated instance IDs are not.
        ids = [s.instance_id for s in self.stops]
        if len(set(ids)) != len(ids):
            raise ValueError("Stop instance_id values must be unique")
        return self


class RefreshRequest(ItineraryRequest):
    """Refresh the remaining timetable from leg ``leg_index`` (D21, Step 7).

    Input provenance: the itinerary fields are the same inputs as a plan
    request and are verified again server-side (city, departure zone and the
    affected suffix stops only, D37). ``planned_departure`` is the selected
    leg's planned departure instant taken from the client's current
    calculated plan (the departure of stop ``leg_index``); the server holds
    no stored results, so it is validated for consistency and provider
    support but cannot be proven to match an earlier response. Earlier stops
    and legs are not sent: the client keeps its confirmed prefix unchanged and
    the response contains only the recomputed suffix.
    """

    leg_index: int = Field(
        ...,
        ge=0,
        description="0-based index of the first leg to refresh (leg k joins stop k to stop k+1).",
    )
    planned_departure: AwareDatetime = Field(
        ...,
        description="Planned departure instant of leg k from the current plan (timezone-aware).",
    )

    @model_validator(mode="after")
    def leg_in_range(self) -> Self:
        if self.leg_index > len(self.stops) - 2:
            raise ValueError("leg_index must refer to a leg between two stops")
        return self


class ComparisonRequest(ItineraryRequest):
    """Compare the current order with one locally generated alternative (Step 8).

    ``fixed_first`` / ``fixed_last`` pin whichever stop instances occupy the
    first/last positions when the comparison starts (D16, D17); the client
    sends the user's current pin settings (pinned by default). Durations are
    resolved once from this order and carried by stop instance into the
    candidate (D11). No browser-supplied totals are accepted (D10).
    """


# ---------------------------------------------------------------------------
# City/place suggestion and selection requests (D34-D36)
# ---------------------------------------------------------------------------

_SESSION_TOKEN_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"
_PROVIDER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,300}$"


class SuggestionQuery(BaseModel):
    """A search for city or place suggestions.

    ``query`` is whitespace-normalised; any nonblank text is accepted so the
    explicit Search action can look up 1-character names. The 2-character
    minimum applies only to automatic (typing-triggered) searches client-side.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., max_length=200)
    session_token: str | None = Field(default=None, pattern=_SESSION_TOKEN_PATTERN)

    @field_validator("query", mode="before")
    @classmethod
    def normalise_query(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("must be a string")
        if any(ord(c) < 32 for c in v):
            raise ValueError("must not contain control characters")
        normalised = " ".join(v.split())
        if not normalised:
            raise ValueError("must not be blank")
        if len(normalised) > 120:
            raise ValueError("must be at most 120 characters")
        return normalised


class ViewportInput(BaseModel):
    """A viewport echoed back by the client (from a city selection) for search bias.

    Only used to bias suggestions; never trusted for verification or warnings
    in plan results, which use the server-verified city viewport.
    """

    model_config = ConfigDict(extra="forbid")

    low_lat: float = Field(..., ge=-90.0, le=90.0)
    low_lng: float = Field(..., ge=-180.0, le=180.0)
    high_lat: float = Field(..., ge=-90.0, le=90.0)
    high_lng: float = Field(..., ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def ordered_latitudes(self) -> Self:
        if self.low_lat > self.high_lat:
            raise ValueError("low_lat must not exceed high_lat")
        return self


class PlaceSuggestionQuery(SuggestionQuery):
    """Place search guided by the selected city's viewport (bias, not restriction)."""

    city_viewport: ViewportInput | None = None


class SelectionRequest(BaseModel):
    """The user explicitly chose a suggestion; look it up to conclude the session."""

    model_config = ConfigDict(extra="forbid")

    place_id: str = Field(..., pattern=_PROVIDER_ID_PATTERN)
    session_token: str | None = Field(default=None, pattern=_SESSION_TOKEN_PATTERN)
