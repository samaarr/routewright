// Mirrors backend/app/models/response.py and request.py exactly.
// Update both files together — there is no codegen yet.

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
  timeline: TimelineItem[];
  overview_map_url: string;
  warnings: PlanWarning[];
}
