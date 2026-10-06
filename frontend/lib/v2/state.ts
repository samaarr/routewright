// Planner state: one reducer for draft inputs, the active operation, progress
// and results (Step 6; D6-D7, D12, D16-D18, D22, D27-D30).
//
// Invariants:
// - Every input edit bumps `revision`. Edits never start routing; only the
//   explicit `planStarted` action does (D30).
// - An edit while an operation runs stops it (the component aborts the
//   request when `operation` leaves "running") and keeps any previous result,
//   which is then shown as belonging to earlier inputs (stale) (D12, D27).
// - Stream events/outcomes are applied only when their operation ID matches
//   the running operation AND their input_revision matches the revision it
//   started with. Anything else — late events after an edit, a cancelled or
//   superseded operation — is ignored.
// - Progress is completed-leg counts and phase names from real events; no
//   percentages or countdowns.

import { areaStatus, type AreaStatus } from "./area.ts";
import type { StreamEnd } from "./ndjson.ts";
import { checkDeparture, type DepartureCheck } from "./time.ts";
import type {
  PhaseName,
  VFailedLeg,
  VKnownStop,
  VPlanResult,
  VPlannedLeg,
  VSelectedCity,
  VSelectedPlace,
  VStreamEvent,
} from "./validate.ts";
import type { PlanStreamRequest } from "./client.ts";

export const MAX_STOPS = 12;
export const MAX_STAY_MINUTES = 720;

export type Mode = "transit" | "walking" | "driving";

export interface SelectedStop extends VSelectedPlace {
  label: string; // the suggestion text the user chose (provider name confirmed at plan time)
}

export interface StopDraft {
  id: string; // stable stop-instance ID (D11, D13)
  query: string;
  selected: SelectedStop | null;
  stayMinutes: number | null; // null = place-type default; 0 is an explicit choice
}

export interface Draft {
  cityQuery: string;
  city: VSelectedCity | null;
  stops: StopDraft[];
  date: string; // YYYY-MM-DD, destination-local
  time: string; // HH:MM, destination-local
  occurrence: 1 | 2 | null;
  mode: Mode;
  pinFirst: boolean; // D16: endpoints pinned by default (used by optimisation, Step 8)
  pinLast: boolean;
}

export type Operation =
  | { kind: "idle" }
  | {
      kind: "running";
      operationId: string;
      revision: number;
      phase: PhaseName | null;
      completedLegs: number;
      totalLegs: number | null;
      stops: VKnownStop[];
      legs: (VPlannedLeg | VFailedLeg)[];
    };

export type Notice =
  | null
  | { kind: "error"; code: string; message: string; instanceIds: string[]; role: string | null }
  | { kind: "timeout"; message: string }
  | { kind: "cancelled"; message: string }
  | { kind: "incomplete"; message: string };

export interface PlannerState {
  draft: Draft;
  revision: number;
  operation: Operation;
  result: { plan: VPlanResult; revision: number } | null;
  notice: Notice;
}

export type Action =
  | { type: "cityQuery"; query: string }
  | { type: "citySelected"; city: VSelectedCity; query: string }
  | { type: "stopQuery"; id: string; query: string }
  | { type: "stopSelected"; id: string; place: VSelectedPlace; label: string }
  | { type: "stopAdded"; id: string }
  | { type: "stopRemoved"; id: string }
  | { type: "stopsReordered"; ids: string[] }
  | { type: "stayChanged"; id: string; minutes: number | null }
  | { type: "dateChanged"; date: string }
  | { type: "timeChanged"; time: string }
  | { type: "occurrenceChanged"; occurrence: 1 | 2 | null }
  | { type: "modeChanged"; mode: Mode }
  | { type: "pinToggled"; end: "first" | "last" }
  | { type: "planStarted"; operationId: string }
  | { type: "streamEvent"; operationId: string; event: VStreamEvent }
  | { type: "streamEnded"; operationId: string; end: StreamEnd }
  | { type: "planFailed"; operationId: string; code: string; message: string; instanceIds?: string[]; role?: string | null }
  | { type: "cancelRequested" };

export function initialState(ids: [string, string]): PlannerState {
  return {
    draft: {
      cityQuery: "",
      city: null,
      stops: ids.map((id) => ({ id, query: "", selected: null, stayMinutes: null })),
      date: "",
      time: "",
      occurrence: null,
      mode: "transit",
      pinFirst: true,
      pinLast: true,
    },
    revision: 0,
    operation: { kind: "idle" },
    result: null,
    notice: null,
  };
}

const STOPPED_BY_EDIT = "Planning stopped because the trip details changed. Press Plan when ready.";
const CANCELLED = "Planning cancelled. Calls already sent to Google still count toward today's allowance.";

function edited(state: PlannerState, draft: Draft): PlannerState {
  const wasRunning = state.operation.kind === "running";
  return {
    ...state,
    draft,
    revision: state.revision + 1,
    operation: { kind: "idle" },
    notice: wasRunning ? { kind: "cancelled", message: STOPPED_BY_EDIT } : state.notice?.kind === "error" ? null : state.notice,
  };
}

function updateStop(draft: Draft, id: string, fn: (s: StopDraft) => StopDraft): Draft {
  return { ...draft, stops: draft.stops.map((s) => (s.id === id ? fn(s) : s)) };
}

function isCurrentOp(state: PlannerState, operationId: string): state is PlannerState & {
  operation: Extract<Operation, { kind: "running" }>;
} {
  return state.operation.kind === "running" && state.operation.operationId === operationId;
}

export function reducer(state: PlannerState, action: Action): PlannerState {
  const d = state.draft;
  switch (action.type) {
    case "cityQuery":
      if (action.query === d.cityQuery) return state;
      // Editing the city text invalidates the selected city (D26).
      return edited(state, { ...d, cityQuery: action.query, city: null, occurrence: null });
    case "citySelected": {
      const zoneChanged = d.city?.timezone !== action.city.timezone;
      // Stops, durations and the local clock are preserved (D27, D28); a new
      // zone resets the repeated-time choice (D29).
      return edited(state, {
        ...d,
        cityQuery: action.query,
        city: action.city,
        occurrence: zoneChanged ? null : d.occurrence,
      });
    }
    case "stopQuery":
      return edited(
        state,
        updateStop(d, action.id, (s) =>
          s.query === action.query ? s : { ...s, query: action.query, selected: null },
        ),
      );
    case "stopSelected":
      return edited(
        state,
        updateStop(d, action.id, (s) => ({
          ...s,
          query: action.label,
          selected: { ...action.place, label: action.label },
        })),
      );
    case "stopAdded":
      if (d.stops.length >= MAX_STOPS) return state;
      return edited(state, {
        ...d,
        stops: [...d.stops, { id: action.id, query: "", selected: null, stayMinutes: null }],
      });
    case "stopRemoved":
      if (d.stops.length <= 2) return state;
      return edited(state, { ...d, stops: d.stops.filter((s) => s.id !== action.id) });
    case "stopsReordered": {
      const byId = new Map(d.stops.map((s) => [s.id, s]));
      if (action.ids.length !== d.stops.length || action.ids.some((id) => !byId.has(id))) return state;
      // Durations travel with their stop instance; no positional re-defaulting.
      return edited(state, { ...d, stops: action.ids.map((id) => byId.get(id)!) });
    }
    case "stayChanged": {
      const m = action.minutes;
      if (m !== null && (!Number.isInteger(m) || m < 0 || m > MAX_STAY_MINUTES)) return state;
      return edited(state, updateStop(d, action.id, (s) => ({ ...s, stayMinutes: m })));
    }
    case "dateChanged":
      return edited(state, { ...d, date: action.date, occurrence: null });
    case "timeChanged":
      return edited(state, { ...d, time: action.time, occurrence: null });
    case "occurrenceChanged":
      return edited(state, { ...d, occurrence: action.occurrence });
    case "modeChanged":
      return edited(state, { ...d, mode: action.mode });
    case "pinToggled":
      // Pins only constrain optimisation (D17); they are not plan inputs, so
      // they do not invalidate a plan or stop an operation.
      return {
        ...state,
        draft: action.end === "first" ? { ...d, pinFirst: !d.pinFirst } : { ...d, pinLast: !d.pinLast },
      };

    case "planStarted":
      if (state.operation.kind === "running" || !readiness(state).ready) return state;
      return {
        ...state,
        notice: null,
        operation: {
          kind: "running",
          operationId: action.operationId,
          revision: state.revision,
          phase: null,
          completedLegs: 0,
          totalLegs: null,
          stops: [],
          legs: [],
        },
      };
    case "streamEvent": {
      if (!isCurrentOp(state, action.operationId)) return state;
      const op = state.operation;
      const e = action.event;
      if (e.operation_id !== op.operationId || e.input_revision !== op.revision) return state;
      switch (e.type) {
        case "phase_start":
          return { ...state, operation: { ...op, phase: e.phase } };
        case "leg_progress":
          return { ...state, operation: { ...op, totalLegs: e.total_legs } };
        case "stop_ready":
          return { ...state, operation: { ...op, stops: [...op.stops, e.stop] } };
        case "leg_ready":
          return {
            ...state,
            operation: { ...op, legs: [...op.legs, e.leg], completedLegs: e.completed_legs, totalLegs: e.total_legs },
          };
        default:
          return state;
      }
    }
    case "streamEnded": {
      if (!isCurrentOp(state, action.operationId)) return state;
      const op = state.operation;
      const end = action.end;
      const idle = { ...state, operation: { kind: "idle" } as const };
      if (end.kind === "aborted") return { ...idle, notice: { kind: "cancelled", message: CANCELLED } };
      if (end.kind === "incomplete") {
        return {
          ...idle,
          notice: {
            kind: "incomplete",
            message:
              "The connection ended before planning finished, so this plan is incomplete. Press Plan to try again.",
          },
        };
      }
      const ev = end.event;
      if (ev.operation_id !== op.operationId || ev.input_revision !== op.revision) return state;
      const outcome = ev.outcome;
      switch (outcome.outcome_type) {
        case "plan":
          return { ...idle, notice: null, result: { plan: outcome.result, revision: op.revision } };
        case "timeout":
          return {
            ...idle,
            notice: { kind: "timeout", message: outcome.message },
            result: outcome.partial ? { plan: outcome.partial, revision: op.revision } : state.result,
          };
        case "error":
          return {
            ...idle,
            notice: {
              kind: "error",
              code: outcome.code,
              message: outcome.message,
              instanceIds: outcome.details?.instance_ids ?? [],
              role: outcome.details?.role ?? null,
            },
          };
        case "cancelled":
          return { ...idle, notice: { kind: "cancelled", message: CANCELLED } };
      }
      return state;
    }
    case "planFailed":
      if (!isCurrentOp(state, action.operationId)) return state;
      return {
        ...state,
        operation: { kind: "idle" },
        notice: {
          kind: "error",
          code: action.code,
          message: action.message,
          instanceIds: action.instanceIds ?? [],
          role: action.role ?? null,
        },
      };
    case "cancelRequested":
      if (state.operation.kind !== "running") return state;
      return { ...state, operation: { kind: "idle" }, notice: { kind: "cancelled", message: CANCELLED } };
  }
}

// ---- Derived values ---------------------------------------------------------

export interface StopCheck {
  id: string;
  area: AreaStatus | null; // null until selected
  timezoneProblem: "unresolved" | "different" | null;
}

export function stopChecks(draft: Draft): StopCheck[] {
  return draft.stops.map((s) => {
    if (!s.selected) return { id: s.id, area: null, timezoneProblem: null };
    const area = draft.city ? areaStatus(draft.city.viewport, s.selected.lat, s.selected.lng) : null;
    let timezoneProblem: StopCheck["timezoneProblem"] = null;
    if (s.selected.timezone === null) timezoneProblem = "unresolved";
    else if (draft.city && s.selected.timezone !== draft.city.timezone) timezoneProblem = "different";
    return { id: s.id, area, timezoneProblem };
  });
}

export function departureCheck(draft: Draft): DepartureCheck {
  return checkDeparture(draft.date, draft.time, draft.city?.timezone ?? null);
}

export type Readiness = { ready: true; request: Omit<PlanStreamRequest, "operation_id" | "input_revision"> } | { ready: false; reasons: string[] };

export function readiness(state: PlannerState): Readiness {
  const d = state.draft;
  const reasons: string[] = [];
  if (!d.city) reasons.push("Choose a city from the suggestions.");
  if (d.stops.some((s) => !s.selected)) reasons.push("Choose each stop from the suggestions.");
  for (const c of stopChecks(d)) {
    if (c.timezoneProblem === "different") {
      reasons.push("Every stop must be in the selected city's timezone.");
      break;
    }
    if (c.timezoneProblem === "unresolved") {
      reasons.push("A stop's timezone could not be determined. Choose a different place.");
      break;
    }
  }
  const dep = departureCheck(d);
  if (dep.kind === "incomplete" && d.city) reasons.push("Enter a departure date and time.");
  if (dep.kind === "invalid") reasons.push("Enter a valid departure date and time.");
  if (dep.kind === "nonexistent") reasons.push("That time is skipped by a clock change. Choose another time.");
  if (dep.kind === "ambiguous" && d.occurrence === null) reasons.push("Choose which occurrence of the repeated time you mean.");
  if (reasons.length || !d.city) return { ready: false, reasons };
  const city = d.city;
  return {
    ready: true,
    request: {
      city: { place_id: city.place_id, name: city.name, lat: city.lat, lng: city.lng },
      stops: d.stops.map((s) => ({
        instance_id: s.id,
        selection: { place_id: s.selected!.place_id, name: s.selected!.label, lat: s.selected!.lat, lng: s.selected!.lng },
        ...(s.stayMinutes !== null ? { stay_minutes: s.stayMinutes } : {}),
      })),
      departure: {
        local_date: d.date,
        local_time: d.time,
        timezone: city.timezone,
        ...(dep.kind === "ambiguous" && d.occurrence ? { occurrence: d.occurrence } : {}),
      },
      mode: d.mode,
    },
  };
}

export function resultIsStale(state: PlannerState): boolean {
  return state.result !== null && state.result.revision !== state.revision;
}

export function progressLabel(op: Operation): string | null {
  if (op.kind !== "running") return null;
  if (op.phase === null || op.phase === "verification") return "Checking your places…";
  if (op.totalLegs === null) return "Planning journeys…";
  return `Planned ${op.completedLegs} of ${op.totalLegs} journeys…`;
}
