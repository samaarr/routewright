import { test } from "node:test";
import assert from "node:assert/strict";
import { ValidationError, planResult, selectedCity, streamEvent, suggestions } from "../../lib/v2/validate.ts";
import { ev, leg, plan, stop } from "./fixtures.ts";

test("valid events are rebuilt with explicit discriminators", () => {
  const e = streamEvent(ev("stop_ready", { stop_index: 0, stop: stop("a") }));
  assert.equal(e.type, "stop_ready");
  if (e.type === "stop_ready") {
    assert.equal(e.stop.item_type, "stop");
    assert.equal(e.stop.hours_detail?.exceptions_unconfirmed, true);
  }
});

test("unknown event types and discriminators are rejected", () => {
  assert.throws(() => streamEvent(ev("surprise")), ValidationError);
  assert.throws(() => streamEvent(ev("leg_ready", { leg_index: 0, leg: { ...leg("a", "b"), item_type: "boat" }, completed_legs: 1, total_legs: 1 })), ValidationError);
});

test("missing or mistyped fields are rejected", () => {
  const bad = stop("a");
  delete (bad as Record<string, unknown>).arrive_at;
  assert.throws(() => streamEvent(ev("stop_ready", { stop_index: 0, stop: bad })), ValidationError);
  assert.throws(() => streamEvent(ev("stop_ready", { stop_index: 0, stop: stop("a", { lat: "53" }) })), ValidationError);
  assert.throws(() => streamEvent(ev("stop_ready", { stop_index: 0, stop: stop("a", { arrive_at: "yesterday" }) })), ValidationError);
  assert.throws(() => streamEvent({ type: "phase_start", phase: "routing" }), ValidationError); // no identity
});

test("progress counts must be consistent", () => {
  assert.throws(
    () => streamEvent(ev("leg_ready", { leg_index: 0, leg: leg("a", "b"), completed_legs: 3, total_legs: 2 })),
    ValidationError,
  );
});

test("a 'complete' plan containing unknown stops is not success", () => {
  const forged = plan("complete", { timeline: [stop("a"), { item_type: "unknown_stop", instance_id: "b", place_id: "P", name: "B" }] });
  assert.throws(() => planResult(forged), ValidationError);
});

test("refresh outcomes are not valid terminal events for planning", () => {
  assert.throws(
    () => streamEvent(ev("terminal", { outcome: { outcome_type: "refresh", leg: leg("a", "b") } })),
    ValidationError,
  );
});

test("partial plans keep unknown downstream stops without timing", () => {
  const p = planResult(plan("partial"));
  assert.equal(p.result_type, "partial");
  const last = p.timeline[p.timeline.length - 1];
  assert.equal(last.item_type, "unknown_stop");
  assert.equal("arrive_at" in last, false);
});

test("suggestion and city payloads are validated", () => {
  assert.deepEqual(suggestions({ status: "no_matches", suggestions: [] }), { status: "no_matches", suggestions: [] });
  assert.throws(() => suggestions({ status: "no_matches", suggestions: [{ place_id: "x", primary_text: "X" }] }), ValidationError);
  assert.throws(() => selectedCity({ place_id: "c", name: "C", lat: 1, lng: 1, timezone: "Europe/Dublin", viewport: { low_lat: 5, low_lng: 0, high_lat: 1, high_lng: 1 } }), ValidationError);
});
