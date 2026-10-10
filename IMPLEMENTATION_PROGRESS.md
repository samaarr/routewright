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
| 2 | Contracts + shared engine boundaries | COMPLETE for planning (SSV, 2026-10-06): items 1-8 implemented and tested — NDJSON POST stream (item 5), frontend runtime validation + bounded parsing (item 7), provider accounting seam (item 8). Exception: item 3's comparison-only outcomes (unchanged candidate, comparison ineligibility) are defined with their behaviour in Step 8 |
| 3 | Verify selections, durations, time before routing | COMPLETE (SSV): items 1-11 — explicit selection UI with text-edit invalidation, backend suggestions/selection, city-change handling, D44 area warnings, debounce/limits, D38 cache migration. Interim choice: selection lookups share the D36 bucket (see unresolved choices) |
| 4 | Ordinary planning with sequential transit | COMPLETE (SSV): streamed progress, disconnect cancellation releasing capacity (verified), one 60 s deadline incl. verification/admission, accounting. Item 8 solver bounding applies once comparison exists (Step 8). Deployment check of 60 s streaming through Railway/Vercel proxies remains (deployment-only) |
| 5 | Opening-hours rules | DONE FOR v2 PLANNING (V2-VH; DST fix in SSV) — instant-based comparison across clock changes, next-opening date. Comparison/acceptance retention is Step 8. v1 `/api/plan` keeps its weekly-only logic |
| 6 | Frontend state + streaming | COMPLETE (SSV): items 1-7; frontend now plans only via `/api/v2/plan/stream`. Item 6 pins: default on, visible, preserved through edits; their effect on optimisation arrives with Step 8 |
| 7 | Suffix refresh via shared engine | COMPLETE — backend e4f5f27 (`/api/v2/refresh[/stream]`, planned departure never now, unchanged prefix, ≤ N−1−k calls, failure → unknown downstream); refresh UI committed with this record ("Refresh from here" / "Try again", previous timings labelled while refreshing, atomic suffix replacement, cancel/incomplete keep the previous plan). Step 8 hook (refresh cancels optimisation) applies once optimisation exists |
| 8 | Compare one local candidate with fresh original | COMPLETE — backend 6329b9d; final-walk arrival fix 25de41b (applies to planning, refresh and comparison); comparison UI with the approved decisions (Compare on a current complete plan ≥ 3 stops, real phases + Cancel, "Your order — recalculated.", "Estimated journey-time saving: X min.", atomic "Use this order" with explicit stays and no network calls, edits invalidate). Live Google verification of the response shape and deployment checks remain (Step 9/10) |
| 9 | Metrics, security regression, deployment verification | LOCALLY COMPLETE — audit fix e3192f5, shared-Redis tests d39edd9 (passed against a local container), journey-time presentation 9c946ac, aggregate metrics 7cc0670, security regressions + bundle check ef3af78, docs + PRODUCTION_VERIFICATION.md; local container check passed (non-root, /healthz, request reached the intended container, no client IPs in app logs). All deployment items unverified (B4) |
| 10 | Review, release readiness, completion report | IN PROGRESS — deployment preparation done locally (approvals A1–A6 recorded; v1 retired 3c9f7ec; Redis TLS 5ef006d; log leaks fixed 8123f47, f3901c9; cache fallback 7365dee). **Blocked**: server-key egress IP needs a hosting decision; push/deploy/live test unapproved. See DEPLOYMENT_PLAN.md §14 |

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

### Step 7 — Refresh
- `backend/app/routers/refresh_leg.py` → replace with a v2 suffix refresh using
  `engine.refresh_suffix` (planned departure, not `datetime.now()`), streamed
  like `/api/v2/plan/stream`
- `frontend/components/v2/TimelineV2.tsx` — enable the per-journey refresh
  button (currently disabled with an explanation)

### Step 8 — Comparison
- `backend/app/routers/optimise.py`, `backend/app/services/engine.py` —
  `compare_orders`; fix the optimiser's first/last stay mismatch; use
  `hours_eligibility`; pins from the request
- `frontend/components/PlannerPage.tsx` — replace the "optimisation is coming"
  note with the comparison flow

---

## Blockers

### B1 — D48 desktop tab layout — RESOLVED
Implemented in commit 3499c1c (desktop uses the tablet map/plan tab toggle).
No longer blocks release under D49.

### B2 — Metrics retention/storage — RESOLVED (Step 9 decision)
Aggregate JSON log lines via the platform (Railway); retention = the Railway
plan's log retention (Hobby 7 / Pro 30 / Enterprise up to 90 days, per docs
2026-10-06). The actual plan and value are unverified (PRODUCTION_VERIFICATION.md §8).

### B3 — npm audit — RESOLVED by e3192f5 (scoped npm overrides, no --force, no new exception)
`npm run security:audit` now fails with "Unaccepted security finding:
tailwindcss": a newly published moderate advisory for dev-only
`postcss-selector-parser` (GHSA-rj75-hqrm-r3gf, via tailwindcss →
postcss-nested) is not covered by the braces-only exception. Lockfile was not
changed by SSV. Runtime (`--omit=dev`) audit is clean. Needs `npm audit fix`
(no --force) or a reviewed exception.

### B3 (original note)
`postcss-selector-parser` safe fix and Next.js 14 advisory remain unresolved
due to ENOSPC during previous session. Run `npm audit fix` (no --force) in
`frontend/` once disk space is freed.

### B4 — Production deployment unverified
Trusted-proxy configuration (corrected 2026-10-06 against the code): the
backend trusts `X-Forwarded-For` only when the connection peer is listed in
`TRUSTED_PROXY_IPS` (exact IPs/CIDRs of the ingress that sanitises the
header). `app/core/limiter.py` then walks the chain from the right and uses
the first hop that is not a trusted proxy (more than 16 entries → the peer is
used). `TRUSTED_PROXY_COUNT` is obsolete: any non-zero value is rejected at
startup in every environment, as is a `/0` trust-all entry
(`main.validate_production`). The container runs uvicorn with
`--no-proxy-headers` so the app sees the real peer. Still to do on Railway:
verify the ingress topology, then set `TRUSTED_PROXY_IPS` (leave it empty
until verified; do NOT set `TRUSTED_PROXY_COUNT`). Two separate Google API
keys (browser-restricted + IP-restricted) are not yet provisioned; the
server key must now also allow Places Autocomplete.

---

## Baseline checks run

- `git status` — HEAD at 49a77e8 (security hardening commit). Clean.
- All 47 decisions in TODO.md confirmed as `[ ]` (unchecked/not implemented).
- All 7 suspected behaviours verified against actual code (see above).
- SYSTEM_DESIGN_HANDOFF.md, TODO.md, SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md
  are untracked (not in git). This file is also untracked.

---

## Step 2 status (historical log — current status in Stage checklist)

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

## Step 3 status (historical log — parts of spec Steps 3–4; current status in Stage checklist)

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

## Step 4 status (historical log — part of spec Step 5; current status in Stage checklist)

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

## Selections, streaming and v2 frontend (SSV) — 2026-10-06

Scope: remaining Step 3 + streaming and frontend migration (Steps 2, 4, 6).
Committed 2026-10-06: 889f310 (selection, accounting seam, area warnings,
minimal cache, hours DST fix), 3f8ea5a (streaming + cancellation), 0b5e8fa
(frontend v2 migration + tests + CI). Each commit's backend checks and the
frontend type-check/lint/drift checks were run on that commit's exact tree
(334 → 348 backend tests). No live Google calls; no deploy/push.

### Baseline (before edits)
308 backend tests passed, 1 skipped (Redis); ruff/mypy clean; frontend
type-check/lint clean. Re-inspection found two defects that this task fixed:
opening-hours comparisons used wall-clock times (wrong "closes soon"/closing
checks across DST changes), and `opens_at` lacked a date when the next opening
was on another day.

### Requirement checklist → status
| Requirement (prompt) | Status | Where |
|---|---|---|
| Backend city/place suggestions, explicit selection, identifying fields only | Done | `routers/selection.py`, `services/autocomplete.py` |
| Place suggestions guided by selected city (bias, not restriction) | Done | `locationBias.rectangle` from city viewport |
| No matches vs invalid input vs provider failure vs rate limit vs budget vs usage-control | Done | 200 `no_matches`; 422; 503 `provider_unavailable`; 429 `rate_limit_exceeded`; 429 `quota_exceeded`; 503 `usage_control_unavailable` |
| Combined 30/min + 100/day per verified IP, incl. manual search | Done | `limiter.shared_limit` scope `selection-search` |
| Trusted-proxy handling, shared counters, fail-closed accounting preserved | Done | existing limiter/provider budget reused |
| Count suggestion/detail calls separately from routing | Done | `core/provider_accounting.py` (per-kind seam, no new limits) |
| Autocomplete session handling per Google's rules, no claimed discount | Done | tokens sent with suggestions + concluding selection lookup; see below |
| Outside-area warnings from verified viewport; unavailable when missing; wrap/boundary | Done | `services/area.py`, `lib/v2/area.ts`, plan warnings `outside_city_area` / `area_unavailable` |
| Warnings recalculated on city/stop change; kept in v2 results incl. unknown stops | Done | `stopChecks()`; `_area_warnings` |
| D38 minimal cache, 30-day non-extending expiry, legacy rich data removed | Done | `services/geocache.py` (migration + VACUUM + secure_delete) |
| v1 endpoint still works with rich details | Done | `geocode_cached` fetches fresh rich details, stores only coords |
| POST stream, phases, completed-leg progress, distinct outcomes | Done | `/api/v2/plan/stream` NDJSON; plan/partial, timeout, error, cancelled |
| One 60 s deadline incl. verification/admission; disconnect stops work; capacity released; bounded queue | Done | `PlanStream` (watcher + sentinel wake-up), `DeadlineScope.bound` |
| Pre-stream vs post-header errors; no-store/security headers | Done | HTTP 422/429 before stream; terminal events after |
| Reducer state, op identity/revision, late events rejected | Done | `lib/v2/state.ts` |
| Explicit selection inputs, edit invalidation, 300 ms/2-char/manual Search, stale results ignored | Done | `components/v2/SearchSelect.tsx`, `lib/v2/search.ts` |
| City change keeps stops/durations/local clock; tz label + warnings update | Done | reducer `citySelected` |
| Repeated-time occurrence selection; clear invalid-time errors | Done | `lib/v2/time.ts`, form radiogroup |
| Plan only on explicit Plan; Cancel; honest progress | Done | no percentages/countdowns; "Planned N of M journeys" |
| Render partial results + hours qualifications/warnings | Done | `components/v2/TimelineV2.tsx` |
| Runtime validation; malformed/truncated ⇒ incomplete | Done | `lib/v2/validate.ts`, `lib/v2/ndjson.ts` |
| Ordinary planning moved to v2; desktop tabs preserved | Done | `PlannerPage.tsx` |
| Refresh/optimise cannot apply legacy results | Done | v1 UI/client removed; refresh disabled with explanation; optimise replaced by a note |

### Files changed (high level)
Backend new: `core/provider_accounting.py`, `routers/selection.py`,
`services/area.py`, `services/autocomplete.py`, tests `test_selection.py`,
`test_plan_v2_stream.py`, `sample_streams.py` (contract sample generator).
Backend modified: `plan_v2.py` (shared `execute_plan`, JSON + stream
endpoints, area warnings), `place_details.py` (purpose masks, viewport,
session tokens, Essentials selection lookup), `verifier.py`, `adapter.py`,
`engine.py`, `venue_hours.py` (instant comparison), `geocache.py` (D38),
`errors.py`, `provider_semaphore.py`, `limiter.py`, models, `main.py`.
Frontend new: `lib/v2/{validate,ndjson,client,state,time,area,search}.ts`,
`components/v2/{SearchSelect,PlanFormV2,TimelineV2}.tsx`, `tests/unit/*`,
`tests/e2e/planner.e2e.mjs`. Modified: `PlannerPage.tsx`, `PlanMap.tsx`
(generic pins), `package.json` (test scripts), `tsconfig.json`
(`allowImportingTsExtensions`), CI. Removed (dead after migration): v1
`PlanForm`, `StopList`, `Timeline`, `StopCard`, `LegCard`, `PlanCanvas`,
`EmptyTimeline`, `WarningBadge`, `lib/api.ts`, `lib/types.ts`.

### Provider calls and billing (verified against Google docs, 2026-10-06)
- Suggestions: Autocomplete (New) — billed per request ("Autocomplete
  Requests") for the first 12 requests of a session; only requests 13+ in a
  session concluded by Place Details are free; abandoned sessions bill per
  request. So debounce/limits, not sessions, are what reduce cost.
- City selection and plan-time city verification: Place Details **Pro**
  (`id,displayName,formattedAddress,location,viewport`).
- Stop selection: Place Details **Essentials** (`id,location,formattedAddress`).
- Plan-time stop verification: Place Details **Enterprise** (hours), one per
  distinct place. Routing: Compute Routes, ≤ N−1 per plan.
- Per plan from a fresh form (N stops, D distinct): ~searches + 1 city
  select + N stop selects (setup) then 1 + D details + ≤ N−1 routes (plan).

### Checks run (actual results)
Backend: `pytest -q` **348 passed, 1 skipped** (Redis test skipped — not
verified); ruff check + format check clean; mypy strict clean (37 files).
Frontend: `check:types-drift` clean; `type-check` clean; `lint` 0 problems;
`test:unit` **57 passed** (incl. cross-language contract test that parses real
backend stream/selection output); `build` OK; `test:e2e` **14 passed**
(Playwright, production build, mocked API, Google blocked);
`security:smoke` passed; `security:audit` **FAILED** (pre-existing B3, see
Blockers). Mutation spot-checks: removing the disconnect sentinel, the
reducer's revision check, or the NDJSON terminal requirement each fails tests.
Visual check via screenshots at 1440px and 390px.

### Deployment-only checks (not verifiable locally)
- 60 s NDJSON streaming through Railway and any proxy/CDN (buffering,
  idle timeouts, disconnect propagation) — TODO open decision.
- Shared Redis counters for the new `selection-search` and `plan-v2` scopes
  (Redis test skipped locally); trusted proxy IPs (B4).
- API key restrictions must include Places Autocomplete; CSP with live maps.

### Remaining defects / unresolved choices
1. **Selection lookup limits (D36 open):** selections currently count in the
   combined 30/min + 100/day search bucket. Needs a product decision.
2. **Free-tier enforcement deferred** (2026-10-06 direction): only the seam
   exists; the 2000/day budget is not a free-tier guarantee.
3. **v1 endpoints** (`/api/plan`, `/api/optimise`, `/api/refresh-leg`) remain
   live but unused by the UI; v1 now makes a fresh Text Search (Enterprise)
   per stop because rich caching was removed. Consider retiring them.
4. The coordinate cache is written on selection, but the read path (selection
   without a session token) is not used by the current UI.
5. Each open stream holds one of `max_concurrent_requests` (20) for up to 60 s.
6. Unknown-hours `info` warnings may be noisy for hotels/stations.
7. `businessStatus` temporary closure not surfaced; date-specific coverage is
   anchored to the server's local date at fetch time.
8. README/CLAUDE.md still describe the v1 architecture and Pro-tier estimate.
9. `npm run security:audit` failure (B3).

## Step 7 — suffix refresh (completed 2026-10-06)

### Backend — commit e4f5f27
- `RefreshRequest` = ItineraryRequest + `leg_index` k + `planned_departure`
  (instant of leg k from the client's current plan). Provenance documented on
  the model: itinerary re-verified; planned departure from the client's
  calculated snapshot, checked for consistency/support (no server result
  storage). The prefix is neither sent nor returned.
- `engine.refresh_suffix` shares `_route_sequence` with planning: leg k at
  the planned departure, later legs at actual arrival + preserved stays,
  downstream hours re-assessed, first failure → FailedLeg + UnknownStops.
- Verifies only city, departure zone and stops k..N-1 (D37). Planned
  departures before the trip departure or outside Routes' documented window
  (transit −7/+100 days; walking/driving future only) → 422
  `planned_departure_unsupported` before any provider call; never "now".
- JSON + NDJSON stream endpoints with planning's events, 60 s deadline,
  disconnect cancellation; own per-IP allowance (existing refresh limits,
  scope `refresh-v2`); legacy `/api/refresh-leg` unused.
- Tests: `tests/test_refresh_v2.py` (14) + contract updates; mutation checks
  (using now / re-emitting the prefix stop / verifying everything) fail tests.

### Frontend — refresh UI
- "↻ Refresh from here" on each confirmed journey and "↻ Try again" on a
  failed journey, only on a current plan with nothing running; on a stale
  plan they are disabled ("Press Plan first — these times are for earlier
  trip details.").
- The planned departure is the origin stop's confirmed departure in the
  current plan (`lib/v2/refresh.ts` `refreshTarget`), so every retry uses the
  same planned departure.
- While refreshing: prefix unchanged; the old suffix stays visible, dimmed,
  under "Previous timings — refreshing."; refreshed journeys appear
  separately as they stream in, with "Refreshing from A → B (planned HH:MM).
  Refreshed N of M journeys…" and Cancel.
- Success: `mergeRefresh` builds prefix + refreshed suffix and replaces the
  plan in one step; downstream warnings come only from the refresh. Routing
  failure: refreshed part + failed journey + unknown later times. Old
  downstream timings are never merged; an inconsistent refresh (other origin,
  other planned departure, other stops) is refused and treated as incomplete.
- Cancel → "Refresh cancelled — showing previous timings."; interrupted or
  malformed stream → "Refresh incomplete — showing previous timings."; both
  keep the previous plan object untouched. Server errors keep the previous
  plan and append "Showing previous timings."
- Refresh reuses the planning operation model (`purpose: "refresh"`): edits
  abort it ("Refresh stopped because the trip details changed — showing
  previous timings."), events for other operations/revisions are ignored, and
  plan/refresh outcomes are validated per stream kind (a refresh outcome in a
  plan stream, or vice versa, is malformed).
- Tests: `tests/unit/refresh.test.ts` (15): target, atomic success merge,
  partial merge without old timings, refused inconsistent merges, reducer
  success/partial/cancel/interrupted/malformed, stale events after cancel,
  after edits and from older operations, cross-stream outcomes. Browser
  (`planner.e2e.mjs`, 6 refresh scenarios): progressive streaming through a
  local HTTPS test server (refreshed journeys shown separately while the
  previous timings stay labelled, then atomic replacement), partial failure
  + repeated "Try again" from the same planned departure, Cancel, truncated
  and malformed streams, edit during refresh. Mutation checks (keeping old
  downstream warnings; generic cancel text) fail tests.

### Checks (2026-10-06)
Backend: 363 passed, 1 skipped (Redis, not verified); ruff, format, mypy
clean. Frontend: types drift clean; type-check and lint clean; unit 72
passed; build OK; browser 20 passed (6 consecutive full runs after one
earlier unexplained failure in the progressive test; its progress assertion
now waits for the label update); security smoke passed; security audit
FAILED (pre-existing B3, dev-only postcss-selector-parser via tailwindcss).

## Step 8 — comparison (completed 2026-10-06)

### Backend — commit 6329b9d
- `ComparisonRequest` (= itinerary + current `fixed_first`/`fixed_last`).
  One verification of city + stops, shared by both orders; durations resolved
  once from the original order and carried by instance (D11, D37).
- Candidate: the existing distance-only `optimise_order` (haversine, OR-Tools)
  run once; pins apply to the stops currently at the ends; integrity check
  (permutation, pins). Solver limit min(2 s, remaining deadline) in the
  solver slot, released when the thread ends (cancellation returns at once).
- Unchanged order by instance identity → `no_different_order`, "No different
  order found by the current search.", zero routing calls.
- Otherwise original (`original_route`) then candidate (`alternative_route`)
  via the shared sequential engine; `RoutingBudget` caps calls at 2(N−1);
  no retries, no further candidates, no stored baseline.
- Statuses: `recommended` (both complete, no closure-on-arrival for a
  positive stay, durations/pins intact, saving ≥ 300 s exact),
  `not_faster`, `hours_ineligible` (with instance IDs), `original_incomplete`
  (stop; client keeps previous plan), `candidate_incomplete` (complete fresh
  original kept). Journey seconds = Σ(arrival − planned departure) per leg,
  so waiting/transfers count. Since 25de41b the arrival includes the
  documented final walk (see "Destination arrival correction").
  Distances are reported as the heuristic only.
- `recommended` carries the complete candidate plan for zero-call acceptance.
- Endpoints share planning's stream/deadline/disconnect handling; own
  allowance on the existing optimise limits (scope `compare-v2`). Legacy
  `/api/optimise` untouched.
- Tests: `tests/test_compare_v2.py` (23). Mutation checks: `>` instead of
  `>=`, ignoring hours ineligibility, never detecting unchanged order and a
  3(N−1) budget each fail tests.

### Frontend coordination (requirement 9, implemented)
- Starting Plan or Refresh supersedes any running operation: the reducer
  replaces it, the page aborts its request (server stops on disconnect), and
  its late events/outcomes are rejected by operation ID and revision. Plan
  stays available while another operation runs. Comparison will join the
  same rule. Tests: unit (plan↔refresh supersession, late events) and a
  browser test (Plan during a refresh aborts the refresh request).

### Destination arrival correction — commit 25de41b
- Review found transit arrival = last scheduled alighting time, omitting the
  walk to the destination (and, if the last ride lacked an arrivalTime, an
  earlier ride's arrival could be reused).
- Verified against Google's computeRoutes reference and transit-route guide
  (2026-10-06): walking to/from/between stations appears as steps with
  travelMode WALK and `staticDuration` (documented as possibly absent);
  TRANSIT steps carry `stopDetails.departureTime/arrivalTime`. The docs do
  not say whether a transit route's `duration` is measured from the
  requested departure, so it is not used for transit arrival.
- Arrival = last ride's arrivalTime + `staticDuration` of every later step.
  Missing ride arrival, missing/invalid final-walk duration, or an arrival
  before the requested departure → leg fails `arrival_unknown`; downstream
  times unknown; nothing invented. Walk-only routes and walking/driving keep
  departure + documented route duration. Field mask adds
  `routes.legs.steps.staticDuration`.
- Shared by planning, refresh and comparison (and v1 `/api/plan`).
- Tests: parser cases + `tests/test_final_walk.py` through the real parser
  with mocked HTTP: arrival and the next requested departure shift with the
  walk; a walk turns "closes soon" into "closed on arrival"; refresh includes
  it; final walks move a comparison across 300 s both ways; undocumented walk
  → arrival_unknown. Dropping the walk again fails 8 tests.

### Comparison UI — approved decisions implemented
- Compare appears only on a current, complete plan with ≥ 3 stops, with
  "Checks one alternative suggested by straight-line distance (up to 2(N−1)
  journey lookups)" and the current pin effect. Request sends current pins.
- During comparison the plan stays visible (not dimmed); status shows real
  phases ("Checking your places…", "Finding another order…", "Recalculating
  your order: journey 2 of 3…", "Checking the alternative: journey 1 of 3…")
  with Cancel. Counts reset per route.
- A complete fresh original replaces the displayed plan atomically, labelled
  "Your order — recalculated." Original incomplete, unchanged order,
  cancellation, timeout, error or interrupted stream leave the plan as it was
  ("Comparison cancelled/didn't finish — your plan is unchanged.").
- Recommended: "Estimated journey-time saving: X min." (floor of exact
  seconds), "We checked one alternative suggested by straight-line distance.
  Other orders may be faster.", both totals, suggested order, candidate
  warnings, "Use this order" / "Keep my order". Not-faster, hours-ineligible
  (names the closed stop), unchanged and failed outcomes are explained with no
  improvement claim and no accept action.
- "Use this order": one reducer step, no network call — form order becomes
  the candidate order, every compared stay becomes an explicit editable value
  (carried by stop instance, D11), and the displayed plan is exactly the
  compared candidate. Only allowed while the input revision still matches.
- Any input edit, Plan or Refresh clears the suggestion; plan/refresh/compare
  supersede each other and late events are rejected by operation ID and
  revision. Comparison outcomes are only valid in comparison streams, and
  results are checked for internal consistency (recommended needs a complete
  candidate in the stated order with saving ≥ threshold; other statuses may
  not carry a candidate).
- Tests: `tests/unit/compare.test.ts` (13) and 10 browser scenarios
  (offer conditions, recommended + zero-network acceptance with explicit
  stays, four non-improving outcomes, cancel, interrupted stream, edit
  invalidation, plan supersession, no legacy calls). Mutation checks
  (replacing the plan on an incomplete original; not making stays explicit)
  fail tests.

### Checks (2026-10-06)
Backend 402 passed, 1 skipped (Redis, not verified); ruff, format, mypy
clean. Frontend: types drift clean; type-check, lint clean; unit 87; build
OK; browser 31; security smoke passed; security audit FAILED (pre-existing
B3, dev-only postcss-selector-parser via tailwindcss).

### Unresolved timing issues (explicit)
- No live Google call has verified that transit WALK steps actually include
  `staticDuration` in our responses (no live testing authorised). If Google
  omits it in practice, affected legs become `arrival_unknown` rather than
  wrong — but plans could fail more often; check during deployment
  verification.
- Transit legs whose ride lacks stopDetails times now fail as
  `arrival_unknown` instead of using the route duration from the requested
  departure, because the docs don't define that duration's start.
- The leg line shows the provider's route `duration`; comparison totals use
  arrival − planned departure (includes waiting), so the two can differ.

## Step 9 — metrics, security, verification (2026-10-06)

### Commits
- e3192f5 fix(deps): `postcss-selector-parser` ^7.1.6 / `postcss-nested` ^7.0.2
  under tailwindcss and `postcss` for next via scoped overrides. No --force;
  the only exception is still braces@3.0.3 (dev, expires 2026-11-04).
- d39edd9 test(redis): `tests/test_security_redis.py` (4) — shared limits,
  shared provider budget, fail-closed admission, release. Skipped unless
  `SECURITY_TEST_REDIS_URL` is set; passed against a disposable local
  redis:7.4-alpine (db 15).
- 9c946ac fix(durations): `journey_seconds` (arrival − planned departure,
  includes waiting) drives the leg display, totals and comparison saving;
  Google's travel time shown separately; summaries carry no durations.
- 7cc0670 feat(metrics): `app/core/opmetrics.py` — one JSON line per v2
  operation (operation, transport, outcome, failure, elapsed_ms, stop_count,
  provider call counts). Excludes names, coordinates, dates, IPs, operation
  IDs, plans, secrets, raw provider text; no comparison savings and no split
  of comparison results (D46 permitted use). uvicorn `--no-access-log`.
  (Amended locally after fixing the Redis worker's stdout parsing; unpushed.)
- ef3af78 test(security): `tests/test_security_v2.py` (12) — trusted-proxy
  identity, headers on JSON + stream endpoints, HSTS only when enabled in
  production, generic 503, server key only in the request header and never in
  responses. `npm run security:bundle` scans the built bundle for the probe
  key; CI builds with `GOOGLE_MAPS_API_KEY` set to a probe and runs it.

### Checks (actual results, 2026-10-06)
Backend 423 passed, 4 skipped (Redis env unset; 415 with Redis at 7cc0670);
ruff, format, mypy clean. Frontend: unit 88, browser 31, types drift clean,
type-check and lint clean, security smoke passed, `security:audit` passes,
bundle check passed on 69 files (negative control detected).

### Container check (local, 2026-10-06)
Docker Desktop was restarted (with approval) after hanging on an ENOSPC. The
existing `routewright-security-check` image and its BuildKit cache layers were
corrupt (no `/etc/passwd`: "unable to find user app/root"); the base image
pulled fresh was fine. Rebuilt with `--pull --no-cache-filter final` (cached
dependency layer reused). Image built from HEAD — app code
  hashes matched the repo; run on an unused port 127.0.0.1:18765 because
  8000–8002/8080 are used by local processes): runs as `uid=1000(app)`,
  uvicorn is PID 1 with `--no-access-log`; `/healthz` → 200
  `{"status":"ok","version":"0.1.0"}`; a rejected v2 plan (past departure,
  zero provider calls) produced its metrics line in that container's log and
  the port refused connections once the container was removed; application
  logs contained no client IP (the spoofed `X-Forwarded-For` and the Docker
  peer `172.17.0.1` were absent; only uvicorn's `0.0.0.0` bind address).
Shared-Redis tests rerun against a disposable `redis:7.4-alpine` (no
persistence, 127.0.0.1:6390, db 15): 4 passed; full suite 427 passed. Test
containers, the test image and the pulled base tag were removed afterwards
(no prune).

### Not verified
- Everything in PRODUCTION_VERIFICATION.md: Railway streaming/disconnect,
  live walking-step `staticDuration`, key restrictions, live map CSP,
  HTTPS/HSTS/proxy, actual log retention, Railway Redis, storage encryption.

## Step 10 — deployment preparation (2026-10-06)

### Approved decisions (owner, 2026-10-06)
A1 ephemeral cache (no volume, non-root); A2 Redis TLS only; A3 retire v1
endpoints; A4 server key needs a verified egress-IP restriction before
deployment; A5 platform-retained aggregate logs, no archive; A6 monthly
free-tier enforcement deferred, limits unchanged. Detail: DEPLOYMENT_PLAN.md §1.

### Completed work (local commits, not pushed)
- `d390592` deployment plan (proposal); `6d02f06` D-1 client-IP proposal.
- `8123f47` 429 log line no longer contains the client IP (real-limiter test).
- `7365dee` ephemeral cache decision; failing cache reads are misses; tests
  prove planning ignores the cache.
- `3c9f7ec` v1 endpoints retired with their models and the Text Search
  client; generic security tests ported to `/api/v2/plan`; retired routes 404
  and absent from OpenAPI; frontend types regenerated (deletions only).
- `5ef006d` production refuses `redis://` and TLS-weakening `rediss://` URLs.
- `f3901c9` uvicorn WebSocket log lines carried client IPs (reproduced on a
  local server); fixed with `--ws none` + address-redacting filter; tested
  with a real uvicorn server.
- Docs reconciled (this commit): DEPLOYMENT_PLAN.md rewritten,
  PRODUCTION_VERIFICATION.md, SECURITY.md, TODO.md, SYSTEM_DESIGN_HANDOFF.md.
  CLAUDE.md (git-ignored) and AGENTS.md updated where they named v1 routes.

### Checks (actual results)
Backend 403 passed, 4 skipped (Redis env unset); shared-Redis tests 4 passed
against a disposable local Redis; ruff, format, mypy clean. Frontend
type-check, lint, unit 88, types drift clean. Browser e2e not re-run (no
frontend runtime change). Container image not rebuilt with `--ws none`.

### Findings from read-only public probes
- `routewright.vercel.app` is live with an older build (README: live site);
  its CSP names `routewright-production.up.railway.app`, which returns
  `502 Application failed to respond`. A browser Maps key is embedded (as
  expected); its restrictions are unknown. `routewright.com` is registered by
  an unknown owner. Nothing was changed.

### Revision after hosting was fixed to Railway + Vercel (2026-10-06)
- Fly.io removed from the plan. Railway Static Outbound IPs are Pro-only
  ($20/month incl. $20 usage; IPv4; may be shared with other customers) →
  deployment **blocked** pending the cost decision; requirement not relaxed.
- Upstash verified against docs: TLS always on, `eu-west-1` available,
  500K commands/month free, eviction off by default (writes rejected when
  full), `ERR max requests limit exceeded` at the limit, adding a card
  auto-upgrades (proposal: no card). Library needs only EVALSHA/GET/TTL/PING.
- Local TLS verification: TLS-only Redis with a throwaway CA — shared-store
  tests 4/4 over `rediss://`; plaintext, wrong CA, wrong hostname refused.
- Final container rebuilt from HEAD (`--ws none`) and run in production mode
  against that Redis: non-root, `/healthz` 200, 429 and Upgrade (405) logged
  without IPs, retired routes 404, no client/forged/peer IPs in the log,
  `redis://` refused at startup. Test resources removed.
- Finding: rate-limit keys in Redis contain raw client IPs → hashed-key
  proposal added to D-1.
- Railway 502: consistent ~15 s then `Application failed to respond`
  (`x-railway-fallback`); cause unknown without dashboard access; required
  information listed in DEPLOYMENT_PLAN.md §3.
- Rollback corrected: Railway Rollback restores image + custom variables
  (docs; 72 h Hobby / 120 h Pro retention), Redeploy not used for rollback;
  Vercel Hobby rolls back only to the previous production build, keeps
  build-time `NEXT_PUBLIC_*`; release pairs defined; first v2 release has no
  compatible predecessor → "safe off" instead.
- Smallest live test: 4 stops (pins on), ≈ 58 billable events.

### Unresolved proposals
C1 Railway Pro, C2 Upstash, D-1 client IP + hashed keys, D-5 Map ID, D-6
push/CI, D-8 domain ownership.

### Deployment blockers
1. Server-key egress IP (A4) — Railway Pro cost decision (+$15/month net).
2. Approvals for push, hosting changes, key creation, deploy, live test.
3. Client identity (D-1) before any public traffic.
4. Monthly free-tier enforcement deferred → no free-tier-safe public claim.

## Prototype deployment — release R1 (2026-10-07)

Deployed and verified live on Railway Hobby + Vercel (closed prototype).
Frontend https://routewright.vercel.app; backend health
https://routewright-production.up.railway.app/healthz. Release pair, settings
and rollback: DEPLOYMENT_PLAN.md §0; evidence: PRODUCTION_VERIFICATION.md
"Live results — release R1".

Work done:
- D-1 Railway client identity + HMAC limiter keys (`d80590f`), accepted
  Hobby key risk recorded (`a7f8aae`).
- CI fixed: gitleaks fingerprint-ignores for three verified test fixtures
  (`8d4118d`); e2e harness race (`d5e1fe5`, reproduced on Node 22). CI green
  on `d5e1fe5`.
- Railway: 502 cause = startup refusal (missing `LIMITER_KEY_SECRET`; Redis
  URL absent; `ALLOWED_ORIGINS` contained http://localhost). Set variables
  (secrets without printing), healthcheck `/healthz`, `PORT=8080`,
  `CLIENT_IP_SOURCE=railway`; deleted the old volume and moved to EU West
  (both approved). Vercel production `NEXT_PUBLIC_API_URL` reset; frontend
  redeployed after backend health.
- Live pass: selection, timezone, streamed planning, refresh from planned
  departure, comparison (40 min saving) and zero-call acceptance, cancel,
  map under CSP, desktop/mobile, headers, CORS, retired routes, forged-header
  rate limiting, hashed keys in TLS Redis, safe logs. 33 backend provider
  calls + 2 map loads.

Remaining (unverified live): opening-hours warnings/partial failures,
mid-call cancellation, production Redis fail-closed, runtime `id`, Map ID
value, log retention, Upstash usage, billing confirmation. Public launch is
gated on the server-key IP-restriction review and free-tier enforcement.

## Experiment — exhaustive four-stop optimiser (2026-10-08, local only)

Commits (not pushed): `d21bdc8` backend + contracts, `851ff2f` UI,
`b2adde0` result-card start assumption. Design and assumptions: TODO.md
"Approved experiment".

- Backend: `ExhaustiveRequest` (4 distinct stops, explicit stays, pins
  rejected); `services/exhaustive.py` (generate_orders,
  resolve_experiment_stays, geographic_path_metres, evaluate_order via the
  shared plan_sequential, rank_complete_candidates, optimise_exhaustive_four
  with a 72-call RoutingBudget); `execute_exhaustive` + streaming endpoint
  with its own 240 s DeadlineScope, comparison rate-limit scope and
  `exhaustive_progress` events; metrics operation `compare_exhaustive`
  (results not split, D46). Haversine now clamps rounding.
- Frontend: validated contracts, `streamExhaustive`, reducer purpose
  `exhaustive` (progress counts, stored result, atomic acceptance with zero
  network calls, pins by identity, edits/late events/cancel keep the plan),
  "Test all 24 orders" panel with assumptions before running, progress +
  Cancel, results, candidate list.

Checks (actual): backend 450 passed, 4 skipped (Redis env unset); ruff,
format, mypy clean; 24 new backend tests. Frontend: unit 99 (11 new),
browser 33 (2 new) on Node 22 and 23, type-check, lint, types drift, smoke,
bundle check, audit. Panel screenshots reviewed at desktop width.

Not done: live run (needs approval; uses up to 72 of 100 daily Compute
Routes), mobile screenshot review of the result card, deployment.

### Experiment review (2026-10-10)
- Mobile (390 px): explanation, live progress (streamed from the local test
  server), expanded 24-row candidate list, result and acceptance — no
  horizontal overflow; screenshots reviewed. New browser test.
- Acceptance now discloses pin changes (`exhaustivePinChanges`): a pinned
  endpoint that stops being an endpoint loses its pin; the new endpoint is
  not pinned. Unit + browser assertions (`197e443`, local).
- Original-order tie preference covered by
  `test_ranking_completion_then_distance_then_original_then_instance_ids`
  and `test_equal_completion_prefers_shorter_path_then_original`; both fail
  when the preference is removed from the ranking key (mutation check).
- Checks: unit 100, browser 34 on Node 22 and 23, type-check, lint;
  backend experiment tests 24/24.
- Found: `8d3d184` was pushed and auto-deployed (Railway `5d6537c7`,
  Vercel); the experiment is reachable in production. Usage since then is
  UNKNOWN — absent logs and expired Redis keys do not establish zero usage
  (corrected). Controlled live run prepared in DEPLOYMENT_PLAN.md (≤ 75
  Compute Routes incl. the 3-call initial plan); headroom must be confirmed
  in the Google Cloud Console.
- Tester-only access (`d6edef5`, local): backend 403 for anyone not on the
  tester allowlist (verified client identity, fails closed when empty),
  `GET /api/v2/experiments` for the UI; 11 backend tests (mutation-checked),
  client and browser tests. Backend 461 passed, 4 skipped; frontend unit
  101, browser 35 on Node 22 and 23.

## Next action

1. Closed-prototype use and feedback.
2. Before any public audience: mandatory server-key review (IP restriction,
   rotation, quotas), monthly free-tier enforcement, D36/D46 decisions,
   `braces` exception (expires 2026-11-04).
