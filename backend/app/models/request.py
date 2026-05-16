"""Request models for the public API.

v1 has a single endpoint: POST /api/plan. The same shape covers initial
generation and reorder/edit, since the only persistent state v1 has is the
geocoding cache — the client always sends the full ordered list.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TransportMode = Literal["transit", "walking", "driving"]


class StopInput(BaseModel):
    """One stop in the user-supplied list.

    `query` is what the user typed (e.g. "Trinity College"). `stay_minutes`
    is optional — if absent, the backend picks a default from the
    place-type duration table after geocoding.
    """

    query: str = Field(..., min_length=2, max_length=200)
    stay_minutes: int | None = Field(
        default=None,
        ge=5,
        le=480,
        description="If omitted, the backend picks a default from place type.",
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()


class PlanRequest(BaseModel):
    """Input for `POST /api/plan`.

    The client sends the full ordered list every time. Reordering on the
    frontend just changes the order and re-POSTs. This is intentionally
    stateless: no plan_id, no server-side session.
    """

    city: str = Field(
        ...,
        min_length=2,
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

    @field_validator("start_time")
    @classmethod
    def start_time_not_stale(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("start_time must be timezone-aware (include Z or offset)")
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        if v < cutoff:
            raise ValueError("start_time must not be more than 30 days in the past")
        return v
