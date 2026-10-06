# RouteWright staged implementation prompt

**Confirmed correction (2026-10-05):** The product manager confirms that the
API project's linked billing account address is India. Apply the non-EEA
service-specific terms. The previous EEA billing assumption is superseded;
EEA-specific map-display restrictions and UI Kit migration are not blockers
for this account. Preserve the Google map, backend suggestions and existing
backend opening-hours lookup. Minimal caching and fresh comparison decisions
remain approved. Any separately approved layout change is not automatically
reversed by this factual correction, but its EEA-compliance rationale is moot.
Do not describe switching tabs alone as proof of compliance under EEA terms.
Normal attribution, caching, security and production checks still apply.

Sources for the confirmed regional correction:
https://cloud.google.com/maps-platform/terms/maps-service-terms
and https://developers.google.com/maps/comms/eea/faq

Prepared: 2026-10-05. Status: implementation brief for product-manager review.
This document does not mean the changes are implemented or production-ready.

## Copy this instruction into the implementing agent's task

You are implementing the approved RouteWright system-design decisions in this
repository. The user is the product manager. Follow the stages below, inspect
the actual code, and keep progress and decisions durable. Do not substitute your
own product requirements or infer approvals from repeated single-letter replies.

Read SYSTEM_DESIGN_HANDOFF.md and all numbered decisions in TODO.md before
editing application code. TODO.md is the authoritative detailed decision
register. Later explicit amendments supersede earlier wording. This prompt
organises those decisions into implementation stages; it does not approve
unresolved integrations or a production deployment.

Preserve existing security controls and the existing Google backend opening-hours
lookup. Do not disable opening-hours checks to simplify integration. Build one
FastAPI modular monolith and the existing Next.js/React frontend, with no new
workers, microservices, durable jobs or state-management library.

### Step 0 — Establish the baseline and working record

1. Read applicable repository instructions and inspect git status, current HEAD,
   dependencies, CI and security documentation. Preserve unrelated user edits.
2. Inspect these real implementation surfaces before refactoring:
   - backend/app/models/request.py and response.py;
   - backend/app/routers/plan.py, optimise.py and refresh_leg.py;
   - backend/app/services/directions.py, geocoder.py, geocache.py, optimise.py,
     stay_defaults.py, hours.py and tz.py;
   - backend/app/core/limiter.py, provider_semaphore.py, config.py and security.py;
   - frontend/components/PlannerPage.tsx, PlanForm, StopList and PlanMap;
   - frontend/lib/api.ts and types.ts; .github/workflows/ci.yml.
3. Verify the suspected current behaviours rather than blindly relying on old
   descriptions: approximate parallel leg departures, fixed failure durations,
   optimiser/planner duration mismatch, device-time conversion, refresh using
   now, isolated frontend flags and persistent rich Places caching.
4. Record baseline checks and create IMPLEMENTATION_PROGRESS.md with a stage
   checklist, decisions covered, files changed, checks run, blockers and next
   action. Record failures honestly; do not call skipped checks passed.
5. Check off TODO.md decisions only after their code and meaningful validation
   are complete. Keep approved-but-pending entries unchecked. Do not rewrite
   the decision history to suggest an unresolved choice was approved.

Acceptance: a reproducible baseline and clear separation of existing behaviour,
approved requirements, unresolved questions and deferred features.

### Step 1 — Validate the existing non-EEA Google integration

Decisions: 13, 25–27, 34–39, 43–44, plus later layout decisions in TODO.md.
This replaces the earlier EEA migration investigation; do not restart completed
Step 1 or discard work already underway in Step 2.

1. Indian linked billing is confirmed by the product manager. Apply the current
   non-EEA agreement and service-specific terms. Record sources and verification
   date; do not require EEA grandfathering checks or Google confirmation solely
   to remove the inapplicable EEA map-display restriction.
2. Keep the Google map/custom place display, backend suggestions and selected-
   place verification, and existing backend opening-hours lookup. Do not adopt
   UI Kit, move provider calls to the browser, suppress names/hours/route details
   or disable opening-hours checks to address the obsolete EEA concern.
3. Verify ordinary attribution, applicable Google-map use, minimal field masks,
   API key restrictions, CSP and caching requirements. Indian billing is not
   blanket permission to store provider content or route results.
4. Finish suggestion session handling, provider field/cost tiers and verification
   admission/accounting within approved Decisions 34–38. Newly proposed numeric
   limits or material product changes still require a concrete approval proposal.
5. Preserve Decision 48's separately approved desktop tab layout unless the
   product manager changes it. Its EEA-compliance rationale is superseded;
   switching tabs is not proof of EEA compliance. Decision 49's EEA gate is moot,
   not a waiver of normal release/security/deployment checks.
6. Update MAP_INTEGRATION_PROPOSAL.md and IMPLEMENTATION_PROGRESS.md to distinguish
   historical EEA analysis from the active Indian-billing requirements. Preserve
   implementation evidence and the decision history. No Google contact is
   authorised, and no blanket contractual compliance claim is justified.

Acceptance: the existing backend-controlled integration remains the design;
EEA migration is not a blocker, ordinary provider requirements are checked,
and Step 2 can continue without restarting or changing approved features.

### Step 2 — Define authoritative contracts and shared engine boundaries

Decisions: 11–14, 18, 21–23, 31–33, 40–45.

1. Keep backend Pydantic models authoritative. Define typed city/place selections,
   distinct stop-instance IDs, explicit versus default duration input, pins,
   destination-local departure date/time, resolved timezone/occurrence data,
   operation identity and input revision. Preserve existing request bounds.
2. Represent complete, partial, previous/stale and failed calculations explicitly.
   Unknown downstream timestamps and totals must be null/absent with a reason,
   never zero or invented values. Distinguish missing hours from route failure.
3. Define structured outcomes for invalid selection/timezone, no route, provider
   failure, ambiguous provider error, quota/rate limit, capacity, timeout,
   cancellation, unchanged candidate and comparison ineligibility.
4. Define streamed models as a discriminated event union: operation start/phase,
   completed-leg progress, valid partial updates and exactly one terminal outcome
   when the connection permits delivery. Identify original versus alternative
   phases; include revision/operation identity on events. Do not leak raw provider
   errors, credentials or full request payloads into diagnostics.
5. Choose and document a POST-compatible streamed transport and parser as an
   implementation detail. No new durable job or polling API. Handle HTTP errors
   before streaming and typed terminal errors after response headers are sent.
6. Generate TypeScript from an offline export of the backend schemas. Choose
   deterministic maintained tooling, pin it, add generation/check commands and
   a CI drift check. Keep public schema/docs disabled if currently disabled.
   Do not introduce an independently maintained competing schema.
7. Add runtime event validation and bounded parsing. Treat invalid, truncated,
   out-of-order or incompatible data as incomplete/failure, never success.
8. Extract a shared calculation engine with injected Places/Routes adapters,
   duration resolver, hours evaluator, progress emitter, deadline/cancellation
   context and call-accounting interface. Endpoints orchestrate differences;
   provider adapters do not decide product eligibility or frontend state.

Acceptance: contracts distinguish every approved state, generated frontend types
match backend models, and deterministic adapters allow no-cost routing tests.

### Step 3 — Verify selections, durations and time before routing

Decisions: 11, 13–14, 25–30, 34–38, 40–45.

1. Require a specific city selection with region/country context and specific
   stop selections. Text edits invalidate the corresponding selected identity.
   Never automatically select the first text-search match.
2. Verify required identity and coordinates server-side, before any routing
   call. Invalid place: identify it and require reselection. Temporary failure:
   explain and allow a manual new attempt. Do not replace, skip or route a new
   prefix through an unverified destination. Optional missing hours are unknown.
3. Fetch needed venue details once per distinct provider place ID per operation.
   Share them across original/candidate calculations. Duplicate visits retain
   separate stop IDs/durations. Refresh verifies its required suffix context,
   not unrelated prior visits. Do not add rich selection previews automatically.
4. Resolve durations once from the original input order: explicit values win,
   including explicit zero; otherwise original endpoints default to zero and
   middle stops use existing place-specific defaults. Carry durations with stop
   instances through reordering and acceptance. Do not re-default candidates.
5. Resolve city and stop IANA zones offline from verified coordinates. No browser
   or UTC fallback and no Time Zone API addition. Unresolved/different-zone stop
   blocks calculation with its identity; same-zone outside-city stops are allowed.
6. Convert local departure using date-aware zone rules. Reject skipped local
   times; expose both repeated occurrences with UTC offsets and require explicit
   selection. Verify the selected occurrence server-side. Reset it on relevant
   edits. Retain current provider-supported departure-range validation.
7. City changes retain selected stop identities and user-entered durations,
   preserve local date/clock, update timezone and area warnings, and invalidate
   existing results. Never remap existing stops by their text names.
8. Use the selected city's permitted provider viewport for approximate outside-
   area warnings. If unavailable, say the check is unavailable; no invented
   50 km radius or official-boundary assertion. Handle longitude wrapping.
9. Subject to the approved integration, implement 300 ms suggestion debounce,
   two-character automatic minimum, explicit Search for shorter nonblank text,
   superseded request cancellation and late-response rejection.
10. Share city/place suggestion limits: 30/minute and 100/day per verified IP,
    including manual search. Preserve production Redis/trusted-proxy handling.
    No-result, rate-limit, storage failure and provider-budget failures are
    distinct. Suggestions and details count separately from routing and all
    actual backend provider calls consume the shared provider allowance.
11. Migrate persistent Places cache to IDs/coordinates only. Expire coordinates
    within 30 calendar days of fetching; reads do not extend expiry. Remove rich
    legacy names/types/hours payloads, avoid raw search text persistence, preserve
    file/security protections and document legacy backup treatment. Missing
    coordinates trigger permitted resolution, not stale-cache trust. A viewport
    permission must not be inferred from coordinate caching permission.

Acceptance: no routing before required verification, fixed comparison durations,
correct destination-local time, and explicit selection/area/timezone errors.

### Step 4 — Implement ordinary planning with sequential transit

Decisions: 1–3, 7–8, 11, 22–24, 31, 42–43, 45.

1. Start one 60-second monotonic deadline at operation entry, including admission
   waits, verification, solver work where applicable and provider calls.
2. Establish the first stop's planned arrival from the selected departure input
   according to the existing form contract; derive its onward departure using
   its resolved visit duration. Make this convention explicit in the schema/UI.
3. For each adjacent pair, request transit for that actual departure instant,
   derive arrival from the returned journey, then add the next stop's fixed
   duration to derive the following departure. Do not precompute all departures
   or fetch time-dependent legs in parallel.
4. Total journey seconds include walking/waiting/transfers as represented by the
   provider without double-counting subcomponents. Visits affect downstream
   departures but remain separately represented from transit totals.
5. Emit completed-leg progress and validated partial snapshots. For N stops,
   make at most N−1 routing calls. On the first failed leg stop; keep the valid
   portion and clear downstream calculated times/hours. No 15-minute fallback.
6. Distinguish confirmed no route for the departure from service unavailability
   when possible. Ambiguous errors say calculation failed. Do not imply that
   a provider no-route result proves no real-world journey exists.
7. Use no automatic routing retries. Manual retry starts a new budgeted attempt.
8. Bound each provider wait by the remaining deadline. Cancel/disconnect/expiry
   prevents further calls, releases capacity and cancels supported local work.
   Bound solver work cooperatively; cancelling an await does not necessarily
   terminate a worker thread. Verify cleanup rather than merely setting a flag.
9. Account actual issued calls, including failed/cancelled calls. Preserve shared
   fail-closed production accounting; do not grant retries or Places calls an
   uncounted path. A call already sent is not refunded by client cancellation.

Acceptance: later leg timestamps depend on earlier actual travel, failures leave
honest partial plans, and limits/cancellation/deadline apply to the whole attempt.

### Step 5 — Apply the latest opening-hours rules

Decisions: 15 as amended by 24, 42 and 43. Keep the existing backend source.

1. Evaluate actual computed local visit times, not candidate heuristic times.
2. Prefer date-specific hours only for dates their coverage actually includes;
   otherwise use regular weekly hours with a holiday/exception qualification.
   Missing, malformed or insufficient data is unknown, not proof of closure.
3. Positive-duration candidate visits: known closed on arrival disqualifies;
   closes during the requested visit warns but does NOT disqualify.
4. Zero-minute stops: known hours conflicts warn only. No claim that a station,
   hotel or outdoor meeting point is physically accessible based solely on hours.
5. An arrival at closing is closed. Preserve the requested stay; do not shorten,
   wait for reopening, delete stops or seek another candidate automatically.
6. Keep original-route conflicts visible. Preserve source qualifications and
   warnings through partial progress, comparison and accepted alternatives.
7. Support overnight/week-boundary periods and recognised 24-hour structures
   without treating every malformed missing close as always-open. No admission
   guarantee; weekly schedules remain unconfirmed for date-specific exceptions.

Acceptance: closed-on-arrival and closes-during-visit produce different candidate
eligibility, and all retained warnings survive acceptance.

### Step 6 — Consolidate frontend state and streaming behaviour

Decisions: 6–7, 12, 16–18, 22, 27–30, 32–33.

1. Use existing React reducer/state tools to coordinate draft, selected context,
   input revision, active operation, progress, previous/partial/complete result
   and unapplied suggestion. Avoid contradictory independent loading flags.
2. Each relevant edit increments revision, cancels superseded work, invalidates
   suggestions and marks retained results stale. Late events cannot change the
   current draft or clear stale status. Search revisions also include city/query
   context so old suggestions do not populate a new search.
3. Routing occurs only on explicit Plan, Optimise or Refresh actions. Reordering,
   duration edits and city changes never automatically calculate itineraries.
4. Show completed-leg counts with phase labels, not fake elapsed-time percentages
   or countdowns. Keep prior results visually distinguishable from newly computed
   partial results. Handle stream loss as incomplete, with an explicit new-attempt
   action; do not reconnect by automatically repeating costly work.
5. Offer Cancel for all operations, using abort/disconnect propagation. Do not
   present cancellation as quota refund or resumable background work.
6. Pin first/last by default. Manual edits remain free. Pins apply to current
   endpoint positions when optimising, preserve explicit unlock choices through
   list edits, and visibly identify protected endpoints.
7. Implement accessible progress/status/error text and selection controls without
   inventing new product flows. Do not expose backend implementation details as
   unnecessary user-facing diagnostics.

Acceptance: meaningful event sequences cannot overwrite newer inputs, edits make
zero routing requests, and users can distinguish previous from current results.

### Step 7 — Implement suffix refresh using the shared engine

Decisions: 21–23, 31–32, 37, 40–45.

1. Accept a matching current plan/input snapshot and selected zero-based leg k.
   Validate identity, ordering and request bounds; never blindly trust arbitrary
   client-supplied place coordinates or derived totals. Document refresh's
   calculated-snapshot input provenance; do not introduce server result storage.
2. Start at that leg's planned departure, NOT datetime.now(). If that timestamp
   is unsupported, explain rather than replacing it with now.
3. Preserve the prefix before k, route leg k and all later legs sequentially,
   propagate new arrivals/departures and re-evaluate affected hours.
4. At most N−1−k routing calls; separate attempt allowance and shared daily budget.
   Verify required suffix details once. Apply the same 60-second deadline,
   cancellation, progress, no-retry and verification rules.
5. Refresh cancels optimisation and invalidates its comparison/suggestion.
   Failure keeps successful refreshed work and unknown downstream times; do not
   mix old downstream timestamps into the new chain. Preserve the distinct old
   snapshot if needed to explain cancellation rather than presenting it as fresh.

Acceptance: unchanged prefix, planned departure, propagated suffix changes,
correct call count and no stale downstream chain after a failed refresh.

### Step 8 — Compare one local candidate with a fresh original

Decisions: 3–12, 15–20, 24, 31–32, 37, 42–43.

1. Verify inputs and resolve fixed durations. Run the existing bounded local
   Haversine/OR-Tools candidate generator, respecting pin constraints. Remove
   duplicate candidate orders by stop-instance identity, not place name/ID.
   Do not enumerate permutations or add paid matrix/candidate evaluations.
2. If the order is unchanged or pins leave no freedom, finish with "No different
   order found by the current search" and zero comparison routing calls.
   Never call it globally fastest or already transit-optimal.
3. Otherwise sequentially calculate the original, then the single alternative,
   using the same verified data, input snapshot, departure, durations and mode.
   Share details only inside the operation; no cross-request baseline totals,
   receipts or stored original-route results.
4. Allow N−1 original plus N−1 candidate routing calls: 2(N−1), maximum 22 at
   twelve stops. Initial plan is additional: plan plus comparison 3(N−1), or
   15 calls at six stops / 33 at twelve. Places and later refreshes are additional.
5. Original failure stops comparison and retains any previous result clearly
   labelled. Candidate failure retains the complete freshly calculated original.
   No route-rescue search, automatic retries or alternative after failure.
6. Compute saving in server-derived transit seconds. Recommend only if both
   routes are complete, candidate passes the amended hours eligibility, pins
   and integrity checks, and saving is at least 300 seconds before rounding.
   Equal/slower/<300-second results retain original order. Warn for unknown
   hours/closure during visits. Do not call it wholly hours-feasible or guarantee
   real-world savings. Distance remains a candidate heuristic, not evidence.
7. Return the complete eligible candidate timeline, fixed durations, warnings
   and comparison metadata. Require explicit Accept with matching revision.
   Atomically update form and displayed plan; acceptance makes zero additional
   planning/routing calls. It applies a snapshot, not a fresh conditions check.

Acceptance: only an accepted, completely evaluated eligible improvement can
replace the user's original; quota cost is bounded and accurately explained.

### Step 9 — Metrics, security regression checks and deployment verification

Decisions: 19, 23, 33, 46–47; existing SECURITY.md requirements.

1. Instrument aggregate operation elapsed time, issued calls and bounded outcome
   categories. Exclude names/IDs/coordinates, exact trip dates, IPs, payloads and
   per-trip identifiers. No high-cardinality labels or reconstruction of trips.
2. Prepare a concrete retention/storage/access proposal before adding an external
   metrics service or persistent telemetry design. No vendor/retention period is
   approved yet. Provider-derived improvement outcomes require permitted-use
   verification; do not persist journey totals as a metrics workaround.
3. Preserve trusted-proxy rules, Redis shared fail-closed counters, body limits,
   input validation, generic errors, selected response fields, no-store/security
   headers, key separation and cache permissions. Keep server credentials off
   the browser. New stream responses also need applicable headers/cleanup.
4. Run the existing relevant backend test/lint/type checks and frontend lint,
   type-check/build/security checks using the actual repository/CI commands.
   Add deterministic mocked-provider tests and browser integration coverage for
   new behaviour. Keep generated contract drift checks in CI.
5. Verify the actual deployment's buffering, request/proxy timeouts and disconnect
   detection support all three 60-second streams. Do not change the deadline to
   fit infrastructure silently or imply response headers guarantee completion.
6. Check live Maps/UI Kit loading under CSP and restricted keys only when the
   integration is approved and available. Verify production HTTPS/proxies/Redis
   and encrypted storage/backup settings; local CI cannot prove those settings.
7. Resolve/reassess the development-only braces advisory exception before
   2026-11-04; do not silently extend it. Reinspect dependencies/current security
   state rather than treating the earlier passed commit as current validation.

Acceptance: no security regressions, real deployment compatibility evidence,
privacy-preserving metrics proposal and honest separation of verified/untested.

### Step 10 — Review, release readiness and durable completion report

1. Deliver small reviewable stages in the approved order. Do not expose unfinished
   replacement features. Keep the deployment cohesive: a new streaming backend
   cannot silently break an old JSON client during a rolling release. Document
   coordinated rollout/compatibility and rollback before production deployment.
2. Maintain IMPLEMENTATION_PROGRESS.md and reference decision numbers in each
   stage report. State changes, checks, remaining risks and unresolved approvals.
3. Produce a final report with completed decision IDs, exact commands/results,
   provider-call evidence, generated-contract status, migration behaviour,
   deployment limitations and outstanding integration/metrics permissions.
4. Do not claim full readiness while an applicable integration approval or
   production check remains unresolved. Prepare a concrete release package;
   production deployment is not authorised by this implementation prompt.
5. Keep targeted implementation documentation accurate. A broad unrelated README
   rewrite and deferred features are not part of this scope.

## Required regression scenarios

Use mocks by default; do not exhaust live provider quota for combinatorial tests.

- Later transit connection changes when an earlier leg's duration changes.
- Invalid required place causes zero routing calls; missing hours do not block.
- Failure at leg j leaves only the valid prefix and unknown later times.
- Exactly 300 seconds saving qualifies; 299/equal/slower do not.
- Shorter-distance but slower-transit candidate cannot replace the original.
- Unchanged candidate and fully pinned two-stop trip make zero comparison calls.
- Duplicate provider place IDs share a detail fetch but retain separate visits.
- Explicit zero and reordered endpoints retain fixed original durations.
- Closed arrival rejects a positive-duration candidate; zero-duration warns;
  closes-during-visit warns without rejection; weekly qualification survives Accept.
- Date-specific coverage, holiday override, overnight/week boundary and bad hours.
- Different device timezone, city change, both repeated-clock occurrences,
  nonexistent local time, unresolved zone and different-zone stop.
- City change preserves stop selections/durations and local clock; outside-area
  warning is approximate and missing viewport is not inferred as inside.
- Edits/cancel/new operation reject late events; no automatic routing on edits.
- Refresh uses planned departure and changes every affected downstream leg/hours;
  failed suffix never presents stale later timestamps as newly calculated.
- Accept applies returned form/timeline atomically with zero provider calls.
- 60-second deadline includes verification/admission/solver/provider waits;
  disconnect/cancel stops future calls, releases resources and counts issued calls.
- Stream truncation/malformed event/pre-stream versus post-header errors are safe.
- Concurrent Redis counters, spoofed forwarded IPs, combined suggestion limits,
  global budget exhaustion and unavailable rate-limit storage fail appropriately.
- Cache migration removes rich legacy payloads, reads do not refresh coordinate
  expiry and expired coordinates cannot be used. Metrics omit prohibited fields.
- Generated types drift is detected; frontend/provider integrations respect CSP.

## Explicit exclusions

No exhaustive stop-order search, extra candidate evaluations, rescue-order
suggestions, automatic routing retries, route matrices, baseline/result retention,
workers/jobs/queues/resume, continue-on-disconnect behaviour, automatic Plan or
optimisation restart, leave-now refresh, multiple-timezone trips, configurable
saving threshold, new stop roles, silent venue replacement, shortened visits,
new routing provider, disabled opening-hours checks or automatic UI Kit adoption.
Keep these in TODO.md as future work; do not implement them as helpful extras.

## Approval boundaries

Approved numbered requirements are not questions to re-ask. Routine module,
schema and test choices can be made within them. Ask only for material changes
or unresolved product decisions, with a concrete proposal and tradeoffs. In
particular: map/Places integration changes, spending-limit changes, new telemetry
storage/vendor/retention and production deployment must not be inferred approved.
The remaining provider-use checks are not resolved by writing this prompt.
