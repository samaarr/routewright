"""Request models for the public API.

v1 has a single endpoint: POST /api/plan. The same shape covers initial
generation and reorder/edit, since the only persistent state v1 has is the
geocoding cache — the client always sends the full ordered list.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TransportMode = Literal["transit", "walking", "driving"]

# Maximum how far into the future a start_time may be.
# A day trip cannot be planned years ahead; reject implausibly far future dates
# (likely clock skew or a bug) without a useful error at runtime.
_MAX_FUTURE_DAYS = 100


class StopInput(BaseModel):
    """One stop in the user-supplied list.

    `query` is what the user typed (e.g. "Trinity College"). `stay_minutes`
    is optional — if absent, the backend picks a default from the
    place-type duration table after geocoding.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=2, max_length=200)
    stay_minutes: int | None = Field(
        default=None,
        ge=0,
        le=480,
        description="If omitted, the backend picks a default from place type.",
    )

    @field_validator("query", mode="before")
    @classmethod
    def normalise_query(cls, v: object) -> str:
        """Strip whitespace before length validation; reject blank strings."""
        if not isinstance(v, str):
            raise ValueError("query must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class PlanRequest(BaseModel):
    """Input for `POST /api/plan`.

    The client sends the full ordered list every time. Reordering on the
    frontend just changes the order and re-POSTs. This is intentionally
    stateless: no plan_id, no server-side session.
    """

    model_config = ConfigDict(extra="forbid")

    city: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="City context for geocoding. Required to avoid wrong-continent errors.",
        examples=["Dublin, Ireland"],
    )
    stops: list[StopInput] = Field(
        ...,
        min_length=2,
        max_length=12,
        description="Stops in user-chosen order. v1 does NOT auto-optimise.",
    )
    start_time: datetime = Field(
        ...,
        description="Timezone-aware ISO 8601. When the user wants to start.",
    )
    mode: TransportMode = Field(
        default="transit",
        description="Transport mode for all legs. v1 uses a single mode globally.",
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone for the trip city (e.g. 'Europe/London'). "
        "Used to compare UTC arrival times against venue-local opening hours.",
    )
    fixed_first: bool = Field(
        default=False,
        description="Pin the first stop — the optimiser will not move it.",
    )
    fixed_last: bool = Field(
        default=False,
        description="Pin the last stop — the optimiser will not move it.",
    )

    @field_validator("city", mode="before")
    @classmethod
    def normalise_city(cls, v: object) -> str:
        """Strip whitespace before length validation; reject blank strings."""
        if not isinstance(v, str):
            raise ValueError("city must be a string")
        stripped = v.strip()
        if not stripped:
            raise ValueError("city must not be blank")
        return stripped

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return v

    @field_validator("start_time")
    @classmethod
    def start_time_not_stale(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("start_time must be timezone-aware (include Z or offset)")
        now = datetime.now(timezone.utc)
        cutoff_past = now - timedelta(days=7)
        cutoff_future = now + timedelta(days=_MAX_FUTURE_DAYS)
        if v < cutoff_past:
            raise ValueError("start_time must not be more than 7 days in the past")
        if v > cutoff_future:
            raise ValueError(
                f"start_time must not be more than {_MAX_FUTURE_DAYS} days in the future"
            )
        return v

    @model_validator(mode="after")
    def bound_work(self) -> Self:
        from app.core.config import settings

        if len(self.stops) > settings.max_stops_per_request:
            raise ValueError("Too many stops")
        if sum(stop.stay_minutes or 0 for stop in self.stops) > 12 * 60:
            raise ValueError("Total explicit visits must not exceed 12 hours")
        if self.mode != "transit" and self.start_time < datetime.now(timezone.utc):
            raise ValueError("Walking and driving plans must start in the future")
        return self


# ---------------------------------------------------------------------------
# New request models (used by Step 3+ endpoints; PlanRequest preserved above)
# ---------------------------------------------------------------------------


class PlaceSelection(BaseModel):
    """A resolved place identified by its Google place_id and coordinates.

    The client resolves the place (via autocomplete or a previous plan
    response) before submitting. The engine verifies coordinates server-side
    before routing — it never trusts the client-supplied lat/lng directly.
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
    """A resolved city with an optional map viewport (D25, D44).

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
    in a fold; the router validates this after resolving the actual datetime.
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
        description="DST fold disambiguation. Supply only during a fall-back hour.",
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
    """Input for the new itinerary-planning endpoints (Step 3+).

    Replaces PlanRequest for new endpoints. PlanRequest is preserved for
    the existing /api/plan endpoint (backwards-compatible).
    """

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
        return self


class RefreshRequest(BaseModel):
    """Input for a single-leg refresh (Step 6+).

    The client supplies the full stop list and the planned departure time
    for the leg being refreshed. The engine recomputes that leg and all
    subsequent stops from the planned departure — not from datetime.now().
    """

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(..., min_length=1, max_length=64)
    input_revision: int = Field(..., ge=0)
    city: CitySelection
    stops: list[StopSpec] = Field(..., min_length=2, max_length=12)
    departure: DepartureInput
    mode: TransportMode = Field(default="transit")
    leg_index: int = Field(
        ...,
        ge=0,
        description="0-based index of the leg to refresh in the stop list.",
    )
    planned_departure_utc: str = Field(
        ...,
        description="ISO 8601 UTC datetime of this leg's planned departure (D21).",
    )
