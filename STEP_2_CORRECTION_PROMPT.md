# Correction prompt — continue Step 2 under confirmed Indian billing

The product manager has confirmed that the billing account linked to this
Google API project has an Indian address. This supersedes the earlier EEA
billing assumption. Apply this correction to the work already underway; do
not restart the implementation or discard existing Step 2 changes.

1. Read the updated SYSTEM_DESIGN_IMPLEMENTATION_PROMPT.md, especially its
   corrected Step 1, and reconcile TODO.md, SYSTEM_DESIGN_HANDOFF.md,
   MAP_INTEGRATION_PROPOSAL.md and IMPLEMENTATION_PROGRESS.md. Preserve prior
   evidence/history but mark obsolete EEA conclusions as superseded.
2. Apply non-EEA Google Maps Platform terms. The EEA prohibition on ordinary
   Places content displayed with any map, and its enumerated permitted-use
   restrictions, are not release blockers for this confirmed Indian billing
   account. Do not claim Google waived them; they are inapplicable here.
3. Retain the existing Google map/custom display, backend-controlled suggestions
   and verification (D34), and existing backend Google Places opening-hours
   lookup. Do not migrate to UI Kit, move autocomplete to browser requests,
   remove provider details or disable hours checks for the obsolete EEA reason.
4. Keep D48's separately approved desktop tab layout pending implementation;
   this correction does not authorise reversing it. Remove the claim that tabs
   prove EEA compliance. D49's EEA-specific gate is moot; ordinary security,
   provider-policy and deployment checks remain. Do not infer new deployment
   authorisation from this correction.
5. Keep D38's minimal persistent cache (IDs/coordinates, coordinates expiring
   within 30 days) and D10's fresh original/candidate comparison. Indian billing
   does not grant blanket caching permission. Do not reintroduce rich place
   caching, stored baseline totals or signed baseline receipts.
6. Keep the latest hours rules: closed on arrival rejects positive-duration
   candidates; closing during a visit only warns; zero-minute conflicts warn;
   date-specific hours are preferred and weekly fallback is qualified.
7. Continue Step 2's Pydantic contracts, generated TypeScript, operation/revision
   metadata, safe streaming outcomes and shared engine boundaries. Preserve
   current edits and tests. Do not add EEA-only validation errors, UI Kit
   dependencies or blockers to these contracts. If such changes were already
   introduced, identify and remove only those obsolete additions safely.
8. Verify normal non-EEA attribution, Google-map restrictions, API key/CSP and
   data-retention requirements. Finish session/field-mask/accounting details
   within approved limits. Other unresolved product questions remain unresolved.
9. Update the progress record, run checks appropriate to any actual code changes,
   and report what was corrected and where Step 2 stands. Do not mark untouched
   requirements implemented or claim production settings were verified by CI.

Official sources:
- https://cloud.google.com/maps-platform/terms/maps-service-terms
- https://developers.google.com/maps/comms/eea/faq

Proceed with Step 2 after applying this correction. Do not re-ask whether the
linked billing address is India; the product manager has explicitly confirmed it.
