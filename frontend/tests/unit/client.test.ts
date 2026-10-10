import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { ApiError, getExperiments, streamPlan, suggestCities } from "../../lib/v2/client.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  globalThis.fetch = async () =>
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json", ...headers },
    });
}

async function kindOf(p: Promise<unknown>): Promise<string> {
  try {
    await p;
    return "ok";
  } catch (e) {
    assert.ok(e instanceof ApiError);
    return `${e.kind}:${e.code}`;
  }
}

test("no matches is a successful empty search", async () => {
  respond(200, { status: "no_matches", suggestions: [] });
  assert.deepEqual(await suggestCities("zz", "tok-12345678"), { status: "no_matches", suggestions: [] });
});

test("per-IP limit, provider allowance, usage control and provider failure are distinct", async () => {
  respond(429, { error: "rate_limit_exceeded", detail: "Too many requests" }, { "retry-after": "30" });
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "rate_limited:rate_limit_exceeded");
  respond(429, { detail: { error: "quota_exceeded", message: "used up" } });
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "quota_exceeded:quota_exceeded");
  respond(503, { detail: { error: "usage_control_unavailable", message: "x" } });
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "usage_control:usage_control_unavailable");
  respond(503, { detail: { error: "provider_unavailable", message: "x" } });
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "provider_unavailable:provider_unavailable");
  respond(422, { error: "validation_error", errors: [] });
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "invalid_input:validation_error");
});

test("malformed success bodies are errors, not empty results", async () => {
  respond(200, { status: "ok", suggestions: [{ place_id: 5 }] });
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "unexpected:malformed_response");
});

test("network failure is reported as such", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };
  assert.equal(await kindOf(suggestCities("du", "tok-12345678")), "network:network");
});

test("a plan response that is not NDJSON is incomplete, not success", async () => {
  respond(200, { result_type: "complete" });
  const end = await streamPlan(
    { operation_id: "op", input_revision: 0 } as never,
    () => {},
    new AbortController().signal,
  );
  assert.deepEqual(end, { kind: "incomplete", reason: "malformed" });
});

test("pre-stream HTTP errors throw with the server's code", async () => {
  respond(422, { detail: { error: "departure_nonexistent", message: "skipped" } });
  const err = await streamPlan({ operation_id: "op", input_revision: 0 } as never, () => {}, new AbortController().signal).catch((e) => e);
  assert.ok(err instanceof ApiError && err.kind === "departure" && err.message === "skipped");
});

test("experiment availability fails closed", async () => {
  respond(200, { exhaustive_four: true });
  assert.deepEqual(await getExperiments(), { exhaustive_four: true });
  for (const [status, body] of [[200, { exhaustive_four: "yes" }], [200, {}], [403, { exhaustive_four: true }], [500, "boom"], [200, "not json"]] as const) {
    respond(status, body);
    assert.deepEqual(await getExperiments(), { exhaustive_four: false }, `${status} ${JSON.stringify(body)}`);
  }
  globalThis.fetch = async () => {
    throw new TypeError("network down");
  };
  assert.deepEqual(await getExperiments(), { exhaustive_four: false });
});
