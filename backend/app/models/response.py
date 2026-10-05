"""Response models for the public API.

v1 returns a flat timeline: an ordered list of items, each either a Stop
or a Leg. The frontend renders them in order. No nested place lookups
needed — Stop carries its display info inline.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WarningSeverity = Literal["info", "warning", "error"]

# Status of a stop's opening hours relative to its planned arrival/departure.
# "unknown" means no hours data was available — never implies closed.
HoursStatus = Literal[
    "open",
    "closed_on_arrival",
    "closes_during_visit",
    "closes_soon",
    "unknown",
]


class HoursDetail(BaseModel):
    """Machine-readable time facts for a stop's hours status.

    Times are HH:MM in the trip-city's local timezone (same tz as start_time).
    Fields not relevant to the current status are None.
    Frontend composes the display sentence; this model carries only the facts.
    """

    closes_at: str | None = None  # e.g. "17:00" — for open/closes_during_visit/closes_soon
    opens_at: str | None = None  # e.g. "14:00" — for closed_on_arrival


class StopItem(BaseModel):
    """A scheduled stop on the timeline."""

    item_type: Literal["stop"] = "stop"
    query: str = Field(..., description="What the user typed.")
    name: str = Field(..., description="Resolved place name from geocoder.")
    address: str | None = None
    lat: float
    lng: float
    arrive_at: datetime
    depart_at: datetime
    stay_minutes: int
    stay_source: Literal["user", "default"] = Field(
        ...,
        description="Whether stay_minutes came from the user or our default table.",
    )
    map_url: str = Field(..., description="Google Maps search URL for the place itself.")
    hours_status: HoursStatus = Field(
        default="unknown",
        description="Open/closed status of this stop at planned arrival time.",
    )
    hours_detail: HoursDetail | None = Field(
        default=None,
        description="Machine-readable time facts (closes_at / opens_at as HH:MM).",
    )


class LegItem(BaseModel):
    """A single travel segment between two stops."""

    item_type: Literal["leg"] = "leg"
    from_name: str
    to_name: str
    mode: Literal["transit", "walking", "driving"]
    duration_seconds: int
    distance_meters: int | None = None
    depart_at: datetime
    arrive_at: datetime
    summary: str = Field(
        ...,
        description="Human-readable summary, e.g. 'Take the 47 bus, 18 min'.",
    )
    map_url: str = Field(..., description="Google Maps directions deeplink.")


class Warning(BaseModel):
    """A timing/closure issue surfaced inline in the timeline."""

    severity: WarningSeverity
    message: str
    affects_stop_index: int | None = None


class Plan(BaseModel):
    """Full timeline response."""

    generated_at: datetime
    city: str
    mode: Literal["transit", "walking", "driving"]
    timezone: str = Field(
        ...,
        description="IANA timezone for the trip city, e.g. 'Europe/London'. "
        "Derived from the first stop's coordinates. Used by the frontend "
        "to display arrival times in destination time regardless of the "
        "user's browser timezone.",
    )
    timeline: list[StopItem | LegItem] = Field(
        ...,
        description="Alternating stop/leg/stop/leg/... in chronological order.",
    )
    overview_map_url: str = Field(
        ...,
        description="Google Maps URL showing all stops as a driving-mode overview.",
    )
    warnings: list[Warning] = Field(default_factory=list)


class OptimisedStop(BaseModel):
    """One stop in an optimised route, preserving the original query and stay override."""

    query: str
    name: str
    stay_minutes: int | None = None


class InfeasibilityFlag(BaseModel):
    """A stop that remains hours-violated in the chosen order.

    Reported when the solver could not schedule the stop within its opening
    hours even as a soft constraint (e.g. the stop is closed all day).
    The frontend uses this to display a warning inline — it never blocks the
    response.
    """

    stop_index: int = Field(
        ...,
        description="Index of the stop in the output order (0-based).",
    )
    stop_name: str
    issue: HoursStatus = Field(
        ...,
        description="'closed_on_arrival' or 'closes_during_visit'.",
    )


class OptimiseResponse(BaseModel):
    """Result of POST /api/optimise — reordered stops plus path-length stats."""

    stops: list[OptimisedStop]
    original_km: float = Field(..., description="Haversine path length of the input order (km).")
    optimised_km: float = Field(..., description="Haversine path length after optimisation (km).")
    infeasibility_flags: list[InfeasibilityFlag] = Field(
        default_factory=list,
        description="Stops that remain hours-violated in the chosen order.",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    # Structured field-level validation errors; omitted on non-validation errors.
    errors: list[dict[str, object]] | None = None
