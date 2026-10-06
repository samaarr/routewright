"""Response models for the public API.

v1 returns a flat timeline: an ordered list of items, each either a Stop
or a Leg. The frontend renders them in order. No nested place lookups
needed — Stop carries its display info inline.

New streaming/engine types are appended at the bottom of the file.
"""

from datetime import date, datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, Field

WarningSeverity = Literal["info", "warning", "error"]
HoursSource: TypeAlias = Literal["date_specific", "weekly"]
# Why an hours status is "unknown": no data, data in an undocumented shape,
# or only date-specific data that does not cover the visit date.
HoursUnknownReason: TypeAlias = Literal["missing", "malformed", "outside_coverage"]

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
    opens_on: date | None = None  # local date of opens_at when not the arrival date
    hours_source: HoursSource | None = (
        None  # "weekly" for regularOpeningHours; "date_specific" for currentOpeningHours
    )
    # v2 qualification facts (D43). Defaults keep the v1 /api/plan shape unchanged.
    always_open: bool = False  # provider's documented 24-hour shape
    exceptions_unconfirmed: bool = False  # weekly schedule; holidays not checked
    coverage_start: date | None = None  # date-specific data window (inclusive)
    coverage_end: date | None = None
    special_day: bool = False  # provider flags exceptional hours on the visit date
    unknown_reason: HoursUnknownReason | None = None


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
    # v2: stable stop-instance identity (positions change on reorder).
    affects_instance_id: str | None = None
    code: str | None = None


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


# ---------------------------------------------------------------------------
# New timeline item types (Step 3+ engine output)
# ---------------------------------------------------------------------------

PlanFailureReason: TypeAlias = Literal[
    "no_route",
    "provider_temporary",
    "quota_exceeded",
    "provider_capacity",
    "place_invalid",
    "place_temporary",
    "deadline_exceeded",
    "cancelled",
]


class KnownStop(BaseModel):
    """A stop with fully resolved coordinates and a complete schedule."""

    item_type: Literal["stop"] = "stop"
    instance_id: str = Field(..., description="Client-assigned stable stop identifier.")
    place_id: str
    name: str
    address: str | None = None
    lat: float
    lng: float
    arrive_at: datetime
    depart_at: datetime
    stay_minutes: int
    stay_source: Literal["user", "default"]
    map_url: str
    hours_status: HoursStatus = "unknown"
    hours_detail: HoursDetail | None = None


class PlannedLeg(BaseModel):
    """A successfully routed travel leg."""

    item_type: Literal["leg"] = "leg"
    from_stop_id: str = Field(..., description="instance_id of the origin stop.")
    to_stop_id: str = Field(..., description="instance_id of the destination stop.")
    from_name: str
    to_name: str
    mode: Literal["transit", "walking", "driving"]
    duration_seconds: int
    distance_meters: int | None = None
    depart_at: datetime
    arrive_at: datetime
    summary: str
    map_url: str


class FailedLeg(BaseModel):
    """A leg that could not be routed — terminates the valid timeline prefix.

    Stops that follow a FailedLeg have unknown arrival/departure times and
    are represented as UnknownStop. There is no invented fallback duration.
    """

    item_type: Literal["failed_leg"] = "failed_leg"
    from_stop_id: str
    to_stop_id: str
    from_name: str
    to_name: str
    failure_reason: PlanFailureReason
    failure_message: str | None = Field(
        default=None,
        description="Human-readable detail. Never contains raw provider error text.",
    )


class UnknownStop(BaseModel):
    """A stop that follows a FailedLeg — arrival/departure times are unknown.

    Downstream stops are always UnknownStop when any preceding leg failed.
    The frontend should display these with a visual 'time unknown' state.
    """

    item_type: Literal["unknown_stop"] = "unknown_stop"
    instance_id: str
    place_id: str
    name: str


# Discriminated union of all new timeline item types.
PlanTimelineItem: TypeAlias = Annotated[
    KnownStop | PlannedLeg | FailedLeg | UnknownStop,
    Field(discriminator="item_type"),
]


# ---------------------------------------------------------------------------
# Plan result shapes
# ---------------------------------------------------------------------------


class CompletePlan(BaseModel):
    """All legs routed successfully — every stop has a known schedule."""

    result_type: Literal["complete"] = "complete"
    operation_id: str
    input_revision: int
    city: str
    mode: Literal["transit", "walking", "driving"]
    timezone: str = Field(
        ...,
        description="IANA timezone resolved offline from the verified city coordinates.",
    )
    timeline: list[PlanTimelineItem]
    overview_map_url: str
    warnings: list[Warning] = Field(default_factory=list)


class PartialPlan(BaseModel):
    """Valid prefix up to a failed leg — downstream times are unknown.

    The timeline contains KnownStop/PlannedLeg items up to the failure,
    then exactly one FailedLeg, then UnknownStop items for all remaining
    stops. No times are invented for the unknown suffix.
    """

    result_type: Literal["partial"] = "partial"
    operation_id: str
    input_revision: int
    city: str
    mode: Literal["transit", "walking", "driving"]
    timezone: str
    timeline: list[PlanTimelineItem]
    failed_at_leg_index: int = Field(
        ...,
        description="0-based index of the FailedLeg within the stop list.",
    )
    failure_reason: PlanFailureReason
    overview_map_url: str
    warnings: list[Warning] = Field(default_factory=list)


PlanResult: TypeAlias = Annotated[
    CompletePlan | PartialPlan,
    Field(discriminator="result_type"),
]


# ---------------------------------------------------------------------------
# Operation outcome shapes
# ---------------------------------------------------------------------------


class PlanOutcome(BaseModel):
    """Terminal outcome for a plan or comparison operation."""

    outcome_type: Literal["plan"] = "plan"
    result: PlanResult


class RefreshOutcome(BaseModel):
    """Terminal outcome for a single-leg refresh (D21)."""

    outcome_type: Literal["refresh"] = "refresh"
    leg: Annotated[PlannedLeg | FailedLeg, Field(discriminator="item_type")]
    subsequent_stops: list[Annotated[KnownStop | UnknownStop, Field(discriminator="item_type")]] = (
        Field(default_factory=list)
    )


class CancelledOutcome(BaseModel):
    """Terminal outcome when the operation was cancelled (client disconnect)."""

    outcome_type: Literal["cancelled"] = "cancelled"
    reason: str


class ErrorDetails(BaseModel):
    """Structured context for an error outcome. Never raw provider text."""

    role: Literal["city", "stop"] | None = None
    reason: str | None = None
    place_id: str | None = None
    instance_ids: list[str] | None = None
    moved_place_id: str | None = None
    retry_after_seconds: int | None = None


class ErrorOutcome(BaseModel):
    """Terminal outcome for an unrecoverable error.

    Never exposes raw provider error text — only a structured code and a
    safe user-facing message.
    """

    outcome_type: Literal["error"] = "error"
    code: str
    message: str


OperationOutcome: TypeAlias = Annotated[
    PlanOutcome | RefreshOutcome | CancelledOutcome | ErrorOutcome,
    Field(discriminator="outcome_type"),
]


# ---------------------------------------------------------------------------
# Streaming event shapes (D6-D7, D22-D23)
# ---------------------------------------------------------------------------


class _BaseEvent(BaseModel):
    """Common identity fields on every streaming event."""

    operation_id: str
    input_revision: int


class OperationStartEvent(_BaseEvent):
    """First event in a stream — announces phases and operation identity."""

    type: Literal["operation_start"] = "operation_start"
    phases: list[str] = Field(default_factory=list)


class LegProgressEvent(_BaseEvent):
    """Emitted when a leg routing call starts."""

    type: Literal["leg_progress"] = "leg_progress"
    leg_index: int
    total_legs: int


class StopReadyEvent(_BaseEvent):
    """Emitted when a stop's schedule is fully resolved."""

    type: Literal["stop_ready"] = "stop_ready"
    stop_index: int
    stop: KnownStop


class LegReadyEvent(_BaseEvent):
    """Emitted when a leg routing call completes (success or failure)."""

    type: Literal["leg_ready"] = "leg_ready"
    leg_index: int
    leg: Annotated[PlannedLeg | FailedLeg, Field(discriminator="item_type")]


class PhaseCompleteEvent(_BaseEvent):
    """Emitted when a named phase finishes (e.g. 'geocoding', 'routing')."""

    type: Literal["phase_complete"] = "phase_complete"
    phase: str


class TerminalEvent(_BaseEvent):
    """Final event in a stream — carries the complete operation outcome."""

    type: Literal["terminal"] = "terminal"
    outcome: OperationOutcome


StreamEvent: TypeAlias = Annotated[
    OperationStartEvent
    | LegProgressEvent
    | StopReadyEvent
    | LegReadyEvent
    | PhaseCompleteEvent
    | TerminalEvent,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# City/place suggestion and selection responses (D34-D36, D44)
# ---------------------------------------------------------------------------


class SuggestionItem(BaseModel):
    """One suggestion. Identifying text and the provider ID only."""

    place_id: str
    primary_text: str
    secondary_text: str | None = None


class SuggestionsResponse(BaseModel):
    """``no_matches`` is a successful search with nothing to choose from."""

    status: Literal["ok", "no_matches"]
    suggestions: list[SuggestionItem] = Field(default_factory=list)


class ViewportOut(BaseModel):
    """Provider-suggested map area for a city. Not an administrative boundary."""

    low_lat: float
    low_lng: float
    high_lat: float
    high_lng: float


class SelectedCity(BaseModel):
    """A verified city selection: trip context for timezone, bias and area checks."""

    place_id: str
    name: str
    secondary_text: str | None = None
    lat: float
    lng: float
    timezone: str = Field(..., description="IANA zone resolved offline from coordinates.")
    viewport: ViewportOut | None = Field(
        default=None, description="Null when the provider supplied no usable viewport."
    )


class SelectedPlace(BaseModel):
    """A verified stop selection (coordinates for map pin and area/timezone preview)."""

    place_id: str
    lat: float
    lng: float
    secondary_text: str | None = None
    timezone: str | None = Field(
        default=None, description="Null when no timezone can be resolved (planning blocks)."
    )
    source: Literal["provider", "cache"]


# ---------------------------------------------------------------------------
# Schema export root — used by scripts/export_schema.py only
# ---------------------------------------------------------------------------


class ContractRoot(BaseModel):
    """Aggregation root for JSON Schema export.

    Never serialised in production. All API types appear as optional fields
    so that json-schema-to-typescript generates a named interface for each
    type in the schema's $defs section.
    """

    # New streaming / engine types
    plan_result: PlanResult | None = None
    stream_event: StreamEvent | None = None
    operation_outcome: OperationOutcome | None = None
    known_stop: KnownStop | None = None
    planned_leg: PlannedLeg | None = None
    failed_leg: FailedLeg | None = None
    unknown_stop: UnknownStop | None = None
    suggestions_response: SuggestionsResponse | None = None
    selected_city: SelectedCity | None = None
    selected_place: SelectedPlace | None = None
    error_details: ErrorDetails | None = None
    # Legacy v1 types (preserved for the existing /api/plan endpoint)
    plan: Plan | None = None
    optimise_response: OptimiseResponse | None = None
    error_response: ErrorResponse | None = None
