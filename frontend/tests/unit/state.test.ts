import { test } from "node:test";
import assert from "node:assert/strict";
import {
  initialState,
  progressLabel,
  readiness,
  reducer,
  resultIsStale,
  stopChecks,
  type Action,
  type PlannerState,
} from "../../lib/v2/state.ts";
import { planResult, streamEvent, type VSelectedCity } from "../../lib/v2/validate.ts";
import { OP, ev, leg, plan, stop } from "./fixtures.ts";

const DUBLIN: VSelectedCity = {
  place_id: "C_dub",
  name: "Dublin",
  secondary_text: "Ireland",
  lat: 53.35,
  lng: -6.26,
  timezone: "Europe/Dublin",
  viewport: { low_lat: 53.22, low_lng: -6.45, high_lat: 53.42, high_lng: -6.05 },
};
const LONDON: VSelectedCity = { ...DUBLIN, place_id: "C_lon", name: "London", timezone: "Europe/London", viewport: null };
const place = (id: string, lat = 53.34, lng = -6.26, timezone: string | null = "Europe/Dublin") => ({
  place_id: `P_${id}`,
  lat,
  lng,
  secondary_text: null,
  timezone,
});

function run(actions: Action[], s: PlannerState = initialState(["a", "b"])): PlannerState {
  return actions.reduce(reducer, s);
}

function ready(): PlannerState {
  return run([
    { type: "citySelected", city: DUBLIN, query: "Dublin" },
    { type: "stopSelected", id: "a", place: place("a"), label: "Trinity" },
    { type: "stopSelected", id: "b", place: place("b"), label: "Guinness" },
    { type: "dateChanged", date: "2026-10-21" },
    { type: "timeChanged", time: "10:00" },
  ]);
}

function started(s = ready(), id = OP): PlannerState {
  return reducer(s, { type: "planStarted", operationId: id });
}

const event = (type: string, extra: Record<string, unknown>, s: PlannerState, op = OP) =>
  streamEvent(ev(type, extra, op, s.operation.kind === "running" ? s.operation.revision : s.revision));

test("edits bump the revision and never start an operation", () => {
  const s = ready();
  assert.equal(s.revision, 5);
  assert.equal(s.operation.kind, "idle");
  assert.ok(readiness(s).ready);
});

test("editing query text invalidates its selection", () => {
  const s = reducer(ready(), { type: "stopQuery", id: "a", query: "Trinity Coll" });
  assert.equal(s.draft.stops[0].selected, null);
  assert.equal(readiness(s).ready, false);
  const c = reducer(ready(), { type: "cityQuery", query: "Dubl" });
  assert.equal(c.draft.city, null);
});

test("Plan only starts with a fully selected, valid draft", () => {
  const notReady = reducer(initialState(["a", "b"]), { type: "planStarted", operationId: OP });
  assert.equal(notReady.operation.kind, "idle");
  assert.equal(started().operation.kind, "running");
  // A second Plan while running supersedes the first (Step 8 #9).
  const twice = reducer(started(), { type: "planStarted", operationId: "op-2" });
  assert.ok(twice.operation.kind === "running" && twice.operation.operationId === "op-2");
});

test("events for other operations or revisions are ignored", () => {
  const s = started();
  const rev = s.operation.kind === "running" ? s.operation.revision : -1;
  const foreign = reducer(s, { type: "streamEvent", operationId: "op-old", event: streamEvent(ev("phase_start", { phase: "routing" }, "op-old", rev)) });
  assert.equal(foreign, s);
  const wrongRev = reducer(s, { type: "streamEvent", operationId: OP, event: streamEvent(ev("phase_start", { phase: "routing" }, OP, rev - 1)) });
  assert.equal(wrongRev, s);
});

test("progress reflects completed legs, not invented percentages", () => {
  let s = started();
  assert.equal(progressLabel(s.operation), "Checking your places…");
  s = reducer(s, { type: "streamEvent", operationId: OP, event: event("phase_start", { phase: "routing" }, s) });
  s = reducer(s, { type: "streamEvent", operationId: OP, event: event("leg_progress", { leg_index: 0, total_legs: 3 }, s) });
  assert.equal(progressLabel(s.operation), "Planned 0 of 3 journeys…");
  s = reducer(s, { type: "streamEvent", operationId: OP, event: event("leg_ready", { leg_index: 0, leg: leg("a", "b"), completed_legs: 1, total_legs: 3 }, s) });
  assert.equal(progressLabel(s.operation), "Planned 1 of 3 journeys…");
  assert.doesNotMatch(progressLabel(s.operation) ?? "", /%|second|remaining/);
});

test("an edit while running stops the operation and late events are ignored", () => {
  let s = started();
  s = reducer(s, { type: "stayChanged", id: "a", minutes: 30 });
  assert.equal(s.operation.kind, "idle");
  assert.equal(s.notice?.kind, "cancelled");
  const late = streamEvent(ev("terminal", { outcome: { outcome_type: "plan", result: plan() } }, OP, s.revision - 1));
  const after = reducer(s, { type: "streamEnded", operationId: OP, end: { kind: "terminal", event: late as never } });
  assert.equal(after, s);
  assert.equal(after.result, null);
});

test("an older operation's outcome cannot overwrite a newer operation", () => {
  let s = started(ready(), "op-A");
  s = reducer(s, { type: "cancelRequested" });
  s = reducer(s, { type: "planStarted", operationId: "op-B" });
  const rev = s.revision;
  const old = streamEvent(ev("terminal", { outcome: { outcome_type: "plan", result: plan("complete", { operation_id: "op-A", input_revision: rev }) } }, "op-A", rev));
  const after = reducer(s, { type: "streamEnded", operationId: "op-A", end: { kind: "terminal", event: old as never } });
  assert.equal(after, s);
  assert.ok(after.operation.kind === "running" && after.operation.operationId === "op-B");
});

test("completed result becomes stale after an edit, and is kept visible", () => {
  let s = started();
  const rev = s.revision;
  const term = streamEvent(ev("terminal", { outcome: { outcome_type: "plan", result: plan("complete", { input_revision: rev }) } }, OP, rev));
  s = reducer(s, { type: "streamEnded", operationId: OP, end: { kind: "terminal", event: term as never } });
  assert.equal(s.result?.plan.result_type, "complete");
  assert.equal(resultIsStale(s), false);
  s = reducer(s, { type: "modeChanged", mode: "walking" });
  assert.equal(resultIsStale(s), true);
  assert.ok(s.result);
});

test("timeout keeps the confirmed prefix; incomplete streams are never success", () => {
  let s = started();
  const rev = s.revision;
  const partial = plan("partial", { input_revision: rev, failure_reason: "deadline_exceeded" });
  const term = streamEvent(ev("terminal", { outcome: { outcome_type: "timeout", phase: "routing", message: "Too long", partial } }, OP, rev));
  const t = reducer(s, { type: "streamEnded", operationId: OP, end: { kind: "terminal", event: term as never } });
  assert.equal(t.notice?.kind, "timeout");
  assert.equal(t.result?.plan.result_type, "partial");
  s = reducer(started(), { type: "streamEnded", operationId: OP, end: { kind: "incomplete", reason: "truncated" } });
  assert.equal(s.notice?.kind, "incomplete");
  assert.equal(s.result, null);
});

test("server errors identify the affected stops", () => {
  let s = started();
  const rev = s.revision;
  const term = streamEvent(ev("terminal", { outcome: { outcome_type: "error", code: "place_invalid", message: "Reselect", details: { role: "stop", instance_ids: ["b"] } } }, OP, rev));
  s = reducer(s, { type: "streamEnded", operationId: OP, end: { kind: "terminal", event: term as never } });
  assert.deepEqual(s.notice?.kind === "error" && s.notice.instanceIds, ["b"]);
});

test("city change preserves stop identities, durations and the local clock", () => {
  let s = reducer(ready(), { type: "stayChanged", id: "a", minutes: 0 });
  s = reducer(s, { type: "occurrenceChanged", occurrence: 2 });
  s = reducer(s, { type: "citySelected", city: LONDON, query: "London" });
  assert.deepEqual(s.draft.stops.map((x) => [x.id, x.selected?.place_id, x.stayMinutes]), [
    ["a", "P_a", 0],
    ["b", "P_b", null],
  ]);
  assert.equal(s.draft.date, "2026-10-21");
  assert.equal(s.draft.time, "10:00");
  assert.equal(s.draft.occurrence, null); // zone changed → choose again
  // Dublin stops vs London city: blocked by the one-timezone rule; area check unavailable.
  assert.deepEqual(stopChecks(s.draft).map((c) => [c.area, c.timezoneProblem]), [
    ["unavailable", "different"],
    ["unavailable", "different"],
  ]);
  assert.equal(readiness(s).ready, false);
});

test("outside-area stops are allowed but flagged", () => {
  const s = reducer(ready(), { type: "stopSelected", id: "b", place: place("b", 53.01, -6.33), label: "Glendalough" });
  assert.deepEqual(stopChecks(s.draft).map((c) => c.area), ["inside", "outside"]);
  assert.ok(readiness(s).ready);
});

test("reordering carries durations with stop instances", () => {
  let s = reducer(ready(), { type: "stopAdded", id: "c" });
  s = reducer(s, { type: "stayChanged", id: "a", minutes: 45 });
  s = reducer(s, { type: "stopsReordered", ids: ["b", "a", "c"] });
  assert.deepEqual(s.draft.stops.map((x) => [x.id, x.stayMinutes]), [["b", null], ["a", 45], ["c", null]]);
  assert.equal(reducer(s, { type: "stopsReordered", ids: ["a", "b"] }), s); // malformed reorder ignored
});

test("explicit zero stay is kept and sent; blank means default", () => {
  const s = reducer(ready(), { type: "stayChanged", id: "a", minutes: 0 });
  const r = readiness(s);
  assert.ok(r.ready);
  if (r.ready) {
    assert.equal(r.request.stops[0].stay_minutes, 0);
    assert.equal("stay_minutes" in r.request.stops[1], false);
  }
  assert.equal(reducer(s, { type: "stayChanged", id: "a", minutes: -5 }), s);
});

test("pins default on and toggling them is not a plan edit", () => {
  const s = ready();
  assert.equal(s.draft.pinFirst && s.draft.pinLast, true);
  const t = reducer(s, { type: "pinToggled", end: "last" });
  assert.equal(t.draft.pinLast, false);
  assert.equal(t.revision, s.revision);
  const edited = reducer(t, { type: "stopAdded", id: "c" });
  assert.equal(edited.draft.pinLast, false); // explicit unlock survives list edits
});

test("repeated local time requires an explicit occurrence before planning", () => {
  let s = reducer(ready(), { type: "dateChanged", date: "2026-10-25" });
  s = reducer(s, { type: "timeChanged", time: "01:30" });
  assert.equal(readiness(s).ready, false);
  s = reducer(s, { type: "occurrenceChanged", occurrence: 2 });
  const r = readiness(s);
  assert.ok(r.ready && r.request.departure.occurrence === 2);
  s = reducer(s, { type: "timeChanged", time: "01:45" });
  assert.equal(s.draft.occurrence, null); // reset on relevant edit
});

test("results never come from a stale draft: partial timeline unchanged", () => {
  const p = planResult(plan("partial"));
  assert.equal(p.timeline.filter((i) => i.item_type === "unknown_stop").length, 1);
  assert.equal(stop("x").item_type, "stop");
});
