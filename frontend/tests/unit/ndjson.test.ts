import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_LINE_CHARS, readPlanStream } from "../../lib/v2/ndjson.ts";
import type { VStreamEvent } from "../../lib/v2/validate.ts";
import { OP, REV, START, TERMINAL_OK, ev, line, ndjsonStream, stop } from "./fixtures.ts";

const id = { operationId: OP, inputRevision: REV };

async function read(chunks: (string | Uint8Array)[], opts?: { close?: boolean }) {
  const seen: VStreamEvent[] = [];
  const end = await readPlanStream(ndjsonStream(chunks, opts), id, (e) => seen.push(e));
  return { end, seen };
}

test("events split across chunk boundaries (incl. multi-byte text) are reassembled", async () => {
  const text = line(START) + line(ev("stop_ready", { stop_index: 0, stop: stop("a", { name: "Café Ó" }) })) + line(TERMINAL_OK);
  const bytes = new TextEncoder().encode(text);
  const chunks = [bytes.slice(0, 7), bytes.slice(7, 151), bytes.slice(151, 152), bytes.slice(152)];
  const { end, seen } = await read(chunks);
  assert.equal(end.kind, "terminal");
  assert.equal(seen.length, 2);
  const s = seen[1];
  assert.ok(s.type === "stop_ready" && s.stop.name === "Café Ó");
});

test("a stream ending without a terminal event is incomplete, not success", async () => {
  const { end } = await read([line(START), line(ev("phase_start", { phase: "routing" }))]);
  assert.deepEqual(end, { kind: "incomplete", reason: "truncated" });
});

test("a truncated final line is incomplete", async () => {
  const { end } = await read([line(START), line(TERMINAL_OK).slice(0, 40)]);
  assert.equal(end.kind, "incomplete");
});

test("malformed JSON or shapes make the stream incomplete", async () => {
  assert.deepEqual((await read([line(START), "{not json}\n"])).end, { kind: "incomplete", reason: "malformed" });
  assert.deepEqual((await read([line(START), line(ev("leg_ready", { leg_index: 0 }))])).end, { kind: "incomplete", reason: "malformed" });
});

test("events for another operation or revision are rejected", async () => {
  assert.deepEqual((await read([line(ev("operation_start", { phases: [] }, "op-old"))])).end, { kind: "incomplete", reason: "wrong_operation" });
  assert.deepEqual((await read([line(START), line(ev("phase_start", { phase: "routing" }, OP, REV - 1))])).end, { kind: "incomplete", reason: "wrong_operation" });
});

test("the stream must start with operation_start", async () => {
  assert.deepEqual((await read([line(TERMINAL_OK)])).end, { kind: "incomplete", reason: "out_of_order" });
});

test("oversized lines are refused without unbounded buffering", async () => {
  const huge = "x".repeat(MAX_LINE_CHARS + 10);
  assert.deepEqual((await read([line(START), huge], { close: false })).end, { kind: "incomplete", reason: "oversized" });
});

test("anything after the terminal event is ignored", async () => {
  const { end, seen } = await read([line(START), line(TERMINAL_OK), line(ev("phase_start", { phase: "routing" }))]);
  assert.equal(end.kind, "terminal");
  assert.equal(seen.length, 1);
});

test("aborting stops reading", async () => {
  const controller = new AbortController();
  controller.abort();
  const end = await readPlanStream(ndjsonStream([line(START)], { close: false }), id, () => {}, controller.signal);
  assert.deepEqual(end, { kind: "aborted" });
});
