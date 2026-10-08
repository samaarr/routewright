// Experimental exhaustive four-stop search (2026-10-08): validation, reducer,
// request construction, acceptance and coordination with other operations.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readPlanStream } from "../../lib/v2/ndjson.ts";
import {
  EXHAUSTIVE_CANCELLED,
  EXHAUSTIVE_INCOMPLETE,
  acceptableExhaustive,
  canRunExhaustive,
  exhaustiveRequest,
  initialState,
  progressLabel,
  reducer,
  type PlannerState,
} from "../../lib/v2/state.ts";
import { ValidationError, exhaustiveResult, planResult, streamEvent, type VSelectedCity } from "../../lib/v2/validate.ts";
import { line, ndjsonStream } from "./fixtures.ts";

const T = (hhmm: string) => `2026-10-21T${hhmm}:00Z`;
const hm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const STAYS: Record<string, number> = { a: 0, b: 60, c: 60, d: 0 };
const stop = (id: string, arrive: string, depart: string, stay: number) => ({
  item_type: "stop", instance_id: id, place_id: `P_${id}`, name: `Stop ${id}`, address: null, lat: 53.34, lng: -6.26,
  arrive_at: T(arrive), depart_at: T(depart), stay_minutes: stay, stay_source: "user", map_url: "m",
  hours_status: "open", hours_detail: null,
});
const leg = (from: string, to: string, depart: string, arrive: string) => ({
  item_type: "leg", from_stop_id: from, to_stop_id: to, from_name: from, to_name: to, mode: "transit",
  duration_seconds: 600, journey_seconds: (Date.parse(T(arrive)) - Date.parse(T(depart))) / 1000, distance_meters: 900,
  depart_at: T(depart), arrive_at: T(arrive), summary: "Bus", map_url: "m",
});

/** Timeline for ``ids`` from 09:00 with per-instance stays and ``minutes`` per leg. */
function timeline(ids: string[], minutes = 20): unknown[] {
  const tl: unknown[] = [];
  let t = 9 * 60;
  ids.forEach((id, i) => {
    tl.push(stop(id, hm(t), hm(t + STAYS[id]), STAYS[id]));
    t += STAYS[id];
    if (i < ids.length - 1) {
      tl.push(leg(id, ids[i + 1], hm(t), hm(t + minutes)));
      t += minutes;
    }
  });
  return tl;
}

function plan(ids: string[], rev: number, op: string, minutes = 20) {
  return {
    result_type: "complete", operation_id: op, input_revision: rev, city: "Dublin", mode: "transit",
    timezone: "Europe/Dublin", timeline: timeline(ids, minutes), overview_map_url: "o", warnings: [],
  };
}

function complete(order: string[], minutes = 20, original = false) {
  const tl = timeline(order, minutes) as { depart_at?: string }[];
  const done = tl[tl.length - 1].depart_at!;
  return {
    order, is_original: original, status: "complete", completion_at: done,
    elapsed_seconds: (Date.parse(done) - Date.parse(T("09:00"))) / 1000, distance_m: 2500,
    failure_reason: null, failure_message: null, timeline: tl, routing_calls: 3,
  };
}

function permutations(xs: string[]): string[][] {
  if (xs.length <= 1) return [xs];
  return xs.flatMap((x, i) => permutations([...xs.slice(0, i), ...xs.slice(i + 1)]).map((p) => [x, ...p]));
}

const ORIGINAL = ["a", "b", "c", "d"];
const WINNER = ["c", "a", "b", "d"]; // a different first stop than the original

function finished(rev: number, op = "op-x") {
  const candidates = permutations(ORIGINAL).map((o) =>
    complete(o, o.join() === WINNER.join() ? 10 : 20, o.join() === ORIGINAL.join()),
  );
  return {
    operation_id: op, input_revision: rev, status: "all_complete",
    message: "Earliest completion among all 24 evaluated stop orders.", search_complete: true,
    requested_orders: 24, evaluated_orders: 24, complete_orders: 24, failed_orders: 0, interruption_reason: null,
    start_at: T("09:00"), original_order: ORIGINAL, original: complete(ORIGINAL, 20, true), winner: complete(WINNER, 10),
    winner_basis: "completion", winner_plan: plan(WINNER, rev, op, 10), saving_seconds: 1800, hours_warnings: [],
    candidates, routing_calls: 72, routing_budget: 72, deadline_seconds: 240,
  };
}

function interrupted(rev: number, op = "op-x") {
  const done = permutations(ORIGINAL).slice(0, 3).map((o, i) => complete(o, 20, i === 0));
  const cut = {
    order: permutations(ORIGINAL)[3], is_original: false, status: "interrupted", completion_at: null, elapsed_seconds: null,
    distance_m: 2000, failure_reason: "deadline_exceeded", failure_message: "x",
    timeline: [stop("a", "09:00", "09:00", 0)], routing_calls: 1,
  };
  return {
    ...finished(rev, op), status: "interrupted", message: "Search incomplete: evaluated 3 of 24 orders.",
    search_complete: false, evaluated_orders: 3, complete_orders: 3, failed_orders: 0,
    interruption_reason: "deadline_exceeded", original: done[0], winner: done[1], winner_basis: "completion",
    winner_plan: null, saving_seconds: 0, candidates: [...done, cut], routing_calls: 10,
  };
}

const CITY: VSelectedCity = { place_id: "C", name: "Dublin", secondary_text: null, lat: 53.35, lng: -6.26, timezone: "Europe/Dublin", viewport: null };

function planned(ids = ORIGINAL, places = ids.map((id) => `P_${id}`)): PlannerState {
  let s = initialState([ids[0], ids[1]]);
  for (const id of ids.slice(2)) s = reducer(s, { type: "stopAdded", id });
  s = reducer(s, { type: "citySelected", city: CITY, query: "Dublin" });
  ids.forEach((id, i) => {
    s = reducer(s, { type: "stopSelected", id, place: { place_id: places[i], lat: 53.34, lng: -6.26, secondary_text: null, timezone: "Europe/Dublin" }, label: `Stop ${id}` });
  });
  s = reducer(s, { type: "dateChanged", date: "2026-10-21" });
  s = reducer(s, { type: "timeChanged", time: "10:00" });
  return { ...s, result: { plan: planResult(plan(ids, s.revision, "op-plan")), revision: s.revision } };
}

const started = (s = planned(), op = "op-x") => reducer(s, { type: "exhaustiveStarted", operationId: op });
const progress = (s: PlannerState, evaluated: number, complete: number, failed: number, op = "op-x", rev?: number) =>
  reducer(s, {
    type: "streamEvent",
    operationId: op,
    event: streamEvent({ operation_id: op, input_revision: rev ?? s.revision, type: "exhaustive_progress", evaluated, complete, failed, total: 24 }, "e", "exhaustive"),
  });
const end = (s: PlannerState, result: unknown, op = "op-x") =>
  reducer(s, {
    type: "streamEnded",
    operationId: op,
    end: {
      kind: "terminal",
      event: streamEvent({ operation_id: op, input_revision: s.revision, type: "terminal", outcome: { outcome_type: "exhaustive", result } }, "e", "exhaustive") as never,
    },
  });

// ---- validation ---------------------------------------------------------------

test("exhaustive results must be internally consistent", () => {
  assert.equal(exhaustiveResult(finished(1)).status, "all_complete");
  assert.equal(exhaustiveResult(interrupted(1)).winner_plan, null);
  const bad = (patch: Record<string, unknown>, base: Record<string, unknown> = finished(1)) => () =>
    exhaustiveResult({ ...base, ...patch });
  assert.throws(bad({ complete_orders: 23 }), ValidationError); // counts vs candidates
  assert.throws(bad({ search_complete: false }), ValidationError); // completeness vs counts
  assert.throws(bad({ winner_plan: plan(WINNER, 1, "op-x") }, interrupted(1)), ValidationError); // interrupted cannot offer a plan
  assert.throws(bad({ winner_plan: null }), ValidationError); // finished with a winner must carry it
  assert.throws(bad({ winner_plan: plan(ORIGINAL, 1, "op-x") }), ValidationError); // plan must match the winner order
  const failedOriginal = { ...complete(ORIGINAL, 20, true), status: "failed", completion_at: null, elapsed_seconds: null, failure_reason: "no_route" };
  assert.throws(bad({ original: failedOriginal }), ValidationError); // saving needs a complete original
  const sneaky = { ...complete(WINNER, 10), timeline: [...timeline(["c"]), { item_type: "unknown_stop", instance_id: "a", place_id: "P_a", name: "a" }] };
  assert.throws(bad({ winner: sneaky }), ValidationError); // a "complete" order with unknown stops
});

test("exhaustive progress and outcomes are only valid in exhaustive streams", async () => {
  const id = { operationId: "op-x", inputRevision: 1 };
  const start = line({ operation_id: "op-x", input_revision: 1, type: "operation_start", phases: ["verification", "exhaustive_search"] });
  const tick = line({ operation_id: "op-x", input_revision: 1, type: "exhaustive_progress", evaluated: 1, complete: 1, failed: 0, total: 24 });
  const done = line({ operation_id: "op-x", input_revision: 1, type: "terminal", outcome: { outcome_type: "exhaustive", result: finished(1) } });
  assert.equal((await readPlanStream(ndjsonStream([start, tick, done]), { ...id, kind: "exhaustive" }, () => {})).kind, "terminal");
  for (const kind of ["plan", "compare"] as const) {
    const r = await readPlanStream(ndjsonStream([start, tick, done]), { ...id, kind }, () => {});
    assert.deepEqual(r, { kind: "incomplete", reason: "malformed" });
  }
  assert.throws(() => streamEvent({ operation_id: "o", input_revision: 1, type: "exhaustive_progress", evaluated: 3, complete: 1, failed: 1, total: 24 }, "e", "exhaustive"), ValidationError);
});

// ---- offering and request -----------------------------------------------------

test("offered only on a current complete plan of exactly four distinct destinations", () => {
  assert.equal(canRunExhaustive(planned()), true);
  assert.equal(canRunExhaustive(planned(["a", "b", "c"])), false);
  assert.equal(canRunExhaustive(planned(ORIGINAL, ["P_a", "P_b", "P_a", "P_d"])), false); // repeated destination
  assert.equal(canRunExhaustive(reducer(planned(), { type: "modeChanged", mode: "walking" })), false); // stale
});

test("the request copies the plan's resolved stays and sends no pins", () => {
  const req = exhaustiveRequest(planned());
  assert.ok(req);
  assert.deepEqual(req.stops.map((s) => [s.instance_id, s.stay_minutes]), [["a", 0], ["b", 60], ["c", 60], ["d", 0]]);
  assert.equal("fixed_first" in req, false);
  assert.equal("fixed_last" in req, false);
});

// ---- running ------------------------------------------------------------------

test("progress counts come from real events; stale and regressing events are ignored", () => {
  let s = started();
  assert.equal(progressLabel(s.operation), "Checking your places…");
  s = reducer(s, { type: "streamEvent", operationId: "op-x", event: streamEvent({ operation_id: "op-x", input_revision: s.revision, type: "phase_start", phase: "exhaustive_search" }, "e", "exhaustive") });
  s = progress(s, 5, 4, 1);
  assert.equal(progressLabel(s.operation), "Evaluated 5 of 24 orders (4 completed, 1 failed)…");
  assert.doesNotMatch(progressLabel(s.operation) ?? "", /%/);
  assert.equal(progressLabel(progress(s, 3, 3, 0).operation), progressLabel(s.operation)); // regression ignored
  assert.equal(progress(s, 9, 9, 0, "op-other"), s); // another operation
  assert.equal(progress(s, 9, 9, 0, "op-x", s.revision + 7), s); // another revision
});

test("a finished search is stored for review; the displayed plan is unchanged", () => {
  const s0 = started();
  const s = end(s0, finished(s0.revision));
  assert.equal(s.operation.kind, "idle");
  assert.equal(s.result, s0.result); // same plan object, not replaced
  assert.equal(s.exhaustive?.result.status, "all_complete");
  assert.ok(acceptableExhaustive(s));
});

test("Use this order applies order, explicit stays and the verified timeline; pins follow identity", () => {
  const s0 = started();
  const s = end(s0, finished(s0.revision));
  const a = reducer(s, { type: "exhaustiveAccepted" });
  assert.deepEqual(a.draft.stops.map((x) => x.id), WINNER);
  assert.deepEqual(a.draft.stops.map((x) => x.stayMinutes), WINNER.map((id) => STAYS[id]));
  assert.equal(a.result?.plan.operation_id, "op-x");
  assert.equal(a.revision, s.revision + 1);
  assert.equal(a.result?.revision, a.revision);
  assert.equal(a.exhaustive, null);
  assert.equal(a.draft.pinFirst, false); // "c" is the new first stop: not silently pinned
  assert.equal(a.draft.pinLast, true); // "d" is still last: its pin is kept
});

test("an interrupted search shows a best-so-far order but can never be accepted", () => {
  const s0 = started();
  const s = end(s0, interrupted(s0.revision));
  assert.equal(s.exhaustive?.result.search_complete, false);
  assert.equal(acceptableExhaustive(s), null);
  assert.equal(reducer(s, { type: "exhaustiveAccepted" }), s);
});

test("edits stop the search, invalidate results and reject late events", () => {
  const running = started();
  const edited = reducer(running, { type: "stayChanged", id: "b", minutes: 30 });
  assert.equal(edited.operation.kind, "idle");
  assert.match((edited.notice as { message: string }).message, /Search stopped because the trip details changed/);
  assert.equal(end(edited, finished(running.revision)), edited); // late terminal ignored
  const done = end(started(), finished(started().revision));
  const after = reducer(done, { type: "modeChanged", mode: "walking" });
  assert.equal(after.exhaustive, null);
  assert.equal(acceptableExhaustive(after), null);
});

test("cancel, aborted and malformed streams keep the previous plan", () => {
  const s0 = started();
  const cancelled = reducer(s0, { type: "cancelRequested" });
  assert.equal((cancelled.notice as { message: string }).message, EXHAUSTIVE_CANCELLED);
  assert.equal(cancelled.result, s0.result);
  const aborted = reducer(s0, { type: "streamEnded", operationId: "op-x", end: { kind: "aborted" } });
  assert.equal((aborted.notice as { message: string }).message, EXHAUSTIVE_CANCELLED);
  const broken = reducer(s0, { type: "streamEnded", operationId: "op-x", end: { kind: "incomplete", reason: "malformed" } });
  assert.equal((broken.notice as { message: string }).message, EXHAUSTIVE_INCOMPLETE);
  assert.equal(broken.result, s0.result);
  assert.equal(broken.exhaustive, null);
});

test("starting another operation supersedes the search", () => {
  const s = reducer(started(), { type: "planStarted", operationId: "op-plan-2" });
  assert.equal(s.operation.kind === "running" && s.operation.purpose, "plan");
  assert.equal(progress(s, 2, 2, 0), s); // its progress no longer applies
});
