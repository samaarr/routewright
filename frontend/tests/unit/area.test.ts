import { test } from "node:test";
import assert from "node:assert/strict";
import { areaStatus } from "../../lib/v2/area.ts";

const vp = { low_lat: 53.22, low_lng: -6.45, high_lat: 53.42, high_lng: -6.05 };

test("inside, outside and boundary points", () => {
  assert.equal(areaStatus(vp, 53.34, -6.26), "inside");
  assert.equal(areaStatus(vp, 53.01, -6.33), "outside");
  assert.equal(areaStatus(vp, 53.42, -6.05), "inside");
  assert.equal(areaStatus(vp, 53.4201, -6.2), "outside");
});

test("viewports crossing the antimeridian wrap longitude", () => {
  const fiji = { low_lat: -19, low_lng: 177, high_lat: -16, high_lng: -179 };
  assert.equal(areaStatus(fiji, -18, 179.5), "inside");
  assert.equal(areaStatus(fiji, -18, -179.5), "inside");
  assert.equal(areaStatus(fiji, -18, 170), "outside");
});

test("missing viewport means the check is unavailable, not inside", () => {
  assert.equal(areaStatus(null, 53.34, -6.26), "unavailable");
});
