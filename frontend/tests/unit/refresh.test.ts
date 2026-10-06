import { test } from "node:test";
import assert from "node:assert/strict";
import { readPlanStream } from "../../lib/v2/ndjson.ts";
import { RefreshMergeError, mergeRefresh, refreshTarget } from "../../lib/v2/refresh.ts";
import {
  REFRESH_CANCELLED,
  REFRESH_INCOMPLETE,
  initialState,
  progressLabel,
  reducer,
  refreshRequest,
  resultIsStale,
  type PlannerState,
} from "../../lib/v2/state.ts";
import { planResult, refreshResult, streamEvent, type VSelectedCity } from "../../lib/v2/validate.ts";
import { line, ndjsonStream } from "./fixtures.ts";

// Plan: a (09:00) -leg0-> b (09:20, stay 60, leave 10:20) -leg1-> c (10:40, stay 30, leave 11:10) -leg2-> d (11:30)
const T = (hhmm: string) => `2026-10-21T${hhmm}:00Z`;
function stop(id: string, arrive: string, depart: string, stay: number) {
  return {
    item_type: "stop", instance_id: id, place_id: `P_${id}`, name: `Stop ${id}`, address: null, lat: 53.34, lng: -6.26,
    arrive_at: T(arrive), depart_at: T(depart), stay_minutes: stay, stay_source: "default", map_url: "m",
    hours_status: "open", hours_detail: null,
  };
}
function leg(from: string, to: string, depart: string, arrive: string) {
  return {
    item_type: "leg", from_stop_id: from, to_stop_id: to, from_name: `Stop ${from}`, to_name: `Stop ${to}`, mode: "transit",
    duration_seconds: 1200, distance_meters: 900, depart_at: T(depart), arrive_at: T(arrive), summary: "Bus", map_url: "m",
  };
}
const OLD = planResult({
  result_type: "complete", operation_id: "op-plan", input_revision: 5, city: "Dublin", mode: "transit", timezone: "Europe/Dublin",
  timeline: [
    stop("a", "09:00", "09:00", 0), leg("a", "b", "09:00", "09:20"),
    stop("b", "09:20", "10:20", 60), leg("b", "c", "10:20", "10:40"),
    stop("c", "10:40", "11:10", 30), leg("c", "d", "11:10", "11:30"),
    stop("d", "11:30", "11:30", 0),
  ],
  overview_map_url: "o",
  warnings: [
    { severity: "warning", message: "Outside the selected city's suggested area.", affects_instance_id: "a", code: "outside_city_area" },
    { severity: "warning", message: "old downstream warning", affects_instance_id: "c", code: "hours_closes_during_visit" },
  ],
});

// Refresh from leg 1 (b -> c), planned 10:20; new travel 35 min.
const REFRESH_OK = refreshResult({
  result_type: "refresh_complete", operation_id: "op-r", input_revision: 5, leg_index: 1, planned_departure: T("10:20"),
  timezone: "Europe/Dublin",
  suffix: [leg("b", "c", "10:20", "10:55"), stop("c", "10:55", "11:25", 30), leg("c", "d", "11:25", "11:45"), stop("d", "11:45", "11:45", 0)],
  warnings: [{ severity: "info", message: "Opening hours for Stop d could not be checked.", affects_instance_id: "d", code: "hours_unknown" }],
});
const REFRESH_PARTIAL = refreshResult({
  result_type: "refresh_partial", operation_id: "op-r", input_revision: 5, leg_index: 1, planned_departure: T("10:20"),
  timezone: "Europe/Dublin", failed_at_leg_index: 2, failure_reason: "no_route",
  suffix: [
    leg("b", "c", "10:20", "10:55"), stop("c", "10:55", "11:25", 30),
    { item_type: "failed_leg", from_stop_id: "c", to_stop_id: "d", from_name: "Stop c", to_name: "Stop d", failure_reason: "no_route" },
    { item_type: "unknown_stop", instance_id: "d", place_id: "P_d", name: "Stop d" },
  ],
  warnings: [],
});

test("refresh target uses the origin stop's confirmed departure", () => {
  const t = refreshTarget(OLD, 1);
  assert.deepEqual(t && [t.plannedDeparture, t.fromStopId, t.retry], [T("10:20"), "b", false]);
  assert.equal(refreshTarget(OLD, 3), null);
});

test("success replaces the suffix atomically and keeps the prefix untouched", () => {
  const merged = mergeRefresh(OLD, REFRESH_OK);
  assert.equal(merged.result_type, "complete");
  for (let i = 0; i < 3; i++) assert.equal(merged.timeline[i], OLD.timeline[i]); // same objects
  assert.deepEqual(merged.timeline.slice(3), REFRESH_OK.suffix);
  const codes = merged.warnings.map((w) => `${w.affects_instance_id}:${w.code}`);
  assert.deepEqual(codes, ["a:outside_city_area", "d:hours_unknown"]); // old downstream warning dropped
});

test("partial failure keeps refreshed part, the failed journey and unknown later times only", () => {
  const merged = mergeRefresh(OLD, REFRESH_PARTIAL);
  assert.equal(merged.result_type, "partial");
  assert.deepEqual(merged.timeline.map((i) => i.item_type), ["stop", "leg", "stop", "leg", "stop", "failed_leg", "unknown_stop"]);
  const oldDownstreamTimes = new Set(OLD.timeline.slice(3).flatMap((i) => ("arrive_at" in i ? [i.arrive_at, i.depart_at] : [])));
  const newTimes = merged.timeline.slice(3).flatMap((i) => ("arrive_at" in i ? [i.arrive_at] : []));
  assert.ok(newTimes.every((t) => !oldDownstreamTimes.has(t))); // no old downstream timing merged in
  const t = refreshTarget(merged, 2);
  assert.ok(t?.retry && t.plannedDeparture === T("11:25")); // "Try again" from the same planned departure
});

test("inconsistent refreshes are refused", () => {
  assert.throws(() => mergeRefresh(OLD, { ...REFRESH_OK, planned_departure: T("10:25") }), RefreshMergeError);
  assert.throws(() => mergeRefresh(OLD, { ...REFRESH_OK, suffix: REFRESH_OK.suffix.slice(0, 2) }), RefreshMergeError);
});

// ---- reducer -----------------------------------------------------------------

const CITY: VSelectedCity = { place_id: "C", name: "Dublin", secondary_text: null, lat: 53.35, lng: -6.26, timezone: "Europe/Dublin", viewport: null };
function planned(): PlannerState {
  let s = initialState(["a", "b"]);
  s = reducer(s, { type: "stopAdded", id: "c" });
  s = reducer(s, { type: "stopAdded", id: "d" });
  s = reducer(s, { type: "citySelected", city: CITY, query: "Dublin" });
  for (const id of ["a", "b", "c", "d"]) {
    s = reducer(s, { type: "stopSelected", id, place: { place_id: `P_${id}`, lat: 53.34, lng: -6.26, secondary_text: null, timezone: "Europe/Dublin" }, label: `Stop ${id}` });
  }
  s = reducer(s, { type: "dateChanged", date: "2026-10-21" });
  s = reducer(s, { type: "timeChanged", time: "10:00" });
  return { ...s, result: { plan: { ...OLD, input_revision: s.revision }, revision: s.revision } };
}
const refreshEnd = (s: PlannerState, outcome: unknown, op = "op-r") => {
  const rev = s.operation.kind === "running" ? s.operation.revision : s.revision;
  return { kind: "terminal" as const, event: streamEvent({ operation_id: op, input_revision: rev, type: "terminal", outcome }, "e", "refresh") as never };
};

test("refresh only starts on a current plan, with the planned departure in the request", () => {
  const s = planned();
  const req = refreshRequest(s, 1);
  assert.ok(req && req.leg_index === 1 && req.planned_departure === T("10:20"));
  const stale = reducer(s, { type: "modeChanged", mode: "walking" });
  assert.equal(refreshRequest(stale, 1), null);
  assert.equal(reducer(stale, { type: "refreshStarted", operationId: "op-r", legIndex: 1 }).operation.kind, "idle");
});

test("progress events never change the plan; success swaps the suffix at once", () => {
  let s = reducer(planned(), { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
  const before = s.result;
  const rev = s.revision;
  s = reducer(s, { type: "streamEvent", operationId: "op-r", event: streamEvent({ operation_id: "op-r", input_revision: rev, type: "phase_start", phase: "routing" }) });
  s = reducer(s, { type: "streamEvent", operationId: "op-r", event: streamEvent({ operation_id: "op-r", input_revision: rev, type: "leg_ready", leg_index: 1, leg: leg("b", "c", "10:20", "10:55"), completed_legs: 1, total_legs: 2 }) });
  assert.equal(s.result, before);
  assert.equal(progressLabel(s.operation), "Refreshed 1 of 2 journeys…");
  s = reducer(s, { type: "streamEnded", operationId: "op-r", end: refreshEnd(s, { outcome_type: "refresh", result: { ...REFRESH_OK, input_revision: rev } }) });
  assert.equal(s.operation.kind, "idle");
  assert.equal(s.notice, null);
  assert.deepEqual(s.result?.plan.timeline.slice(3), REFRESH_OK.suffix);
  assert.equal(resultIsStale(s), false);
});

test("routing failure during refresh replaces the suffix with refreshed part + failure", () => {
  let s = reducer(planned(), { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
  s = reducer(s, { type: "streamEnded", operationId: "op-r", end: refreshEnd(s, { outcome_type: "refresh", result: { ...REFRESH_PARTIAL, input_revision: s.revision } }) });
  assert.equal(s.result?.plan.result_type, "partial");
  assert.equal(s.result?.plan.timeline.at(-1)?.item_type, "unknown_stop");
});

for (const [label, end, message] of [
  ["cancel", { kind: "aborted" } as const, REFRESH_CANCELLED],
  ["interrupted stream", { kind: "incomplete", reason: "truncated" } as const, REFRESH_INCOMPLETE],
  ["malformed stream", { kind: "incomplete", reason: "malformed" } as const, REFRESH_INCOMPLETE],
] as const) {
  test(`${label} keeps the previous plan and says so`, () => {
    const s0 = reducer(planned(), { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
    const s = reducer(s0, { type: "streamEnded", operationId: "op-r", end });
    assert.equal(s.result, s0.result); // previous plan object retained untouched
    assert.equal(s.notice?.message, message);
  });
}

test("Cancel button: previous plan retained, later events ignored", () => {
  const s0 = reducer(planned(), { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
  const s = reducer(s0, { type: "cancelRequested" });
  assert.equal(s.notice?.message, REFRESH_CANCELLED);
  assert.equal(s.result, s0.result);
  const late = reducer(s, { type: "streamEnded", operationId: "op-r", end: refreshEnd(s0, { outcome_type: "refresh", result: { ...REFRESH_OK, input_revision: s0.revision } }) });
  assert.equal(late, s);
});

test("an input change stops the refresh and late results cannot apply", () => {
  const s0 = reducer(planned(), { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
  const s = reducer(s0, { type: "stayChanged", id: "b", minutes: 15 });
  assert.equal(s.operation.kind, "idle");
  assert.match(s.notice?.message ?? "", /Refresh stopped/);
  assert.equal(resultIsStale(s), true);
  const late = reducer(s, { type: "streamEnded", operationId: "op-r", end: refreshEnd(s0, { outcome_type: "refresh", result: { ...REFRESH_OK, input_revision: s0.revision } }) });
  assert.equal(late, s);
});

test("a newer operation ignores an older refresh's events", () => {
  let s = reducer(planned(), { type: "refreshStarted", operationId: "op-old", legIndex: 1 });
  s = reducer(s, { type: "cancelRequested" });
  s = reducer(s, { type: "refreshStarted", operationId: "op-new", legIndex: 1 });
  const old = reducer(s, { type: "streamEnded", operationId: "op-old", end: refreshEnd(s, { outcome_type: "refresh", result: { ...REFRESH_OK, input_revision: s.revision } }, "op-old") });
  assert.equal(old, s);
});

test("a refresh that doesn't fit the plan is treated as incomplete", () => {
  let s = reducer(planned(), { type: "refreshStarted", operationId: "op-r", legIndex: 1 });
  const before = s.result;
  s = reducer(s, { type: "streamEnded", operationId: "op-r", end: refreshEnd(s, { outcome_type: "refresh", result: { ...REFRESH_OK, input_revision: s.revision, planned_departure: T("10:30") } }) });
  assert.equal(s.result, before);
  assert.equal(s.notice?.message, REFRESH_INCOMPLETE);
});

test("plan and refresh outcomes cannot cross streams", async () => {
  const id = { operationId: "op", inputRevision: 1 };
  const start = line({ operation_id: "op", input_revision: 1, type: "operation_start", phases: [] });
  const refreshTerminal = line({ operation_id: "op", input_revision: 1, type: "terminal", outcome: { outcome_type: "refresh", result: { ...REFRESH_OK, operation_id: "op", input_revision: 1 } } });
  const asPlan = await readPlanStream(ndjsonStream([start, refreshTerminal]), { ...id, kind: "plan" }, () => {});
  assert.deepEqual(asPlan, { kind: "incomplete", reason: "malformed" });
  const asRefresh = await readPlanStream(ndjsonStream([start, refreshTerminal]), { ...id, kind: "refresh" }, () => {});
  assert.equal(asRefresh.kind, "terminal");
});
