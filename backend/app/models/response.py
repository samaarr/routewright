"""Response models for the v2 API (/api/v2/*).

The legacy v1 response models (Plan, StopItem, LegItem, OptimiseResponse,
ErrorResponse) were retired with their endpoints on 2026-10-06.
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


class Warning(BaseModel):
    """A timing/closure issue surfaced inline in the timeline."""

    severity: WarningSeverity
    message: str
    affects_stop_index: int | None = None
    # v2: stable stop-instance identity (positions change on reorder).
    affects_instance_id: str | None = None
    code: str | None = None


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


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


# ---------------------------------------------------------------------------
# New timeline item types (Step 3+ engine output)
# ---------------------------------------------------------------------------

PlanFailureReason: TypeAlias = Literal[
    "no_route",
    "arrival_unknown",
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
    duration_seconds: int = Field(
        ..., description="Google's travel time for the route (does not define waiting)."
    )
    journey_seconds: int = Field(
        ...,
        description=(
            "Elapsed journey time: arrival minus planned departure, including waiting, "
            "transfers and walking. Comparison totals sum this value."
        ),
    )
    distance_meters: int | None = None
    depart_at: datetime
    arrive_at: datetime
    summary: str = Field(..., description="Line or mode label, without a duration.")
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


class _RefreshCommon(BaseModel):
    """Recomputed suffix of a plan, starting at leg ``leg_index`` (D21).

    ``suffix`` starts with leg k (PlannedLeg or FailedLeg) and then alternates
    stops k+1.. and later legs. The confirmed prefix (stops 0..k and legs
    before k) is NOT included: it is unchanged and stays with the client.
    ``planned_departure`` is the instant leg k was requested for — never the
    time of the refresh request.
    """

    operation_id: str
    input_revision: int
    leg_index: int
    planned_departure: datetime
    timezone: str
    suffix: list[PlanTimelineItem]
    warnings: list[Warning] = Field(default_factory=list)


class RefreshComplete(_RefreshCommon):
    """Every leg from k onward was routed."""

    result_type: Literal["refresh_complete"] = "refresh_complete"


class RefreshPartial(_RefreshCommon):
    """A leg at or after k failed: routed legs before it are kept; later times
    are unknown (UnknownStop). No earlier/stale downstream times are reused."""

    result_type: Literal["refresh_partial"] = "refresh_partial"
    failed_at_leg_index: int = Field(..., description="Global 0-based index of the failed leg.")
    failure_reason: PlanFailureReason


RefreshResult: TypeAlias = Annotated[
    RefreshComplete | RefreshPartial,
    Field(discriminator="result_type"),
]


class RefreshOutcome(BaseModel):
    """Terminal outcome for a suffix refresh (D21)."""

    outcome_type: Literal["refresh"] = "refresh"
    result: RefreshResult


# Planning/refresh use verification + routing. A comparison (Step 8) uses
# verification, candidate (local distance search), original_route and
# alternative_route so progress identifies which itinerary is being checked.
PhaseName: TypeAlias = Literal[
    "verification", "routing", "candidate", "original_route", "alternative_route"
]


class CancelledOutcome(BaseModel):
    """Terminal outcome when the operation was cancelled.

    A client that cancels by disconnecting cannot receive this; the server
    simply stops work. It is delivered when cancellation is observed while
    the connection can still carry a final event.
    """

    outcome_type: Literal["cancelled"] = "cancelled"
    reason: str


ComparisonStatus: TypeAlias = Literal[
    "no_different_order",
    "recommended",
    "not_faster",
    "hours_ineligible",
    "original_incomplete",
    "candidate_incomplete",
]


class ComparisonResult(BaseModel):
    """Outcome of comparing the user's order with one local candidate (Step 8).

    - ``no_different_order``: the distance search returned the same order (or
      pins left no freedom); zero comparison routing calls. Never a claim that
      the original is fastest.
    - ``recommended``: both itineraries complete, the candidate passes the
      opening-hours eligibility rules and saves >= ``threshold_seconds``.
      ``candidate`` is the complete verified timeline to apply on acceptance.
    - ``not_faster`` / ``hours_ineligible``: complete comparison, original kept.
    - ``original_incomplete``: the fresh original failed; comparison stopped and
      the client keeps its previous plan (``original`` shows the partial run).
    - ``candidate_incomplete``: candidate failed; ``original`` is the complete
      freshly recalculated original; no saving is claimed.

    Totals are server-computed journey seconds (arrival minus planned
    departure of each leg, so waiting and transfers are included); distances
    are the candidate heuristic only, not evidence of a saving.
    """

    result_type: Literal["comparison"] = "comparison"
    operation_id: str
    input_revision: int
    status: ComparisonStatus
    message: str
    original_order: list[str]
    candidate_order: list[str] | None = None
    fixed_first: bool
    fixed_last: bool
    original: Annotated[CompletePlan | PartialPlan, Field(discriminator="result_type")] | None = (
        None
    )
    candidate: CompletePlan | None = Field(
        default=None, description="Only for status=recommended: the plan to apply on acceptance."
    )
    original_seconds: int | None = None
    candidate_seconds: int | None = None
    saving_seconds: int | None = None
    threshold_seconds: int = 300
    original_distance_km: float | None = None
    candidate_distance_km: float | None = None
    ineligible_instance_ids: list[str] = Field(default_factory=list)
    routing_calls: int = Field(..., description="Routing calls issued by this comparison.")


class ComparisonOutcome(BaseModel):
    """Terminal outcome for a comparison operation."""

    outcome_type: Literal["comparison"] = "comparison"
    result: ComparisonResult


class TimeoutOutcome(BaseModel):
    """Terminal outcome when the 60-second operation deadline expired.

    ``partial`` carries the valid portion when the deadline expired during
    routing (a PartialPlan for planning, a RefreshPartial for refresh); it is
    null when it expired during verification (no routing).
    """

    outcome_type: Literal["timeout"] = "timeout"
    phase: PhaseName
    message: str
    partial: Annotated[PartialPlan | RefreshPartial, Field(discriminator="result_type")] | None = (
        None
    )


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

    Never exposes raw provider error text — only a structured code, a safe
    user-facing message and optional structured details.
    """

    outcome_type: Literal["error"] = "error"
    code: str
    message: str
    details: ErrorDetails | None = None


OperationOutcome: TypeAlias = Annotated[
    PlanOutcome
    | RefreshOutcome
    | ComparisonOutcome
    | CancelledOutcome
    | TimeoutOutcome
    | ErrorOutcome,
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
    phases: list[PhaseName] = Field(default_factory=list)


class PhaseStartEvent(_BaseEvent):
    """Emitted when a named phase begins."""

    type: Literal["phase_start"] = "phase_start"
    phase: PhaseName


class LegProgressEvent(_BaseEvent):
    """Emitted when a leg routing call starts (not a completion count)."""

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
    completed_legs: int = Field(..., description="Legs successfully routed so far.")
    total_legs: int


class PhaseCompleteEvent(_BaseEvent):
    """Emitted when a named phase finishes (e.g. 'geocoding', 'routing')."""

    type: Literal["phase_complete"] = "phase_complete"
    phase: PhaseName


class TerminalEvent(_BaseEvent):
    """Final event in a stream — carries the complete operation outcome."""

    type: Literal["terminal"] = "terminal"
    outcome: OperationOutcome


StreamEvent: TypeAlias = Annotated[
    OperationStartEvent
    | PhaseStartEvent
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
    refresh_result: RefreshResult | None = None
    comparison_result: ComparisonResult | None = None
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
