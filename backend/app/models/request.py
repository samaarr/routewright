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
