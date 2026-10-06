// API types are generated from the backend schema into api-types.ts.
// Run `npm run gen:types` to regenerate after backend model changes.
//
// This file re-exports the generated types alongside frontend-only types
// that are not part of the wire contract. Existing v1 components continue
// to import from this file; new engine code imports from api-types.ts directly.

export type TransportMode = "transit" | "walking" | "driving";
export type StaySource = "user" | "default";
export type WarningSeverity = "info" | "warning" | "error";

// ---- Request ---------------------------------------------------------

export interface StopInput {
  query: string;
  stay_minutes?: number;
}

export interface PlanRequest {
  city: string;
  stops: StopInput[];
  start_time: string; // ISO 8601, timezone-aware
  mode: TransportMode;
  timezone: string;   // IANA zone for the trip city, e.g. "Europe/London"
  fixed_first?: boolean;
  fixed_last?: boolean;
}

export interface InfeasibilityFlag {
  stop_index: number;
  stop_name: string;
  issue: "closed_on_arrival" | "closes_during_visit";
}

export interface OptimisedStop {
  query: string;
  name: string;
  stay_minutes: number | null;
}

export interface OptimiseResponse {
  stops: OptimisedStop[];
  original_km: number;
  optimised_km: number;
  infeasibility_flags: InfeasibilityFlag[];
}

// Frontend-only: StopInput extended with a stable client-generated UUID.
// The id is stripped before any network call. Never derived from user
// input so two stops with identical query strings stay distinguishable
// by React and dnd-kit. See the duplicate-drag bug fix for history.
export interface StopDraft extends StopInput {
  id: string;
}

// Form state that flows through PlanForm / StopList. Uses StopDraft so
// the id is threaded all the way to the sortable list without touching
// the backend contract.
export interface FormState {
  city: string;
  stops: StopDraft[];
  start_time: string;
  mode: TransportMode;
}

// ---- Response --------------------------------------------------------

// Status of a stop's opening hours relative to its planned arrival/departure.
// "unknown" means no hours data — never displayed as "closed".
export type HoursStatus =
  | "open"
  | "closed_on_arrival"
  | "closes_during_visit"
  | "closes_soon"
  | "unknown";

// Machine-readable time facts for a stop's hours status.
// Times are HH:MM in the trip-city's local timezone.
// Timezone assumption: client submits start_time in the city's local timezone;
// all derived datetimes share it. Per-venue timezone lookup is not performed.
export interface HoursDetail {
  closes_at: string | null; // e.g. "17:00"
  opens_at: string | null;  // e.g. "14:00"
}

export interface StopItem {
  item_type: "stop";
  query: string;
  name: string;
  address: string | null;
  lat: number;
  lng: number;
  arrive_at: string; // ISO 8601
  depart_at: string;
  stay_minutes: number;
  stay_source: StaySource;
  map_url: string;
  hours_status: HoursStatus;
  hours_detail: HoursDetail | null;
}

export interface LegItem {
  item_type: "leg";
  from_name: string;
  to_name: string;
  mode: TransportMode;
  duration_seconds: number;
  distance_meters: number | null;
  depart_at: string;
  arrive_at: string;
  summary: string; // verbatim from Routes API, e.g. "Take the 47, 18 min"
  map_url: string;
}

export interface PlanWarning {
  severity: WarningSeverity;
  message: string;
  affects_stop_index: number | null;
}

export type TimelineItem = StopItem | LegItem;

export interface Plan {
  generated_at: string;
  city: string;
  mode: TransportMode;
  timezone: string; // IANA zone derived from the first stop's coordinates, e.g. "Europe/London"
  timeline: TimelineItem[];
  overview_map_url: string;
  warnings: PlanWarning[];
}

// ---- New engine types (generated from backend schema) -----------------
// Import these directly from api-types.ts in new code; they are re-exported
// here so a single import covers both legacy and new types when convenient.

export type {
  KnownStop,
  PlannedLeg,
  FailedLeg,
  UnknownStop,
  CompletePlan,
  PartialPlan,
  PlanOutcome,
  RefreshOutcome,
  CancelledOutcome,
  ErrorOutcome,
  OperationStartEvent,
  LegProgressEvent,
  StopReadyEvent,
  LegReadyEvent,
  PhaseCompleteEvent,
  TerminalEvent,
} from "./api-types";
