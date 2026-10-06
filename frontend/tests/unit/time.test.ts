import { test } from "node:test";
import assert from "node:assert/strict";
import { checkDeparture } from "../../lib/v2/time.ts";

test("ordinary destination-local time converts with the city's offset", () => {
  const r = checkDeparture("2026-10-21", "10:00", "Europe/Dublin");
  assert.equal(r.kind, "ok");
  if (r.kind === "ok") {
    assert.equal(new Date(r.utcMs).toISOString(), "2026-10-21T09:00:00.000Z");
    assert.equal(r.offsetLabel, "UTC+01:00");
  }
  const tokyo = checkDeparture("2026-10-21", "10:00", "Asia/Tokyo");
  assert.ok(tokyo.kind === "ok" && new Date(tokyo.utcMs).toISOString() === "2026-10-21T01:00:00.000Z");
});

test("skipped spring-forward time is nonexistent", () => {
  assert.equal(checkDeparture("2027-03-28", "01:30", "Europe/Dublin").kind, "nonexistent");
});

test("repeated fall-back time offers both occurrences chronologically with offsets", () => {
  const r = checkDeparture("2026-10-25", "01:30", "Europe/Dublin");
  assert.equal(r.kind, "ambiguous");
  if (r.kind === "ambiguous") {
    assert.deepEqual(r.options.map((o) => [o.occurrence, new Date(o.utcMs).toISOString(), o.offsetLabel]), [
      [1, "2026-10-25T00:30:00.000Z", "UTC+01:00"],
      [2, "2026-10-25T01:30:00.000Z", "UTC+00:00"],
    ]);
  }
});

test("southern-hemisphere fall-back is also chronological", () => {
  const r = checkDeparture("2026-04-05", "02:30", "Australia/Sydney");
  assert.ok(r.kind === "ambiguous");
  if (r.kind === "ambiguous") assert.deepEqual(r.options.map((o) => o.offsetLabel), ["UTC+11:00", "UTC+10:00"]);
});

test("invalid dates and missing inputs are not converted", () => {
  assert.equal(checkDeparture("2026-02-30", "10:00", "Europe/Dublin").kind, "invalid");
  assert.equal(checkDeparture("2026-10-21", "", "Europe/Dublin").kind, "incomplete");
  assert.equal(checkDeparture("2026-10-21", "10:00", null).kind, "incomplete");
  assert.equal(checkDeparture("2026-10-21", "10:00", "Not/AZone").kind, "invalid");
});
