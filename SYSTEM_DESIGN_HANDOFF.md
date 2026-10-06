# RouteWright system-design handoff

**Latest scope (2026-10-06):** Defer new per-SKU monthly free-tier enforcement
during development; preserve existing controls and record it for future scope.
Next product work: selections/area warnings/cache migration, then streaming/v2
frontend, refresh and comparison. Do not restart meta-design discussion or
implement a reservation scheme (none approved). Free-tier-only remains the
future cost constraint, not a guarantee provided by current daily counters.

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


Updated: 2026-10-05 (Europe/Dublin)

## Read this before continuing

The user is the product manager. We are developing a detailed, step-by-step
implementation prompt through approved multiple-choice design decisions.
Application implementation has NOT started during this design discussion.
Replies such as "a" approve the immediately preceding named option; they do not
approve similarly labelled options from other questions. If the user clarifies
which question they meant, preserve that clarification rather than inferring.

[TODO.md](TODO.md) is the detailed decision register: decisions 1–47, remaining
questions, deferred features, research links and security follow-ups. Read the
actual entries before making a proposal or writing implementation instructions.
This file is a navigation and context-recovery aid, not a competing spec.

SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md now contains the detailed staged brief,
prepared at the user's request. Read it alongside the register; unresolved
integration/telemetry choices remain unresolved and application work is pending.

## Working method

1. Inspect relevant code before describing current behaviour. Distinguish
   code evidence, provider documentation, assumptions and proposed changes.
2. Explain each material product/design choice in basic terms: the issue,
   options, pros/cons, reason and future scope. Ask the product manager to choose.
3. Record each approval immediately in TODO.md. Explicitly mark superseded
   requirements; never silently reinterpret an earlier approval.
4. Resolve routine implementation details within approved requirements without
   turning every technical detail into another product question. Group related
   choices. Previously estimated 8–10 decisions remained after question 42;
   that was an estimate, not a guaranteed count.
5. Maintain separate approved, unresolved, deferred and implemented statuses.
   An unchecked approved entry means implementation is pending.
6. Verify time-sensitive Google documentation and link primary sources. An API
   returning data does not establish permission to store, display or derive
   metrics from it. Do not claim a legal exception applies without evidence.
7. Assemble the final prompt with stages, acceptance criteria, relevant tests,
   rollout requirements and explicit exclusions; obtain final product approval.
8. After context loss, read this file, TODO.md, applicable repository guidance,
   git status and relevant code. Do not recreate missing decisions from memory.

## Approved design overview — consult numbered entries for exact details

- Sequential transit legs use actual preceding arrival plus visit duration.
  No invented 15-minute fallback. Routing failure leaves a valid prefix and
  unknown downstream times, with a reason (1–2).
- Local straight-line/OR-Tools search generates one alternative. It is a
  heuristic, not proof of transit optimality. Unchanged candidate makes no
  routing comparison calls. Recalculate original and alternative within one
  operation; recommend only a complete faster eligible candidate saving at
  least five minutes, and apply only after explicit acceptance (3–10, 18, 20).
- N stops: plan up to N−1 routing calls; comparison up to 2(N−1); initial plan
  plus comparison up to 3(N−1). Failed/issued cancelled calls count. No automatic
  routing retries. Places usage is additional. No retained baseline cache.
- Stream real progress for plan/comparison/refresh, with 60-second overall
  deadlines. Cancel/disconnect stops remaining work. Edits invalidate snapshots;
  operation IDs and revisions prevent late updates (6–8, 12, 19, 22–23, 30).
- Stable stop instances differ from provider place IDs. Explicit place/city
  selection and server verification; shared resolved durations follow stops.
  Pins default to first/last and constrain optimisation, not manual editing
  (11, 13, 16–17, 26–27). Accept completed alternative without rerouting (18).
- Refresh starts at the selected leg's planned departure and recomputes its
  suffix; it does not mean "leave now" (21).
- Destination-local time, explicit DST ambiguity handling, preserve local clock
  on city-zone changes. Offline city/stop timezone lookup; unresolved or
  different-zone stops block calculation. One timezone per trip (14, 28–29,
  40–41). Outside-city area checks are approximate warnings, not a boundary ban
  (25, 44).
- Opening hours stay enabled using the existing backend Google Places lookup.
  For positive stays reject known closure ON ARRIVAL; closure during the visit
  warns and does not disqualify. Zero-minute stops warn only. Prefer hours valid
  for the visit date; otherwise qualify weekly schedules; missing hours unknown.
  Do not shorten stays or claim guaranteed admission (24, 42–43 amend 15).
- Modular FastAPI monolith/shared engine; central frontend state; generate TS
  contracts from backend schemas (31–33). No workers/durable jobs approved.
- Backend-controlled suggestions are the currently approved design (34), with
  debounce and per-IP limits (35–36). Required venue details once per distinct
  place per operation (37). Persistent Places cache only IDs/coordinates, with
  coordinates expiring within 30 days and legacy rich fields removed (38).
- Verify all required place identities/coordinates before routing; on failure
  identify the place, distinguish invalid selection from temporary failure, and
  stop without substitution (45).
- Aggregate operational metrics exclude trip details; provider-derived outcome
  metrics require permitted-use verification. Retention/storage unspecified (46).
- Staged implementation approved: integration/contracts, planning, refresh,
  comparison/acceptance, full validation before production release (47).

## Integration investigation — superseded by Indian billing confirmation

The investigation (question 39 A) found: UI Kit exposes only place_id,
location, and viewport programmatically — not hours/types/names. UI Kit
therefore cannot replace the backend opening-hours lookup. Backend
suggestions (D34) and opening-hours evaluation remain the chosen design.

**Correction 2026-10-05:** The product manager confirmed India as the
billing account address. The EEA Places/Routes map-display restrictions
(effective 8 July 2025) apply only to EEA billing accounts and are not
blockers here. Non-EEA service terms (Sections 14/19) restrict use with
non-Google maps, not with Google Maps themselves. The existing integration
— Google Maps JS API, backend Places REST calls for hours/names, backend
Routes API for directions — does not require UI Kit migration or desktop
tab layout for EEA compliance. D48 (desktop tab layout) remains approved
as a product design choice and release prerequisite; its EEA-compliance
rationale is moot and must not be cited as proof of EEA compliance.
No Google contact is authorised. Normal attribution, API key restrictions,
minimal field masks, CSP and caching requirements still apply.

Sources:
https://cloud.google.com/maps-platform/terms/maps-service-terms
https://developers.google.com/maps/comms/eea/faq

## Existing code and verification status

Frontend: Next.js/React; PlannerPage, PlanForm, StopList, PlanMap, lib/api.ts.
Backend: FastAPI, Google Places/Routes adapters, OR-Tools/Haversine candidate
generation, SQLite place cache, Redis production budget/rate limits.
Relevant service files include backend/app/services/tz.py and hours.py.
Reinspect current code; this description is not proof of current HEAD behaviour.

Earlier security commit 49a77e8 passed GitHub CI, as recorded in TODO.md.
Production HTTPS/proxy/Redis/key/storage/CSP configuration remains unverified.
The development-only braces advisory exception expires 2026-11-04.
Security hardening did not establish provider licensing compliance.

## Deployment decisions (2026-10-06)

Approved by the owner (details and status: DEPLOYMENT_PLAN.md §1):
- **Cache:** ephemeral container storage, no volume, non-root container,
  `RAILWAY_RUN_UID` unset. Planning correctness never depends on it (tested);
  cache failures are misses. Storage-security considerations remain (host
  disk, shell access, old deployment's data).
- **Redis:** TLS required (`rediss://`, verified); no plaintext exception.
  Enforced at production startup. Provider not yet chosen (proposal: Upstash).
- **Legacy endpoints retired:** `/api/plan`, `/api/optimise`,
  `/api/refresh-leg` and the Text Search client removed; v2 services and the
  local optimiser kept.
- **Server key:** must have a verified outbound-IP restriction plus Places API
  (New) + Routes API restriction before deployment. Current hosting cannot
  provide a static egress IP without a paid change → **deployment blocked**
  pending a hosting decision.
- **Metrics:** aggregate app logs on the hosting platform only, no archive,
  no sensitive content or comparison savings; platform HTTP logs (with client
  IPs) documented separately; actual retention to be verified.
- **Free tier:** monthly enforcement deferred; limits unchanged; no zero-charge
  claim.

Completed fixes: client IPs removed from 429 and uvicorn WebSocket log lines.
Open proposals: Railway client-IP integration (D-1), Redis provider, egress-IP
hosting option, production Map ID, push/CI, domain ownership. Existing live
deployment found: `routewright.vercel.app` (old build) calling
`routewright-production.up.railway.app` (returns 502). Nothing deployed.

## Next work

Read TODO.md's remaining-decisions section, consolidate overlapping technical
items, and continue the product-manager dialogue. Remaining work includes the
concrete map-preserving proposal, Places usage limits/session handling, metrics
retention/storage, deployment verification and final implementation prompt.
Do not invent approved numeric limits or select an analytics vendor.

Files are saved locally; no commit/push or deployment is implied by this record.
