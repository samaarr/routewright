export type PlanResult = (CompletePlan | PartialPlan) | null;
export type ResultType = "complete";
export type OperationId = string;
export type InputRevision = number;
export type City = string;
export type Mode = "transit" | "walking" | "driving";
/**
 * IANA timezone resolved offline from the verified city coordinates.
 */
export type Timezone = string;
export type ItemType = "stop";
/**
 * Client-assigned stable stop identifier.
 */
export type InstanceId = string;
export type PlaceId = string;
export type Name = string;
export type Address = string | null;
export type Lat = number;
export type Lng = number;
export type ArriveAt = string;
export type DepartAt = string;
export type StayMinutes = number;
export type StaySource = "user" | "default";
export type MapUrl = string;
export type HoursStatus = "open" | "closed_on_arrival" | "closes_during_visit" | "closes_soon" | "unknown";
export type ClosesAt = string | null;
export type OpensAt = string | null;
export type OpensOn = string | null;
export type HoursSource = ("date_specific" | "weekly") | null;
export type AlwaysOpen = boolean;
export type ExceptionsUnconfirmed = boolean;
export type CoverageStart = string | null;
export type CoverageEnd = string | null;
export type SpecialDay = boolean;
export type UnknownReason = ("missing" | "malformed" | "outside_coverage") | null;
export type ItemType1 = "leg";
/**
 * instance_id of the origin stop.
 */
export type FromStopId = string;
/**
 * instance_id of the destination stop.
 */
export type ToStopId = string;
export type FromName = string;
export type ToName = string;
export type Mode1 = "transit" | "walking" | "driving";
/**
 * Google's travel time for the route (does not define waiting).
 */
export type DurationSeconds = number;
/**
 * Elapsed journey time: arrival minus planned departure, including waiting, transfers and walking. Comparison totals sum this value.
 */
export type JourneySeconds = number;
export type DistanceMeters = number | null;
export type DepartAt1 = string;
export type ArriveAt1 = string;
/**
 * Line or mode label, without a duration.
 */
export type Summary = string;
export type MapUrl1 = string;
export type ItemType2 = "failed_leg";
export type FromStopId1 = string;
export type ToStopId1 = string;
export type FromName1 = string;
export type ToName1 = string;
export type FailureReason =
  | "no_route"
  | "arrival_unknown"
  | "provider_temporary"
  | "quota_exceeded"
  | "provider_capacity"
  | "place_invalid"
  | "place_temporary"
  | "deadline_exceeded"
  | "cancelled";
/**
 * Human-readable detail. Never contains raw provider error text.
 */
export type FailureMessage = string | null;
export type ItemType3 = "unknown_stop";
export type InstanceId1 = string;
export type PlaceId1 = string;
export type Name1 = string;
export type Timeline = (KnownStop | PlannedLeg | FailedLeg | UnknownStop)[];
export type OverviewMapUrl = string;
export type Severity = "info" | "warning" | "error";
export type Message = string;
export type AffectsStopIndex = number | null;
export type AffectsInstanceId = string | null;
export type Code = string | null;
export type Warnings = Warning[];
export type ResultType1 = "partial";
export type OperationId1 = string;
export type InputRevision1 = number;
export type City1 = string;
export type Mode2 = "transit" | "walking" | "driving";
export type Timezone1 = string;
export type Timeline1 = (KnownStop | PlannedLeg | FailedLeg | UnknownStop)[];
/**
 * 0-based index of the FailedLeg within the stop list.
 */
export type FailedAtLegIndex = number;
export type FailureReason1 =
  | "no_route"
  | "arrival_unknown"
  | "provider_temporary"
  | "quota_exceeded"
  | "provider_capacity"
  | "place_invalid"
  | "place_temporary"
  | "deadline_exceeded"
  | "cancelled";
export type OverviewMapUrl1 = string;
export type Warnings1 = Warning[];
export type RefreshResult = (RefreshComplete | RefreshPartial) | null;
export type OperationId2 = string;
export type InputRevision2 = number;
export type LegIndex = number;
export type PlannedDeparture = string;
export type Timezone2 = string;
export type Suffix = (KnownStop | PlannedLeg | FailedLeg | UnknownStop)[];
export type Warnings2 = Warning[];
export type ResultType2 = "refresh_complete";
export type OperationId3 = string;
export type InputRevision3 = number;
export type LegIndex1 = number;
export type PlannedDeparture1 = string;
export type Timezone3 = string;
export type Suffix1 = (KnownStop | PlannedLeg | FailedLeg | UnknownStop)[];
export type Warnings3 = Warning[];
export type ResultType3 = "refresh_partial";
/**
 * Global 0-based index of the failed leg.
 */
export type FailedAtLegIndex1 = number;
export type FailureReason2 =
  | "no_route"
  | "arrival_unknown"
  | "provider_temporary"
  | "quota_exceeded"
  | "provider_capacity"
  | "place_invalid"
  | "place_temporary"
  | "deadline_exceeded"
  | "cancelled";
export type ResultType4 = "comparison";
export type OperationId4 = string;
export type InputRevision4 = number;
export type Status =
  | "no_different_order"
  | "recommended"
  | "not_faster"
  | "hours_ineligible"
  | "original_incomplete"
  | "candidate_incomplete";
export type Message1 = string;
export type OriginalOrder = string[];
export type CandidateOrder = string[] | null;
export type FixedFirst = boolean;
export type FixedLast = boolean;
export type Original = (CompletePlan | PartialPlan) | null;
export type OriginalSeconds = number | null;
export type CandidateSeconds = number | null;
export type SavingSeconds = number | null;
export type ThresholdSeconds = number;
export type OriginalDistanceKm = number | null;
export type CandidateDistanceKm = number | null;
export type IneligibleInstanceIds = string[];
/**
 * Routing calls issued by this comparison.
 */
export type RoutingCalls = number;
export type ResultType5 = "exhaustive";
export type OperationId5 = string;
export type InputRevision5 = number;
export type Status1 = "all_complete" | "some_failed" | "interrupted";
export type Message2 = string;
export type SearchComplete = boolean;
export type RequestedOrders = number;
export type EvaluatedOrders = number;
export type CompleteOrders = number;
export type FailedOrders = number;
export type InterruptionReason =
  | (
      | "no_route"
      | "arrival_unknown"
      | "provider_temporary"
      | "quota_exceeded"
      | "provider_capacity"
      | "place_invalid"
      | "place_temporary"
      | "deadline_exceeded"
      | "cancelled"
    )
  | null;
/**
 * Shared start instant at each first destination.
 */
export type StartAt = string;
export type OriginalOrder1 = string[];
/**
 * Stop instance IDs in visiting order.
 */
export type Order = string[];
export type IsOriginal = boolean;
export type Status2 = "complete" | "failed" | "interrupted";
export type CompletionAt = string | null;
/**
 * completion_at minus the shared start instant.
 */
export type ElapsedSeconds = number | null;
/**
 * Straight-line path length, metres (tie-break only).
 */
export type DistanceM = number;
export type FailureReason3 =
  | (
      | "no_route"
      | "arrival_unknown"
      | "provider_temporary"
      | "quota_exceeded"
      | "provider_capacity"
      | "place_invalid"
      | "place_temporary"
      | "deadline_exceeded"
      | "cancelled"
    )
  | null;
export type FailureMessage1 = string | null;
export type Timeline2 = (KnownStop | PlannedLeg | FailedLeg | UnknownStop)[];
export type RoutingCalls1 = number;
export type WinnerBasis = ("completion" | "distance" | "original" | "instance_order") | null;
export type SavingSeconds1 = number | null;
export type HoursWarnings = Warning[];
export type Candidates = CandidateEvaluation[];
export type RoutingCalls2 = number;
export type RoutingBudget = number;
export type DeadlineSeconds = number;
export type StreamEvent =
  | (
      | OperationStartEvent
      | PhaseStartEvent
      | LegProgressEvent
      | StopReadyEvent
      | LegReadyEvent
      | PhaseCompleteEvent
      | ExhaustiveProgressEvent
      | TerminalEvent
    )
  | null;
export type OperationId6 = string;
export type InputRevision6 = number;
export type Type = "operation_start";
export type Phases = (
  "verification" | "routing" | "candidate" | "original_route" | "alternative_route" | "exhaustive_search"
)[];
export type OperationId7 = string;
export type InputRevision7 = number;
export type Type1 = "phase_start";
export type Phase =
  "verification" | "routing" | "candidate" | "original_route" | "alternative_route" | "exhaustive_search";
export type OperationId8 = string;
export type InputRevision8 = number;
export type Type2 = "leg_progress";
export type LegIndex2 = number;
export type TotalLegs = number;
export type OperationId9 = string;
export type InputRevision9 = number;
export type Type3 = "stop_ready";
export type StopIndex = number;
export type OperationId10 = string;
export type InputRevision10 = number;
export type Type4 = "leg_ready";
export type LegIndex3 = number;
export type Leg = PlannedLeg | FailedLeg;
/**
 * Legs successfully routed so far.
 */
export type CompletedLegs = number;
export type TotalLegs1 = number;
export type OperationId11 = string;
export type InputRevision11 = number;
export type Type5 = "phase_complete";
export type Phase1 =
  "verification" | "routing" | "candidate" | "original_route" | "alternative_route" | "exhaustive_search";
export type OperationId12 = string;
export type InputRevision12 = number;
export type Type6 = "exhaustive_progress";
/**
 * Orders evaluated so far (complete + failed).
 */
export type Evaluated = number;
export type Complete = number;
export type Failed = number;
export type Total = number;
export type OperationId13 = string;
export type InputRevision13 = number;
export type Type7 = "terminal";
export type Outcome =
  | PlanOutcome
  | RefreshOutcome
  | ComparisonOutcome
  | ExhaustiveOutcome
  | CancelledOutcome
  | TimeoutOutcome
  | ErrorOutcome;
export type OutcomeType = "plan";
export type Result = CompletePlan | PartialPlan;
export type OutcomeType1 = "refresh";
export type Result1 = RefreshComplete | RefreshPartial;
export type OutcomeType2 = "comparison";
export type OutcomeType3 = "exhaustive";
export type OutcomeType4 = "cancelled";
export type Reason = string;
export type OutcomeType5 = "timeout";
export type Phase2 =
  "verification" | "routing" | "candidate" | "original_route" | "alternative_route" | "exhaustive_search";
export type Message3 = string;
export type Partial = (PartialPlan | RefreshPartial) | null;
export type OutcomeType6 = "error";
export type Code1 = string;
export type Message4 = string;
export type Role = ("city" | "stop") | null;
export type Reason1 = string | null;
export type PlaceId2 = string | null;
export type InstanceIds = string[] | null;
export type MovedPlaceId = string | null;
export type RetryAfterSeconds = number | null;
export type OperationOutcome =
  | (
      | PlanOutcome
      | RefreshOutcome
      | ComparisonOutcome
      | ExhaustiveOutcome
      | CancelledOutcome
      | TimeoutOutcome
      | ErrorOutcome
    )
  | null;
export type Status3 = "ok" | "no_matches";
export type PlaceId3 = string;
export type PrimaryText = string;
export type SecondaryText = string | null;
export type Suggestions = SuggestionItem[];
export type PlaceId4 = string;
export type Name2 = string;
export type SecondaryText1 = string | null;
export type Lat1 = number;
export type Lng1 = number;
/**
 * IANA zone resolved offline from coordinates.
 */
export type Timezone4 = string;
export type LowLat = number;
export type LowLng = number;
export type HighLat = number;
export type HighLng = number;
export type PlaceId5 = string;
export type Lat2 = number;
export type Lng2 = number;
export type SecondaryText2 = string | null;
/**
 * Null when no timezone can be resolved (planning blocks).
 */
export type Timezone5 = string | null;
export type Source = "provider" | "cache";

/**
 * Aggregation root for JSON Schema export.
 *
 * Never serialised in production. All API types appear as optional fields
 * so that json-schema-to-typescript generates a named interface for each
 * type in the schema's $defs section.
 */
export interface ContractRoot {
  plan_result?: PlanResult;
  refresh_result?: RefreshResult;
  comparison_result?: ComparisonResult | null;
  exhaustive_result?: ExhaustiveResult | null;
  stream_event?: StreamEvent;
  operation_outcome?: OperationOutcome;
  known_stop?: KnownStop | null;
  planned_leg?: PlannedLeg | null;
  failed_leg?: FailedLeg | null;
  unknown_stop?: UnknownStop | null;
  suggestions_response?: SuggestionsResponse | null;
  selected_city?: SelectedCity | null;
  selected_place?: SelectedPlace | null;
  error_details?: ErrorDetails | null;
  [k: string]: unknown;
}
/**
 * All legs routed successfully — every stop has a known schedule.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "CompletePlan".
 */
export interface CompletePlan {
  result_type?: ResultType;
  operation_id: OperationId;
  input_revision: InputRevision;
  city: City;
  mode: Mode;
  timezone: Timezone;
  timeline: Timeline;
  overview_map_url: OverviewMapUrl;
  warnings?: Warnings;
  [k: string]: unknown;
}
/**
 * A stop with fully resolved coordinates and a complete schedule.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "KnownStop".
 */
export interface KnownStop {
  item_type?: ItemType;
  instance_id: InstanceId;
  place_id: PlaceId;
  name: Name;
  address?: Address;
  lat: Lat;
  lng: Lng;
  arrive_at: ArriveAt;
  depart_at: DepartAt;
  stay_minutes: StayMinutes;
  stay_source: StaySource;
  map_url: MapUrl;
  hours_status?: HoursStatus;
  hours_detail?: HoursDetail | null;
  [k: string]: unknown;
}
/**
 * Machine-readable time facts for a stop's hours status.
 *
 * Times are HH:MM in the trip-city's local timezone (same tz as start_time).
 * Fields not relevant to the current status are None.
 * Frontend composes the display sentence; this model carries only the facts.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "HoursDetail".
 */
export interface HoursDetail {
  closes_at?: ClosesAt;
  opens_at?: OpensAt;
  opens_on?: OpensOn;
  hours_source?: HoursSource;
  always_open?: AlwaysOpen;
  exceptions_unconfirmed?: ExceptionsUnconfirmed;
  coverage_start?: CoverageStart;
  coverage_end?: CoverageEnd;
  special_day?: SpecialDay;
  unknown_reason?: UnknownReason;
  [k: string]: unknown;
}
/**
 * A successfully routed travel leg.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "PlannedLeg".
 */
export interface PlannedLeg {
  item_type?: ItemType1;
  from_stop_id: FromStopId;
  to_stop_id: ToStopId;
  from_name: FromName;
  to_name: ToName;
  mode: Mode1;
  duration_seconds: DurationSeconds;
  journey_seconds: JourneySeconds;
  distance_meters?: DistanceMeters;
  depart_at: DepartAt1;
  arrive_at: ArriveAt1;
  summary: Summary;
  map_url: MapUrl1;
  [k: string]: unknown;
}
/**
 * A leg that could not be routed — terminates the valid timeline prefix.
 *
 * Stops that follow a FailedLeg have unknown arrival/departure times and
 * are represented as UnknownStop. There is no invented fallback duration.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "FailedLeg".
 */
export interface FailedLeg {
  item_type?: ItemType2;
  from_stop_id: FromStopId1;
  to_stop_id: ToStopId1;
  from_name: FromName1;
  to_name: ToName1;
  failure_reason: FailureReason;
  failure_message?: FailureMessage;
  [k: string]: unknown;
}
/**
 * A stop that follows a FailedLeg — arrival/departure times are unknown.
 *
 * Downstream stops are always UnknownStop when any preceding leg failed.
 * The frontend should display these with a visual 'time unknown' state.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "UnknownStop".
 */
export interface UnknownStop {
  item_type?: ItemType3;
  instance_id: InstanceId1;
  place_id: PlaceId1;
  name: Name1;
  [k: string]: unknown;
}
/**
 * A timing/closure issue surfaced inline in the timeline.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "Warning".
 */
export interface Warning {
  severity: Severity;
  message: Message;
  affects_stop_index?: AffectsStopIndex;
  affects_instance_id?: AffectsInstanceId;
  code?: Code;
  [k: string]: unknown;
}
/**
 * Valid prefix up to a failed leg — downstream times are unknown.
 *
 * The timeline contains KnownStop/PlannedLeg items up to the failure,
 * then exactly one FailedLeg, then UnknownStop items for all remaining
 * stops. No times are invented for the unknown suffix.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "PartialPlan".
 */
export interface PartialPlan {
  result_type?: ResultType1;
  operation_id: OperationId1;
  input_revision: InputRevision1;
  city: City1;
  mode: Mode2;
  timezone: Timezone1;
  timeline: Timeline1;
  failed_at_leg_index: FailedAtLegIndex;
  failure_reason: FailureReason1;
  overview_map_url: OverviewMapUrl1;
  warnings?: Warnings1;
  [k: string]: unknown;
}
/**
 * Every leg from k onward was routed.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "RefreshComplete".
 */
export interface RefreshComplete {
  operation_id: OperationId2;
  input_revision: InputRevision2;
  leg_index: LegIndex;
  planned_departure: PlannedDeparture;
  timezone: Timezone2;
  suffix: Suffix;
  warnings?: Warnings2;
  result_type?: ResultType2;
  [k: string]: unknown;
}
/**
 * A leg at or after k failed: routed legs before it are kept; later times
 * are unknown (UnknownStop). No earlier/stale downstream times are reused.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "RefreshPartial".
 */
export interface RefreshPartial {
  operation_id: OperationId3;
  input_revision: InputRevision3;
  leg_index: LegIndex1;
  planned_departure: PlannedDeparture1;
  timezone: Timezone3;
  suffix: Suffix1;
  warnings?: Warnings3;
  result_type?: ResultType3;
  failed_at_leg_index: FailedAtLegIndex1;
  failure_reason: FailureReason2;
  [k: string]: unknown;
}
/**
 * Outcome of comparing the user's order with one local candidate (Step 8).
 *
 * - ``no_different_order``: the distance search returned the same order (or
 *   pins left no freedom); zero comparison routing calls. Never a claim that
 *   the original is fastest.
 * - ``recommended``: both itineraries complete, the candidate passes the
 *   opening-hours eligibility rules and saves >= ``threshold_seconds``.
 *   ``candidate`` is the complete verified timeline to apply on acceptance.
 * - ``not_faster`` / ``hours_ineligible``: complete comparison, original kept.
 * - ``original_incomplete``: the fresh original failed; comparison stopped and
 *   the client keeps its previous plan (``original`` shows the partial run).
 * - ``candidate_incomplete``: candidate failed; ``original`` is the complete
 *   freshly recalculated original; no saving is claimed.
 *
 * Totals are server-computed journey seconds (arrival minus planned
 * departure of each leg, so waiting and transfers are included); distances
 * are the candidate heuristic only, not evidence of a saving.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ComparisonResult".
 */
export interface ComparisonResult {
  result_type?: ResultType4;
  operation_id: OperationId4;
  input_revision: InputRevision4;
  status: Status;
  message: Message1;
  original_order: OriginalOrder;
  candidate_order?: CandidateOrder;
  fixed_first: FixedFirst;
  fixed_last: FixedLast;
  original?: Original;
  /**
   * Only for status=recommended: the plan to apply on acceptance.
   */
  candidate?: CompletePlan | null;
  original_seconds?: OriginalSeconds;
  candidate_seconds?: CandidateSeconds;
  saving_seconds?: SavingSeconds;
  threshold_seconds?: ThresholdSeconds;
  original_distance_km?: OriginalDistanceKm;
  candidate_distance_km?: CandidateDistanceKm;
  ineligible_instance_ids?: IneligibleInstanceIds;
  routing_calls: RoutingCalls;
  [k: string]: unknown;
}
/**
 * Terminal result of the exhaustive four-stop experiment.
 *
 * ``search_complete`` is true only when every one of the 24 orders reached a
 * terminal state (complete or failed). ``winner`` is the complete order with
 * the earliest completion (ties: straight-line distance, then the original
 * order, then instance-ID order); for an interrupted search it is the best
 * so far and ``winner_plan`` is null (not acceptable). ``saving_seconds`` is
 * exact and present only when the original order is complete.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ExhaustiveResult".
 */
export interface ExhaustiveResult {
  result_type?: ResultType5;
  operation_id: OperationId5;
  input_revision: InputRevision5;
  status: Status1;
  message: Message2;
  search_complete: SearchComplete;
  requested_orders?: RequestedOrders;
  evaluated_orders: EvaluatedOrders;
  complete_orders: CompleteOrders;
  failed_orders: FailedOrders;
  interruption_reason?: InterruptionReason;
  start_at: StartAt;
  original_order: OriginalOrder1;
  original?: CandidateEvaluation | null;
  winner?: CandidateEvaluation | null;
  winner_basis?: WinnerBasis;
  /**
   * Only for a terminal search with a complete winner.
   */
  winner_plan?: CompletePlan | null;
  saving_seconds?: SavingSeconds1;
  hours_warnings?: HoursWarnings;
  candidates: Candidates;
  routing_calls: RoutingCalls2;
  routing_budget?: RoutingBudget;
  deadline_seconds?: DeadlineSeconds;
  [k: string]: unknown;
}
/**
 * One stop order evaluated from the shared start instant.
 *
 * ``complete``: every leg routed; ``completion_at`` is the end of the last
 * visit (its arrival plus its stay). ``failed``: a leg had no usable route
 * (no_route / arrival_unknown); the valid prefix is kept and later stops are
 * unknown. ``interrupted``: the search stopped during this order
 * (cancellation, deadline, quota, usage controls or provider failure).
 * ``distance_m`` is the straight-line (haversine) path length, used only to
 * break exact completion ties; it is not transit distance.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "CandidateEvaluation".
 */
export interface CandidateEvaluation {
  order: Order;
  is_original: IsOriginal;
  status: Status2;
  completion_at?: CompletionAt;
  elapsed_seconds?: ElapsedSeconds;
  distance_m: DistanceM;
  failure_reason?: FailureReason3;
  failure_message?: FailureMessage1;
  timeline: Timeline2;
  routing_calls: RoutingCalls1;
  [k: string]: unknown;
}
/**
 * First event in a stream — announces phases and operation identity.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "OperationStartEvent".
 */
export interface OperationStartEvent {
  operation_id: OperationId6;
  input_revision: InputRevision6;
  type?: Type;
  phases?: Phases;
  [k: string]: unknown;
}
/**
 * Emitted when a named phase begins.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "PhaseStartEvent".
 */
export interface PhaseStartEvent {
  operation_id: OperationId7;
  input_revision: InputRevision7;
  type?: Type1;
  phase: Phase;
  [k: string]: unknown;
}
/**
 * Emitted when a leg routing call starts (not a completion count).
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "LegProgressEvent".
 */
export interface LegProgressEvent {
  operation_id: OperationId8;
  input_revision: InputRevision8;
  type?: Type2;
  leg_index: LegIndex2;
  total_legs: TotalLegs;
  [k: string]: unknown;
}
/**
 * Emitted when a stop's schedule is fully resolved.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "StopReadyEvent".
 */
export interface StopReadyEvent {
  operation_id: OperationId9;
  input_revision: InputRevision9;
  type?: Type3;
  stop_index: StopIndex;
  stop: KnownStop;
  [k: string]: unknown;
}
/**
 * Emitted when a leg routing call completes (success or failure).
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "LegReadyEvent".
 */
export interface LegReadyEvent {
  operation_id: OperationId10;
  input_revision: InputRevision10;
  type?: Type4;
  leg_index: LegIndex3;
  leg: Leg;
  completed_legs: CompletedLegs;
  total_legs: TotalLegs1;
  [k: string]: unknown;
}
/**
 * Emitted when a named phase finishes (e.g. 'geocoding', 'routing').
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "PhaseCompleteEvent".
 */
export interface PhaseCompleteEvent {
  operation_id: OperationId11;
  input_revision: InputRevision11;
  type?: Type5;
  phase: Phase1;
  [k: string]: unknown;
}
/**
 * Emitted after each order of the exhaustive experiment finishes.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ExhaustiveProgressEvent".
 */
export interface ExhaustiveProgressEvent {
  operation_id: OperationId12;
  input_revision: InputRevision12;
  type?: Type6;
  evaluated: Evaluated;
  complete: Complete;
  failed: Failed;
  total?: Total;
  [k: string]: unknown;
}
/**
 * Final event in a stream — carries the complete operation outcome.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "TerminalEvent".
 */
export interface TerminalEvent {
  operation_id: OperationId13;
  input_revision: InputRevision13;
  type?: Type7;
  outcome: Outcome;
  [k: string]: unknown;
}
/**
 * Terminal outcome for a plan or comparison operation.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "PlanOutcome".
 */
export interface PlanOutcome {
  outcome_type?: OutcomeType;
  result: Result;
  [k: string]: unknown;
}
/**
 * Terminal outcome for a suffix refresh (D21).
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "RefreshOutcome".
 */
export interface RefreshOutcome {
  outcome_type?: OutcomeType1;
  result: Result1;
  [k: string]: unknown;
}
/**
 * Terminal outcome for a comparison operation.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ComparisonOutcome".
 */
export interface ComparisonOutcome {
  outcome_type?: OutcomeType2;
  result: ComparisonResult;
  [k: string]: unknown;
}
/**
 * Terminal outcome for the exhaustive experiment.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ExhaustiveOutcome".
 */
export interface ExhaustiveOutcome {
  outcome_type?: OutcomeType3;
  result: ExhaustiveResult;
  [k: string]: unknown;
}
/**
 * Terminal outcome when the operation was cancelled.
 *
 * A client that cancels by disconnecting cannot receive this; the server
 * simply stops work. It is delivered when cancellation is observed while
 * the connection can still carry a final event.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "CancelledOutcome".
 */
export interface CancelledOutcome {
  outcome_type?: OutcomeType4;
  reason: Reason;
  [k: string]: unknown;
}
/**
 * Terminal outcome when the 60-second operation deadline expired.
 *
 * ``partial`` carries the valid portion when the deadline expired during
 * routing (a PartialPlan for planning, a RefreshPartial for refresh); it is
 * null when it expired during verification (no routing).
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "TimeoutOutcome".
 */
export interface TimeoutOutcome {
  outcome_type?: OutcomeType5;
  phase: Phase2;
  message: Message3;
  partial?: Partial;
  [k: string]: unknown;
}
/**
 * Terminal outcome for an unrecoverable error.
 *
 * Never exposes raw provider error text — only a structured code, a safe
 * user-facing message and optional structured details.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ErrorOutcome".
 */
export interface ErrorOutcome {
  outcome_type?: OutcomeType6;
  code: Code1;
  message: Message4;
  details?: ErrorDetails | null;
  [k: string]: unknown;
}
/**
 * Structured context for an error outcome. Never raw provider text.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ErrorDetails".
 */
export interface ErrorDetails {
  role?: Role;
  reason?: Reason1;
  place_id?: PlaceId2;
  instance_ids?: InstanceIds;
  moved_place_id?: MovedPlaceId;
  retry_after_seconds?: RetryAfterSeconds;
  [k: string]: unknown;
}
/**
 * ``no_matches`` is a successful search with nothing to choose from.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "SuggestionsResponse".
 */
export interface SuggestionsResponse {
  status: Status3;
  suggestions?: Suggestions;
  [k: string]: unknown;
}
/**
 * One suggestion. Identifying text and the provider ID only.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "SuggestionItem".
 */
export interface SuggestionItem {
  place_id: PlaceId3;
  primary_text: PrimaryText;
  secondary_text?: SecondaryText;
  [k: string]: unknown;
}
/**
 * A verified city selection: trip context for timezone, bias and area checks.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "SelectedCity".
 */
export interface SelectedCity {
  place_id: PlaceId4;
  name: Name2;
  secondary_text?: SecondaryText1;
  lat: Lat1;
  lng: Lng1;
  timezone: Timezone4;
  /**
   * Null when the provider supplied no usable viewport.
   */
  viewport?: ViewportOut | null;
  [k: string]: unknown;
}
/**
 * Provider-suggested map area for a city. Not an administrative boundary.
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "ViewportOut".
 */
export interface ViewportOut {
  low_lat: LowLat;
  low_lng: LowLng;
  high_lat: HighLat;
  high_lng: HighLng;
  [k: string]: unknown;
}
/**
 * A verified stop selection (coordinates for map pin and area/timezone preview).
 *
 * This interface was referenced by `ContractRoot`'s JSON-Schema
 * via the `definition` "SelectedPlace".
 */
export interface SelectedPlace {
  place_id: PlaceId5;
  lat: Lat2;
  lng: Lng2;
  secondary_text?: SecondaryText2;
  timezone?: Timezone5;
  source: Source;
  [k: string]: unknown;
}
