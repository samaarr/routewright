# Map-Preserving Integration Proposal

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

Prepared: 2026-10-05 (Europe/Dublin)
Status: INVESTIGATION COMPLETE — awaiting product-manager decisions

This document covers Decisions 13, 25-27, 34-39, 43-44 of the design
register. Investigation is approved; adoption of any option is not.
Provider-independent backend work (engine, contracts, refresh) may continue
while this is unresolved.

---

## 1. Current map integration — exact inventory

### Map library
`@vis.gl/react-google-maps` 1.8.3 wraps the Maps JavaScript API. A separate
`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` browser key loads it.

### What is displayed ON the map (inside the Map tile area)
| Content | Source | EEA category |
|---------|--------|-------------|
| Numbered circle pins (1, 2, 3…) | Our own HTML/CSS. Marker position from backend lat/lng | Permitted — lat/lng only |
| Dotted polyline between stops | Our own computed path from backend lat/lng | Permitted — lat/lng only |
| Google transit layer (bus/rail lines) | Maps JS API TransitLayer, no extra fetch | Maps JS API tile, not Places API |
| Map tiles and POI markers | Google tile server | Maps JS API tile |

The map markers display a **number only** — `title={stop.name}` is a HTML
attribute (tooltip on hover, no visible text). Stop names are not rendered as
visible text on the map itself.

### What is displayed NEAR the map (same screen, same time)
Desktop (≥1024px) shows all three panes simultaneously:

| Content | Source | EEA category |
|---------|--------|-------------|
| Stop names in timeline (e.g. "Trinity College Dublin") | Places API `displayName` via backend | Restricted |
| `hours_detail.closes_at` / `opens_at` times | Derived from Places API `regularOpeningHours` | Restricted (derived) |
| `hours_status` label (e.g. "Open", "Closed on arrival") | Computed from Places API data | Uncertain — derived |
| Leg summary string (e.g. "Take the 47, 18 min") | Built from Routes API `transitLine.name` + duration | Restricted |
| Leg duration in minutes | Computed from Routes API `duration` | Uncertain — derived numeric |
| Google Maps deeplinks ("Get directions") | Our own URL construction from coordinates | Permitted (source link) |

Tablet (768–1023px): map and timeline are on **separate tabs** — never shown
simultaneously. This is likely not "visually associated with any map."

Mobile (<768px): map, form, and timeline are on separate tabs. Not
simultaneous.

### Stop input
Plain `<input type="text">`. No autocomplete widget. No UI Kit. No
browser-side Places calls. Stop queries are sent to the backend on form
submit. There is no existing suggestions/autocomplete flow — D34-37 describe
a planned feature that has not been built.

---

## 2. EEA restriction summary

**Sources and verification date: 2026-10-05**

### 2a. Places API EEA restriction
Source: https://developers.google.com/maps/comms/eea/places

Effective date: **8 July 2025**. Applies to projects with EEA billing accounts.

> "Other than latitude, longitude, and place_id, Customer must not use
> Google Maps Content from the Places API With any Map."

"With any Map" means displayed on, next to, or visually associated with any
map (Google or third-party), or linked to any map.

Permitted exceptions:
- Latitude, longitude, and place_id may be used with maps.
- Places API content without any map present is unrestricted.
- **Places UI Kit in any configuration is fully exempt from these restrictions.**

### 2b. Routes API EEA restriction
Source: https://developers.google.com/maps/comms/eea/routes

> "Customer may not use description or steps from the Routes API With any Map."

Permitted exceptions:
- Routes API source links provided by the service may continue to be used.
- Routes data without any map present is unrestricted.
- Numeric durations and distances are not explicitly named as "description or
  steps"; their status is unconfirmed.

### 2c. What "With any Map" means in a 3-pane layout
The 3-pane desktop layout (form | map | timeline) shows the timeline pane
next to the map pane. Under the plain reading of "next to a map," stop names,
opening hours details, and route summaries displayed in the timeline pane are
displayed with the map simultaneously.

This reading has NOT been confirmed with Google. It has also NOT been ruled
out. It is an unresolved compliance question.

### 2d. What is NOT in scope to assert here
- A grandfathered integration exception is not established. Project creation
  date and billing account history have not been verified.
- The project's EEA billing classification has not been confirmed in the Cloud
  Console — this requires the product manager to verify.
- No contact with Google has been authorised. This document does not request
  or authorise any such contact.

**Facts needed from the product manager:**
- When was the Google Cloud project created?
- Is the billing account linked to an Irish/EEA address?
- Has any grandfathering notice been received from Google?
- Has the Cloud Console shown any policy-change notices for this project?

---

## 3. What Places UI Kit exposes programmatically

Source: https://developers.google.com/maps/documentation/javascript/adopt-places-ui-kit

**From the Basic Place Autocomplete Element:**
- Place ID only.
- `gmp-select` event fires; `placePrediction.toPlace()` returns a Place
  object with place_id. A subsequent `place.fetchFields()` call (which incurs
  a separate billing event) can fetch additional fields.

**From the Place Search Element and Place Details Element:**
- Place ID, Location (lat/lng), Viewport.

**Explicitly not programmatically accessible (UI-rendered only):**
- Names, addresses, photos, ratings, reviews, price levels, opening hours,
  business type, accessible entrance indicators.

**Consequence:** UI Kit cannot replace the backend opening-hours lookup.
Even if UI Kit displays opening hours in a browser component, we cannot read
those hours out programmatically to run `compute_hours_status()` in the
planning engine. Backend REST lookup must continue. This is not a limitation
to work around — it is a fundamental architectural constraint of the UI Kit.

**The UI Kit exemption applies to display, not to data extraction.** Adopting
UI Kit for display does not grant permission to use separately fetched
Places REST API data next to a map.

---

## 4. Decision 34-37 status — not revised by this proposal

Decision 34 specifies **backend-controlled suggestions**: the server performs
the Places Text Search and returns candidates to the client. Redis per-IP
limits (D35-36) gate these requests. Required venue details (D37) are fetched
once per distinct place per operation.

Places UI Kit Autocomplete would replace this with **browser-side** direct
calls to Google's autocomplete service. These calls:
- Are billed via the Places UI Kit Autocomplete per Session SKU ($10/session
  above the 10K free tier — see Section 7);
- Do not go through the backend, so Redis rate limits and per-IP budgets do
  not apply to them;
- Cannot be constrained by `provider_calls_per_day` or `consume_provider_budget()`;
- Do not produce a backend-logged audit trail.

D34-37 remain as approved. Any option that adopts UI Kit Autocomplete as the
stop-input mechanism requires explicit product-manager revision of D34-37.
This proposal does NOT silently revise them; the question is presented
explicitly in Section 9 (decisions required).

---

## 5. Routes display restriction impact

Current leg summaries (e.g. "Take the 47, 18 min") are constructed from
Routes API `transitLine.name` and a duration string. These appear in the
timeline pane, which in the desktop layout is shown next to the map.

Under the Routes EEA restriction, "description or steps from the Routes API"
may not be displayed with any map. Whether a constructed summary string from
`transitLine.name` constitutes a "description" is unconfirmed. The deeplinks
("Get directions" URLs) are likely permitted as "source links."

If the restriction applies to our summaries, the compliant path is the same
as for Places: ensure route descriptions are never shown simultaneously with
the map.

---

## 6. Browser key, attribution and CSP requirements

### Browser key restrictions
The Maps JavaScript API requires a browser key restricted to HTTP referrers
(your domain). This is **separate** from the server key used for backend
Places and Routes REST calls. The server key must not be `NEXT_PUBLIC_`.

The current split (implied by two separate env vars) is correct in principle
but not confirmed as fully configured in the Cloud Console — see the
deployment checklist.

### Attribution
Maps JS API requires the Google logo to remain visible on the map. The
current `disableDefaultUI` configuration removes the default controls but the
Google logo must be preserved. Standard `@vis.gl/react-google-maps` behaviour
keeps this visible by default.

Places UI Kit elements include attribution in the rendered component. Styling
customisation must not remove or obscure Google attribution.

### CSP
The current backend CSP is `default-src 'none'`. The frontend Next.js
`next.config.js` does not set a CSP on `/:path*` responses.

Maps JS API requires:
- `script-src https://maps.googleapis.com`
- `img-src https://maps.gstatic.com https://maps.googleapis.com`
- `connect-src https://maps.googleapis.com`

If UI Kit elements are adopted, additional CSP entries for Places UI Kit
subresources would be required. No UI Kit CSP directive list has been
verified from Google documentation; this must be confirmed before adoption.

---

## 7. Billing and quota analysis

### Existing backend costs (unchanged in all options)
| SKU | Trigger | Free tier | Cost above free |
|-----|---------|-----------|-----------------|
| Places Text Search (New) — Pro | per geocode call (cache miss) | 5K/month | $17/1K |
| Routes computeRoutes | per leg fetch | 1K/month | varies |

At the current scale (~217 plans/month at 8 stops each, from CLAUDE.md), both
fit well within free tiers. Cache hits cost nothing.

### Additional costs for UI Kit Autocomplete (if adopted — D34 revision required)
| SKU | Trigger | Free tier | Cost above free |
|-----|---------|-----------|-----------------|
| Places UI Kit — Autocomplete per Session | per session (user selects a stop) | 10K/month | $10/1K sessions |

A "session" = one autocomplete interaction (user types → selects a result).
At 8 stops per plan × 217 plans/month = ~1,736 sessions/month, safely within
the 10K free tier at current scale. However, abandoned sessions (user types
but does not select) are billed as individual keystrokes if no session token
is used.

**These calls are NOT gated by the backend rate limiter.** A single user
making 50 stop searches in rapid succession triggers 50 separate billing
events that the backend cannot see or limit.

### UI Kit Place Details (if adopted)
| SKU | Trigger | Free tier | Cost above free |
|-----|---------|-----------|-----------------|
| Places UI Kit Query (Essentials) | per component instantiation | 10K/month | $1/1K |
| Places UI Kit Pro | per component instantiation | 5K/month | $5/1K |

Using the Place Details element to display stop information (e.g., after
selection) would trigger these SKUs at component render time.

### Maps JS API
| SKU | Trigger | Free tier | Cost above free |
|-----|---------|-----------|-----------------|
| Dynamic Maps | per map load | 10K/month | $7/1K |

Already incurred for the current map. No change in any option.

---

## 8. Three concrete integration options

### Option A — Separate display from map (no UI Kit)

**What changes:**
- Desktop (≥1024px) switches from 3-pane simultaneous to a tab layout like
  the current tablet view: map tab and plan/timeline tab, not shown together.
- No new Google API keys, no new billing SKUs, no UI Kit adoption.
- The map pane shows only lat/lng-derived content (numbered pins, polyline,
  transit layer) — all explicitly permitted with maps.
- All Places-derived and Routes-derived text is in the timeline pane, visible
  only when the map is not shown.

**EEA compliance outcome:**
- Desktop: timeline and map never appear simultaneously → "next to a map"
  issue eliminated.
- Tablet and mobile: already on separate tabs (no change needed).
- Backend REST calls for opening hours continue unchanged.
- `hours_status` and leg summaries are shown only in the timeline tab (no map
  present on screen at the same time).

**Decisions affected:** None. No revision to D13, D25-27, D34-39, D43-44.

**Tradeoffs:**
- Pro: EEA-compliant without any Google verification, no new billing, no
  architectural complexity.
- Pro: Preserves current backend budget controls, Redis rate limits, hours
  logic entirely.
- Con: Desktop users lose the simultaneous map + timeline view.
- Con: Does not provide place disambiguation (D13) — that needs a separate
  feature decision regardless.
- Con: The compliance benefit depends on "not on screen simultaneously" being
  a sufficient reading of "not next to a map" — this has not been confirmed.

**Decisions resolved:** None — this is a conservative mitigation, not a
definitive compliance ruling.

### Option B — Add UI Kit Autocomplete for stop input only

**What changes:**
- Replace the plain text `<input>` in StopList with a Places UI Kit Basic
  Autocomplete element.
- On user selection, `gmp-select` event fires with the place_id and lat/lng.
  The frontend sends place_id to the backend; the backend verifies the place
  and fetches opening hours via REST (D37).
- The map and display layers are unchanged.
- The desktop 3-pane layout is unchanged (timeline next to map issue remains).

**EEA compliance outcome:**
- Stop input is EEA-compliant (UI Kit is exempt).
- The 3-pane desktop display gap (timeline next to map) is not addressed.
- Still requires Option A layout change or Google verification to resolve
  the display question.

**Decisions affected if adopted:**
- D13: Explicit place selection via UI Kit (resolves place disambiguation).
- D34: **Changes from backend-controlled to browser-side suggestions.** This
  is a revision of an approved decision and requires explicit approval.
- D35-36: Redis per-IP limits no longer gate autocomplete traffic.
- D37: Place verification still required after UI Kit selection — backend must
  confirm the place_id is valid and fetch the required fields.

**Tradeoffs:**
- Pro: Solves place disambiguation (D13) cleanly.
- Pro: UI Kit exception is clear and documented.
- Con: Revises D34-37 (backend suggestion control replaced by browser calls).
- Con: Adds a separate billing line not covered by backend budgets.
- Con: Session abandonment billing risk if users type without selecting.
- Con: Opens a CSP configuration requirement for UI Kit subresources.
- Con: Does not solve the desktop 3-pane display question on its own.

### Option C — UI Kit Autocomplete + tab layout (combined)

**What changes:** Everything in Option B, plus the Option A desktop tab layout.

**EEA compliance outcome:**
- Stop input is EEA-compliant (UI Kit).
- Desktop timeline is never shown next to the map (tab layout).
- This addresses both the input and the display dimensions of the EEA question.
- Opening hours still come from backend REST (UI Kit cannot provide them
  programmatically); this is not a compliance gap — it is correct.

**Decisions affected if adopted:** Same as Option B (D34 requires explicit
revision). The tab layout does not affect any numbered decision.

**Tradeoffs:**
- Pro: Most comprehensive response to the EEA situation.
- Pro: Provides place disambiguation (D13).
- Con: Revises D34-37; requires explicit approval.
- Con: Additional billing line, CSP changes, UI Kit integration complexity.
- Con: Desktop UX change (no simultaneous map + timeline).
- Con: "All other data in UI Kit elements is not programmatically accessible"
  — opening hours, venue types, names must still come from backend REST or
  be displayed via UI Kit components (which we cannot read back out).

---

## 9. Explicit product decisions required

These are questions for the product manager. None are decided by this
document. Implementation of any option waits for approval.

### D9-A — Desktop layout change
Should the desktop (≥1024px) view switch from 3-pane simultaneous (form |
map | timeline side by side) to a tab view (map tab | plan tab)?

Options:
- **a) Yes** — implement tab layout. Resolves the "next to map" question
  without Google verification. No new costs. Least-risk path.
- **b) No** — keep 3-pane simultaneous. Requires Google verification or
  acceptance that the current layout may be non-compliant. No change to
  current code.

### D9-B — Stop input: UI Kit Autocomplete
Should the plain text stop input be replaced with Places UI Kit Basic
Autocomplete?

Options:
- **a) Yes** — requires explicit revision of D34 (backend-controlled
  suggestions → browser-side UI Kit). Adds a new billing line outside
  backend budget controls. Resolves D13 place disambiguation.
- **b) No** — keep plain text input. D34 backend suggestions remain as
  approved. D13 place disambiguation to be addressed separately.

### D9-C — Routes description display
If D9-A is "No" (desktop keeps 3-pane), should leg summary strings ("Take
the 47, 18 min") be suppressed from the timeline pane when the map is visible,
replacing them with permitted data only (duration number, deeplink)?

Options:
- **a) Yes** — comply conservatively; route descriptions in timeline only
  when map is not visible.
- **b) No** — keep current display; accept unverified compliance status.

### D9-D — Google verification contact
Should Google Maps Platform support be contacted to confirm: (a) whether
the project's existing integration is grandfathered; (b) whether the desktop
3-pane layout violates "next to a map"; (c) whether constructed summary
strings count as "descriptions" under the Routes restriction?

This contact has NOT been authorised. It is listed as an explicit decision
because it may shorten uncertainty.

Options:
- **a) Yes** — authorise contacting Google. Note: disclosure of integration
  details to Google is implied.
- **b) No** — proceed with conservative mitigation (Option A layout) without
  verification.

### D9-E — Production release gate
If verification remains unresolved, is unverified EEA compliance acceptable
for production release, or is resolution a hard gate?

Options:
- **a) Hard gate** — do not release to production until compliance is either
  verified or conservatively addressed.
- **b) Soft gate** — release with Option A layout change as a conservative
  mitigation; continue investigation after launch.

---

## 10. What this proposal does NOT resolve

- It does not establish that the current integration is compliant.
- It does not establish that any grandfathered exception applies.
- It does not confirm the CSP directives required for Places UI Kit.
- It does not establish that constructed summary strings are exempt from the
  Routes "description" restriction.
- It does not resolve metrics retention/storage (D46 — separate unresolved).
- It does not revise Decisions 34-37. Those remain as approved.

---

## 11. What can proceed now (not blocked by this)

The EEA/UI Kit question does not block:

- Step 2: API contracts (backend schemas, TS types, streaming shape) — no
  map provider dependency.
- Step 3: Planning engine (sequential legs, partial failure, streaming) —
  backend-only, no map dependency.
- Step 4: Opening-hours enforcement (D42-43 amendment) — backend-only.
- Step 6: Refresh (planned departure, suffix recompute) — backend-only.
- Step 7: Comparison/acceptance (candidate generation, routing) — backend-only.
- Step 8: Regression tests and CI — all provider-independent.

The frontend display changes (Step 5) for streaming and timeline updates can
also proceed against the existing map layout. The D9-A layout decision affects
the *desktop responsive behaviour* but does not block the timeline component
work.

Only these are blocked:
- Any change to stop input that adopts UI Kit Autocomplete (requires D9-B
  approval and D34 revision).
- Production release pending D9-E decision.

---

## 12. Recommendation

The conservative-minimum path is:
1. **Approve D9-A(a)**: switch desktop view to tabs (map | plan), matching
   the existing tablet layout. No new costs, no new dependencies, resolves
   the "next to a map" display question without Google verification.
2. **Approve D9-B(b)**: keep plain text input for now. D34 backend
   suggestions remain as specified. Place disambiguation (D13) addressed
   later as a separate feature.
3. **Approve D9-C(a) if D9-A(b)**: if desktop keeps 3-pane, suppress route
   descriptions near the map.
4. **Defer D9-D**: no Google contact unless the product manager sees benefit
   that outweighs disclosure.
5. **Set D9-E as soft gate**: release with Option A layout change as
   mitigation; investigate further after launch if EEA terms change or
   billing triggers a notice.

This recommendation makes zero changes to the backend, preserves D34-37
exactly, and keeps the opening-hours decision intact. It is the path of least
risk and least complexity.

If place disambiguation (D13) is a priority, Option B/C (UI Kit Autocomplete)
can be revisited as a separate decision after D34 is explicitly revised. That
revision requires a standalone product-manager decision, not a bundled one
here.

---

## Sources (verified 2026-10-05)

- Places API EEA restrictions (effective 8 July 2025):
  https://developers.google.com/maps/comms/eea/places
- Routes API EEA restrictions:
  https://developers.google.com/maps/comms/eea/routes
- Places UI Kit overview and programmatic data access:
  https://developers.google.com/maps/documentation/javascript/adopt-places-ui-kit
- Places UI Kit Basic Autocomplete element:
  https://developers.google.com/maps/documentation/javascript/places-ui-kit/basic-autocomplete
- Places UI Kit overview (components and billing model):
  https://developers.google.com/maps/documentation/javascript/places-ui-kit/overview
- Google Maps Platform pricing (SKU list including UI Kit):
  https://developers.google.com/maps/billing-and-pricing/pricing
- Session pricing for Autocomplete (New):
  https://developers.google.com/maps/documentation/places/web-service/session-pricing
