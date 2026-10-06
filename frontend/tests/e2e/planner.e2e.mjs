// Browser integration tests for the v2 planner against the production build.
//
// The backend is mocked at the network layer (page.route on the configured
// API origin), so these tests exercise the real UI, reducer, validators and
// NDJSON reader without any Google or backend calls. Google Maps requests are
// blocked. Progressive (chunk-by-chunk) streaming cannot be produced with
// page.route; ordering/late-event/truncation behaviour is covered by the Node
// unit tests (tests/unit), and here by whole-body and never-answered streams.
//
// Run: npm run build && npm run test:e2e

import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:https";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, afterEach, before, beforeEach, describe, test } from "node:test";
import { chromium } from "playwright";

const PORT = 3198;
const ORIGIN = `http://127.0.0.1:${PORT}`;
const API = "https://api.routewright.invalid";

const VIEWPORT_DUBLIN = { low_lat: 53.22, low_lng: -6.45, high_lat: 53.42, high_lng: -6.05 };
const CITIES = {
  C_dublin: { place_id: "C_dublin", name: "Dublin", secondary_text: "Ireland", lat: 53.35, lng: -6.26, timezone: "Europe/Dublin", viewport: VIEWPORT_DUBLIN },
  C_london: { place_id: "C_london", name: "London", secondary_text: "UK", lat: 51.5, lng: -0.12, timezone: "Europe/London", viewport: null },
};
const PLACES = {
  P_trinity: { label: "Trinity College", lat: 53.3438, lng: -6.2546 },
  P_guinness: { label: "Guinness Storehouse", lat: 53.3419, lng: -6.2867 },
  P_glen: { label: "Glendalough", lat: 53.0107, lng: -6.329 },
  P_x: { label: "X Bar", lat: 53.345, lng: -6.26 },
  P_trin: { label: "Trinity Street", lat: 53.344, lng: -6.263 },
};

let server;
let browser;
let page;
let log; // requests seen by the mock API
let planMode; // how the mocked stream answers
let suggestDelays; // query -> ms
let pendingPlan; // resolve fn for a held stream
let refreshMode; // how the mocked refresh stream answers
let slow; // local HTTPS server that streams refresh events progressively
let releaseRefresh; // lets a progressive refresh stream send its terminal event

function cors(extra = {}) {
  return {
    "access-control-allow-origin": ORIGIN,
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "POST",
    ...extra,
  };
}

function json(route, status, body, headers = {}) {
  return route.fulfill({ status, headers: cors({ "content-type": "application/json", ...headers }), body: JSON.stringify(body) });
}

function planEvents(req, mode) {
  const op = { operation_id: req.operation_id, input_revision: req.input_revision };
  const ev = (type, extra) => ({ ...op, type, ...extra });
  const out = [ev("operation_start", { phases: ["verification", "routing"] }), ev("phase_start", { phase: "verification" }), ev("phase_complete", { phase: "verification" }), ev("phase_start", { phase: "routing" })];
  let t = Date.parse("2026-10-21T09:00:00Z");
  const timeline = [];
  const n = req.stops.length;
  const failAt = mode === "partial" ? 0 : -1;
  for (let i = 0; i < n; i++) {
    const s = req.stops[i];
    const stay = s.stay_minutes ?? (i === 0 || i === n - 1 ? 0 : 60);
    const isGuinness = s.selection.place_id === "P_guinness";
    const stop = {
      item_type: "stop", instance_id: s.instance_id, place_id: s.selection.place_id, name: s.selection.name, address: null,
      lat: s.selection.lat, lng: s.selection.lng, arrive_at: new Date(t).toISOString(), depart_at: new Date(t + stay * 60000).toISOString(),
      stay_minutes: stay, stay_source: s.stay_minutes === undefined ? "default" : "user", map_url: "https://www.google.com/maps/search/?api=1&query=1,1",
      hours_status: isGuinness ? "closes_during_visit" : i === n - 1 ? "unknown" : "open",
      hours_detail: isGuinness
        ? { closes_at: "10:30", hours_source: "weekly", exceptions_unconfirmed: true }
        : i === n - 1 ? { unknown_reason: "missing" } : { closes_at: "17:00", hours_source: "date_specific", coverage_start: "2026-10-20", coverage_end: "2026-10-26" },
    };
    timeline.push(stop);
    out.push(ev("stop_ready", { stop_index: i, stop }));
    if (i === n - 1) break;
    out.push(ev("leg_progress", { leg_index: i, total_legs: n - 1 }));
    const next = req.stops[i + 1];
    if (i === failAt) {
      const failed = { item_type: "failed_leg", from_stop_id: s.instance_id, to_stop_id: next.instance_id, from_name: s.selection.name, to_name: next.selection.name, failure_reason: "no_route", failure_message: "No route" };
      timeline.push(failed);
      out.push(ev("leg_ready", { leg_index: i, leg: failed, completed_legs: i, total_legs: n - 1 }));
      for (let j = i + 1; j < n; j++) timeline.push({ item_type: "unknown_stop", instance_id: req.stops[j].instance_id, place_id: req.stops[j].selection.place_id, name: req.stops[j].selection.name });
      break;
    }
    const depart = t + stay * 60000;
    const leg = { item_type: "leg", from_stop_id: s.instance_id, to_stop_id: next.instance_id, from_name: s.selection.name, to_name: next.selection.name, mode: req.mode, duration_seconds: 1200, distance_meters: 900, depart_at: new Date(depart).toISOString(), arrive_at: new Date(depart + 1200000).toISOString(), summary: "Bus 15, 20 min", map_url: "https://www.google.com/maps/dir/?api=1" };
    timeline.push(leg);
    out.push(ev("leg_ready", { leg_index: i, leg, completed_legs: i + 1, total_legs: n - 1 }));
    t = depart + 1200000;
  }
  const warnings = [];
  req.stops.forEach((s, i) => {
    if (s.selection.place_id === "P_glen") warnings.push({ severity: "warning", message: "Outside the selected city's suggested area.", affects_stop_index: i, affects_instance_id: s.instance_id, code: "outside_city_area" });
  });
  const result = {
    ...op, result_type: mode === "partial" ? "partial" : "complete", city: "Dublin", mode: req.mode, timezone: req.departure.timezone,
    timeline, overview_map_url: "https://www.google.com/maps/dir/?api=1", warnings,
    ...(mode === "partial" ? { failed_at_leg_index: 0, failure_reason: "no_route" } : {}),
  };
  if (mode !== "partial") out.push(ev("phase_complete", { phase: "routing" }));
  out.push(ev("terminal", { outcome: { outcome_type: "plan", result } }));
  return out;
}

function refreshEvents(req, mode) {
  const op = { operation_id: req.operation_id, input_revision: req.input_revision };
  const ev = (type, extra) => ({ ...op, type, ...extra });
  const k = req.leg_index;
  const n = req.stops.length;
  const out = [ev("operation_start", { phases: ["verification", "routing"] }), ev("phase_start", { phase: "verification" }), ev("phase_complete", { phase: "verification" }), ev("phase_start", { phase: "routing" })];
  const suffix = [];
  let depart = Date.parse(req.planned_departure);
  for (let i = k; i < n - 1; i++) {
    const s = req.stops[i];
    const next = req.stops[i + 1];
    out.push(ev("leg_progress", { leg_index: i, total_legs: n - 1 - k }));
    const failAt = mode === "partial" ? k + 1 : mode === "fail-first" ? k : -1;
    if (i === failAt) {
      const failed = { item_type: "failed_leg", from_stop_id: s.instance_id, to_stop_id: next.instance_id, from_name: s.selection.name, to_name: next.selection.name, failure_reason: "no_route" };
      suffix.push(failed);
      out.push(ev("leg_ready", { leg_index: i, leg: failed, completed_legs: i - k, total_legs: n - 1 - k }));
      for (let j = i + 1; j < n; j++) suffix.push({ item_type: "unknown_stop", instance_id: req.stops[j].instance_id, place_id: req.stops[j].selection.place_id, name: req.stops[j].selection.name });
      break;
    }
    const arrive = depart + 35 * 60000;
    const leg = { item_type: "leg", from_stop_id: s.instance_id, to_stop_id: next.instance_id, from_name: s.selection.name, to_name: next.selection.name, mode: req.mode, duration_seconds: 2100, distance_meters: 900, depart_at: new Date(depart).toISOString(), arrive_at: new Date(arrive).toISOString(), summary: "Bus 99 (refreshed)", map_url: "https://www.google.com/maps/dir/?api=1" };
    const stay = next.stay_minutes ?? (i + 1 === n - 1 ? 0 : 60);
    const stop = { item_type: "stop", instance_id: next.instance_id, place_id: next.selection.place_id, name: next.selection.name, address: null, lat: next.selection.lat, lng: next.selection.lng, arrive_at: new Date(arrive).toISOString(), depart_at: new Date(arrive + stay * 60000).toISOString(), stay_minutes: stay, stay_source: "default", map_url: "x", hours_status: "unknown", hours_detail: { unknown_reason: "missing" } };
    suffix.push(leg, stop);
    out.push(ev("leg_ready", { leg_index: i, leg, completed_legs: i - k + 1, total_legs: n - 1 - k }));
    out.push(ev("stop_ready", { stop_index: i + 1, stop }));
    depart = arrive + stay * 60000;
  }
  const failed = suffix.some((i) => i.item_type === "failed_leg");
  const result = {
    ...op, result_type: failed ? "refresh_partial" : "refresh_complete", leg_index: k, planned_departure: req.planned_departure,
    timezone: req.departure.timezone, suffix, warnings: [],
    ...(failed ? { failed_at_leg_index: k + suffix.filter((i) => i.item_type === "leg").length, failure_reason: "no_route" } : {}),
  };
  out.push(ev("terminal", { outcome: { outcome_type: "refresh", result } }));
  return out;
}

async function apiRoute(route) {
  const req = route.request();
  if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors() });
  const path = new URL(req.url()).pathname;
  const body = JSON.parse(req.postData() || "{}");
  log.push({ path, body });
  if (path === "/api/v2/suggest/cities") {
    const q = body.query.toLowerCase();
    if (q === "rl") return json(route, 429, { error: "rate_limit_exceeded", detail: "Too many requests" }, { "retry-after": "60" });
    if (q === "qq") return json(route, 429, { detail: { error: "quota_exceeded", message: "The daily search allowance has been used up." } });
    if (q.startsWith("lon")) return json(route, 200, { status: "ok", suggestions: [{ place_id: "C_london", primary_text: "London", secondary_text: "UK" }] });
    if (q.startsWith("du")) return json(route, 200, { status: "ok", suggestions: [{ place_id: "C_dublin", primary_text: "Dublin", secondary_text: "Ireland" }] });
    return json(route, 200, { status: "no_matches", suggestions: [] });
  }
  if (path === "/api/v2/suggest/places") {
    const q = body.query.toLowerCase();
    if (suggestDelays[q]) await new Promise((r) => setTimeout(r, suggestDelays[q]));
    const pick = q === "trin" ? ["P_trin"] : q.startsWith("tri") ? ["P_trinity"] : q.startsWith("gui") ? ["P_guinness"] : q.startsWith("glen") ? ["P_glen"] : q === "x" ? ["P_x"] : [];
    if (!pick.length) return json(route, 200, { status: "no_matches", suggestions: [] });
    return json(route, 200, { status: "ok", suggestions: pick.map((id) => ({ place_id: id, primary_text: PLACES[id].label, secondary_text: "Dublin" })) });
  }
  if (path === "/api/v2/select/city") return json(route, 200, CITIES[body.place_id]);
  if (path === "/api/v2/select/place") {
    const p = PLACES[body.place_id];
    return json(route, 200, { place_id: body.place_id, lat: p.lat, lng: p.lng, secondary_text: "Dublin", timezone: "Europe/Dublin", source: "provider" });
  }
  if (path === "/api/v2/plan/stream") {
    if (planMode === "hang") {
      await new Promise((resolve) => { pendingPlan = resolve; });
      return route.abort().catch(() => {});
    }
    let text = planEvents(body, planMode).map((e) => JSON.stringify(e)).join("\n") + "\n";
    if (planMode === "truncated") text = text.split("\n").slice(0, -2).join("\n") + "\n"; // no terminal
    if (planMode === "malformed") text = text.replace('"stop_ready"', '"stop_ready","stop_index":"zero"').replace('"stop_index":0,', "");
    return route.fulfill({ status: 200, headers: cors({ "content-type": "application/x-ndjson" }), body: text });
  }
  if (path === "/api/v2/refresh/stream") {
    if (refreshMode === "progressive") return route.continue({ url: `https://127.0.0.1:${slow.port}${path}` });
    if (refreshMode === "hang") {
      await new Promise((resolve) => { pendingPlan = resolve; });
      return route.abort().catch(() => {});
    }
    const lines = refreshEvents(body, refreshMode).map((e) => JSON.stringify(e));
    let text = lines.join("\n") + "\n";
    if (refreshMode === "truncated") text = lines.slice(0, -1).join("\n") + "\n"; // no terminal
    if (refreshMode === "malformed") text = lines.slice(0, -1).join("\n") + '\n{"type":"terminal","outcome":' + "\n";
    return route.fulfill({ status: 200, headers: cors({ "content-type": "application/x-ndjson" }), body: text });
  }
  return json(route, 404, { error: "not_found" });
}

// Local HTTPS server (self-signed, test-only) that writes refresh events one
// at a time and holds the terminal event until the test releases it, so the
// UI can be observed mid-stream.
function startSlowServer() {
  const dir = mkdtempSync(join(tmpdir(), "rw-e2e-"));
  execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", join(dir, "k.pem"), "-out", join(dir, "c.pem"), "-days", "1", "-subj", "/CN=127.0.0.1"], { stdio: "ignore" });
  const server = createServer({ key: readFileSync(join(dir, "k.pem")), cert: readFileSync(join(dir, "c.pem")) }, (req, res) => {
    if (req.method === "OPTIONS") {
      res.writeHead(204, cors());
      return res.end();
    }
    let raw = "";
    req.on("data", (c) => { raw += c; });
    req.on("end", async () => {
      const body = JSON.parse(raw);
      log.push({ path: "/api/v2/refresh/stream", body });
      res.writeHead(200, cors({ "content-type": "application/x-ndjson" }));
      const events = refreshEvents(body, "ok");
      for (const e of events.slice(0, -1)) {
        res.write(JSON.stringify(e) + "\n");
        await new Promise((r) => setTimeout(r, 30));
      }
      await new Promise((resolve) => { releaseRefresh = resolve; });
      res.end(JSON.stringify(events.at(-1)) + "\n");
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, dir, port: server.address().port })));
}

const count = (path) => log.filter((r) => r.path === path).length;
const city = () => page.getByRole("combobox", { name: "City", exact: true }).filter({ visible: true });
const stopBox = (i) => page.getByRole("combobox", { name: `Stop ${i}`, exact: true }).filter({ visible: true });
const planButton = () => page.getByRole("button", { name: "Plan ↗" }).filter({ visible: true });

async function chooseCity(text = "Dublin") {
  await city().fill(text);
  const option = page.getByRole("option", { name: new RegExp(text.split(",")[0]) });
  await option.click();
  await page.getByTestId("city-context").filter({ visible: true }).waitFor();
}

async function chooseStop(i, text, optionName) {
  await stopBox(i).fill(text);
  await page.getByRole("option", { name: new RegExp(optionName) }).click();
  await page.locator(`[data-testid="stop-search-${i - 1}"] [aria-label="Selected"]`).filter({ visible: true }).waitFor();
}

async function fillReadyDraft() {
  await chooseCity("Dublin");
  await chooseStop(1, "trinity", "Trinity College");
  await chooseStop(2, "guinness", "Guinness Storehouse");
  await page.getByLabel("Departure date").filter({ visible: true }).fill("2026-10-21");
  await page.getByLabel("Departure time").filter({ visible: true }).fill("10:00");
}

describe("v2 planner (browser)", () => {
  before(async () => {
    server = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "-p", String(PORT)], {
      env: { ...process.env, NEXT_PUBLIC_API_URL: API },
      stdio: ["ignore", "pipe", "pipe"],
    });
    for (let i = 0; i < 150; i++) {
      try {
        if ((await fetch(ORIGIN)).ok) break;
      } catch {}
      await new Promise((r) => setTimeout(r, 100));
    }
    browser = await chromium.launch({ headless: true });
    slow = await startSlowServer();
  });

  after(async () => {
    await browser?.close();
    server?.kill("SIGTERM");
    slow?.server.close();
    if (slow) rmSync(slow.dir, { recursive: true, force: true });
  });

  afterEach(async () => {
    pendingPlan?.();
    releaseRefresh?.();
    await page?.close();
  });

  beforeEach(async () => {
    log = [];
    planMode = "complete";
    refreshMode = "ok";
    releaseRefresh = null;
    suggestDelays = {};
    pendingPlan = null;
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: true });
    await page.route(/googleapis|gstatic|google\.com/, (r) => r.abort());
    await page.route(`${API}/**`, apiRoute);
    await page.goto(ORIGIN);
  });

  test("typing waits 300 ms and selection must be explicit; editing invalidates it", async () => {
    await city().pressSequentially("Dub", { delay: 40 });
    await page.getByRole("option", { name: /Dublin/ }).waitFor();
    assert.equal(count("/api/v2/suggest/cities"), 1);
    assert.equal(log[0].body.query, "Dub");
    assert.match(log[0].body.session_token, /^[A-Za-z0-9_-]{8,64}$/);
    assert.equal(count("/api/v2/select/city"), 0); // suggestions alone select nothing
    await page.getByRole("option", { name: /Dublin/ }).click();
    await page.getByTestId("city-context").filter({ visible: true }).waitFor();
    assert.equal(count("/api/v2/select/city"), 1);
    const sel = log.find((r) => r.path === "/api/v2/select/city");
    assert.equal(sel.body.session_token, log[0].body.session_token); // concludes the session
    assert.match(await page.getByTestId("city-context").filter({ visible: true }).innerText(), /Europe\/Dublin/);
    await city().press("End");
    await city().pressSequentially("x");
    assert.equal(await page.getByTestId("city-context").count(), 0);
  });

  test("short text needs the explicit Search action", async () => {
    await chooseCity();
    await stopBox(1).fill("x");
    await page.waitForTimeout(500);
    assert.equal(count("/api/v2/suggest/places"), 0);
    await page.getByRole("button", { name: "Search Stop 1" }).filter({ visible: true }).click();
    await page.getByRole("option", { name: /X Bar/ }).waitFor();
    assert.equal(count("/api/v2/suggest/places"), 1);
    const req = log.find((r) => r.path === "/api/v2/suggest/places");
    assert.deepEqual(req.body.city_viewport, VIEWPORT_DUBLIN); // guided by the selected city
  });

  test("a stop search typed while the city is being confirmed still runs", async () => {
    await city().fill("Dublin");
    await page.getByRole("option", { name: /Dublin/ }).click();
    await stopBox(1).fill("trinity"); // before the city confirmation re-renders
    await page.getByRole("option", { name: /Trinity College/ }).waitFor();
    const last = log.filter((r) => r.path === "/api/v2/suggest/places").at(-1);
    assert.deepEqual(last.body.city_viewport, VIEWPORT_DUBLIN); // ran in the new city context
  });

  test("stale suggestions never replace newer ones", async () => {
    await chooseCity();
    suggestDelays = { trin: 900 };
    await stopBox(1).pressSequentially("trin", { delay: 20 });
    await page.waitForTimeout(400); // "trin" request now in flight (slow)
    await stopBox(1).pressSequentially("ity", { delay: 20 });
    await page.getByRole("option", { name: /Trinity College/ }).waitFor();
    await page.waitForTimeout(900); // let the slow, superseded response arrive
    assert.equal(await page.getByRole("option", { name: /Trinity Street/ }).count(), 0);
  });

  test("no matches, per-IP limit and allowance errors read differently", async () => {
    await city().fill("zz");
    await page.getByText("No matches. Try different words.").filter({ visible: true }).waitFor();
    await city().fill("rl");
    await page.getByText(/Too many searches/).filter({ visible: true }).waitFor();
    await city().fill("qq");
    await page.getByText("The daily search allowance has been used up.").filter({ visible: true }).waitFor();
  });

  test("city change keeps stops, durations and local clock; area and timezone checks update", async () => {
    await fillReadyDraft();
    await page.getByLabel("Stay at stop 1 in minutes (blank for the usual time)").filter({ visible: true }).fill("0");
    await page.getByRole("button", { name: "+ Add another stop" }).filter({ visible: true }).click();
    await chooseStop(3, "glen", "Glendalough");
    await page.getByText("Outside the selected city's suggested area.").filter({ visible: true }).waitFor();
    await chooseCity("London");
    assert.equal(await stopBox(1).inputValue(), "Trinity College");
    assert.equal(await page.getByLabel("Stay at stop 1 in minutes (blank for the usual time)").filter({ visible: true }).inputValue(), "0");
    assert.equal(await page.getByLabel("Departure time").filter({ visible: true }).inputValue(), "10:00");
    assert.match(await page.getByTestId("city-context").filter({ visible: true }).innerText(), /Europe\/London.*unavailable/s);
    assert.ok((await page.getByText(/different timezone/).filter({ visible: true }).count()) >= 1);
    assert.equal(await page.getByText("Outside the selected city's suggested area.").filter({ visible: true }).count(), 0);
    assert.equal(await planButton().isDisabled(), true);
    assert.equal(count("/api/v2/plan/stream"), 0);
  });

  test("edits make no routing requests; one Plan starts one operation and renders hours", async () => {
    await fillReadyDraft();
    await page.getByLabel("Stay at stop 2 in minutes (blank for the usual time)").filter({ visible: true }).fill("90");
    await page.getByRole("button", { name: "+ Add another stop" }).filter({ visible: true }).click();
    await chooseStop(3, "trinity", "Trinity College");
    assert.equal(count("/api/v2/plan/stream"), 0);
    await planButton().click();
    await page.getByTestId("current-result").waitFor();
    assert.equal(count("/api/v2/plan/stream"), 1);
    const req = log.find((r) => r.path === "/api/v2/plan/stream").body;
    assert.equal(req.departure.timezone, "Europe/Dublin");
    assert.equal(req.stops[1].stay_minutes, 90);
    assert.ok(!("stay_minutes" in req.stops[0]));
    const text = await page.getByTestId("current-result").innerText();
    assert.match(text, /usual weekly hours; holiday hours not confirmed/);
    assert.match(text, /Closes at 10:30, during your visit/);
    assert.match(text, /hours for this date/);
    assert.match(text, /Opening hours unavailable/);
    assert.match(text, /Stay 90 min \(your choice\)/);
    // Travel (20 min) plus the 90 min stay shifts the next departure: 10:20 → 11:50 → 12:10 arrival.
    assert.match(text, /leave 11:50/);
    assert.match(text, /12:10/);
  });

  test("partial failure shows unknown downstream times", async () => {
    planMode = "partial";
    await fillReadyDraft();
    await planButton().click();
    await page.getByTestId("tl-failed-leg").waitFor();
    const text = await page.getByTestId("current-result").innerText();
    assert.match(text, /Only part of the day could be planned/);
    assert.match(text, /Arrival time unknown/);
  });

  for (const mode of ["truncated", "malformed"]) {
    test(`${mode} stream is reported incomplete, never as a plan`, async () => {
      planMode = mode;
      await fillReadyDraft();
      await planButton().click();
      await page.getByTestId("plan-notice").waitFor();
      assert.match(await page.getByTestId("plan-notice").innerText(), /incomplete/);
      assert.equal(await page.getByTestId("current-result").count(), 0);
      });
  }

  test("Cancel aborts the request and keeps the previous plan labelled", async () => {
    await fillReadyDraft();
    await planButton().click();
    await page.getByTestId("current-result").waitFor();
    planMode = "hang";
    const failed = page.waitForEvent("requestfailed", (r) => r.url().endsWith("/api/v2/plan/stream"));
    await planButton().click();
    await page.getByTestId("plan-progress").filter({ visible: true }).waitFor();
    assert.match(await page.getByTestId("plan-progress").filter({ visible: true }).innerText(), /Checking your places/);
    await page.getByRole("button", { name: "Cancel" }).filter({ visible: true }).click();
    await failed; // the browser aborted the in-flight stream
    assert.match(await page.getByTestId("plan-notice").innerText(), /cancelled/i);
    assert.equal(count("/api/v2/plan/stream"), 2);
    assert.equal(await page.getByTestId("current-result").count(), 1); // same inputs: still current
    pendingPlan?.();
  });

  test("editing during planning stops it and marks the old plan as earlier inputs", async () => {
    await fillReadyDraft();
    await planButton().click();
    await page.getByTestId("current-result").waitFor();
    planMode = "hang";
    const failed = page.waitForEvent("requestfailed", (r) => r.url().endsWith("/api/v2/plan/stream"));
    await planButton().click();
    await page.getByTestId("plan-progress").filter({ visible: true }).waitFor();
    await page.getByLabel("Departure time").filter({ visible: true }).fill("11:00");
    await failed;
    assert.match(await page.getByTestId("plan-notice").innerText(), /stopped because the trip details changed/);
    assert.match(await page.getByTestId("stale-label").innerText(), /earlier trip details/);
    pendingPlan?.();
  });

  test("repeated clock-change time needs an explicit occurrence", async () => {
    await fillReadyDraft();
    await page.getByLabel("Departure date").filter({ visible: true }).fill("2026-10-25");
    await page.getByLabel("Departure time").filter({ visible: true }).fill("01:30");
    await page.getByRole("radiogroup", { name: "Which occurrence of this time?" }).filter({ visible: true }).waitFor();
    assert.equal(await planButton().isDisabled(), true);
    await page.getByLabel(/Second 01:30 \(UTC\+00:00\)/).filter({ visible: true }).check();
    await planButton().click();
    await page.getByTestId("current-result").waitFor();
    assert.equal(log.find((r) => r.path === "/api/v2/plan/stream").body.departure.occurrence, 2);
  });

  async function planThreeStops() {
    await fillReadyDraft();
    await page.getByRole("button", { name: "+ Add another stop" }).filter({ visible: true }).click();
    await chooseStop(3, "trinity", "Trinity College");
    await planButton().click();
    await page.getByTestId("current-result").waitFor();
  }
  const refreshButton = (n) => page.getByRole("button", { name: "↻ Refresh from here" }).nth(n);
  const refreshRequests = () => log.filter((r) => r.path === "/api/v2/refresh/stream").map((r) => r.body);

  test("refresh from here streams new journeys separately, then replaces the suffix at once", async () => {
    await planThreeStops();
    const before = await page.getByTestId("current-result").innerText();
    assert.match(before, /Bus 15, 20 min/);
    refreshMode = "progressive";
    await refreshButton(1).click();
    const progress = page.getByTestId("refresh-progress");
    await page.getByTestId("refreshed-items").getByText("Bus 99 (refreshed)").waitFor();
    await progress.filter({ hasText: "Refreshed 1 of 1 journey" }).waitFor(); // label updates with the event
    assert.match(await progress.innerText(), /Refreshing from Guinness Storehouse → Trinity College \(planned 11:20\)\. Refreshed 1 of 1 journey…/);
    // Previous suffix still visible and labelled; prefix unchanged.
    const previous = page.getByTestId("previous-timings");
    assert.match(await previous.innerText(), /Previous timings — refreshing\./);
    assert.match(await previous.innerText(), /Bus 15, 20 min/);
    const req = refreshRequests()[0];
    assert.equal(req.leg_index, 1);
    // Stop 2's planned departure in the mocked plan: arrive 09:20Z + 60 min stay.
    assert.equal(req.planned_departure, "2026-10-21T10:20:00.000Z");
    releaseRefresh();
    await page.getByTestId("current-result").waitFor();
    await page.getByTestId("previous-timings").waitFor({ state: "detached" });
    const after = await page.getByTestId("current-result").innerText();
    assert.match(after, /Bus 99 \(refreshed\)/);
    assert.equal((after.match(/Bus 15, 20 min/g) ?? []).length, 1); // only the unchanged first journey
    assert.equal(count("/api/v2/plan/stream"), 1); // refresh did not re-plan
  });

  test("a failed refreshed journey shows unknown later times and retries from the same departure", async () => {
    await planThreeStops();
    refreshMode = "partial";
    await refreshButton(0).click();
    await page.getByTestId("tl-failed-leg").waitFor();
    const text = await page.getByTestId("current-result").innerText();
    assert.match(text, /Bus 99 \(refreshed\)/);
    assert.match(text, /Arrival time unknown/);
    assert.equal((text.match(/Bus 15, 20 min/g) ?? []).length, 0); // no old downstream timings
    refreshMode = "fail-first"; // the retried journey fails again
    const tryAgain = page.getByRole("button", { name: "↻ Try again" });
    await tryAgain.click();
    await page.getByTestId("tl-failed-leg").waitFor();
    await page.getByRole("button", { name: "↻ Try again" }).click();
    await page.getByTestId("tl-failed-leg").waitFor();
    const [, retry1, retry2] = refreshRequests();
    assert.equal(retry1.leg_index, 1);
    assert.equal(retry1.planned_departure, retry2.planned_departure); // same planned departure each retry
  });

  test("cancelling a refresh keeps and labels the previous timings", async () => {
    await planThreeStops();
    refreshMode = "hang";
    const failed = page.waitForEvent("requestfailed", (r) => r.url().endsWith("/api/v2/refresh/stream"));
    await refreshButton(1).click();
    await page.getByTestId("previous-timings").waitFor();
    await page.getByTestId("refreshing-view").getByRole("button", { name: "Cancel" }).click();
    await failed;
    assert.equal(await page.getByTestId("plan-notice").innerText(), "Refresh cancelled — showing previous timings.");
    assert.match(await page.getByTestId("current-result").innerText(), /Bus 15, 20 min/);
  });

  for (const mode of ["truncated", "malformed"]) {
    test(`a ${mode} refresh stream keeps the previous timings`, async () => {
      await planThreeStops();
      const before = await page.getByTestId("current-result").innerText();
      refreshMode = mode;
      await refreshButton(1).click();
      await page.getByTestId("plan-notice").waitFor();
      assert.equal(await page.getByTestId("plan-notice").innerText(), "Refresh incomplete — showing previous timings.");
      assert.equal(await page.getByTestId("current-result").innerText(), before);
    });
  }

  test("editing during a refresh stops it; refresh then needs a new plan", async () => {
    await planThreeStops();
    refreshMode = "hang";
    const failed = page.waitForEvent("requestfailed", (r) => r.url().endsWith("/api/v2/refresh/stream"));
    await refreshButton(1).click();
    await page.getByTestId("previous-timings").waitFor();
    await page.getByLabel("Departure time").filter({ visible: true }).fill("11:00");
    await failed;
    assert.match(await page.getByTestId("plan-notice").innerText(), /Refresh stopped because the trip details changed/);
    const stale = page.getByRole("button", { name: "↻ Refresh from here" }).first();
    assert.equal(await stale.isDisabled(), true);
    assert.match(await stale.getAttribute("title"), /Press Plan first/);
  });

  test("optimisation stays unavailable; legacy endpoints unused; desktop tabs preserved", async () => {
    await planThreeStops();
    await page.getByRole("button", { name: "Map", exact: true }).filter({ visible: true }).click();
    await page.getByTestId("optimise-unavailable").filter({ visible: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: /Optimise/ }).count(), 0);
    assert.equal(count("/api/optimise") + count("/api/refresh-leg") + count("/api/plan"), 0);
  });
});
