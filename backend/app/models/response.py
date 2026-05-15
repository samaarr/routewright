"""Response models for the public API.

v1 returns a flat timeline: an ordered list of items, each either a Stop
or a Leg. The frontend renders them in order. No nested place lookups
needed — Stop carries its display info inline.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WarningSeverity = Literal["info", "warning", "error"]


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
    timeline: list[StopItem | LegItem] = Field(
        ...,
        description="Alternating stop/leg/stop/leg/... in chronological order.",
    )
    overview_map_url: str = Field(
        ...,
        description="Google Maps URL showing all stops as a driving-mode overview.",
    )
    warnings: list[Warning] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    env: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
