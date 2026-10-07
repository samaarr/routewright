# System-design decisions and future work

## Latest scope direction — 2026-10-06

The product manager defers new monthly per-SKU free-tier enforcement during
development. This supersedes the earlier instruction to implement it first.
Preserve existing security/rate/global provider limits; do not add the proposed
reservation/accounting layer now. Reservation option A/B was not selected.
Continue product implementation: selection endpoints/area warnings/minimal
cache, frontend state/streaming/v2 migration, suffix refresh, then comparison
and acceptance. Focus on approved functional/nonfunctional behaviour, not new
agent workflows or repeated meta-design decisions.

Free-tier-only remains the future cost requirement. Do not claim existing limits
guarantee zero charges or authorise paid overflow. Use mocked providers for
development verification; preserve a central outbound-call accounting seam for
later per-SKU controls and identify browser map loads separately. No new live
Google testing or production deployment is authorised by this scope change.
Revisit enforcement with actual SKU allowances, existing account-wide usage,
atomic persistent counters, month boundaries and browser protections before
claiming a free-tier-safe public release. Do not disable hours or reintroduce
prohibited caching as a cost workaround.

## Latest cost requirement — 2026-10-06

The product manager requires remaining within the free tier. In this Google
billing discussion, treat zero paid Google Maps usage as a hard requirement:
stop issuing calls before verified free allowances are exceeded, rather than
allowing paid overflow or treating alerts as spending caps. Do not disable
opening hours to reduce the SKU tier. Exact counter architecture/admission UX
still requires a concrete proposal. Cover each actual SKU and browser map loads,
all projects sharing the billing account, existing usage and persistent atomic
monthly accounting; the current 2000/day aggregate limit is insufficient.
Indian billing determines non-EEA terms, but India PRICE eligibility additionally
requires a large majority of usage in India. Verify actual billing SKUs; do not
assume the India 7000/month Enterprise allowance applies to an Irish-focused app.
Until eligibility is verified, design against the lower global free allowances.
Sources verified 2026-10-06:
https://developers.google.com/maps/billing-and-pricing/india-overview
https://developers.google.com/maps/billing-and-pricing/pricing
https://developers.google.com/maps/billing-and-pricing/pricing-india

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

## Latest billing-region correction — 2026-10-05

The user states their Google API account is registered in India, superseding
our earlier assumed EEA billing context. Confirm the billing account address
actually linked to this API project; registration country alone is not proof.
If that address is India, apply non-EEA terms. Their Places section 14 and
Routes section 19 restrict use with non-Google maps, rather than imposing the
EEA prohibition on Places content with any map. Existing Google-map display
and the backend opening-hours lookup therefore need not be replaced by UI Kit
for that EEA reason. Earlier EEA-specific blockers/proposals in this document
are conditional until billing applicability is checked, not established facts.
Keep approved minimal caching and fresh-original comparison; Indian billing
is not blanket permission to cache names, hours or route results. Preserve
other approvals and any subsequent implementation evidence.
Sources: https://cloud.google.com/maps-platform/terms/maps-service-terms
and https://developers.google.com/maps/comms/eea/faq


Updated: 2026-10-05 (Step 1 decisions added)

This file records product-manager decisions from the system-design discussion.
The changes below are approved for inclusion in the implementation prompt;
they have not been implemented. Every further design change requires the
product manager's approval. The final step-by-step implementation prompt is
still being developed.

For restart/context recovery, read [SYSTEM_DESIGN_HANDOFF.md](SYSTEM_DESIGN_HANDOFF.md)
first, then this decision register. Later explicit superseding decisions take
precedence over earlier wording. Unchecked approved decisions are not evidence
that application code has been implemented.

## Approved decisions

- [ ] **1. Calculate journey legs sequentially.** Request the first leg, calculate
  arrival plus visit duration, then use that departure time for the next leg.
  Replace the current parallel pre-chain approximation, which omits previous
  travel time when requesting later routes. A complete N-stop itinerary needs
  N−1 routing calls, but sequential calls increase response time. Do not promise
  a particular loading time until performance is measured.

- [ ] **2. Preserve the valid portion when a leg fails; stop the timetable.**
  Keep successful stops and journeys visible. Identify the failed connection
  and leave downstream arrival/departure times unknown. Do not substitute the
  current fixed 15-minute duration or fabricate downstream opening-hours
  assessments. Distinguish provider unavailability from no transit route found
  for the requested departure time when the provider response permits it. If
  ambiguous, report that the route could not be calculated. Missing routing
  data does not prove that no real-world journey exists.

- [ ] **3. Prefer shorter achievable transit journey time.** Include waiting
  and transfers where the routing data represents them; visit durations affect
  subsequent departure times. This is the objective, not a guarantee of the
  globally fastest itinerary. Distinguish distance savings from verified time
  savings in the product.

- [ ] **4. Keep straight-line candidate generation; verify one alternative.**
  Retain the local Haversine/OR-Tools approach to propose a promising order.
  Respect pinned stops and compare it with the original user order using
  sequential transit routing. Recommend the alternative only when it is fully
  evaluated, feasible according to provider results, and faster. A complete
  comparison for six stops requires up to ten routing calls before retries or
  valid reuse: five for the original and five for the alternative. Place
  lookups are additional. Do not enumerate every possible stop order.

- [ ] **5. Budget one complete alternative: N−1 additional routing calls.**
  Scale the per-attempt allowance with the number of stops, capped at eleven
  under the current twelve-stop limit. Failed calls and retries consume this
  same allowance; there are no extra retry calls outside the budget. Place
  lookups are accounted for separately. Decision 10 supersedes the earlier
  baseline-reuse assumption: also allow up to N−1 calls to recalculate the
  original, for a total comparison cap of 2(N−1). If the alternative cannot
  be fully evaluated within its allowance, retain an available complete
  original and do not present an unverified improvement. No-route rescue
  search remains deferred.

- [ ] **6. Stream real progress within the optimisation request.** Keep the
  original plan visible while checking the alternative. Send updates based on
  completed work, such as "Checking journey 3 of 5", followed by a completed
  comparison or an explicit incomplete/failure outcome. Do not imply that a
  completed-leg fraction is a percentage of elapsed waiting time, or show a
  fabricated countdown. Work remains tied to the request lifecycle; no durable
  background jobs, workers, or job-result storage are approved for this version.
  Transport details, deadlines, and cancellation mechanics remain to resolve;
  Decision 7 defines the approved cancellation/disconnect behaviour.

- [ ] **7. Stop remaining optimisation work on cancellation or disconnect.**
  Offer an explicit Cancel action and stop scheduling further provider calls
  when the user cancels or the streaming client disconnects. Cancel local
  in-flight work where supported and release request/provider/solver capacity.
  Do not claim cancellation refunds a request already sent to Google; it may
  still consume quota and must remain accounted for. Keep the original plan
  available. Returning later starts a new attempt; resumable jobs are deferred.

- [ ] **8. No automatic routing retries in this version.** On a provider
  failure, explain the outcome and preserve an available valid original plan;
  do not silently retry or present an incomplete alternative as an improvement.
  Let the user explicitly start another attempt, subject to the existing rate
  limits and shared provider budget. A manual retry is a new attempt and may
  incur new calls; it is not an extension of the previous attempt's allowance.
  Confirmed no-route results are not automatically retried. All issued calls,
  including unsuccessful or cancelled ones, remain accounted for.

- [ ] **9. Stop without extra routing calls when the local suggestion is unchanged.**
  If the distance-based optimiser returns the user's existing order, report
  "No different order found by the current search" and finish. Do not claim
  that the order is fastest by transit or globally optimal. Generating further
  local candidates or offering a deeper search is deferred.

  Candidate generation currently uses Haversine straight-line geographical
  distance, not actual transit journey time. Treat the belief that a shorter
  geographical order will usually be faster as an unvalidated assumption,
  not an established fact. Decision 4's transit check is required before any
  different order can be recommended as faster. Preserve the user's original
  order and valid baseline throughout the comparison. Do not replace them on
  distance alone or on an incomplete, failed, equal-time, or slower comparison.
  Apply a verified improvement only after the user accepts it.

- [ ] **10. Recalculate the original and alternative in the same optimisation request.**
  This supersedes the previously approved retained-baseline design and removes
  baseline-storage permission confirmation as a dependency of this version.
  Generate the local candidate first: if its order is unchanged, Decision 9
  applies and no routing comparison calls are made. Otherwise calculate the
  original order afresh, then the single alternative, with sequential legs
  inside each itinerary. Both use the same input snapshot, departure time,
  stop identities, visit durations, mode, and applicable preferences.
  Compare server-calculated complete journey totals; never rely on totals
  supplied by the browser. Keep calculation state scoped to this operation;
  do not introduce a cross-request baseline-duration/result cache.

  Account separately for up to N−1 baseline calls and up to N−1 alternative
  calls: **2(N−1) routing calls per comparison**, capped at twenty-two for twelve
  stops, with no automatic retries. Six stops cost up to ten comparison calls.
  If the user already generated a plan, its original N−1 calls are additional:
  initial planning plus one comparison costs up to **3(N−1)**, or fifteen for
  six stops and thirty-three for twelve stops. Place calls and later explicit
  actions are accounted for separately. Failed/cancelled calls remain counted,
  and the existing shared daily provider budget still applies.

  Stream identifiable original-route and alternative-route progress. If the
  original recalculation fails, preserve the previously displayed plan as a
  previous result, explain that the new comparison could not be completed,
  and do not claim that the old result has been freshly verified. Stop at the
  failed leg under Decision 2; no automatic rescue-order search is approved.
  If the alternative fails, keep the completed recalculated original and
  explain the incomplete comparison. Cancellation/disconnect and no-retry
  rules remain in force. An alternative replaces the original only after a
  complete faster comparison and user acceptance.

- [ ] **11. Keep each place's visit duration fixed during comparison.** Resolve
  effective durations once from the original input order: explicit user values
  win, otherwise original first/last stops default to zero and middle stops
  use the place-specific planning defaults. Use the same resolved values in
  the local candidate calculation and both sequential transit evaluations.
  Carry each duration with its stop identity when reordered; do not reapply
  positional defaults to the candidate. An original zero-minute endpoint
  remains zero if moved into the middle, and a middle-stop visit remains intact
  if moved to an endpoint. Preserve these resolved durations in an accepted
  alternative so later client rendering or recalculation does not silently
  change them. Unify planning and optimisation duration resolution. Test
  explicit zero values, place defaults, reordered endpoints, and duplicate
  places with distinct stop identities. Explicit stop roles are deferred.

- [ ] **12. Cancel optimisation when relevant trip inputs change.** Keep editing
  available. A change to stop identity/order, visit duration, departure time,
  mode, city/resolution context, pinning constraints, or other inputs used by
  the current optimisation invalidates its input snapshot and cancels the
  attempt. Propagate cancellation to the server under Decision 7; already
  issued calls remain counted. Identify attempts and input revisions so late
  progress, errors, or completed results cannot overwrite a newer form, plan,
  or attempt. Invalidate any unapplied suggestion from the old inputs as well.
  The user explicitly starts a new attempt; automatic restart is not approved.
  Test an edit during routing, a late result after cancellation, and an older
  attempt finishing after a newer attempt starts.

- [ ] **13. Let users select a specific place before planning.** Offer place
  suggestions with identifying context such as name and address, and require
  selection of the intended place before routing. Carry the selected place
  identity through planning and optimisation instead of resolving the typed
  name to the first search result on each request. Editing a query invalidates
  its previous selection and requires selection again; also apply Decision 12
  to ongoing optimisation. Distinguish stop-instance identity from place
  identity so repeated visits to one place can have different durations.
  Validate submitted selection data server-side; do not treat browser-supplied
  coordinates, names, or other details as provider-verified merely because a
  place ID accompanies them. Preserve the entered query for user context where
  appropriate, but route to the selected identity. Autocomplete/session and
  place-detail costs, API integration, geographical bias/restrictions, field
  selection, attribution, and permitted retention remain implementation
  decisions. These requests are separate from the routing-call allowance and
  must not bypass the existing shared provider-budget controls.

- [ ] **14. Interpret departure input in the destination's local timezone.**
  Resolve the trip timezone from the selected destination context before
  converting the local date/time into a UTC instant. Label the departure field
  with the destination/timezone so users travelling from another timezone know
  what the value means. Do not use the browser/device timezone implicitly.
  Apply the same conversion to planning and optimisation, and display itinerary
  times consistently in the trip timezone. Preserve both the intended local
  date/time and resolved timezone in the request contract as appropriate for
  server verification; validate conversion server-side. A change to the trip's
  timezone invalidates the current plan/comparison under Decision 12. Detect
  nonexistent and ambiguous local times around clock changes rather than
  silently shifting them or picking an offset. Exact resolution UX is still
  to decide. Multi-timezone itineraries and a device-time entry toggle are
  deferred.

- [ ] **15. Reject alternatives with known opening-hours conflicts.**
  **Amended by Decisions 24, 42 and 43:** reject known closure on arrival for
  positive-duration visits, warn rather than reject for closing during a visit,
  warn only for zero-minute stops, and qualify weekly-hours fallback.
  After sequential routing establishes the candidate's actual planned arrival and
  departure times, check its visits against available venue hours in the
  destination timezone. Do not recommend a faster alternative whose planned
  visits fall outside known opening hours. Missing or unresolvable hours remain
  unknown and produce a warning; they are not proof that a venue is open or
  closed. Keep the original order visible and explain its own conflicts rather
  than silently moving/removing stops. If the one approved candidate conflicts,
  explain why it was rejected; do not start additional candidate searches.
  Local optimiser estimates/soft hours penalties alone do not establish final
  eligibility. Test arrival after closing, a visit extending beyond closing,
  unknown hours, and a faster but hours-ineligible candidate. Exact treatment
  of zero-minute anchors, boundaries, exceptional/holiday hours, and unreliable
  provider data requires clarification. Visit-specific overrides are deferred.

- [ ] **16. Pin the first and last stops by default; allow either to be unlocked.**
  Make the initial optimisation constraints preserve the user's intended start
  and finish. Clearly show both pin controls and respect explicit user changes
  in candidate generation and server validation. Keep this rule separate from
  Decision 11: unlocking or moving an endpoint does not silently change its
  resolved visit duration. A change to pinning invalidates the current
  optimisation/suggestion under Decision 12. If the constraints leave no
  different candidate (including two-stop trips with both ends pinned), follow
  Decision 9 and avoid routing comparison calls. Test locked endpoints,
  unlocking either endpoint, and no reorder freedom. Define how endpoint pins
  behave when stops are added, removed, or manually reordered separately.

- [ ] **17. Endpoint pins constrain optimisation only, not manual editing.**
  Let users manually reorder, add, or remove stops without unlocking first or
  confirming a boundary change. The current start/end pin settings apply to
  whichever stop instances occupy the first/last positions when optimisation
  starts; they do not follow a particular place into the middle. Keep existing
  explicit pin settings through list edits rather than silently resetting them
  to defaults. Make the protected endpoint names/positions visible. Relevant
  manual changes cancel ongoing optimisation and invalidate old suggestions
  under Decision 12. Test moving a previously pinned endpoint into the middle,
  changing the first/last stop, and preserving explicit unlock choices.

- [ ] **18. Apply the completed alternative directly on acceptance.** Return
  the full verified alternative timeline, resolved visit durations, warnings,
  and comparison data in the completed optimisation result. If the input
  revision still matches, accepting the suggestion updates the form order and
  displayed plan together without another planning/routing request. Do not
  regenerate durations or show a different timetable from the one compared.
  Treat it as the calculated snapshot, not newly refreshed transit conditions.
  Relevant edits invalidate acceptance under Decision 12. Keep the result in
  the current client flow; no server-side result cache is introduced. Test
  acceptance with zero additional routing calls, matching form/timeline order,
  fixed durations, and rejection of stale-input results. Refresh remains a
  separate user action; an age-based acceptance threshold is deferred.

- [ ] **19. Use a sixty-second overall optimisation deadline.** Start one
  monotonic deadline when the optimisation operation begins; include place
  verification, local candidate generation, admission/queue waits, and both
  sequential itinerary calculations. Progress updates and phase changes do
  not reset it. Combine remaining deadline time with provider timeouts so a
  slow call cannot indefinitely extend the operation. On expiry stop scheduling
  calls, cancel local work where supported, release capacity, and report an
  explicit incomplete-comparison outcome. Never recommend a partially evaluated
  alternative. Preserve a complete recalculated original if available; otherwise
  preserve the prior displayed result with its previous-result status. Issued
  calls stay counted. Verify deployment streaming/buffering/request limits can
  support sixty seconds before rollout; report incompatibilities rather than
  silently changing the limit. Measure timeout/completion rates to inform any
  later deadline change. Test deadline coverage across phases and cleanup.

- [ ] **20. Require at least five minutes of estimated transit-time savings.**
  Recommend the fully evaluated alternative only when its total journey time
  is at least 300 seconds lower than the freshly recalculated original, and
  it passes all other eligibility checks including Decision 15. Compare exact
  computed seconds before display rounding; exactly 300 seconds qualifies.
  Smaller improvements produce no recommendation and leave the original order
  intact. Describe savings as estimated, not guaranteed real-world savings or
  proof of a global optimum. The threshold filters small benefits; it is not a
  claim about provider accuracy. Test below, at, and above the threshold,
  including a time-saving candidate that fails the hours check. Configurable
  user thresholds are deferred.

- [ ] **21. Refresh the remaining timetable from the selected journey leg.**
  Start at the selected leg's planned departure instant, not the current clock
  time. Recalculate it and every subsequent journey sequentially, using the
  preserved visit durations to derive new downstream departures. Recheck
  downstream venue hours and replace downstream times consistently. Preserve
  the preceding itinerary unchanged. A refresh of leg index k (zero-based) in
  an N-stop trip needs at most N−1−k routing calls, counted separately from
  optimisation and against the shared provider budget. No automatic retries.
  Apply Decision 2 on failure: preserve successfully refreshed results, identify
  the failed connection, and mark downstream times unknown rather than mixing
  stale downstream times into the refreshed chain. Starting refresh cancels
  active optimisation and invalidates its suggestion/comparison; protect against
  late responses overwriting a newer trip. Define the in-flight and cancellation
  UI before implementation. Test changed arrival times propagating through all
  later legs/hours, unchanged prefix, selected planned departure, and failure
  halfway through refresh. A "leave now" replan/preview is deferred. If a planned
  departure is no longer supported by the provider, explain the failure; do not
  silently replace it with now.

- [ ] **22. Stream progress for planning, optimisation, and refresh.** Use a
  common progress approach across all three operations, with stages and counts
  based on completed work rather than fabricated percentages or countdowns.
  Offer cancellation and stop remaining work on client disconnect, using the
  same issued-call accounting and cleanup principles as Decision 7. Cancelling
  or superseding an operation must prevent its late events/results from
  overwriting newer input/results. Keep available previous plans clearly
  distinguished from newly completed or partial outcomes. Reuse event/error
  semantics where appropriate, while naming each operation and phase clearly.
  This adds no routing calls and no background workers/storage. Planning and
  refresh deadlines remain separate pending decisions; the sixty-second
  optimisation deadline is unchanged.

- [ ] **23. Use a sixty-second overall deadline for all three operations.**
  Planning and refresh use the same overall limit as optimisation, starting
  when each operation begins and covering all phases, provider/admission waits,
  and any relevant place verification. Progress never resets the timer. Bound
  individual provider waits by the remaining operation time, stop remaining
  work on expiry, release capacity, and report a terminal timeout/incomplete
  outcome. Do not invent downstream times or report success for a partial
  timetable. Preserve the available valid portion under Decision 2 and identify
  previous results separately. Verify deployment support for all streaming
  routes before rollout. Adaptive or shorter per-operation limits are deferred
  until measured performance justifies a change.

- [ ] **24. Warn on zero-minute opening-hours conflicts without rejecting.**
  Decision 42 later narrows positive-duration rejection to known closure on
  arrival; closure during a visit warns rather than disqualifies.
  Refine Decision 15: a known hours conflict during a positive-duration visit
  disqualifies the alternative, while a zero-minute stop outside known hours
  produces a visible warning and does not disqualify it. Do not claim a
  zero-minute stop is accessible or inaccessible merely from venue hours;
  explain the possible access issue. Missing hours remain unknown as already
  approved. Preserve warnings in the comparison and accepted plan. Test the
  same known-closed stop with zero and positive durations, including reordered
  original endpoints whose durations remain zero under Decision 11. Explicit
  access constraints and stop roles remain deferred.

- [ ] **25. Prefer city-nearby place matches, but allow outside-city selections
  with a warning.** Use the resolved intended city/area to guide suggestions;
  do not silently choose a distant first match. Make selected place locations
  clear and warn when outside the intended area, while allowing an explicit
  selection for nearby day-trip destinations. This is search guidance and a
  warning, not a strict administrative-boundary restriction. Area resolution,
  the warning threshold/geometry, and how to present/clear warnings remain
  decisions to settle. Do not assume the city name alone establishes a reliable
  boundary. One trip timezone remains the approved scope; this does not approve
  silently handling multi-timezone trips. Test an in-area place, an explicitly
  selected outside-area place, and misleading same-name matches.

- [ ] **26. Select the city from suggestions before planning.** Show city/area
  names with region and country so users can distinguish same-name locations.
  Use the selected city's provider identity and verified location as the trip
  context for nearby place suggestions, outside-area warnings, and destination
  timezone resolution. Do not silently infer the city from the first stop or
  pick the first result of an ambiguous city-name query. Editing city text
  invalidates the selected city until a new selection is made; changes to the
  resolved trip context invalidate ongoing operations and suggestions. Account
  for city selection/detail requests separately from routing calls. Exact
  supported locality types, city-change handling for existing stops, area-warning
  geometry, and the timezone-resolution mechanism remain to decide. Selecting
  a city does not itself supply or verify an IANA timezone; resolve that
  separately before interpreting departure input under Decision 14.

- [ ] **27. Preserve selected place identities when the city changes.** Keep
  each stop's selected provider identity and user-entered visit duration; do
  not silently resolve its name to a different place in the new city. Update
  the trip context and location warnings, cancel active calculations, and
  invalidate the old timetable/comparison/suggestion until recalculated. If an
  old result remains visible, explicitly identify it as belonging to previous
  inputs rather than the current trip. Existing selected places can be replaced
  individually by the user. New suggestions use the newly selected city.
  Re-resolve destination timezone under Decision 14; the departure-field
  behaviour on timezone changes still needs a separate decision. Test a city
  correction, a change to another city, same-name venues, and a late response
  from the previous city. Clearing selections or asking keep/clear confirmation
  on every city change is not approved.

- [ ] **28. Preserve the local departure date/time when the city timezone changes.**
  Keep the user's entered wall-clock date and time, and interpret them in the
  newly resolved destination timezone. Update the visible timezone label and
  revalidate the conversion and supported date range. Do not preserve the old
  UTC instant by silently changing the displayed local date/time. Invalidate
  the previous resolved instant and timetable/comparison; do not submit a new
  calculation until the new timezone is resolved and the local entry is valid.
  Ambiguous/nonexistent clock-change times require explicit handling, still to
  decide. Test a city change between different timezones with the local input
  preserved and UTC conversion updated, as well as failed timezone resolution.

- [ ] **29. Ask users to resolve clock-change departure ambiguity explicitly.**
  For nonexistent destination-local date/times, explain that the clock change
  skips the entered time and require another valid entry; do not shift it
  automatically. For repeated local times, offer both occurrences with their
  UTC offsets and require a selection before submission. Verify that the
  selected occurrence maps correctly to the local date/time and IANA timezone
  server-side. Reset the occurrence choice when relevant date/time/timezone
  inputs change. Use timezone-aware validation, not the device timezone or
  a fixed-offset assumption. Test valid normal times, skipped times, both
  repeated occurrences, invalid offset/occurrence submissions, and edits after
  an occurrence selection.

- [ ] **30. Recalculate edited itineraries only on an explicit Plan action.**
  Stop automatically issuing planning requests on reorder, visit-duration,
  departure, city, place-selection, mode, or other routing-affecting edits.
  Relevant edits invalidate the displayed timetable and comparisons, cancel
  superseded operations, and clearly mark any retained previous result as out
  of date. Allow users to complete multiple edits before pressing Plan to
  calculate their current input snapshot once. Validate selected city/places
  and destination-local departure before starting. Late results must not clear
  the stale state or overwrite a newer draft. Direct acceptance under Decision
  18 updates matching form/result state without another request; Refresh remains
  explicit. Place suggestions/details may still make their separately budgeted
  requests during editing; this decision stops automatic itinerary routing,
  not approved autocomplete. Test multiple draft edits with no planning calls,
  one explicit Plan submission, stale-result labelling, and late-event rejection.
  Debounced or live automatic replanning is deferred.

- [ ] **31. Keep one backend with a shared itinerary-calculation engine.**
  Retain FastAPI as one deployed application (a modular monolith). Move common
  duration resolution, sequential routing, hours assessment, progress reporting,
  cancellation/deadline enforcement, and provider-call accounting into shared
  modules with explicit interfaces. Keep endpoint orchestration and operation-
  specific rules separate: planning calculates the requested order, optimisation
  compares the original and one candidate, and refresh recalculates a suffix.
  Share typed input/result/event contracts and inject provider adapters for
  deterministic tests; do not create a second deployed service or background
  workers. Preserve all approved failure, eligibility, budget, and acceptance
  behaviours during refactoring. Test the common engine and meaningful endpoint
  differences. Future workers may call the same engine if separately approved.

- [ ] **32. Use a shared frontend state model for itinerary operations.**
  Consolidate planning, optimisation, and refresh coordination into explicit
  states/transitions rather than independent potentially contradictory flags.
  Represent draft validity, active operation/progress, complete or partial
  results, stale previous results, eligible suggestions, cancellation, and
  failures without losing the user's draft or original order. Tag events/results
  with operation identity and input revision; reject stale events and ensure
  edits, acceptance, refresh, and cancellation update related state together.
  Keep original/candidate comparison results distinguishable. Use React's
  existing state/reducer capabilities; no new state-management library is
  approved. Exact state/event schemas remain implementation details to specify
  consistently with the API contracts. Test meaningful transition sequences,
  including older attempts finishing after edits or newer attempts, partial
  failures, cancellation, and acceptance with no extra routing request. The
  model may later support background jobs without introducing them now.

- [ ] **33. Generate frontend API types from the backend schema.** Treat
  backend request, response, and streamed-event models as the authoritative
  contract. Generate TypeScript definitions and check in development/CI that
  generated files match the models. Include place/city identities, destination-
  local departure semantics, operation/input revision metadata, progress events,
  partial results, comparison eligibility/reasons, and terminal outcomes.
  Generate schemas offline; public documentation/schema endpoints need not be
  re-enabled. Specify deterministic tooling and commands in the implementation
  prompt; do not silently add a separately authored schema as a competing source.
  Compile-time types do not validate received JSON: handle malformed, unexpected,
  truncated, or version-incompatible stream data safely. Test contract generation
  and meaningful compatibility/error cases without duplicating every field in
  handwritten tests.

- [ ] **34. Route city/place suggestions and verification through FastAPI.**
  The browser uses backend endpoints for suggestions and selected-place
  verification; provider adapters perform the Google requests server-side.
  Apply server-side input validation, rate/admission limits, selected response
  fields, and fail-closed shared provider-budget accounting to actual outbound
  suggestion/detail calls. Do not allow autocomplete to bypass the existing
  budget or expose the server key. These requests are distinct from routing
  calls and must be measured/accounted for separately within the shared daily
  allowance. Existing browser map rendering remains separate; this decision
  does not proxy Google Maps tiles or its JavaScript loader. Session tokens,
  query timing/minimum length, per-user suggestion limits, no-result/error UX,
  provider field/cost tiers, and allowed retention still need specification.
  Keep the single backend deployment and use mockable provider adapters. Direct
  browser autocomplete with a separate cost-control model is deferred.

- [ ] **35. Request suggestions after a 300 ms typing pause, with two characters.**
  Apply this to city and place searches. Reset the pending timer on each edit;
  automatic suggestions require at least two characters after whitespace
  normalisation. Provide an explicit Search action for shorter nonblank names.
  Cancel superseded in-flight requests where possible and reject late responses
  whose search context/query/selection revision no longer matches. Do not issue
  redundant simultaneous requests for the same current query and context.
  Cancelling a timer before dispatch incurs no provider call; requests already
  sent to Google remain counted even if later abandoned. This reduces traffic
  but is not a hard spending limit. Preserve explicit result selection and keep
  query text separate from selected identity. Test quick typing with one request,
  timer reset, short queries, manual Search, and stale response rejection.

- [ ] **36. Limit city/place suggestion searches to 30/minute and 100/day per IP.**
  Share these counters across city and place search endpoints, including manual
  Search, rather than granting each endpoint separate allowances. Derive the
  IP through the existing explicitly trusted-proxy rules and share counters
  across replicas in production. Keep the actual outbound provider-call counter
  separate: suggestions still consume the shared daily provider allowance.
  Show rate-limit/storage/provider-budget errors distinctly from a successful
  search with no matches, with appropriate retry information. Do not retry
  automatically on a quota error. Recognise shared-network/NAT users share the
  per-IP allowance; these are initial limits to assess with measurements, not
  established optimal values. Selected-place verification/detail requests need
  their own accounting/limits specification. Test combined city/place usage,
  minute/day boundaries, spoofed forwarded IPs, and meaningful quota error UX.

- [ ] **37. Resolve required venue details once per distinct place per operation.**
  Fetch and verify the fields needed for the operation's affected stops, then
  share the resulting request-scoped data across its phases. Optimisation uses
  the same verified place data for original and alternative calculations; do
  not fetch it again for each order or leg. Repeated visits to one provider
  place identity share a detail lookup but remain distinct stop instances with
  their own durations/positions. Refresh resolves only details needed for its
  affected suffix and operation verification, not unrelated completed visits.
  Do not add rich venue-detail fetches on selection solely for previews. City
  resolution may still make the requests needed to establish the trip context
  and departure timezone before calculation. Later operations verify again
  unless a particular field's reuse is explicitly permitted and approved; no
  full-result cross-request cache is authorised. Track detail calls separately
  from routing/suggestions and against the shared provider budget. Specify
  minimal field masks, missing-detail handling, admission limits, and provider
  session completion rules in the implementation prompt. Test shared lookup
  across comparison orders, duplicate visits, and suffix-only refresh needs.

- [ ] **38. Retain only a minimal persistent Places cache.**
  Persist provider place IDs and latitude/longitude only; expire and delete
  coordinates no later than thirty consecutive calendar days after fetching.
  Do not extend expiry merely because an entry is read. Remove previously
  cached provider names, types and opening hours through an explicit migration;
  do not preserve rich legacy payloads in replacement tables or logs. Fetch
  needed venue details within each operation under Decision 37. Use stable
  place-ID keys rather than persisting raw user search text. Include migration,
  expiry-boundary and expired-entry lookup checks in the implementation prompt.
  Document treatment of existing backups separately; dropping database fields
  does not establish physical erasure from older backups. This decision covers
  storage only, not EEA permitted-use, attribution or map-display restrictions.

- [ ] **39. Investigate a map-preserving integration before proposing changes.**
  Evaluate Places UI Kit capabilities, EEA applicability, pricing, available
  quota controls, and compatibility with the custom itinerary and backend
  calculation engine. Produce a concrete integration proposal for product
  approval before revising approved Decisions 34–37 or any other architecture.
  This approves investigation only, not adoption or application-code changes.
  In particular, automatic opening-hours requirements remain approved: the
  user has not chosen to remove them or mark them unchecked. UI Kit does not
  expose hours/types/names programmatically; assess a permitted data source for
  backend checks separately. Distinguish browser UI Kit usage from enforceable
  backend counters, and review Routes-specific map-display restrictions too.
  User clarification: retain automatic opening-hours checks using the existing
  backend Google Places lookup; do not disable them or substitute another
  provider without approval. Applicable permitted use still needs verification;
  UI Kit adoption alone does not settle that backend use.

- [ ] **40. Resolve the selected city's timezone offline; fail explicitly.**
  Reuse timezonefinder with server-verified city coordinates to resolve an IANA
  timezone. If lookup fails or the zone is invalid/unavailable, block planning
  and comparison, explain that the destination timezone could not be resolved,
  and request another city selection. Never silently fall back to the browser
  timezone, supplied client timezone, or UTC. Do not add Google Time Zone API
  calls. Use date-aware timezone conversion with the approved DST handling in
  Decision 29; retain local clock semantics in Decision 28. Test failed lookup,
  invalid zone, device/destination mismatch and seasonal offsets. This resolves
  the trip timezone only; cross-timezone journeys remain a separate scope issue.

- [ ] **41. Support one timezone per trip for now.**
  Resolve each selected stop's IANA timezone offline from verified coordinates.
  Before routing, block calculation if a stop's timezone cannot be resolved or
  differs from the selected city's timezone, and identify the affected stop
  with an actionable explanation. Do not silently interpret its opening hours
  in another timezone. Outside-city stops remain allowed under Decision 25
  when they satisfy this timezone constraint. Apply validation consistently to
  planning, optimisation and refresh; reject stale client timezone claims.
  Test outside-city same-zone stops, differing zones and unresolved lookups.

- [ ] **42. Require opening on arrival; warn about closing during a visit.**
  For positive-duration visits, known closure on arrival still disqualifies an
  alternative, but a venue closing during the requested stay does not. Display
  the closing time and an explicit warning that the full visit may not fit;
  preserve the requested duration and do not automatically shorten the visit or
  wait for reopening. This supersedes Decision 15's rejection of alternatives
  specifically for closing during a visit. Do not describe such an alternative
  as fully opening-hours-feasible. Original-route warnings and Decision 24's
  warning-only zero-minute handling remain. Unknown hours stay unknown. Test
  arrival at closing, closure during a stay, and warning retention on acceptance.

- [ ] **43. Prefer date-specific hours; qualify weekly-hours fallback.**
  Using the existing backend Places lookup, prefer date-specific hours when
  provided for the actual local visit date. Do not apply limited current-hours
  coverage to dates outside its validity window. Otherwise evaluate regular
  weekly hours and label the result as based on the weekly schedule, with
  holiday/date-specific changes unconfirmed. Missing, malformed or insufficient
  hours remain unknown, not open or closed. Preserve Decision 42's arrival-only
  requirement and closing-during-visit warnings, and Decision 24's zero-minute
  handling. Carry source/coverage qualification through streaming, comparison
  and acceptance; do not automatically add separate exception-search calls.
  Test date coverage, exceptions overriding regular hours, weekly fallback,
  overnight/week-boundary periods and unknown data. Backend permitted use
  remains a separate verification item; this does not establish that permission.

- [ ] **44. Warn outside the selected city's provider-supplied map area.**
  Use the verified city's returned bounding area/viewport to check selected
  stop coordinates. Outside points receive a warning labelled "Outside the
  selected city's suggested area"; this is not an official administrative
  boundary and must not block a same-timezone stop. If a valid area is missing,
  explicitly mark the area check unavailable rather than inventing a radius or
  asserting the stop is inside. Update warnings on city/stop changes under
  Decisions 25–28, independently of Decision 41's timezone constraint. Handle
  boundary points and longitude wrapping consistently. Test inside, outside,
  unavailable-area and changed-city cases. Use the approved integration's
  permitted viewport data; do not add a separate boundary-data service.

- [ ] **45. Stop before routing when a required place cannot be verified.**
  Verify identity and coordinates for all places required by the calculation
  before issuing routing calls. If a selection is confirmed invalid/unresolvable,
  identify it and request reselection. For temporary provider failures, explain
  the failure and offer a manual new attempt under the approved budgets; do not
  claim the place is invalid. Never substitute a first search result, skip the
  stop or create a new routed prefix for this failure. Previously displayed
  results retain their existing stale/previous-result labels. Apply this to
  plan and comparison and to required refresh verification under Decision 37.
  Missing optional hours remain unknown; this requirement concerns identity
  and coordinates. Test invalid selections, temporary failures, zero routing
  calls after failed verification, and no silent destination replacement.

- [ ] **46. Collect aggregate operational metrics without trip details.**
  Measure operation duration, actual provider-call counts, completion/failure
  rates and, only after confirming permitted use, the aggregate frequency of
  alternatives meeting Decision 20's five-minute improvement threshold. Do not
  retain provider journey totals/savings or trip-level comparisons as a way to
  bypass baseline-storage restrictions. Exclude place names/IDs, coordinates,
  exact trip dates, IPs and complete itineraries from metrics; avoid identifiers
  or high-cardinality labels that reconstruct individual trips. Preserve
  existing privacy controls. Operational elapsed times and counters can be
  measured independently of retaining Google-derived journey attributes.
  Specify retention, aggregate labels, access controls and collection/storage
  implementation before release; no external analytics vendor or new telemetry
  infrastructure is selected by this decision. Test excluded fields and bounded
  labels. Use measurements to assess approved starting limits and comparison
  benefit, not to silently change product behaviour or budgets.

- [ ] **47. Implement the redesign in stages.**
  First settle the map/Places integration and shared data contracts. Then fix
  ordinary planning with verified inputs, sequential transit, partial results
  and progress. Next implement consistent refresh, followed by original-versus-
  alternative comparison and acceptance. Validate the complete flow before
  production release; keep unfinished features unavailable to users. Use small,
  reviewable changes with relevant checks at each stage. This changes delivery
  order only; it does not remove requirements or authorise production deployment.

- [ ] **48. Switch desktop view to map-tab / plan-tab layout.**
  On desktop (≥1024 px), replace the three-pane simultaneous layout (form |
  map | timeline visible at once) with a two-tab layout matching the existing
  tablet layout: one tab shows the map, the other shows the timeline/plan.
  The form pane remains always visible alongside the active tab.

  **Correction 2026-10-05:** The EEA map-display restriction rationale for
  this decision is superseded (Indian billing confirmed; EEA restrictions do
  not apply). The tab layout remains approved as a product/UX improvement and
  release prerequisite (D49). Do not cite tab layout alone as proof of EEA
  compliance; it is not required for that purpose under non-EEA terms.

  Do not change the map pane content or the timeline content. Do not add UI
  Kit elements. Do not change the stop input widget (D34 remains as approved).
  Apply Decision 12 tab-switch semantics: switching tabs does not trigger a
  new plan calculation. Test that map and timeline are never simultaneously
  visible on desktop, that the tablet and mobile tab layouts are unchanged,
  and that the optimise button and order-toggle placement remain correct on
  each tab. Map pins, polyline, transit layer, and AdvancedMarker positioning
  remain unchanged.

- [ ] **49. Meet normal release criteria before production deployment.**
  Release to production once the desktop tab layout (Decision 48) is
  implemented, all stage checks pass, and ordinary security/deployment
  requirements are met. No Google EEA verification is required (Indian billing
  confirmed; EEA gate is moot). Continue to monitor Google Maps Platform
  policy communications after launch. Do not contact Google on behalf of
  the product without separate explicit authorisation. Decision 34 (backend-
  controlled suggestions) remains approved as-is; Places UI Kit Autocomplete
  as a stop-input mechanism is not adopted and is not approved by this decision.
  If Google policy communications or billing notices raise a new issue after
  launch, resolve it as a separate decision at that time.

  **Correction 2026-10-05:** Original framing as "EEA compliance gate"
  superseded. Normal deployment checks (TRUSTED_PROXY_IPS for the verified
  ingress — TRUSTED_PROXY_COUNT is obsolete and rejected at startup — Redis, key
  restrictions, HTTPS/CSP, storage) remain required.

## Decisions still required before implementation

- [ ] Define place-call accounting separately from the routing-call allowance.
  Routing retry policy is settled by Decision 8: no automatic retries.
- [ ] Specify place-selection integration and autocomplete session handling,
  server verification, fields, attribution, allowed retention, and cost limits.
  Decisions 25/44 settle outside-area warning semantics; specify verified city
  resolution, permitted viewport access and unsupported-selection UX.
- [x] **Resolved (superseded by Indian billing — 2026-10-05).** Original
  question was whether EEA Places/Routes map-display restrictions required
  UI Kit migration. Investigation found: UI Kit cannot replace backend
  hours lookup (hours/types/names are UI-only, not programmatically
  accessible). Correction: Indian billing confirmed; EEA restrictions do
  not apply. Existing integration (Google Maps JS API, backend Places REST,
  backend Routes API) needs no EEA-driven changes. Decision 34 (backend
  suggestions) unchanged. Decision 48 (desktop tab layout) remains approved
  as a product/UX change, not as an EEA compliance measure. No Google
  contact authorised. Normal attribution, key restrictions, CSP and caching
  requirements still apply. See MAP_INTEGRATION_PROPOSAL.md for historical
  EEA analysis and SYSTEM_DESIGN_HANDOFF.md for the correction record.
- [ ] Specify opening-hours source/coverage representation and robust boundary
  parsing under Decisions 24, 42 and 43; do not claim guaranteed admission.
- [ ] Verify deployment support for Decision 19's sixty-second streaming
  deadline and the transport/error behaviour when infrastructure closes a
  connection before the application can deliver its terminal outcome.
- [ ] Confirm deployment support for streaming all three flows with Decision 23's
  sixty-second overall deadlines and consistent terminal/error handling.
- [ ] Define the streaming event contract, deployment buffering/time limits,
  disconnect detection, and cancellation propagation through the provider and
  solver work. Explicit cancellation and stopping on disconnect are approved.
  Progress must reflect completed work and must not leak request payloads.
- [ ] Define selection and duplicate elimination for the single local candidate.
  Unchanged-order behaviour is settled by Decision 9. One alternative is the
  approved scope; additional paid candidate evaluations require approval.
- [ ] Define the API representation and UI for partial plans, unknown times,
  provider failures, and no-route results.
- [ ] Specify response/event schemas for the full completed alternative and
  input revision used by Decision 18. Cross-request server caching is not
  approved; acceptance must not issue another planning/routing request.
- [ ] Define refresh partial-result/in-progress UI and how input edits invalidate
  refresh responses. Decision 22 approves progress/cancellation/disconnect
  behaviour; Decision 23 sets their deadlines to sixty seconds.
- [x] Define aggregate metrics retention/storage under Decision 46 (Step 9,
  2026-10-06): one JSON log line per v2 operation via Railway's log platform,
  retained per the Railway plan (Hobby 7 / Pro 30 / Enterprise up to 90 days;
  actual plan unverified); bounded labels; excluded fields tested
  (`tests/test_opmetrics.py`). See `app/core/opmetrics.py`.
- [ ] Confirm permitted use before collecting the frequency of alternatives
  meeting the five-minute threshold (Decision 46). Until then comparisons log
  only `compared`/`incomplete`/`no_different_order`, with no savings.
- [ ] Review and approve SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md, prepared on
  2026-10-05 with stages, tests, rollout requirements and explicit exclusions.
  Creating the prompt does not settle remaining integration/metrics decisions.

## Deferred product problems — recorded, not approved for implementation

- [ ] **Trips spanning multiple timezones.** Revisit Decision 41 using absolute
  timestamps for travel, venue-local opening-hours checks, and explicitly
  labelled local arrival/departure times. Define date-boundary and DST behaviour
  before allowing cross-timezone stops; current scope requires one trip zone.

- [ ] **Optional automatic itinerary recalculation or live editing mode.** Revisit
  only if users need it, with a defined debounce, cancellation, duplicate-work
  prevention, and provider-call budget. Decision 30 requires explicit Plan
  submission after edits, so intermediate drafts do not incur routing calls.

- [ ] **"I'm leaving now" remaining-day replanning or a separate live preview.**
  Revisit how a traveller's current time/location and completed stops should
  affect the remaining itinerary. Decision 21 refreshes from a planned departure
  and does not introduce current-time replanning or alter the completed prefix.

- [ ] **User-configurable minimum time savings.** Revisit whether users should
  choose a threshold based on trip length or preferences. Decision 20 currently
  requires at least five minutes of estimated savings before recommending an
  alternative; assess usefulness through approved measurements before changing it.

- [ ] **Visit-specific hours requirements and outside-visit overrides.** Revisit
  controls for visits that do not require venue entry, reservations, or other
  explicit time constraints. Decision 15 currently disqualifies candidates
  with known opening-hours conflicts and warns when hours are unknown.

- [ ] **Multi-timezone trips and optional device-time entry.** Revisit how stop
  timezones, departure entry, and opening hours interact when trips cross
  timezone boundaries. Decision 14 currently assumes one resolved trip timezone
  and destination-local departure input. Additional entry modes require approval.

- [ ] **Optional automatic optimisation restart after edits settle.** Revisit
  restarting after an input pause only if users need it, with explicit quota
  accounting, duplicate prevention, and cancellation rules. Manual restart is
  the approved behaviour now. Comparing saved trip versions is also deferred.

- [ ] **Explicit stop roles instead of positional duration defaults.** Revisit
  distinguishing start/end locations (for example hotels or stations) from
  places to visit, with role-based durations and constraints. This would avoid
  the ambiguity of an original zero-minute endpoint moving into the middle.
  It requires separate approval of form fields, API semantics, defaults, and
  migration behaviour. Decision 11 preserves fixed original durations now.

- [ ] **Revisit retained baseline reuse only if expressly permitted.** The product
  manager confirmed EEA billing and chose recalculation to avoid an unresolved
  storage dependency. Previous proposals for short-lived server baseline
  records, server-signed receipts, or aggregate-only totals are superseded for
  this version. Aggregate journey seconds would suffice mathematically for a
  comparison, but storage/reuse permission was not established. Before future
  adoption, confirm the applicable agreement and permissions, freshness,
  exact-input matching, expiry, anonymous access protection, and allowed fields.
  Do not assume a short expiry or aggregation exempts provider-derived data from
  the restrictions. EEA Terms 3.3.2(b) and Routes terms 20.2 informed the review;
  they do not establish general permission to retain durations for this use.

- [ ] **Validate the straight-line-distance assumption and protect user routes.**
  Haversine distance measures geographical separation (rather than literal
  Cartesian distance); it does not encode transit lines, direction, service
  frequency, waiting, transfers, barriers, or departure-time availability.
  A geographically shorter itinerary can therefore be slower by transit.
  Record the product risk that a user's already efficient or fastest order
  could be lost if distance-only output is automatically applied. This is a
  potential regression to prevent, not a confirmed current-code bug.
  The approved safeguard is to retain the original and apply only an accepted,
  fully transit-verified faster alternative. Future evaluation should measure
  how often geographical candidates are faster, equal, slower, or infeasible;
  do not assume "usually fastest" without evidence. Tests in the implementation
  prompt must cover a shorter-distance but slower-transit candidate, a failed
  candidate, an equal-time candidate, and an unchanged geographical suggestion.

- [ ] **Broader local candidate generation when the first suggestion is unchanged.**
  Revisit local swaps or other candidate-generation approaches, or an explicit
  "Check another order" action. Select at most the separately approved number
  of paid evaluations and respect pinned stops. A different candidate is not
  guaranteed to exist or improve the original. Decision 9 currently stops the
  search without additional routing calls.

- [ ] **Selective automatic routing retries.** Revisit only after measuring
  transient provider failures and deciding how retries fit the per-attempt
  allowance, completion capacity, deadlines, and shared daily budget. Consider
  retrying eligible temporary failures with backoff; do not treat a no-route
  result as a transient service failure. No automatic retries are approved now.

- [ ] **Background optimisation infrastructure with progress.** Revisit workers,
  a controlled queue, job-status/result storage, and frontend status polling
  when longer searches, higher concurrency, or work surviving disconnected
  requests justify them. Assess anonymous job-access protection, retention and
  expiry, duplicate-work prevention, cancellation, recovery, deployment cost,
  and budget accounting across retries. Preserve the approved progress messages
  if migrating later. Background execution does not itself make sequential
  provider calls faster, and queue waiting must be visible to users.

- [ ] **Continue through a disconnect; stop only on explicit cancellation.**
  Revisit Decision 7 option B when background-job infrastructure and secure
  reconnect/result retrieval exist. A temporary network interruption could
  then leave the job running so the user can reconnect to its progress/result.
  Define expiry, abandoned-job limits, duplicate-attempt prevention, and quota
  accounting before adoption. For the current request-bound design, disconnects
  stop remaining work; this future behaviour is not approved for implementation.

- [ ] **Find a doable stop order when the chosen order has no transit route.**
  A place may be reachable from another user-selected stop even when it cannot
  be reached from its current predecessor at the relevant time. In a future
  feature, explain the failed connection and suggest a feasible alternative
  order, even if it is less optimal, for the user to accept. Reordering changes
  departure times, so feasibility must be checked. For now, stop the timetable
  with a reason; do not add automatic rescue search.

- [ ] **Reassess the cost versus quality of transit-aware search.** Straight-line
  distance is cheap but can miss useful transit connections. With six freely
  movable stops there are 720 possible orders; exhaustive external evaluations
  are unsuitable for the current quota model. The approved shortlist is one
  alternative. Revisit a larger shortlist, targeted search around a failed
  connection, or optional thorough search only after measuring benefit and cost.

- [ ] **Investigate owning transit-routing infrastructure if justified.**
  OpenTripPlanner with appropriate transit feeds and OpenStreetMap data could
  enable more searches without per-query Google routing fees. Assess supported
  cities, feed availability/licensing, real-time updates, hosting costs,
  operational maintenance, and accuracy before proposing adoption. This is not
  part of the current implementation scope.

- [ ] **Reassess route matrices and caching before using them.** Google route
  matrices are billed per origin–destination element, not merely per HTTP
  request; a full six-by-six matrix represents 36 elements. A fixed-time matrix
  does not capture a day's changing transit departures. Most Routes content has
  caching restrictions. Review applicable terms and freshness requirements
  before proposing persistent route-result caching.

- [ ] **Bring documentation into agreement with the code.** The README still
  describes an LLM parser, older endpoints, and older stack/feature information.
  Use the implemented `/api/plan`, `/api/optimise`, and `/api/refresh-leg` flow
  as the factual baseline. A documentation rewrite has not yet been approved.

## Research informing the discussion

These are published approaches, not claims about the companies' complete
current proprietary algorithms. Their scale and routing-data ownership differ
from RouteWright's external-API model.

- [Google transit transfer-pattern research](https://research.google/pubs/fast-routing-in-very-large-public-transportation-networks-using-transfer-patterns/):
  precompute reusable routing structure to make individual queries cheaper.
- [Google Maps ETA architecture](https://deepmind.google/blog/traffic-prediction-with-advanced-graph-neural-networks/):
  separate candidate routes from travel-time prediction and ranking.
- [Uber traffic and routing architecture](https://www.uber.com/nl/en/blog/scaling-real-time-traffic/):
  routing consumes forecasts generated from its own road-network data.
- [DoorDash dispatch architecture](https://careersatdoordash.com/blog/using-ml-and-optimization-to-solve-doordashs-dispatch-problem/):
  separate candidate generation, outcome estimation, and optimisation; assess
  changes through simulation and experimentation.
- [Google Routes billing](https://developers.google.com/maps/documentation/routes/usage-and-billing)
  and [Routes policies](https://developers.google.com/maps/documentation/routes/policies).
- [Non-EEA service terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)
  and [EEA service terms](https://cloud.google.com/terms/maps-platform/eea/maps-service-terms):
  confirm the applicable agreement before designing baseline retention/reuse.
- [EEA Terms of Service](https://cloud.google.com/terms/maps-platform/eea)
  and [EEA transition FAQ](https://developers.google.com/maps/comms/eea/faq).
- [OpenTripPlanner](https://www.opentripplanner.org/).

## Existing security follow-ups

The security code is implemented and commit `49a77e8` passed all four GitHub CI
jobs; later local commits have not run in CI (not pushed). None of this
verifies the deployment's settings. See [SECURITY.md](SECURITY.md),
[DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md) (proposal) and
[PRODUCTION_VERIFICATION.md](PRODUCTION_VERIFICATION.md) (all unverified).

### Approved 2026-10-06 and implemented locally
- [x] Ephemeral location cache, no volume, non-root container; cache failures
  are misses; planning independent of it (`7365dee`). Storage-security
  considerations remain (host disk, shell access, old deployment's data).
- [x] Redis must use verified TLS (`rediss://`); production refuses plaintext
  or weakened TLS (`5ef006d`).
- [x] v1 endpoints `/api/plan`, `/api/optimise`, `/api/refresh-leg` retired;
  v2 services and the local optimiser kept; retired routes 404 (`3c9f7ec`).
- [x] Client IPs removed from 429 log lines (`8123f47`) and uvicorn WebSocket
  log lines (`f3901c9`, `--ws none` + redaction filter).
- [x] Metrics: aggregate app logs on the hosting platform only; no archive; no
  sensitive content or comparison savings.

### Deployment blockers and open approvals
- [ ] **Public-launch gate (mandatory):** review the accepted Hobby risk —
  server key without an outbound-IP restriction (accepted 2026-10-07 for the
  closed prototype). Re-decide the IP restriction, rotate the key, re-check
  quotas/usage before opening the app to a public audience.
- [ ] **Server key outbound-IP restriction (approved requirement) — BLOCKED:**
  hosting is fixed to Railway + Vercel; Static Outbound IPs need Railway Pro
  ($20/month incl. $20 usage; +$15/month net over Hobby; IPs may be shared
  with other customers). Cost decision pending; not relaxed
  (DEPLOYMENT_PLAN.md §6).
- [ ] Redis provider with TLS (proposal: Upstash free plan, `eu-west-1`, no
  payment method so no automatic paid upgrade; eviction off). TLS path
  verified locally with the existing client and limiter library.
- [ ] Client-IP integration (final proposal D-1, Railway) incl. HMAC-hashed
  limiter keys (Redis keys currently contain raw client IPs). Until then all
  visitors share one rate-limit identity.
- [ ] Railway 502 on the existing service: owner to collect deployment status,
  deploy logs and settings (DEPLOYMENT_PLAN.md §3).
- [ ] Confirm ownership of `routewright.vercel.app` and the Railway project;
  the live frontend serves an old build and its backend returns 502.
- [ ] Check the restrictions of the browser key embedded in the live bundle.
- [ ] Production Map ID (proposal; creating one is free).
- [ ] Push local commits and get green CI.

### Unverified until deployed (PRODUCTION_VERIFICATION.md)
- [ ] HTTPS/HSTS, CORS, retired routes on the live host, headers.
- [ ] Streaming (60 s, no buffering) and disconnect propagation through the
  host's proxy.
- [ ] Key restrictions (browser and server), live map under CSP.
- [ ] Redis TLS connection, eviction policy, outage behaviour.
- [ ] Live walking-step `staticDuration` completeness; billing SKU mapping.
- [ ] Actual log retention for the hosting plan; platform HTTP logs access.
- [ ] Container non-root and `/healthz` on the host (CI and local checks only).

### Deferred
- [ ] Monthly free-tier enforcement (approved deferral). Quotas, alerts and the
  app budget do not guarantee zero charges.
- [ ] D36 selection limits: lookups share the combined 30/min + 100/day
  allowance as an interim choice.
- [ ] D46: permitted use before logging how often alternatives meet the
  five-minute threshold.
- [ ] Resolve or reassess the development-only `braces@3.0.3` advisory exception
  before it expires on **2026-11-04**. Do not silently extend the exception.

### Done earlier
- [x] Shared-Redis regression tests pass against a disposable local Redis.
- [x] Server-key bundle leak check runs in CI.
- [x] npm audit fixed with scoped overrides (e3192f5).
- [x] Local container check (non-root, `/healthz`, intended container, no IPs).
