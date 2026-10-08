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
import { mergeRefresh, refreshTarget, type RefreshTarget } from "./refresh.ts";
import { checkDeparture, type DepartureCheck } from "./time.ts";
import type {
  PhaseName,
  VFailedLeg,
  VKnownStop,
  VPlanResult,
  VPlannedLeg,
  VSelectedCity,
  VComparisonResult,
  VExhaustiveResult,
  VSelectedPlace,
  VStreamEvent,
} from "./validate.ts";
import type { ExhaustiveStreamRequest, PlanStreamRequest, RefreshStreamRequest } from "./client.ts";

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
      // "refresh" recomputes the suffix of the current plan from leg k (D21);
      // "compare" checks one alternative order against a fresh original (Step 8).
      // "exhaustive" is the experimental all-24-orders search (2026-10-08).
      purpose: "plan" | "refresh" | "compare" | "exhaustive";
      refresh: RefreshTarget | null;
      operationId: string;
      revision: number;
      phase: PhaseName | null;
      completedLegs: number;
      totalLegs: number | null;
      stops: VKnownStop[];
      legs: (VPlannedLeg | VFailedLeg)[];
      // Exhaustive search only: orders finished so far (from real events).
      orders?: { evaluated: number; complete: number; failed: number; total: number };
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
  // label "recalculated": the plan is the fresh original from a comparison.
  result: { plan: VPlanResult; revision: number; label?: "recalculated" } | null;
  // Latest comparison outcome for the current inputs (cleared by any edit,
  // Plan or Refresh). Only a "recommended" one can be accepted.
  comparison: { result: VComparisonResult; revision: number } | null;
  // Latest exhaustive search for the current inputs (cleared like comparison).
  // The displayed plan never changes until its winner is explicitly accepted.
  exhaustive: { result: VExhaustiveResult; revision: number } | null;
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
  // planStarted / refreshStarted replace any running operation (Step 8 #9).
  | { type: "planStarted"; operationId: string }
  | { type: "refreshStarted"; operationId: string; legIndex: number }
  | { type: "compareStarted"; operationId: string }
  | { type: "comparisonAccepted" }
  | { type: "comparisonDismissed" }
  | { type: "exhaustiveStarted"; operationId: string }
  | { type: "exhaustiveAccepted" }
  | { type: "exhaustiveDismissed" }
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
    comparison: null,
    exhaustive: null,
    notice: null,
  };
}

const STOPPED_BY_EDIT = "Planning stopped because the trip details changed. Press Plan when ready.";
const CANCELLED = "Planning cancelled. Calls already sent to Google still count toward today's allowance.";
export const REFRESH_CANCELLED = "Refresh cancelled — showing previous timings.";
export const REFRESH_INCOMPLETE = "Refresh incomplete — showing previous timings.";
export const COMPARE_CANCELLED = "Comparison cancelled — your plan is unchanged.";
export const COMPARE_INCOMPLETE = "Comparison didn't finish — your plan is unchanged.";
const COMPARE_STOPPED_BY_EDIT = "Comparison stopped because the trip details changed — your plan is unchanged.";
export const EXHAUSTIVE_CANCELLED = "Search cancelled — your plan is unchanged.";
export const EXHAUSTIVE_INCOMPLETE = "The search didn't finish — your plan is unchanged.";
const EXHAUSTIVE_STOPPED_BY_EDIT = "Search stopped because the trip details changed — your plan is unchanged.";
const REFRESH_STOPPED_BY_EDIT =
  "Refresh stopped because the trip details changed — showing previous timings. Press Plan when ready.";

function isRefresh(op: Operation): boolean {
  return op.kind === "running" && op.purpose === "refresh";
}

function edited(state: PlannerState, draft: Draft): PlannerState {
  const op = state.operation;
  const wasRunning = op.kind === "running";
  const message = !wasRunning
    ? STOPPED_BY_EDIT
    : op.purpose === "refresh"
      ? REFRESH_STOPPED_BY_EDIT
      : op.purpose === "compare"
        ? COMPARE_STOPPED_BY_EDIT
        : op.purpose === "exhaustive"
          ? EXHAUSTIVE_STOPPED_BY_EDIT
          : STOPPED_BY_EDIT;
  return {
    ...state,
    draft,
    revision: state.revision + 1,
    operation: { kind: "idle" },
    comparison: null, // input edits invalidate any suggestion
    exhaustive: null,
    notice: wasRunning ? { kind: "cancelled", message } : state.notice?.kind === "error" ? null : state.notice,
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
      // Starting any operation supersedes a running one (its events are then
      // rejected by operation ID; the page aborts its request).
      if (!readiness(state).ready) return state;
      return {
        ...state,
        notice: null,
        comparison: null,
        exhaustive: null,
        operation: {
          kind: "running",
          purpose: "plan",
          refresh: null,
          operationId: action.operationId,
          revision: state.revision,
          phase: null,
          completedLegs: 0,
          totalLegs: null,
          stops: [],
          legs: [],
        },
      };
    case "refreshStarted": {
      const target = refreshableTarget(state, action.legIndex);
      if (!target) return state;
      return {
        ...state,
        notice: null,
        comparison: null,
        exhaustive: null,
        operation: {
          kind: "running",
          purpose: "refresh",
          refresh: target,
          operationId: action.operationId,
          revision: state.revision,
          phase: null,
          completedLegs: 0,
          totalLegs: null,
          stops: [],
          legs: [],
        },
      };
    }
    case "compareStarted":
      if (!canCompare(state)) return state;
      return {
        ...state,
        notice: null,
        comparison: null,
        exhaustive: null,
        operation: {
          kind: "running",
          purpose: "compare",
          refresh: null,
          operationId: action.operationId,
          revision: state.revision,
          phase: null,
          completedLegs: 0,
          totalLegs: null,
          stops: [],
          legs: [],
        },
      };
    case "exhaustiveStarted":
      if (!canRunExhaustive(state)) return state;
      return {
        ...state,
        notice: null,
        comparison: null,
        exhaustive: null,
        operation: {
          kind: "running",
          purpose: "exhaustive",
          refresh: null,
          operationId: action.operationId,
          revision: state.revision,
          phase: null,
          completedLegs: 0,
          totalLegs: null,
          stops: [],
          legs: [],
          orders: { evaluated: 0, complete: 0, failed: 0, total: 24 },
        },
      };
    case "exhaustiveDismissed":
      return state.exhaustive ? { ...state, exhaustive: null } : state;
    case "exhaustiveAccepted":
      return acceptExhaustive(state);
    case "comparisonDismissed":
      return state.comparison ? { ...state, comparison: null } : state;
    case "comparisonAccepted":
      return acceptComparison(state);
    case "streamEvent": {
      if (!isCurrentOp(state, action.operationId)) return state;
      const op = state.operation;
      const e = action.event;
      if (e.operation_id !== op.operationId || e.input_revision !== op.revision) return state;
      switch (e.type) {
        case "phase_start":
          // Counts are per phase (a comparison routes two itineraries).
          return { ...state, operation: { ...op, phase: e.phase, completedLegs: 0, totalLegs: null, stops: [], legs: [] } };
        case "leg_progress":
          return { ...state, operation: { ...op, totalLegs: e.total_legs } };
        case "stop_ready":
          return { ...state, operation: { ...op, stops: [...op.stops, e.stop] } };
        case "leg_ready":
          return {
            ...state,
            operation: { ...op, legs: [...op.legs, e.leg], completedLegs: e.completed_legs, totalLegs: e.total_legs },
          };
        case "exhaustive_progress":
          if (op.purpose !== "exhaustive") return state;
          // Counts only ever grow; a regressing or replayed event is ignored.
          if (op.orders && e.evaluated < op.orders.evaluated) return state;
          return {
            ...state,
            operation: { ...op, orders: { evaluated: e.evaluated, complete: e.complete, failed: e.failed, total: e.total } },
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
      if (op.purpose === "refresh") return endRefresh(state, idle, op.revision, end);
      if (op.purpose === "compare") return endCompare(state, idle, op.revision, end);
      if (op.purpose === "exhaustive") return endExhaustive(state, idle, op.operationId, op.revision, end);
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
            result:
              outcome.partial && outcome.partial.result_type === "partial"
                ? { plan: outcome.partial, revision: op.revision }
                : state.result,
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
        case "refresh":
        case "comparison":
        case "exhaustive":
          return state; // impossible: validated per stream kind
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
      return {
        ...state,
        operation: { kind: "idle" },
        notice: {
          kind: "cancelled",
          message: isRefresh(state.operation)
            ? REFRESH_CANCELLED
            : state.operation.purpose === "compare"
              ? COMPARE_CANCELLED
              : state.operation.purpose === "exhaustive"
                ? EXHAUSTIVE_CANCELLED
                : CANCELLED,
        },
      };
  }
}

/**
 * Outcome of a refresh. The previous plan is kept unless a validated refresh
 * result merges cleanly onto it (prefix unchanged, suffix replaced as a whole).
 */
function endRefresh(
  state: PlannerState,
  idle: PlannerState,
  revision: number,
  end: StreamEnd,
): PlannerState {
  if (end.kind === "aborted") return { ...idle, notice: { kind: "cancelled", message: REFRESH_CANCELLED } };
  if (end.kind === "incomplete") return { ...idle, notice: { kind: "incomplete", message: REFRESH_INCOMPLETE } };
  const outcome = end.event.outcome;
  const base = state.result;
  const merge = (partial: Parameters<typeof mergeRefresh>[1]): PlannerState | null => {
    if (!base) return null;
    try {
      return { ...idle, result: { plan: mergeRefresh(base.plan, partial), revision } };
    } catch {
      return null;
    }
  };
  const incomplete: PlannerState = { ...idle, notice: { kind: "incomplete", message: REFRESH_INCOMPLETE } };
  switch (outcome.outcome_type) {
    case "refresh": {
      const merged = merge(outcome.result);
      return merged ? { ...merged, notice: null } : incomplete;
    }
    case "timeout": {
      if (outcome.partial && outcome.partial.result_type === "refresh_partial") {
        const merged = merge(outcome.partial);
        if (merged) return { ...merged, notice: { kind: "timeout", message: outcome.message } };
      }
      return { ...idle, notice: { kind: "timeout", message: `${outcome.message} Showing previous timings.` } };
    }
    case "error":
      return {
        ...idle,
        notice: {
          kind: "error",
          code: outcome.code,
          message: `${outcome.message} Showing previous timings.`,
          instanceIds: outcome.details?.instance_ids ?? [],
          role: outcome.details?.role ?? null,
        },
      };
    case "cancelled":
      return { ...idle, notice: { kind: "cancelled", message: REFRESH_CANCELLED } };
    case "plan":
    case "comparison":
    case "exhaustive":
      return incomplete; // impossible: validated per stream kind
  }
}

/**
 * Outcome of a comparison. A complete fresh original replaces the displayed
 * plan atomically ("Your order — recalculated."); an incomplete original,
 * cancellation, timeout or error leaves the plan untouched.
 */
function endCompare(state: PlannerState, idle: PlannerState, revision: number, end: StreamEnd): PlannerState {
  if (end.kind === "aborted") return { ...idle, notice: { kind: "cancelled", message: COMPARE_CANCELLED } };
  if (end.kind === "incomplete") return { ...idle, notice: { kind: "incomplete", message: COMPARE_INCOMPLETE } };
  const outcome = end.event.outcome;
  switch (outcome.outcome_type) {
    case "comparison": {
      const r = outcome.result;
      const fresh = r.original && r.original.result_type === "complete" ? r.original : null;
      return {
        ...idle,
        notice: null,
        comparison: { result: r, revision },
        result: fresh ? { plan: fresh, revision, label: "recalculated" } : state.result,
      };
    }
    case "timeout":
      return { ...idle, notice: { kind: "timeout", message: `${outcome.message} Your plan is unchanged.` } };
    case "error":
      return {
        ...idle,
        notice: {
          kind: "error",
          code: outcome.code,
          message: `${outcome.message} Your plan is unchanged.`,
          instanceIds: outcome.details?.instance_ids ?? [],
          role: outcome.details?.role ?? null,
        },
      };
    case "cancelled":
      return { ...idle, notice: { kind: "cancelled", message: COMPARE_CANCELLED } };
    default:
      return { ...idle, notice: { kind: "incomplete", message: COMPARE_INCOMPLETE } };
  }
}

/**
 * Outcome of the exhaustive search. The displayed plan is never replaced here:
 * the result is stored for review, and only an explicit acceptance of a
 * finished search's winner changes the plan. Cancellation, interrupted or
 * malformed streams, timeouts and errors keep the previous plan.
 */
function endExhaustive(
  state: PlannerState,
  idle: PlannerState,
  operationId: string,
  revision: number,
  end: StreamEnd,
): PlannerState {
  if (end.kind === "aborted") return { ...idle, notice: { kind: "cancelled", message: EXHAUSTIVE_CANCELLED } };
  if (end.kind === "incomplete") return { ...idle, notice: { kind: "incomplete", message: EXHAUSTIVE_INCOMPLETE } };
  const ev = end.event;
  if (ev.operation_id !== operationId || ev.input_revision !== revision) return state;
  const outcome = ev.outcome;
  switch (outcome.outcome_type) {
    case "exhaustive":
      if (outcome.result.operation_id !== operationId || outcome.result.input_revision !== revision) {
        return { ...idle, notice: { kind: "incomplete", message: EXHAUSTIVE_INCOMPLETE } };
      }
      return { ...idle, notice: null, exhaustive: { result: outcome.result, revision } };
    case "timeout":
      return { ...idle, notice: { kind: "timeout", message: `${outcome.message} Your plan is unchanged.` } };
    case "error":
      return {
        ...idle,
        notice: {
          kind: "error",
          code: outcome.code,
          message: `${outcome.message} Your plan is unchanged.`,
          instanceIds: outcome.details?.instance_ids ?? [],
          role: outcome.details?.role ?? null,
        },
      };
    case "cancelled":
      return { ...idle, notice: { kind: "cancelled", message: EXHAUSTIVE_CANCELLED } };
    default:
      return { ...idle, notice: { kind: "incomplete", message: EXHAUSTIVE_INCOMPLETE } };
  }
}

/** Instance ID -> resolved stay of the current plan, or null if any is missing. */
function planStays(state: PlannerState): Map<string, number> | null {
  const plan = state.result?.plan;
  if (!plan) return null;
  const stays = new Map<string, number>();
  for (const item of plan.timeline) if (item.item_type === "stop") stays.set(item.instance_id, item.stay_minutes);
  return state.draft.stops.every((s) => stays.has(s.id)) ? stays : null;
}

/**
 * "Test all 24 orders" (experimental) is offered only on a current, complete
 * plan of exactly four distinct destinations whose resolved stays are known.
 */
export function canRunExhaustive(state: PlannerState): boolean {
  const r = state.result;
  const stops = state.draft.stops;
  return (
    r !== null &&
    !resultIsStale(state) &&
    r.plan.result_type === "complete" &&
    stops.length === 4 &&
    new Set(stops.map((s) => s.selected?.place_id)).size === 4 &&
    planStays(state) !== null &&
    readiness(state).ready
  );
}

/** The experiment request: current inputs with every stay made explicit from
 *  the plan's resolved durations (no positional defaulting server-side). */
export function exhaustiveRequest(state: PlannerState): Omit<ExhaustiveStreamRequest, "operation_id" | "input_revision"> | null {
  const ready = readiness(state);
  const stays = planStays(state);
  if (!canRunExhaustive(state) || !ready.ready || !stays) return null;
  return {
    ...ready.request,
    stops: ready.request.stops.map((s) => ({ ...s, stay_minutes: stays.get(s.instance_id)! })),
  };
}

/** The finished search whose winner can be accepted now, or null. Interrupted
 *  searches show their best-so-far order but are never acceptable. */
export function acceptableExhaustive(state: PlannerState): VExhaustiveResult | null {
  const x = state.exhaustive;
  if (!x || x.revision !== state.revision || state.operation.kind === "running") return null;
  const r = x.result;
  return r.search_complete && r.winner && r.winner.status === "complete" && r.winner_plan ? r : null;
}

/**
 * "Use this order" for the experiment: atomically apply the winner's verified
 * timeline, order and explicit stays with no network call. Pins are kept by
 * stop identity: an end stays pinned only if the same stop is still there;
 * new endpoints are never silently pinned.
 */
function acceptExhaustive(state: PlannerState): PlannerState {
  const r = acceptableExhaustive(state);
  if (!r || !r.winner || !r.winner_plan) return state;
  const order = r.winner.order;
  const byId = new Map(state.draft.stops.map((s) => [s.id, s]));
  const stays = new Map(
    r.winner_plan.timeline.flatMap((i) => (i.item_type === "stop" ? [[i.instance_id, i.stay_minutes] as const] : [])),
  );
  if (order.length !== byId.size || order.some((id) => !byId.has(id) || !stays.has(id))) return state;
  const before = state.draft.stops.map((s) => s.id);
  const stops = order.map((id) => ({ ...byId.get(id)!, stayMinutes: stays.get(id)! }));
  const revision = state.revision + 1;
  return {
    ...state,
    draft: {
      ...state.draft,
      stops,
      pinFirst: state.draft.pinFirst && order[0] === before[0],
      pinLast: state.draft.pinLast && order[order.length - 1] === before[before.length - 1],
    },
    revision,
    result: { plan: r.winner_plan, revision },
    exhaustive: null,
    comparison: null,
    notice: null,
  };
}

/** Compare is offered on a current, complete plan with at least three stops. */
export function canCompare(state: PlannerState): boolean {
  const r = state.result;
  return (
    r !== null &&
    !resultIsStale(state) &&
    r.plan.result_type === "complete" &&
    state.draft.stops.length >= 3 &&
    readiness(state).ready
  );
}

/** The verified recommendation that can be accepted now, or null. */
export function acceptableComparison(state: PlannerState): VComparisonResult | null {
  const c = state.comparison;
  if (!c || c.revision !== state.revision || state.operation.kind === "running") return null;
  return c.result.status === "recommended" && c.result.candidate ? c.result : null;
}

/**
 * "Use this order": apply the compared candidate atomically, with no network
 * call. The form takes the candidate order, every stay becomes an explicit
 * (editable) value equal to the compared duration, and the displayed plan is
 * exactly the compared candidate timeline.
 */
function acceptComparison(state: PlannerState): PlannerState {
  const r = acceptableComparison(state);
  if (!r || !r.candidate || !r.candidate_order) return state;
  const byId = new Map(state.draft.stops.map((s) => [s.id, s]));
  const stays = new Map(
    r.candidate.timeline.flatMap((i) => (i.item_type === "stop" ? [[i.instance_id, i.stay_minutes] as const] : [])),
  );
  if (r.candidate_order.some((id) => !byId.has(id) || !stays.has(id)) || r.candidate_order.length !== byId.size) return state;
  const stops = r.candidate_order.map((id) => ({ ...byId.get(id)!, stayMinutes: stays.get(id)! }));
  const revision = state.revision + 1;
  return {
    ...state,
    draft: { ...state.draft, stops },
    revision,
    result: { plan: r.candidate, revision },
    comparison: null,
    notice: null,
  };
}

/** The comparison request for the current inputs (with current pins), or null. */
export function compareRequest(state: PlannerState): (Omit<PlanStreamRequest, "operation_id" | "input_revision"> & { fixed_first: boolean; fixed_last: boolean }) | null {
  const ready = readiness(state);
  if (!canCompare(state) || !ready.ready) return null;
  return { ...ready.request, fixed_first: state.draft.pinFirst, fixed_last: state.draft.pinLast };
}

/** A refresh target, only for a current (not stale) plan. Starting a refresh
 *  supersedes any running operation. */
export function refreshableTarget(state: PlannerState, legIndex: number): RefreshTarget | null {
  if (!state.result || resultIsStale(state)) return null;
  if (!readiness(state).ready) return null;
  return refreshTarget(state.result.plan, legIndex);
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

function journeys(n: number): string {
  return `${n} ${n === 1 ? "journey" : "journeys"}`;
}

export function progressLabel(op: Operation): string | null {
  if (op.kind !== "running") return null;
  if (op.purpose === "exhaustive") {
    if (op.phase === null || op.phase === "verification") return "Checking your places…";
    const o = op.orders ?? { evaluated: 0, complete: 0, failed: 0, total: 24 };
    return `Evaluated ${o.evaluated} of ${o.total} orders (${o.complete} completed, ${o.failed} failed)…`;
  }
  if (op.purpose === "compare") {
    const n = op.totalLegs === null ? "" : `: journey ${Math.min(op.completedLegs + 1, op.totalLegs)} of ${op.totalLegs}`;
    if (op.phase === null || op.phase === "verification") return "Checking your places…";
    if (op.phase === "candidate") return "Finding another order…";
    if (op.phase === "original_route") return `Recalculating your order${n}…`;
    return `Checking the alternative${n}…`;
  }
  if (op.purpose === "refresh") {
    if (op.phase === null || op.phase === "verification") return "Checking the remaining places…";
    if (op.totalLegs === null) return "Refreshing journeys…";
    return `Refreshed ${op.completedLegs} of ${journeys(op.totalLegs)}…`;
  }
  if (op.phase === null || op.phase === "verification") return "Checking your places…";
  if (op.totalLegs === null) return "Planning journeys…";
  return `Planned ${op.completedLegs} of ${journeys(op.totalLegs)}…`;
}

/** The refresh request for leg ``legIndex`` of the current plan, or null. */
export function refreshRequest(
  state: PlannerState,
  legIndex: number,
): (Omit<RefreshStreamRequest, "operation_id" | "input_revision"> & { target: RefreshTarget }) | null {
  const target = refreshableTarget(state, legIndex);
  const ready = readiness(state);
  if (!target || !ready.ready) return null;
  return { ...ready.request, leg_index: legIndex, planned_departure: target.plannedDeparture, target };
}
