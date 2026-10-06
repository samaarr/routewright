import { test } from "node:test";
import assert from "node:assert/strict";
import { readPlanStream } from "../../lib/v2/ndjson.ts";
import {
  COMPARE_CANCELLED,
  COMPARE_INCOMPLETE,
  acceptableComparison,
  canCompare,
  compareRequest,
  initialState,
  progressLabel,
  readiness,
  reducer,
  resultIsStale,
  type PlannerState,
} from "../../lib/v2/state.ts";
import { ValidationError, comparisonResult, planResult, streamEvent, type VSelectedCity } from "../../lib/v2/validate.ts";
import { line, ndjsonStream } from "./fixtures.ts";

const T = (hhmm: string) => `2026-10-21T${hhmm}:00Z`;
const stop = (id: string, arrive: string, depart: string, stay: number) => ({
  item_type: "stop", instance_id: id, place_id: `P_${id}`, name: `Stop ${id}`, address: null, lat: 53.34, lng: -6.26,
  arrive_at: T(arrive), depart_at: T(depart), stay_minutes: stay, stay_source: "default", map_url: "m",
  hours_status: "open", hours_detail: null,
});
const leg = (from: string, to: string, depart: string, arrive: string) => ({
  item_type: "leg", from_stop_id: from, to_stop_id: to, from_name: from, to_name: to, mode: "transit",
  duration_seconds: 600, distance_meters: 900, depart_at: T(depart), arrive_at: T(arrive), summary: "Bus", map_url: "m",
});
function plan(ids: string[], rev: number, op = "op-c", minutes = 20) {
  const tl: unknown[] = [];
  let t = 9 * 60;
  const hm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  ids.forEach((id, i) => {
    const stay = i === 0 || i === ids.length - 1 ? 0 : 60;
    tl.push(stop(id, hm(t), hm(t + stay), stay));
    t += stay;
    if (i < ids.length - 1) {
      tl.push(leg(id, ids[i + 1], hm(t), hm(t + minutes)));
      t += minutes;
    }
  });
  return {
    result_type: "complete", operation_id: op, input_revision: rev, city: "Dublin", mode: "transit",
    timezone: "Europe/Dublin", timeline: tl, overview_map_url: "o", warnings: [],
  };
}

const CITY: VSelectedCity = { place_id: "C", name: "Dublin", secondary_text: null, lat: 53.35, lng: -6.26, timezone: "Europe/Dublin", viewport: null };
function planned(n = 4): PlannerState {
  const ids = ["a", "b", "c", "d"].slice(0, n);
  let s = initialState(["a", "b"]);
  for (const id of ids.slice(2)) s = reducer(s, { type: "stopAdded", id });
  s = reducer(s, { type: "citySelected", city: CITY, query: "Dublin" });
  for (const id of ids) {
    s = reducer(s, { type: "stopSelected", id, place: { place_id: `P_${id}`, lat: 53.34, lng: -6.26, secondary_text: null, timezone: "Europe/Dublin" }, label: `Stop ${id}` });
  }
  s = reducer(s, { type: "dateChanged", date: "2026-10-21" });
  s = reducer(s, { type: "timeChanged", time: "10:00" });
  return { ...s, result: { plan: planResult(plan(ids, s.revision, "op-plan")), revision: s.revision } };
}

function comparison(status: string, rev: number, extra: Record<string, unknown> = {}) {
  const base: Record<string, unknown> = {
    operation_id: "op-c", input_revision: rev, status, message: "m", original_order: ["a", "b", "c", "d"],
    candidate_order: ["a", "c", "b", "d"], fixed_first: true, fixed_last: true, original: plan(["a", "b", "c", "d"], rev, "op-c", 25),
    candidate: null, original_seconds: 4500, candidate_seconds: 4200, saving_seconds: 300, threshold_seconds: 300,
    original_distance_km: 3, candidate_distance_km: 2, ineligible_instance_ids: [], routing_calls: 6,
  };
  if (status === "recommended") base.candidate = plan(["a", "c", "b", "d"], rev, "op-c", 15);
  if (status === "no_different_order") Object.assign(base, { original: null, candidate_order: ["a", "b", "c", "d"], routing_calls: 0, original_seconds: null, candidate_seconds: null, saving_seconds: null });
  if (status === "original_incomplete") base.original = { ...plan(["a", "b", "c", "d"], rev, "op-c"), result_type: "partial", failed_at_leg_index: 0, failure_reason: "no_route", timeline: [stop("a", "09:00", "09:00", 0), { item_type: "failed_leg", from_stop_id: "a", to_stop_id: "b", from_name: "a", to_name: "b", failure_reason: "no_route" }, ...["b", "c", "d"].map((id) => ({ item_type: "unknown_stop", instance_id: id, place_id: `P_${id}`, name: `Stop ${id}` }))] };
  return { ...base, ...extra };
}

const terminal = (s: PlannerState, result: unknown) => {
  const rev = s.operation.kind === "running" ? s.operation.revision : s.revision;
  return { kind: "terminal" as const, event: streamEvent({ operation_id: "op-c", input_revision: rev, type: "terminal", outcome: { outcome_type: "comparison", result } }, "e", "compare") as never };
};
const started = (s = planned()) => reducer(s, { type: "compareStarted", operationId: "op-c" });

// ---- validation ---------------------------------------------------------------

test("comparison results must be internally consistent", () => {
  assert.equal(comparisonResult(comparison("recommended", 1)).status, "recommended");
  assert.throws(() => comparisonResult(comparison("recommended", 1, { saving_seconds: 299 })), ValidationError);
  assert.throws(() => comparisonResult(comparison("not_faster", 1, { candidate: plan(["a", "c", "b", "d"], 1) })), ValidationError);
  assert.throws(() => comparisonResult(comparison("recommended", 1, { candidate_order: ["a", "b", "c", "d"] })), ValidationError);
  assert.throws(() => comparisonResult(comparison("no_different_order", 1, { routing_calls: 2 })), ValidationError);
});

test("comparison outcomes are only valid in comparison streams", async () => {
  const id = { operationId: "op", inputRevision: 1 };
  const start = line({ operation_id: "op", input_revision: 1, type: "operation_start", phases: [] });
  const end = line({ operation_id: "op", input_revision: 1, type: "terminal", outcome: { outcome_type: "comparison", result: comparison("not_faster", 1, { operation_id: "op" }) } });
  assert.deepEqual(await readPlanStream(ndjsonStream([start, end]), { ...id, kind: "plan" }, () => {}), { kind: "incomplete", reason: "malformed" });
  assert.equal((await readPlanStream(ndjsonStream([start, end]), { ...id, kind: "compare" }, () => {})).kind, "terminal");
});

// ---- starting ---------------------------------------------------------------

test("compare is offered only on a current, complete plan with at least three stops", () => {
  assert.equal(canCompare(planned(4)), true);
  assert.equal(canCompare(planned(2)), false);
  const stale = reducer(planned(), { type: "modeChanged", mode: "walking" });
  assert.equal(canCompare(stale), false);
  const s = planned();
  const partial = { ...s, result: { plan: planResult({ ...plan(["a", "b", "c", "d"], s.revision), result_type: "partial", failed_at_leg_index: 0, failure_reason: "no_route", timeline: [stop("a", "09:00", "09:00", 0), { item_type: "failed_leg", from_stop_id: "a", to_stop_id: "b", from_name: "a", to_name: "b", failure_reason: "no_route" }, { item_type: "unknown_stop", instance_id: "b", place_id: "P_b", name: "b" }] }), revision: s.revision } };
  assert.equal(canCompare(partial), false);
  const req = compareRequest(planned());
  assert.ok(req && req.fixed_first && req.fixed_last); // pins default on
});

test("progress shows real phases and per-route journey counts", () => {
  let s = started();
  const rev = s.revision;
  const ev = (type: string, extra: Record<string, unknown>) =>
    reducer(s, { type: "streamEvent", operationId: "op-c", event: streamEvent({ operation_id: "op-c", input_revision: rev, type, ...extra }) });
  assert.equal(progressLabel(s.operation), "Checking your places…");
  s = ev("phase_start", { phase: "candidate" });
  assert.equal(progressLabel(s.operation), "Finding another order…");
  s = ev("phase_start", { phase: "original_route" });
  s = ev("leg_progress", { leg_index: 0, total_legs: 3 });
  assert.equal(progressLabel(s.operation), "Recalculating your order: journey 1 of 3…");
  s = ev("leg_ready", { leg_index: 0, leg: leg("a", "b", "09:00", "09:20"), completed_legs: 1, total_legs: 3 });
  assert.equal(progressLabel(s.operation), "Recalculating your order: journey 2 of 3…");
  s = ev("phase_start", { phase: "alternative_route" });
  s = ev("leg_progress", { leg_index: 0, total_legs: 3 });
  assert.equal(progressLabel(s.operation), "Checking the alternative: journey 1 of 3…"); // counts reset per route
  assert.doesNotMatch(progressLabel(s.operation) ?? "", /%/);
});

// ---- outcomes ---------------------------------------------------------------

test("a complete fresh original replaces the displayed plan atomically and is labelled", () => {
  const s0 = started();
  const s = reducer(s0, { type: "streamEnded", operationId: "op-c", end: terminal(s0, comparison("not_faster", s0.revision)) });
  assert.equal(s.result?.label, "recalculated");
  assert.equal(s.result?.plan.operation_id, "op-c"); // the fresh original
  assert.equal(resultIsStale(s), false);
  assert.equal(s.comparison?.result.status, "not_faster");
  assert.equal(acceptableComparison(s), null); // nothing to accept
});

for (const status of ["original_incomplete", "no_different_order"]) {
  test(`${status} leaves the previous plan untouched`, () => {
    const s0 = started();
    const s = reducer(s0, { type: "streamEnded", operationId: "op-c", end: terminal(s0, comparison(status, s0.revision)) });
    assert.equal(s.result, s0.result);
    assert.equal(s.comparison?.result.status, status);
  });
}

for (const [label, end, message] of [
  ["cancel", { kind: "aborted" } as const, COMPARE_CANCELLED],
  ["interrupted stream", { kind: "incomplete", reason: "truncated" } as const, COMPARE_INCOMPLETE],
] as const) {
  test(`${label} preserves the plan`, () => {
    const s0 = started();
    const s = reducer(s0, { type: "streamEnded", operationId: "op-c", end });
    assert.equal(s.result, s0.result);
    assert.equal(s.notice?.message, message);
    assert.equal(s.comparison, null);
  });
}

test("Cancel button keeps the plan and later comparison events are ignored", () => {
  const s0 = started();
  const s = reducer(s0, { type: "cancelRequested" });
  assert.equal(s.notice?.message, COMPARE_CANCELLED);
  const late = reducer(s, { type: "streamEnded", operationId: "op-c", end: terminal(s0, comparison("recommended", s0.revision)) });
  assert.equal(late, s);
});

// ---- acceptance ---------------------------------------------------------------

test("Use this order applies the verified candidate atomically with explicit, editable stays", () => {
  const s0 = started();
  const done = reducer(s0, { type: "streamEnded", operationId: "op-c", end: terminal(s0, comparison("recommended", s0.revision)) });
  const candidate = done.comparison?.result.candidate;
  assert.ok(candidate && acceptableComparison(done));
  const s = reducer(done, { type: "comparisonAccepted" });
  assert.deepEqual(s.draft.stops.map((x) => x.id), ["a", "c", "b", "d"]);
  assert.deepEqual(s.draft.stops.map((x) => x.stayMinutes), [0, 60, 60, 0]); // every compared stay explicit
  assert.equal(s.result?.plan, candidate); // exactly the compared timeline
  assert.equal(resultIsStale(s), false);
  assert.equal(s.comparison, null);
  const r = readiness(s);
  assert.ok(r.ready && r.request.stops.every((x) => typeof x.stay_minutes === "number")); // a later Plan reproduces them
  const edited = reducer(s, { type: "stayChanged", id: "c", minutes: 30 }); // still editable
  assert.equal(edited.draft.stops[1].stayMinutes, 30);
});

test("input edits invalidate the suggestion; Plan and Refresh clear it", () => {
  const s0 = started();
  const done = reducer(s0, { type: "streamEnded", operationId: "op-c", end: terminal(s0, comparison("recommended", s0.revision)) });
  const edited = reducer(done, { type: "timeChanged", time: "10:30" });
  assert.equal(edited.comparison, null);
  assert.equal(reducer(edited, { type: "comparisonAccepted" }), edited);
  assert.equal(reducer(done, { type: "planStarted", operationId: "p2" }).comparison, null);
  assert.equal(reducer(done, { type: "refreshStarted", operationId: "r2", legIndex: 1 }).comparison, null);
  assert.equal(reducer(done, { type: "comparisonDismissed" }).comparison, null);
});

test("planning supersedes a running comparison and its late result is rejected", () => {
  const s0 = started();
  const p = reducer(s0, { type: "planStarted", operationId: "op-p" });
  const late = reducer(p, { type: "streamEnded", operationId: "op-c", end: terminal(s0, comparison("recommended", s0.revision)) });
  assert.equal(late, p);
  const r = reducer(s0, { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
  assert.ok(r.operation.kind === "running" && r.operation.purpose === "refresh");
});
