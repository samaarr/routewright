import { test } from "node:test";
import assert from "node:assert/strict";
import { SuggestionSearch, type SearchState } from "../../lib/v2/search.ts";
import type { VSuggestions } from "../../lib/v2/validate.ts";

function harness() {
  let now = 0;
  const timers: { at: number; fn: () => void; id: number }[] = [];
  let nextId = 1;
  const requests: { query: string; context: string; signal: AbortSignal; resolve: (v: VSuggestions) => void }[] = [];
  const states: SearchState[] = [];
  const search = new SuggestionSearch({
    setTimer: (fn, ms) => {
      const t = { at: now + ms, fn, id: nextId++ };
      timers.push(t);
      return t.id;
    },
    clearTimer: (h) => {
      const i = timers.findIndex((t) => t.id === h);
      if (i >= 0) timers.splice(i, 1);
    },
    fetch: (query, context, signal) =>
      new Promise((resolve) => requests.push({ query, context, signal, resolve })),
    onState: (s) => states.push(s),
  });
  const advance = (ms: number) => {
    now += ms;
    for (const t of [...timers].sort((a, b) => a.at - b.at)) {
      if (t.at <= now) {
        timers.splice(timers.indexOf(t), 1);
        t.fn();
      }
    }
  };
  return { search, requests, states, advance };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const result = (id: string): VSuggestions => ({ status: "ok", suggestions: [{ place_id: id, primary_text: id, secondary_text: null }] });

test("quick typing makes one request after a 300 ms pause", () => {
  const h = harness();
  for (const q of ["du", "dub", "dubl", "dubli"]) {
    h.search.input(q, "");
    h.advance(100);
  }
  assert.equal(h.requests.length, 0);
  h.advance(300);
  assert.deepEqual(h.requests.map((r) => r.query), ["dubli"]);
});

test("automatic search needs two characters after whitespace normalisation", () => {
  const h = harness();
  h.search.input("  d  ", "");
  h.advance(1000);
  assert.equal(h.requests.length, 0);
  h.search.searchNow(" d ", ""); // explicit Search allows one character
  assert.deepEqual(h.requests.map((r) => r.query), ["d"]);
  h.search.searchNow("   ", "");
  assert.equal(h.requests.length, 1); // blank never searched
});

test("a newer search aborts the older one and stale responses are ignored", async () => {
  const h = harness();
  h.search.searchNow("trin", "city-A");
  h.search.searchNow("trinity", "city-A");
  assert.equal(h.requests[0].signal.aborted, true);
  h.requests[1].resolve(result("new"));
  h.requests[0].resolve(result("old"));
  await tick();
  const last = h.states[h.states.length - 1];
  assert.ok(last.kind === "results" && last.result.suggestions[0].place_id === "new");
});

test("a changed search context (new city) never shows old suggestions", async () => {
  const h = harness();
  h.search.searchNow("main street", "city-A");
  h.search.input("main street", "city-B");
  h.advance(300);
  h.requests[0].resolve(result("A"));
  await tick();
  assert.ok(!h.states.some((s) => s.kind === "results" && s.result.suggestions[0].place_id === "A"));
  assert.equal(h.requests[1].context, "city-B");
});

test("the same query and context is not requested again", async () => {
  const h = harness();
  h.search.input("dublin", "");
  h.advance(300);
  h.requests[0].resolve(result("d"));
  await tick();
  h.search.input("dublin ", ""); // same after normalisation
  h.advance(300);
  assert.equal(h.requests.length, 1);
});

test("cancel stops pending timers and in-flight requests", () => {
  const h = harness();
  h.search.input("dub", "");
  h.search.cancel();
  h.advance(1000);
  assert.equal(h.requests.length, 0);
  h.search.searchNow("dub", "");
  h.search.cancel();
  assert.equal(h.requests[0].signal.aborted, true);
});
