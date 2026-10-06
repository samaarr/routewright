// Runtime validation for v2 API payloads.
//
// Generated TypeScript (api-types.ts) describes what the backend promises; it
// does not check what actually arrives. Every streamed event and JSON body is
// validated here and rebuilt into a typed object. Anything malformed, of the
// wrong shape, or with an unknown discriminator throws ValidationError and
// the caller treats the operation as incomplete — never as success.
//
// Only type imports cross module boundaries so this file runs unchanged under
// Node's TypeScript stripping in unit tests.

import type {
  ErrorDetails,
  FailedLeg,
  HoursDetail,
  KnownStop,
  PlannedLeg,
  UnknownStop,
  Warning,
} from "../api-types";

export class ValidationError extends Error {
  constructor(path: string, problem: string) {
    super(`${path}: ${problem}`);
    this.name = "ValidationError";
  }
}

// ---- Narrowed shapes (discriminators always present) -------------------------

export type PhaseName = "verification" | "routing";
export type VKnownStop = KnownStop & { item_type: "stop" };
export type VPlannedLeg = PlannedLeg & { item_type: "leg" };
export type VFailedLeg = FailedLeg & { item_type: "failed_leg" };
export type VUnknownStop = UnknownStop & { item_type: "unknown_stop" };
export type VTimelineItem = VKnownStop | VPlannedLeg | VFailedLeg | VUnknownStop;

interface PlanCommon {
  operation_id: string;
  input_revision: number;
  city: string;
  mode: "transit" | "walking" | "driving";
  timezone: string;
  timeline: VTimelineItem[];
  overview_map_url: string;
  warnings: Warning[];
}
export type VCompletePlan = PlanCommon & { result_type: "complete" };
export type VPartialPlan = PlanCommon & {
  result_type: "partial";
  failed_at_leg_index: number;
  failure_reason: string;
};
export type VPlanResult = VCompletePlan | VPartialPlan;

export type VOutcome =
  | { outcome_type: "plan"; result: VPlanResult }
  | { outcome_type: "timeout"; phase: PhaseName; message: string; partial: VPartialPlan | null }
  | { outcome_type: "error"; code: string; message: string; details: ErrorDetails | null }
  | { outcome_type: "cancelled"; reason: string };

interface EventBase {
  operation_id: string;
  input_revision: number;
}
export type VStreamEvent =
  | (EventBase & { type: "operation_start"; phases: PhaseName[] })
  | (EventBase & { type: "phase_start"; phase: PhaseName })
  | (EventBase & { type: "phase_complete"; phase: PhaseName })
  | (EventBase & { type: "leg_progress"; leg_index: number; total_legs: number })
  | (EventBase & { type: "stop_ready"; stop_index: number; stop: VKnownStop })
  | (EventBase & {
      type: "leg_ready";
      leg_index: number;
      leg: VPlannedLeg | VFailedLeg;
      completed_legs: number;
      total_legs: number;
    })
  | (EventBase & { type: "terminal"; outcome: VOutcome });

export interface VSuggestion {
  place_id: string;
  primary_text: string;
  secondary_text: string | null;
}
export interface VSuggestions {
  status: "ok" | "no_matches";
  suggestions: VSuggestion[];
}
export interface VViewport {
  low_lat: number;
  low_lng: number;
  high_lat: number;
  high_lng: number;
}
export interface VSelectedCity {
  place_id: string;
  name: string;
  secondary_text: string | null;
  lat: number;
  lng: number;
  timezone: string;
  viewport: VViewport | null;
}
export interface VSelectedPlace {
  place_id: string;
  lat: number;
  lng: number;
  secondary_text: string | null;
  timezone: string | null;
}

// ---- Primitive readers ---------------------------------------------------------

type Obj = Record<string, unknown>;
const MAX_STRING = 2000;

function obj(v: unknown, path: string): Obj {
  if (typeof v !== "object" || v === null || Array.isArray(v)) {
    throw new ValidationError(path, "expected object");
  }
  return v as Obj;
}

function str(o: Obj, key: string, path: string): string {
  const v = o[key];
  if (typeof v !== "string" || v.length > MAX_STRING) {
    throw new ValidationError(`${path}.${key}`, "expected string");
  }
  return v;
}

function optStr(o: Obj, key: string, path: string): string | null {
  const v = o[key];
  if (v === undefined || v === null) return null;
  return str(o, key, path);
}

function num(o: Obj, key: string, path: string, min = -Infinity, max = Infinity): number {
  const v = o[key];
  if (typeof v !== "number" || !Number.isFinite(v) || v < min || v > max) {
    throw new ValidationError(`${path}.${key}`, "expected finite number in range");
  }
  return v;
}

function int(o: Obj, key: string, path: string, min = 0, max = 10_000_000): number {
  const v = num(o, key, path, min, max);
  if (!Number.isInteger(v)) throw new ValidationError(`${path}.${key}`, "expected integer");
  return v;
}

function optNum(o: Obj, key: string, path: string): number | null {
  const v = o[key];
  return v === undefined || v === null ? null : num(o, key, path);
}

function bool(o: Obj, key: string, path: string, fallback: boolean): boolean {
  const v = o[key];
  if (v === undefined) return fallback;
  if (typeof v !== "boolean") throw new ValidationError(`${path}.${key}`, "expected boolean");
  return v;
}

function oneOf<T extends string>(o: Obj, key: string, path: string, allowed: readonly T[]): T {
  const v = o[key];
  if (typeof v !== "string" || !(allowed as readonly string[]).includes(v)) {
    throw new ValidationError(`${path}.${key}`, `expected one of ${allowed.join(", ")}`);
  }
  return v as T;
}

function arr(o: Obj, key: string, path: string, max = 500): unknown[] {
  const v = o[key];
  if (!Array.isArray(v) || v.length > max) {
    throw new ValidationError(`${path}.${key}`, "expected bounded array");
  }
  return v;
}

function isoTime(o: Obj, key: string, path: string): string {
  const v = str(o, key, path);
  if (Number.isNaN(Date.parse(v))) throw new ValidationError(`${path}.${key}`, "invalid datetime");
  return v;
}

// ---- Domain validators ---------------------------------------------------------

const MODES = ["transit", "walking", "driving"] as const;
const PHASES = ["verification", "routing"] as const;
const HOURS_STATUSES = [
  "open",
  "closed_on_arrival",
  "closes_during_visit",
  "closes_soon",
  "unknown",
] as const;

function hoursDetail(v: unknown, path: string): HoursDetail | null {
  if (v === undefined || v === null) return null;
  const o = obj(v, path);
  const source = o.hours_source;
  if (source !== undefined && source !== null && source !== "weekly" && source !== "date_specific") {
    throw new ValidationError(`${path}.hours_source`, "unexpected value");
  }
  const reason = o.unknown_reason;
  if (
    reason !== undefined &&
    reason !== null &&
    !["missing", "malformed", "outside_coverage"].includes(reason as string)
  ) {
    throw new ValidationError(`${path}.unknown_reason`, "unexpected value");
  }
  return {
    closes_at: optStr(o, "closes_at", path),
    opens_at: optStr(o, "opens_at", path),
    opens_on: optStr(o, "opens_on", path),
    hours_source: (source ?? null) as HoursDetail["hours_source"],
    always_open: bool(o, "always_open", path, false),
    exceptions_unconfirmed: bool(o, "exceptions_unconfirmed", path, false),
    coverage_start: optStr(o, "coverage_start", path),
    coverage_end: optStr(o, "coverage_end", path),
    special_day: bool(o, "special_day", path, false),
    unknown_reason: (reason ?? null) as HoursDetail["unknown_reason"],
  };
}

export function knownStop(v: unknown, path = "stop"): VKnownStop {
  const o = obj(v, path);
  if (o.item_type !== "stop") throw new ValidationError(`${path}.item_type`, "expected stop");
  return {
    item_type: "stop",
    instance_id: str(o, "instance_id", path),
    place_id: str(o, "place_id", path),
    name: str(o, "name", path),
    address: optStr(o, "address", path),
    lat: num(o, "lat", path, -90, 90),
    lng: num(o, "lng", path, -180, 180),
    arrive_at: isoTime(o, "arrive_at", path),
    depart_at: isoTime(o, "depart_at", path),
    stay_minutes: int(o, "stay_minutes", path, 0, 24 * 60),
    stay_source: oneOf(o, "stay_source", path, ["user", "default"] as const),
    map_url: str(o, "map_url", path),
    hours_status: o.hours_status === undefined ? "unknown" : oneOf(o, "hours_status", path, HOURS_STATUSES),
    hours_detail: hoursDetail(o.hours_detail, `${path}.hours_detail`),
  };
}

function plannedLeg(o: Obj, path: string): VPlannedLeg {
  return {
    item_type: "leg",
    from_stop_id: str(o, "from_stop_id", path),
    to_stop_id: str(o, "to_stop_id", path),
    from_name: str(o, "from_name", path),
    to_name: str(o, "to_name", path),
    mode: oneOf(o, "mode", path, MODES),
    duration_seconds: int(o, "duration_seconds", path, 0, 7 * 86400),
    distance_meters: optNum(o, "distance_meters", path),
    depart_at: isoTime(o, "depart_at", path),
    arrive_at: isoTime(o, "arrive_at", path),
    summary: str(o, "summary", path),
    map_url: str(o, "map_url", path),
  };
}

function failedLeg(o: Obj, path: string): VFailedLeg {
  return {
    item_type: "failed_leg",
    from_stop_id: str(o, "from_stop_id", path),
    to_stop_id: str(o, "to_stop_id", path),
    from_name: str(o, "from_name", path),
    to_name: str(o, "to_name", path),
    failure_reason: str(o, "failure_reason", path) as VFailedLeg["failure_reason"],
    failure_message: optStr(o, "failure_message", path),
  };
}

function leg(v: unknown, path: string): VPlannedLeg | VFailedLeg {
  const o = obj(v, path);
  if (o.item_type === "leg") return plannedLeg(o, path);
  if (o.item_type === "failed_leg") return failedLeg(o, path);
  throw new ValidationError(`${path}.item_type`, "expected leg or failed_leg");
}

function timelineItem(v: unknown, path: string): VTimelineItem {
  const o = obj(v, path);
  switch (o.item_type) {
    case "stop":
      return knownStop(o, path);
    case "leg":
      return plannedLeg(o, path);
    case "failed_leg":
      return failedLeg(o, path);
    case "unknown_stop":
      return {
        item_type: "unknown_stop",
        instance_id: str(o, "instance_id", path),
        place_id: str(o, "place_id", path),
        name: str(o, "name", path),
      };
    default:
      throw new ValidationError(`${path}.item_type`, "unknown timeline item");
  }
}

function warning(v: unknown, path: string): Warning {
  const o = obj(v, path);
  return {
    severity: oneOf(o, "severity", path, ["info", "warning", "error"] as const),
    message: str(o, "message", path),
    affects_stop_index: optNum(o, "affects_stop_index", path),
    affects_instance_id: optStr(o, "affects_instance_id", path),
    code: optStr(o, "code", path),
  };
}

export function planResult(v: unknown, path = "result"): VPlanResult {
  const o = obj(v, path);
  const timeline = arr(o, "timeline", path, 60).map((x, i) => timelineItem(x, `${path}.timeline[${i}]`));
  const common: PlanCommon = {
    operation_id: str(o, "operation_id", path),
    input_revision: int(o, "input_revision", path),
    city: str(o, "city", path),
    mode: oneOf(o, "mode", path, MODES),
    timezone: str(o, "timezone", path),
    timeline,
    overview_map_url: str(o, "overview_map_url", path),
    warnings: o.warnings === undefined ? [] : arr(o, "warnings", path, 100).map((x, i) => warning(x, `${path}.warnings[${i}]`)),
  };
  if (o.result_type === "complete") {
    if (timeline.some((i) => i.item_type === "failed_leg" || i.item_type === "unknown_stop")) {
      throw new ValidationError(path, "complete plan contains unknown items");
    }
    return { ...common, result_type: "complete" };
  }
  if (o.result_type === "partial") {
    return {
      ...common,
      result_type: "partial",
      failed_at_leg_index: int(o, "failed_at_leg_index", path),
      failure_reason: str(o, "failure_reason", path),
    };
  }
  throw new ValidationError(`${path}.result_type`, "expected complete or partial");
}

function errorDetails(v: unknown, path: string): ErrorDetails | null {
  if (v === undefined || v === null) return null;
  const o = obj(v, path);
  const ids = o.instance_ids;
  if (ids !== undefined && ids !== null && (!Array.isArray(ids) || ids.some((x) => typeof x !== "string"))) {
    throw new ValidationError(`${path}.instance_ids`, "expected string array");
  }
  return {
    role: (o.role === "city" || o.role === "stop" ? o.role : null) as ErrorDetails["role"],
    reason: optStr(o, "reason", path),
    place_id: optStr(o, "place_id", path),
    instance_ids: (ids as string[] | undefined) ?? null,
    moved_place_id: optStr(o, "moved_place_id", path),
    retry_after_seconds: optNum(o, "retry_after_seconds", path),
  };
}

function outcome(v: unknown, path: string): VOutcome {
  const o = obj(v, path);
  switch (o.outcome_type) {
    case "plan":
      return { outcome_type: "plan", result: planResult(o.result, `${path}.result`) };
    case "timeout": {
      const partial = o.partial === undefined || o.partial === null ? null : planResult(o.partial, `${path}.partial`);
      if (partial !== null && partial.result_type !== "partial") {
        throw new ValidationError(`${path}.partial`, "expected partial plan");
      }
      return {
        outcome_type: "timeout",
        phase: oneOf(o, "phase", path, PHASES),
        message: str(o, "message", path),
        partial,
      };
    }
    case "error":
      return {
        outcome_type: "error",
        code: str(o, "code", path),
        message: str(o, "message", path),
        details: errorDetails(o.details, `${path}.details`),
      };
    case "cancelled":
      return { outcome_type: "cancelled", reason: str(o, "reason", path) };
    default:
      // RefreshOutcome and anything unknown are not valid for a plan stream.
      throw new ValidationError(`${path}.outcome_type`, "unexpected outcome for planning");
  }
}

export function streamEvent(v: unknown, path = "event"): VStreamEvent {
  const o = obj(v, path);
  const base: EventBase = {
    operation_id: str(o, "operation_id", path),
    input_revision: int(o, "input_revision", path),
  };
  switch (o.type) {
    case "operation_start":
      return {
        ...base,
        type: "operation_start",
        phases: arr(o, "phases", path, 5).map((p, i) => oneOf({ p }, "p", `${path}.phases[${i}]`, PHASES)),
      };
    case "phase_start":
      return { ...base, type: "phase_start", phase: oneOf(o, "phase", path, PHASES) };
    case "phase_complete":
      return { ...base, type: "phase_complete", phase: oneOf(o, "phase", path, PHASES) };
    case "leg_progress":
      return {
        ...base,
        type: "leg_progress",
        leg_index: int(o, "leg_index", path, 0, 100),
        total_legs: int(o, "total_legs", path, 0, 100),
      };
    case "stop_ready":
      return {
        ...base,
        type: "stop_ready",
        stop_index: int(o, "stop_index", path, 0, 100),
        stop: knownStop(o.stop, `${path}.stop`),
      };
    case "leg_ready": {
      const completed = int(o, "completed_legs", path, 0, 100);
      const total = int(o, "total_legs", path, 0, 100);
      if (completed > total) throw new ValidationError(path, "completed_legs exceeds total_legs");
      return {
        ...base,
        type: "leg_ready",
        leg_index: int(o, "leg_index", path, 0, 100),
        leg: leg(o.leg, `${path}.leg`),
        completed_legs: completed,
        total_legs: total,
      };
    }
    case "terminal":
      return { ...base, type: "terminal", outcome: outcome(o.outcome, `${path}.outcome`) };
    default:
      throw new ValidationError(`${path}.type`, "unknown event type");
  }
}

export function suggestions(v: unknown): VSuggestions {
  const o = obj(v, "suggestions");
  const status = oneOf(o, "status", "suggestions", ["ok", "no_matches"] as const);
  const items = (o.suggestions === undefined ? [] : arr(o, "suggestions", "suggestions", 10)).map((x, i) => {
    const s = obj(x, `suggestions[${i}]`);
    return {
      place_id: str(s, "place_id", `suggestions[${i}]`),
      primary_text: str(s, "primary_text", `suggestions[${i}]`),
      secondary_text: optStr(s, "secondary_text", `suggestions[${i}]`),
    };
  });
  if (status === "no_matches" && items.length) throw new ValidationError("suggestions", "inconsistent status");
  return { status, suggestions: items };
}

function viewport(v: unknown, path: string): VViewport | null {
  if (v === undefined || v === null) return null;
  const o = obj(v, path);
  const vp = {
    low_lat: num(o, "low_lat", path, -90, 90),
    low_lng: num(o, "low_lng", path, -180, 180),
    high_lat: num(o, "high_lat", path, -90, 90),
    high_lng: num(o, "high_lng", path, -180, 180),
  };
  if (vp.low_lat > vp.high_lat) throw new ValidationError(path, "inverted latitudes");
  return vp;
}

export function selectedCity(v: unknown): VSelectedCity {
  const o = obj(v, "city");
  return {
    place_id: str(o, "place_id", "city"),
    name: str(o, "name", "city"),
    secondary_text: optStr(o, "secondary_text", "city"),
    lat: num(o, "lat", "city", -90, 90),
    lng: num(o, "lng", "city", -180, 180),
    timezone: str(o, "timezone", "city"),
    viewport: viewport(o.viewport, "city.viewport"),
  };
}

export function selectedPlace(v: unknown): VSelectedPlace {
  const o = obj(v, "place");
  return {
    place_id: str(o, "place_id", "place"),
    lat: num(o, "lat", "place", -90, 90),
    lng: num(o, "lng", "place", -180, 180),
    secondary_text: optStr(o, "secondary_text", "place"),
    timezone: optStr(o, "timezone", "place"),
  };
}
