# Next implementation task: finish verified inputs and hours in v2

Prepared 2026-10-06. This is an implementation task for the existing agent;
do not restart completed contracts or desktop layout work.

## Task

Complete the missing verified-input and opening-hours integration for
POST /api/v2/plan before migrating the frontend or adding streaming. This
finishes relevant requirements from Steps 3–5 of
SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md. Progress labels have drifted; identify
work by requirement and prompt section, not solely by a claimed step number.

Read AGENTS.md, TODO.md, SYSTEM_DESIGN_HANDOFF.md,
SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md and IMPLEMENTATION_PROGRESS.md.
The user's explicitly approved system-design decisions take precedence over
older v1 assumptions in AGENTS.md. Preserve its applicable coding/test guidance.

The linked Google billing address is confirmed as India. Preserve the Google
map, backend-controlled provider requests and existing backend opening-hours
source. Do not introduce UI Kit or EEA-only blockers. Do not change permissions,
deploy, push, install design skills or touch unrelated work.

## 1. Verify the starting state

- Inspect git status/current commits and run backend tests before edits using
  backend/.venv/bin/python -m pytest -q. Do not use Anaconda's bare tools.
- Inspect plan_v2.py, verifier.py, departure.py, adapter.py, engine.py, geocoder.py,
  hours.py, stay_defaults.py, request/response models and existing tests.
- Confirm these observed gaps against current code: browser coordinates copied
  into VerifiedStop; trip zone taken from first stop with UTC fallback; departure
  zone not verified against city; missing place-type defaults and hours in v2.
- Preserve user changes and completed contract/codegen/layout work. Use mocks
  rather than live Google calls for tests.

## 2. Add real server-side selected-place verification

- Use Google Place Details by selected place ID, not text search's first result.
  Verify city and all required stops before issuing routing calls.
- Verify current official API documentation before writing provider integration.
  Use server-only credentials, minimal field masks, bounded provider admission
  and existing shared fail-closed provider accounting. No automatic retries.
- Verify returned identity/location and use provider-confirmed coordinates and
  names rather than submitted labels/coordinates. Do not silently replace a
  provider-reported moved/deleted place with another ID.
- Share one required detail lookup per distinct provider place per operation;
  keep duplicate visits as separate stop instances/durations. Share city/stop
  lookups when the identity and fetched fields genuinely cover both needs.
- Keep richer details request-scoped, without writing new cache payloads. Do
  not worsen the existing legacy-cache gap; track its separate migration honestly.
- Distinguish invalid/unresolvable selections from temporary provider failures,
  quota/storage/capacity errors and deadline expiry. Identify the affected stop.
  A failed required verification must make ZERO routing calls.
- Keep existing limits. If a new numeric detail limit or billing policy is
  needed, prepare a concrete proposal instead of inventing product approval.

## 3. Enforce verified city timezone and departure semantics

- Resolve the selected city's zone offline from its verified coordinates.
  Never silently use the first stop, browser zone, submitted zone or UTC instead.
- Resolve each stop's zone offline from verified coordinates. Unresolved zones
  or stops in another zone block calculation with a clear explanation.
- Match the submitted departure timezone to the resolved city timezone before
  conversion. Validate the chosen repeated-time occurrence server-side.
- Reject nonexistent local times, invalid dates and occurrences supplied for
  ordinary unambiguous times. First/second occurrence means chronological order;
  do not hard-code standard/summer labels, which differ by location.
- Preserve applicable supported departure range and input bounds; invalid input
  must return a controlled validation error, not an uncaught 500.
- Include verification/waits in the existing overall 60-second deadline. Bound
  in-flight awaits by remaining time; checking only between calls is insufficient.

## 4. Correct fixed duration resolution

- Explicit user durations win at EVERY position, including explicit endpoint
  durations and explicit zero. Only unspecified original endpoints default to 0.
- Unspecified middle stops use existing place-type stay_defaults lookup from
  verified details, not a flat 60 minutes unless no type matches.
- Resolve once, keyed by unique stop-instance ID; reject duplicate instance IDs
  while allowing repeated provider place IDs. Preserve source labels.
- Keep durations fixed for later comparison/reorder/acceptance. Do not silently
  change the approved model's limits; report discrepancies with existing bounds.
- Test that a nonzero intermediate stay is added after actual arrival before
  requesting the next leg. Do not confuse arrival threading with departure.

## 5. Integrate actual opening-hours assessment into v2

- Feed verified provider hours into the shared sequential engine. Evaluate each
  known stop against its actual arrival/departure in the verified trip timezone.
- Prefer date-specific/current hours only within their documented date coverage;
  respect provider dates and truncated endpoints. Outside coverage use regular
  weekly hours with an explicit qualification. Do not merely label weekly data
  date_specific or infer coverage from one period.
- Missing/malformed/insufficient data is unknown. Correctly distinguish Google's
  documented always-open shape from malformed missing closing fields. Handle
  explicit closed dates without treating unavailable data as proof of closure.
- Preserve hours source/coverage facts, including 24-hour venues, in response
  models; regenerate frontend types when contracts change. Unknown downstream
  stops after route failure must not receive fabricated timing/hours conclusions.
- Latest eligibility: positive visit closed ON ARRIVAL disqualifies a candidate;
  closes DURING the visit only warns; zero-minute conflicts warn only; unknown
  warns. Do not shorten visits, wait for reopening or guarantee venue admission.
- Arrival exactly at closing is closed; finishing at closing is allowed. Handle
  overnight/week-boundary schedules and date-specific overrides robustly.
- Keep original-route warnings visible. Prepare reusable eligibility assessment
  for later optimisation, but do not implement optimisation in this task.
- Check field-mask billing accurately: opening-hours fields trigger Enterprise
  Place Details billing in current docs. Do not repeat the legacy comment that
  requesting hours remains in the Pro tier. Request only the approved needed
  fields and report the existing billing-documentation discrepancy.

## 6. Required tests and checks

Add deterministic provider/endpoint tests, not tests that merely mirror helpers:

- A forged selected-place location is ignored in favour of provider coordinates.
- An invalid ID, temporary verification failure, unresolved zone, different-zone
  stop or departure-zone mismatch causes zero routing calls.
- City determines trip zone; duplicate visits share detail lookup but retain
  distinct stays; duplicate instance IDs are rejected.
- Explicit endpoint duration survives; place-specific middle default is used;
  intermediate stay shifts the following departure.
- Date-specific closure overrides weekly opening; outside-coverage visit uses
  qualified weekly data; malformed hours remain unknown; 24-hour source retained.
- Closing during visit warns; closed arrival differs; zero-duration stays warn;
  arrival at closing and overnight/week boundary behave correctly.
- /api/v2/plan returns assessed hours for known stops, while a failed route
  retains the valid prefix and unknown downstream times/hours.
- A hanging verification/routing call cannot exceed the remaining overall
  deadline; resource cleanup and shared provider budget remain correct.
- DST gaps/folds, invalid dates/occurrences and date-range violations fail safely.

Run relevant focused tests, then full backend tests, ruff lint/format check,
mypy, TypeScript generation/drift check and frontend type-check. Use repository
scripts and the venv's Python; do not blindly format unrelated files. Do not
claim Redis integration passed if skipped or live deployment verified by CI.

## 7. Completion and handoff

Update IMPLEMENTATION_PROGRESS.md with exact requirements finished, checks and
remaining gaps. Correct decision-number references and separate models from
implemented runtime behaviour. Preserve history without misleading COMPLETE
labels. Report files changed, test outcomes, provider-call accounting and any
unresolved approval. Keep legacy /api/plan compatible until migration.

Stop this task at verified v2 planning + hours integration. Frontend reducer,
streaming transport, refresh, comparison and cache migration follow as separate
stages. Do not commit/push/deploy unless separately authorised. Do not describe
the app as release-ready while those stages/security configuration remain open.
