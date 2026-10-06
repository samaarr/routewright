# RouteWright — Implementation Progress

## Billing correction — confirmed 2026-10-05

The product manager confirms the API project's linked billing address is India.
The EEA-specific Step 1 rationale below is superseded. Continue Step 2 under the
updated SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md; see STEP_2_CORRECTION_PROMPT.md.
Preserve existing implementation work and separately approved D48 layout; do
not adopt UI Kit or disable hours for the obsolete EEA reason. D49's EEA gate
is moot; ordinary release checks remain. Earlier entries are historical evidence,
not confirmation of current code status or applicable EEA compliance.

Updated: 2026-10-06

## Step 1 status: COMPLETE (EEA rationale superseded — see correction above)

Approved 2026-10-05. Decisions 48 and 49 added to TODO.md.

- **D48 approved (EEA rationale moot):** Desktop (≥1024px) switches to
  map-tab / plan-tab layout. Remains a release prerequisite and UX improvement;
  no longer required for EEA compliance (non-EEA billing confirmed).
- **D49 approved (EEA gate superseded):** Release once D48 is implemented and
  ordinary security/deployment checks pass. No Google EEA verification required.
  No Google contact authorised. D34 backend suggestions unchanged.
- D9-B(b): Plain text stop input retained. D34-37 are not revised.
- D9-C: EEA-specific rationale moot. D48 remains approved on UX grounds.

MAP_INTEGRATION_PROPOSAL.md contains the historical EEA analysis (verified
2026-10-05) and the Indian billing correction banner at the top.

### Non-EEA integration status (confirmed 2026-10-05)

Existing integration is consistent with non-EEA terms:
- Google Maps JS API: map tiles, transit layer, AdvancedMarker — Maps JS API
  use, no restriction on display with Google Maps.
- Backend Places REST: geocoding, hours, names — for planning engine only.
  Non-EEA Section 14 restricts display with non-Google maps; not applicable.
- Backend Routes REST: direction data for engine; deeplinks via our own URL
  construction. Non-EEA Section 19 restricts display with non-Google maps;
  not applicable.
- Attribution, API key restrictions, CSP, minimal field masks, cache limits:
  still required. Production settings unverified (B4 blocker unchanged).

---

## Step 0 status: COMPLETE

Baseline established. No application code has been changed by the design
implementation process. Security hardening (commit 49a77e8) is the last
committed change. SYSTEM_DESIGN_HANDOFF.md, TODO.md, and
SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md are untracked.

---

## Verified current behaviours

### 1. Approximate parallel leg departures — CONFIRMED
**File:** `backend/app/routers/plan.py:143-166`

Phase 3 computes each leg's departure time using `stays[:n_legs]` summed
from the start time, treating leg travel time as zero. All leg fetches then
run concurrently via `asyncio.gather`. The comment explicitly documents this
as a known approximation.

**Gap vs Decision 1:** Decision 1 requires sequential legs where each leg
uses the actual preceding arrival time (real leg travel time included). This
requires switching from parallel `asyncio.gather` to a sequential loop that
threads `leg.arrive_at` forward as each call completes.

### 2. Fixed failure duration — CONFIRMED
**File:** `backend/app/routers/plan.py:35`

`_FALLBACK_LEG_SECONDS = 15 * 60` (900 s, 15 min). Any leg that raises an
exception gets this duration. It also produces the string "Route unavailable
— check Google Maps" as the summary.

**Gap vs Decision 2:** Decision 2 requires leaving downstream times
**unknown** on routing failure — no invented fallback duration. The plan
should return a valid prefix up to the failed leg and mark subsequent times
as unknown with a reason.

### 3. Optimiser / planner stay-duration mismatch — CONFIRMED
**File:** `backend/app/routers/optimise.py:60-62`

The optimiser computes stays as:
```python
stays = [
    s.stay_minutes if s.stay_minutes is not None else DEFAULT_STAY_MINUTES
    for s in req.stops
]
```
`DEFAULT_STAY_MINUTES = 60`. It does **not** apply the planner's
first/last = 0 rule.

**Gap:** Optimiser's time-dimension arc costs use 60 min for the first and
last stops; the planner charges 0. Estimated post-accept arrival times from
the time dimension will be systematically longer than actual plan times.
Decision 3 implies consistent stay handling between comparison and planning.

### 4. Device timezone instead of city timezone — CONFIRMED
**File:** `frontend/components/PlannerPage.tsx:80`

```typescript
timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
```
This is the **browser's local timezone**, not the trip city's timezone.
If the user is in London planning a Dublin trip, the sent timezone is
`Europe/London`, not `Europe/Dublin`.

**Gap vs Decision 14/28-29/40-41:** The spec requires an explicit
city/destination timezone — offline lookup from the first stop's coordinates
(already done server-side in `tz.py`). The backend correctly derives
`trip_timezone` from the geocoded first-stop coordinates and ignores the
client-supplied value when coordinates are available. However the current
system sends the device timezone in `req.timezone`, which becomes the
fallback when `timezonefinder` returns None (ocean/null-island). For all
real cities this is harmless since the backend overrides it, but the
frontend should send the intended trip-city timezone, not the device timezone.

**Decisions 28-29/40-41 also require:** preserving local clock on city-zone
changes, unresolved/different-zone stops blocking calculation, DST ambiguity
handling. None of these exist yet.

### 5. Refresh uses datetime.now() — CONFIRMED
**File:** `backend/app/routers/refresh_leg.py:65`

```python
depart_at = datetime.now(timezone.utc)
```
The docstring says "if I left right now, how long would this leg take?"

**Gap vs Decision 21:** Decision 21 requires refresh to start from the
stop's **planned departure time** and recompute the suffix from there. It
must NOT use datetime.now(). The button semantics are "what does this leg
look like if I leave on schedule?" not "leave now".

### 6. fixedFirst / fixedLast are frontend-only state — CONFIRMED
**File:** `frontend/components/PlannerPage.tsx:156-157`

```typescript
const [fixedFirst, setFixedFirst] = useState(false);
const [fixedLast, setFixedLast] = useState(false);
```
Reset to false on any form change (handleFormChange). They are passed to
the optimise call only — not to the plan call.

**Current behaviour:** Consistent with Decision 16-17 (pins constrain
optimisation, not manual editing). This is already correct per the spec.

### 7. Persistent rich Places cache — CONFIRMED
**File:** `backend/app/services/geocache.py:41-52, 113-151`

Current schema stores: `query_key, place_id, name, lat, lng,
primary_type, types_json, cached_at, opening_hours_json`. Full rich data
including names and types is persisted indefinitely until TTL expiry.

**Gap vs Decision 38:** Decision 38 requires the cache to store only
`place_id` and `coordinates`, with coordinates expiring within 30 days.
Legacy rich fields should be removed. Names/types should be re-fetched on
each plan (or the cache schema must be migrated to drop name/primary_type/
types_json/opening_hours_json).

---

## Stage checklist

**Numbering note (corrected 2026-10-06).** Earlier entries in this file used
their own step numbers, which drifted from SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md.
This table uses the spec's numbering. The historical section headings below
keep their original labels, mapped as follows:

| Historical heading here | Spec step(s) |
|-------------------------|--------------|
| "Step 2 status"         | Step 2 |
| "Step 3 status"         | Parts of Steps 3 and 4 |
| "Step 4 status"         | Part of Step 5 |
| "Step 5 — Frontend streaming" (old next action) | Step 6 |

Status per spec step. "PARTIAL" lists what is still missing; nothing below is
claimed beyond what the code and tests show.

| Spec step | Description | Status |
|-----------|-------------|--------|
| 0 | Baseline + working record | COMPLETE |
| 1 | Validate non-EEA Google integration (EEA rationale superseded) | COMPLETE |
| — | D48 desktop map/plan tab layout | COMPLETE (commit 3499c1c) |
| 2 | Contracts + shared engine boundaries | PARTIAL — models, codegen, CI drift check, engine protocols (c8cb60b); Places adapter protocol, hours evaluator wired into the engine, deadline-bounded awaits, typed admission/budget errors (V2-VH, uncommitted). Missing: POST-compatible streamed transport (item 5), runtime event validation/bounded parsing (item 7), a call-accounting *interface* beyond the in-process `OperationContext` counters (item 8) |
| 3 | Verify selections, durations, time before routing | PARTIAL — DONE (V2-VH): server-side Place Details verification of city + stops by selected ID (items 1-2, server half), one lookup per distinct place (item 3), durations resolved once with explicit-wins-everywhere and place-type defaults (item 4), offline city/stop zones with no fallback (item 5), departure-zone match, chronological occurrence, invalid-date/range checks (item 6). Missing: frontend selection UX + text-edit invalidation (item 1, client half), city-change handling (item 7), D44 viewport/outside-area warning (item 8), suggestions debounce/limits D34-36 (items 9-10), D38 cache migration (item 11) |
| 4 | Ordinary planning with sequential transit | PARTIAL — `/api/v2/plan` sequential legs, partial-failure results, no 15-min fallback (c07f3c7); 60 s deadline now bounds in-flight provider awaits incl. verification and admission waits, with slot release verified (V2-VH). Missing: streamed progress (emitter is a no-op), client-disconnect cancellation, solver bounding (n/a until comparison). v1 `/api/plan` unchanged and still used by the frontend |
| 5 | Opening-hours rules | DONE FOR v2 PLANNING (V2-VH) — date-specific hours within documented 7-day coverage, qualified weekly fallback, documented always-open shape only, malformed/missing → unknown, arrival-at-closing closed, overnight/week-boundary, truncated endpoints, special days, warnings kept on the original order, reusable `hours_eligibility()`. Not yet exercised by comparison/acceptance (Step 8). v1 `/api/plan` keeps its weekly-only logic |
| 6 | Frontend state + streaming | PENDING |
| 7 | Suffix refresh via shared engine | PENDING |
| 8 | Compare one local candidate with fresh original | PENDING |
| 9 | Metrics, security regression, deployment verification | PENDING (B2, B4) |
| 10 | Review, release readiness, completion report | PENDING |

---

## Decisions per spec step

Taken from the "Decisions:" line of each step in
SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md. Decisions appear under several steps.

- **Step 2:** D11–14, D18, D21–23, D31–33, D40–45
- **Step 3:** D11, D13–14, D25–30, D34–38, D40–45
- **Step 4:** D1–3, D7–8, D11, D22–24, D31, D42–43, D45
- **Step 5:** D15 (as amended by D24, D42, D43)
- **Step 6:** D6–7, D12, D16–18, D22, D27–30, D32–33
- **Step 7:** D21–23, D31–32, D37, D40–45
- **Step 8:** D3–12, D15–20, D24, D31–32, D37, D42–43
- **Step 9:** D19, D23, D33, D46–47; SECURITY.md requirements

D38 (minimal cache) is part of Step 3 item 11. It is not deferred; the
correction prompt keeps it in scope.

---

## Key files per remaining work

### Step 3 remainder — cache, area warning, suggestions
(Verification and hours in v2 were completed by V2-VH; see that section.)
- `backend/app/services/geocache.py` — D38 migration to IDs/coordinates only,
  30-day non-extending expiry
- `backend/app/services/place_details.py` — add `viewport` to the city mask
  when the D44 outside-area warning is implemented
- New suggestion endpoints (D34-36) with Autocomplete session tokens

### Step 6 — Frontend
- `backend/app/routers/plan_v2.py` — streamed transport
- `frontend/components/PlannerPage.tsx`, `frontend/lib/api.ts` — reducer
  state, consume v2 PlanResult and stream events, cancel

### Step 7 — Refresh
- `backend/app/routers/refresh_leg.py` — start from planned departure, not
  `datetime.now()`; recompute suffix via engine
- `backend/app/services/engine.py` — implement `refresh_suffix`

### Step 8 — Comparison
- `backend/app/routers/optimise.py`, `backend/app/services/engine.py` —
  implement `compare_orders`; fix optimiser's first/last stay mismatch;
  wire `is_disqualifying_for_optimisation`

---

## Blockers

### B1 — D48 desktop tab layout — RESOLVED
Implemented in commit 3499c1c (desktop uses the tablet map/plan tab toggle).
No longer blocks release under D49.

### B2 — Metrics retention/storage unspecified (D46)
Decision 46 approves collecting operational metrics but leaves
retention/storage unspecified. This blocks Step 9 finalization. Does not
block earlier stages.

### B3 — npm audit: disk space
`postcss-selector-parser` safe fix and Next.js 14 advisory remain unresolved
due to ENOSPC during previous session. Run `npm audit fix` (no --force) in
`frontend/` once disk space is freed.

### B4 — Production deployment unverified
TRUSTED_PROXY_COUNT=1 not yet set in Railway. Two separate Google API keys
(browser-restricted + IP-restricted) not yet provisioned.

---

## Baseline checks run

- `git status` — HEAD at 49a77e8 (security hardening commit). Clean.
- All 47 decisions in TODO.md confirmed as `[ ]` (unchecked/not implemented).
- All 7 suspected behaviours verified against actual code (see above).
- SYSTEM_DESIGN_HANDOFF.md, TODO.md, SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md
  are untracked (not in git). This file is also untracked.

---

## Step 2 status (historical log — spec Step 2 is PARTIAL, see Stage checklist)

Completed 2026-10-06. All contracts implemented, 43/43 new tests pass.
No EEA-only constraints introduced.

### New files created

- `backend/app/core/deadline.py` — DeadlineScope, DeadlineExceededError,
  OPERATION_DEADLINE_SECONDS=60.0
- `backend/app/services/errors.py` — PlaceVerificationError,
  ProviderTemporaryError, NoRouteError, QuotaExceededError
- `backend/app/services/engine.py` — PlacesAdapter/RoutesAdapter/
  ProgressEmitter protocols, VerifiedStop, ResolvedDurations,
  OperationContext, resolve_durations(), plan_sequential/compare_orders/
  refresh_suffix stubs
- `backend/scripts/export_schema.py` — ContractRoot → schema.json
- `frontend/schema.json` — generated from ContractRoot
- `frontend/lib/api-types.ts` — generated TypeScript from schema
- `backend/tests/test_contracts.py` — 43 tests covering all new types

### Modified files

- `backend/app/models/request.py` — added PlaceSelection, CitySelection,
  StopSpec, DepartureInput, ItineraryRequest, RefreshRequest
- `backend/app/models/response.py` — added KnownStop, PlannedLeg,
  FailedLeg, UnknownStop, PlanTimelineItem, CompletePlan, PartialPlan,
  PlanResult, streaming events, OperationOutcome, ContractRoot
- `frontend/lib/types.ts` — re-exports new engine types from api-types.ts;
  legacy v1 types preserved for existing components unchanged
- `frontend/package.json` — added json-schema-to-typescript devDep,
  gen:types and check:types-drift scripts
- `.github/workflows/ci.yml` — added schema drift check to frontend job

### Checks run (2026-10-06)

- `python -m ruff check` — all files pass
- `python -m mypy app` — 27 source files, no issues
- `python -m pytest -q` — 203 passed, 1 skipped (Redis not in env)
- `npm run type-check` — no errors
- `npm run gen:types` — schema.json + api-types.ts generated clean

### Decisions covered by Step 2

D11 (duration resolver), D12 (operation ID/revision), D13 (place/city
selection models), D14 (destination-local departure), D22 (streaming events),
D23 (terminal outcomes), D31 (Pydantic-authoritative contracts), D32 (TS
codegen), D33 (drift check in CI), D40-41 (IANA timezone/occurrence fields),
D44 (city viewport), D45 (pre-routing verification models).
Stubs for D1-2 (sequential legs / partial failure), D6-8 (streaming), D18,
D21 (refresh planned departure), D26-29 (timezone) — implemented in Steps 3+.

---

## Step 3 status (historical log — covers parts of spec Steps 3–4, both PARTIAL)

Completed 2026-10-06. 228 tests pass (25 new), 1 skipped (Redis). Mypy clean.

### New files created

- `backend/app/services/verifier.py` — `verify_stops()`: offline timezone
  derivation + timezone-conflict check (D29, D45); pre-routing, no API calls
- `backend/app/services/departure.py` — `resolve_departure()`: DepartureInput
  → UTC datetime; spring-forward gap rejection, fall-back occurrence handling
  (D14, D40-41)
- `backend/app/services/adapter.py` — `GoogleRoutesAdapter`: wraps
  `directions.fetch_leg()` under RoutesAdapter Protocol; maps DirectionsError
  to NoRouteError/ProviderTemporaryError
- `backend/app/routers/plan_v2.py` — `POST /api/v2/plan` using ItineraryRequest;
  returns PlanResult (CompletePlan or PartialPlan); no streaming yet (Step 5)
- `backend/tests/test_engine_sequential.py` — 25 tests: timestamp threading,
  partial failure, deadline/cancellation, departure DST, timezone conflict,
  endpoint integration

### Modified files

- `backend/app/services/engine.py` — implemented `plan_sequential()`:
  sequential leg loop, deadline inside routing try/except, FailedLeg +
  UnknownStop on failure; extended ResolvedDurations with `sources` dict and
  `get_source()` method; deadline param added to compare_orders/refresh_suffix
  stubs
- `backend/app/services/errors.py` — added `TimezoneConflictError`
- `backend/app/main.py` — registered plan_v2 router
- `backend/tests/test_contracts.py` — minor comment/style fixes (ruff)

### Decisions covered by Step 3

D1 (sequential actual arrivals), D2 (no invented fallback duration),
D6 (streaming events emitted — plan_sequential emits start/stop_ready/
leg_progress/leg_ready/phase_complete), D11 (stay sources tracked),
D14 (DepartureInput → UTC resolver), D22 (streaming event types),
D29 (one timezone per trip), D40-41 (IANA timezone, occurrence disambiguation),
D45 (pre-routing verification without routing calls).
Partial coverage: D7-8, D12 (operation_id/input_revision echoed on all events),
D26-28 (timezone derivation offline).

### Gap vs. SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md Step 3

- `/api/plan` (v1) still uses parallel asyncio.gather + fallback — not changed
  (v2 endpoint `/api/v2/plan` implements D1/D2 correctly; v1 preserved for
  existing frontend compatibility until Step 5 wires the frontend)
- Streaming (D7-8): events emitted to a NullEmitter; HTTP streaming transport
  (SSE/NDJSON) wired in Step 5
- Opening-hours enforcement (D15/D42-43): Step 4

## Step 4 status (historical log — covers part of spec Step 5, PARTIAL)

Completed 2026-10-06. 241 tests pass (13 new), 1 skipped (Redis). Ruff + mypy clean.

### Modified files

- `backend/app/models/response.py` — added `HoursSource` TypeAlias
  (`Literal["date_specific", "weekly"]`); added `hours_source: HoursSource | None`
  field to `HoursDetail` (default None, null-safe for existing callers)
- `backend/app/services/hours.py` — added `hours_source` param to
  `compute_hours_status` (default None); threaded through all four return
  sites so HoursDetail carries the source qualifier; added
  `is_disqualifying_for_optimisation(status, stay_minutes) -> bool` helper
- `backend/app/routers/plan.py` — passes `hours_source="weekly"` to
  `compute_hours_status` (all current hours come from `regularOpeningHours`)
- `backend/tests/test_hours.py` — 13 new tests: arrival exactly at closing,
  `hours_source` propagation for all status variants, 24h place (no detail),
  `is_disqualifying_for_optimisation` for all D42/D24 cases

### Decisions covered by Step 4

D15 (hours enforcement in plan), D24 (zero-minute stop warn-only),
D42 (closed_on_arrival positive stay = disqualifying; closes_during_visit =
warning only), D43 (weekly schedule qualification via hours_source field;
date_specific path reserved for currentOpeningHours in a future stage).

### Gap notes

- `regularOpeningHours` is the only hours source in the geocoder today;
  `hours_source` is always `"weekly"` at the call site. The `"date_specific"`
  branch is wired and ready but not yet exercised (requires adding
  `currentOpeningHours` to the Places API field mask and a second lookup path
  in geocoder.py — deferred to v1.5 as per D43 amendment).
- `is_disqualifying_for_optimisation` is ready for the optimisation stage
  (Step 7) to wire into candidate ranking. Not yet called from any router.
- Sequential routing stay duration confirmed by existing
  `test_sequential_timestamps_thread_forward` (30-min stop_b stay threads
  through leg_bc.depart_at correctly).

## Commits (2026-10-06)

Previously uncommitted work committed in four chunks on main:

- c8cb60b feat(contracts) — 203 tests pass at this commit
- c07f3c7 feat(engine) — 228 tests pass
- b511637 feat(hours) — 241 tests pass; generated TS types were stale
  (missing `hours_source`) and were regenerated here
- 3499c1c feat(layout) — D48

## V2 verified planning + opening-hours integration (V2-VH) — 2026-10-06

Executed NEXT_STEP_V2_INTEGRATION_PROMPT.md. Committed in d63ef89 (code)
and 791af55 (docs). Baseline before edits: 241 passed, 1 skipped.

### Gaps confirmed against code before editing

All four observed gaps were real: `verify_stops` copied browser lat/lng and
name into `VerifiedStop`; trip zone came from the first stop with a `"UTC"`
fallback; `DepartureInput.timezone` was never checked against the city; v2
called `resolve_durations(..., {})` (flat 60 min) and set every stop's hours
to `"unknown"`. Also found: endpoints were forced to 0 even when explicit
(contradicting D11), an occurrence on an unambiguous time was silently
ignored, `2026-02-30` raised an uncaught ValueError (500), and the deadline
was only checked between calls.

### Requirements finished (runtime behaviour, not just models)

- **Server-side verification (D13, D37, D45)** — `services/place_details.py`
  (Place Details (New) GET by ID, minimal masks), `GooglePlacesAdapter`
  (shared semaphore + fail-closed budget, no retries), `verify_itinerary()`.
  Provider name/coordinates replace submitted hints. Moved / permanently
  closed / ID-mismatch / no-location / 404 / 400 → `place_invalid` (422) with
  the affected instance IDs and any `moved_place_id` surfaced, never adopted.
  5xx/401/403/network → `place_temporary` (503); provider 429 or exhausted
  budget → `quota_exceeded` (429); admission busy / usage-control down →
  `provider_capacity` (503). Malformed IDs are rejected before admission and
  cost no budget. Any verification failure → zero routing calls (tested).
- **One lookup per distinct place per operation (D37)** — repeated visits
  share the lookup; city shares a stop lookup when it is also a stop (stop
  mask is a superset). Lookups are sequential so the first failure is
  deterministic and stops further spend. Details are request-scoped; nothing
  new is written to the persistent cache.
- **Timezones (D40, D41)** — `tz.resolve_timezone()` returns None instead of
  falling back; city zone from verified city coordinates; unresolved city or
  stop zone → `timezone_unresolved`; other-zone stop → `timezone_conflict`
  with instance ID; submitted departure zone ≠ city zone →
  `departure_timezone_mismatch` (checked before any stop lookup).
- **Departure (D14, D29)** — chronological occurrence (1 = earlier instant);
  occurrence on a once-only time rejected; impossible dates rejected; v1's
  supported range reused (−7 / +100 days; walking/driving must be future);
  all → 422 with a code, before any provider call.
- **Durations (D11)** — explicit wins at every position incl. endpoints and
  zero; unspecified endpoints 0; unspecified middle stops use
  `stay_defaults.lookup_stay_minutes` on verified primaryType/types; keyed by
  instance ID; duplicate instance IDs rejected (request validator + resolver).
- **Hours in the v2 engine (D24, D42, D43)** — `services/venue_hours.py`
  parses `currentOpeningHours`/`regularOpeningHours`; `plan_sequential`
  assesses each KnownStop against its actual arrival/departure in the trip
  zone; UnknownStops get no timing or hours. `HoursDetail` now carries
  `always_open`, `exceptions_unconfirmed`, `coverage_start/end`,
  `special_day`, `unknown_reason`. Plan-level `warnings` (with
  `affects_instance_id` + `code`) for closed-on-arrival, zero-minute
  closure, closing during visit and unknown hours. Visits are never
  shortened, delayed or dropped. `hours_eligibility()` is the reusable
  ok/warning/disqualifying rule for the later comparison stage.
- **Deadline** — `DeadlineScope.bound()` wraps every Place Details and
  routing await with the remaining time (incl. semaphore waits); on expiry
  the inner task is cancelled and the provider slot released; budget already
  consumed is not refunded (tested). Mid-route expiry → PartialPlan with
  `deadline_exceeded`.
- **Contracts** — additive: `HoursDetail` fields above, `Warning.affects_instance_id`
  / `code`, `PlanFailureReason += "provider_capacity"`. TS types regenerated.

### Provider-call accounting per v2 plan

At most `1 + D` Place Details calls (D = distinct stop place IDs; city shared
when it is also a stop) followed by at most `N − 1` routing calls; none if
verification fails. Worst case at the 12-stop cap: 13 details + 11 routes =
24 provider calls per plan request, all against the shared
`provider_calls_per_day` budget (default 2000). Per-IP limits still count one
plan request as 1. Counters are kept in `OperationContext` (places/routing)
but not yet exported as metrics (D46, B2).

### Billing — corrected facts and open discrepancy

- Place Details (New): `regularOpeningHours`/`currentOpeningHours` →
  **Enterprise**; `displayName`/`primaryType`/`businessStatus` → Pro;
  `id`/`movedPlaceId`/`location`/`types` → Essentials. Every v2 **stop**
  lookup is a Place Details Enterprise event; **city** lookups (no hours) are
  Pro.
- Text Search (New): `places.regularOpeningHours` → **Enterprise**. The
  legacy v1 geocoder comment claiming Pro was wrong and is corrected in
  `geocoder.py` (comment only; behaviour unchanged).
- **Unresolved:** CLAUDE.md/AGENTS.md still say RouteWright "sits in the 5K
  Pro tier (~217 free generations/month)". With hours requested, both v1
  geocoding and v2 stop verification fall in Enterprise (1K free
  events/month). Not edited here; needs a product/billing decision on
  whether to keep the free-tier estimate, adjust budget/quotas, or both.
- **Proposal, not implemented:** consider a separate per-request or per-day
  Place Details cap (e.g. count details calls separately from routing in the
  provider budget) — TODO.md still lists "place-call accounting separately
  from the routing-call allowance" as an open decision. Existing limits are
  unchanged.

### Checks run (actual results, 2026-10-06)

- `backend/.venv/bin/python -m pytest -q` — **308 passed, 1 skipped**
  (skip = `test_security_redis.py`, needs `SECURITY_TEST_REDIS_URL`; Redis
  integration NOT verified). New/changed: test_venue_hours 20,
  test_place_details 21, test_plan_v2_verified 28, test_engine_sequential 21
  (offline-only verifier tests replaced by provider-backed ones),
  test_contracts 45, test_hours 36.
- Mutation spot-checks: reverting to submitted coordinates fails
  `test_forged_selection_location_ignored`; forcing endpoint durations to 0
  fails three duration tests.
- `ruff check .` clean; `ruff format --check .` clean (only touched files
  were formatted); `mypy app` (strict) — no issues in 33 files.
- `npm run gen:types` → `check:types-drift` clean → `npm run type-check`
  and `npm run lint` clean. `npm run build` not run.
- No live Google calls were made; production keys/quotas/CSP unverified (B4).

### Remaining gaps (not done in this task)

- Frontend still uses v1 `/api/plan`; no reducer/streaming (Step 6).
- Streaming transport + runtime event validation; client-disconnect
  cancellation (only the deadline cancels today).
- D38 cache migration — legacy v1 cache still stores names/types/hours.
- D44 outside-area warning (viewport not requested yet); D34-36 suggestion
  endpoints and Autocomplete session tokens (Place Details calls are not
  session-linked, so each bills as a standalone Enterprise/Pro event).
- Refresh (Step 7) and comparison/acceptance (Step 8); `hours_eligibility`
  not yet consumed by any candidate ranking.
- `businessStatus` CLOSED_TEMPORARILY / FUTURE_OPENING are not surfaced.
- `closed_on_arrival.opens_at` is HH:MM without a date.
- Hours compare wall-clock times; a visit spanning a DST transition can be
  off by the transition offset. Date-specific coverage is anchored to the
  server's local date at fetch time and may differ from Google's "today"
  near midnight.
- Unknown hours produce an `info` warning for every hour-less stop (e.g.
  hotels, stations) — check with product whether that is too noisy.
- v1 `geocoder._parse_opening_hours` still treats any missing close as 24 h;
  only the v2 path enforces the documented always-open shape.
- Not release-ready: Steps 6-10 and B2/B4 remain open.

## Next action

1. V2-VH committed (d63ef89, 791af55).
2. Resolve the billing-tier discrepancy and the place-call accounting decision.
3. **Step 6:** streamed transport + frontend migration to `/api/v2/plan`.
4. Step 3 remainder: D38 cache migration, D44 area warning, D34-36 suggestions.
