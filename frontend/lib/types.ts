// Mirrors backend/app/models/response.py.
// Update both files together — there's no codegen yet.

export type TransportMode = "transit" | "walking" | "driving" | "mixed";
export type LegMode = "transit" | "walking" | "driving";
export type ConflictSeverity = "info" | "warning" | "error";

export interface Place {
  place_id: string;
  name: string;
  address?: string | null;
  lat: number;
  lng: number;
  opening_hours?: string[] | null;
}

export interface Stop {
  place_id: string;
  arrive_at: string; // ISO 8601
  depart_at: string;
  stay_minutes: number;
}

export interface Leg {
  from_place_id: string;
  to_place_id: string;
  mode: LegMode;
  duration_seconds: number;
  distance_meters?: number | null;
  depart_at: string;
  arrive_at: string;
  map_url: string;
}

export interface Conflict {
  severity: ConflictSeverity;
  place_id?: string | null;
  message: string;
}

export interface Plan {
  plan_id: string;
  generated_at: string;
  mode: TransportMode;
  overview_map_url: string;
  overview_map_urls_overflow: string[];
  places: Place[];
  stops: Stop[];
  legs: Leg[];
  conflicts: Conflict[];
  notes: string[];
}

export interface GenerateRequest {
  text: string;
  start_time: string;
  mode?: TransportMode;
  city_hint?: string;
}

export interface RecalculateRequest {
  plan_id: string;
  start_time: string;
  mode?: TransportMode;
  ordered_stops: { place_id: string; stay_minutes: number }[];
}
