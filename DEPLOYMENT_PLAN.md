# Deployment plan — RouteWright v2

> **PROPOSAL — NOT APPROVED FOR EXECUTION.** Approved design decisions are
> recorded in §1, but deployment itself, every hosting change, the push, key
> creation, purchases and live Google calls still require explicit approval
> (§14). Nothing in this document has been deployed or verified live.

Prepared 2026-10-06; revised the same day after the owner's approvals.
Companion checklist: [PRODUCTION_VERIFICATION.md](PRODUCTION_VERIFICATION.md).

Labels used below:

- **VERIFIED (repo)** — read in the current code/config at HEAD.
- **VERIFIED (public probe)** — observed from outside with read-only
  requests (GET/OPTIONS/DNS; nothing that reaches Google), 2026-10-06.
- **VERIFIED (docs)** — official provider documentation, 2026-10-06.
  Staff forum answers are labelled separately.
- **UNKNOWN** — needs dashboard/account access that is not available here.
- **PROPOSED** — a change awaiting approval.

---

## 1. Decision record

### Approved (2026-10-06)

| ID | Decision | Implementation status |
|----|----------|-----------------------|
| A1 / D-2 | **Ephemeral cache.** Container filesystem, no volume, non-root user kept, `RAILWAY_RUN_UID` unset; planning independent of the cache; cache failures fall back safely | Done in code (`7365dee`): read failures are misses; tests prove planning ignores the cache. Storage-security caveats remain (§9) |
| A2 / D-3 | **Redis requires TLS (`rediss://`)**, no plaintext exception | Done in code (`5ef006d`): production refuses `redis://` and URLs that disable certificate/hostname checks. Provider choice and cost: §5 (needs approval) |
| A3 / D-7 | **Retire `/api/plan`, `/api/optimise`, `/api/refresh-leg`**, keep v2 services incl. the local optimiser | Done (`3c9f7ec`): routers, models and the Text Search client removed; retired routes return 404 and are absent from OpenAPI |
| A4 / D-4 | **Server key needs a verified outbound-IP restriction** plus Places API (New) + Routes API restriction, before deployment; no paid upgrade authorised | **BLOCKER**: current hosting (Railway; plan UNKNOWN, Hobby per CLAUDE.md) cannot provide it without a paid change. Options and costs: §6 |
| A5 | **Metrics**: aggregate app logs kept by the hosting platform only, no archive; no sensitive content or comparison savings; platform HTTP logs documented separately; actual retention to be verified | Code done (Step 9). Retention UNKNOWN until the plan is confirmed (§10) |
| A6 | **Monthly free-tier enforcement stays deferred**; existing limits unchanged; no claim that quotas or alerts guarantee zero charges | Unchanged. Blocks any "free-tier-safe" public claim |

### Fixes and investigations completed

| ID | Item | Result |
|----|------|--------|
| D-9 | Client IP in rate-limit (429) log line | Fixed `8123f47`; regression test drives the real limiter |
| D-9b | Other log paths (audit) | uvicorn logged `<ip>:<port> - "WebSocket …" 403` on `uvicorn.error` despite `--no-access-log`. Fixed `f3901c9`: `--ws none` + address-redacting filter; real-server test. Own log calls carry only request IDs, exception type names and fixed labels |
| — | Selection lookups | Still share the D36 combined allowance (30/min, 100/day per client) — **interim**, unchanged |
| — | `braces@3.0.3` dev audit exception | Expires **2026-11-04**; not extended |

### Open proposals (need approval)

| ID | Proposal | Section |
|----|----------|---------|
| D-1 | Railway client-IP integration (conditional `X-Real-IP`) — depends on the D-4 hosting outcome | §7 |
| D-3 provider | Redis provider offering TLS | §5 |
| D-4 option | How to obtain a verified egress IP | §6 |
| D-5 | Production Map ID | §8 |
| D-6 | Push all local commits (34 at the time of writing, plus this record); require green CI | §11 |
| D-8 | Domains: confirm ownership of the existing Vercel/Railway names | §4 |

---

## 2. Existing deployment found (VERIFIED public probe, 2026-10-06)

| Item | Observation |
|------|-------------|
| Frontend `https://routewright.vercel.app` | Live (HTTP 200, `server: Vercel`). README calls it the live site. Serves an older build: nonce CSP present; `connect-src` names `https://routewright-production.up.railway.app`. HSTS `max-age=63072000; includeSubDomains; preload` (Vercel default) |
| Browser Maps key | One key-shaped string is embedded in the live JS bundle (expected for `NEXT_PUBLIC_*`; value not recorded). Its referrer/API restrictions are **UNKNOWN** — checking needs Google Cloud access or a live call |
| Backend `https://routewright-production.up.railway.app` | Railway edge reachable (`x-railway-edge: lhr1`); `http://` → `301` to `https://`. The application returns **`502 Application failed to respond`** (`x-railway-fallback: true`) — the service is down or not listening. Cause UNKNOWN. While down, its legacy v1 routes are unreachable; if restarted from old code they would be served again |
| `routewright.com` | Registered, behind Cloudflare, redirects to `www.` — **owner UNKNOWN**; not assumed to be ours |

Consequences: the production frontend is live but broken (its backend is
down). Nothing was changed. Retiring the old Railway service and any volume
it may have (it could still hold the legacy rich cache with place names and
hours) is part of the deployment (§11, step 9).

---

## 3. Repository configuration (VERIFIED repo)

| Item | Finding |
|------|---------|
| `backend/Dockerfile` | python:3.11-slim, hash-locked deps, `USER app` (uid 1000), uvicorn `--no-proxy-headers --no-access-log --ws none --workers 1 --limit-concurrency 40`, `${PORT:-8000}`, `umask 077` |
| Startup validation (`app/main.py`) | production requires `GOOGLE_MAPS_API_KEY`, **verified-TLS `rediss://`**, HTTPS-only `ALLOWED_ORIGINS`; rejects `TRUSTED_PROXY_COUNT` and `/0` trust; checks Redis connectivity |
| Routes | only `/healthz` and `/api/v2/*` (`tests/test_retired_endpoints.py`) |
| Logging | one JSON metrics line per v2 operation; no access log; slowapi and uvicorn loggers redact addresses |
| Railway config-as-code | none; dashboard settings UNKNOWN |
| `frontend/vercel.json` | `framework: nextjs`, `regions: ["dub1"]` |
| `frontend/middleware.ts`, `lib/security.ts` | per-request nonce CSP; production build requires an HTTPS `NEXT_PUBLIC_API_URL` origin |
| Browser → backend | direct cross-origin calls; Vercel functions are not in the streaming path |
| CI (`.github/workflows/ci.yml`) | backend (ruff, mypy, pytest with a Redis service, pip-audit), frontend (type-check, lint, unit, drift, npm audit, probe-key build + bundle check, smoke, e2e), gitleaks, container (non-root + `/healthz`) |
| Git | local commits not pushed (last pushed `49a77e8`); CI has not run on them |

---

## 4. Domains, allowed origins, browser key, CSP (D-8)

Ownership of all names below is **UNKNOWN** from here; the README and the
live CSP strongly suggest the first two belong to this project. Confirm in
the Vercel and Railway dashboards before use. `routewright.com` is not used.

| Role | Proposed value | Status |
|------|----------------|--------|
| Frontend origin | `https://routewright.vercel.app` | exists, live (old build); ownership to confirm |
| Backend origin | `https://routewright-production.up.railway.app` if staying on Railway; a new origin if D-4 moves the backend (e.g. `https://<app>.fly.dev`) | exists, 502; depends on D-4 |

Exact settings (frontend on `routewright.vercel.app`, backend `<BACKEND>`):

- Backend `ALLOWED_ORIGINS=https://routewright.vercel.app` (exact; no
  preview URLs, no wildcard).
- Frontend `NEXT_PUBLIC_API_URL=<BACKEND>` (HTTPS origin, no path).
- Browser key → Application restriction **Websites**:
  `https://routewright.vercel.app/*` only; API restriction **Maps JavaScript
  API** only. Preview deployments intentionally get no map.
- Server key → API restriction **Places API (New)** and **Routes API**;
  Application restriction **IP addresses**: the verified egress IP(s) (§6).
- Frontend CSP (generated by `lib/security.ts`; only the API origin is
  configurable):
  ```
  default-src 'none'; script-src 'self' 'nonce-<per request>' https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://maps.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com; connect-src 'self' https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com <BACKEND>; worker-src 'self' blob:; frame-src https://www.google.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'
  ```
- Backend API responses: `default-src 'none'; frame-ancestors 'none'`.

---

## 5. Redis with TLS (A2 approved; provider needs approval)

Requirement: `rediss://`, certificate and hostname verified (enforced at
startup). Each v2 request makes a few Redis commands (rate-limit windows
plus one budget increment per provider call; a 3-stop plan ≈ 10–15 — an
estimate from the code paths, not measured).

| Option | TLS | Cost | Notes |
|--------|-----|------|-------|
| Railway Redis template | **No** — URL is `redis://`, no TLS option (Railway staff answer) | included in usage | Does not meet A2 |
| Railway self-managed Redis with TLS (custom image + certificates) | possible | Railway usage | Self-managed CA, rotation, `ssl_ca_certs`; operational burden; not recommended |
| **Upstash Redis** | always on (VERIFIED docs) | **Free**: 500K commands/month, 256 MB, 10 GB bandwidth, 1 DB; pay-as-you-go $0.20 per 100K commands; fixed from $10/month (VERIFIED docs) | AWS `eu-west-1` (Ireland) available (Upstash API docs). Public endpoint protected by password + TLS; exceeding the free allowance stops service or needs a paid plan |
| Redis Cloud | free 30 MB tier: TLS not listed; Essentials from $5/month includes TLS (VERIFIED pricing page) | $5/month | Paid |
| Aiven for Valkey | free availability unclear in docs | UNKNOWN | Not evaluated further |

**Proposal:** Upstash, free plan, region `eu-west-1`, one database used only
by RouteWright, password only in the backend secret. At ~15 commands per
plan the free allowance covers on the order of 30,000 operations/month, far
above expected use, but this is not a guarantee. Verify after setup:
`rediss://` URL, TLS handshake succeeds from the backend (startup check),
eviction policy does not drop limit keys.

---

## 6. Server-key outbound-IP restriction (A4) — BLOCKER

Google accepts IPv4/IPv6 addresses or CIDR ranges for server keys (VERIFIED
docs). The restriction is only as strong as the exclusivity of the IP:
anyone sending traffic from the same IP can use a leaked key.

| Option | Egress IP | Cost | Limitations |
|--------|-----------|------|-------------|
| Railway Hobby (current, per CLAUDE.md) | none static | $5/month | **Cannot satisfy A4** |
| Railway Pro + Static Outbound IPs | static IPv4 per service | Pro $20/month per workspace (incl. $20 usage credit; also 30-day logs) | IPs "may be shared with other customers" (VERIFIED docs) — restriction does not exclude co-tenants; region change changes IPs |
| Fly.io app-scoped static egress IP | static IPv4 + IPv6, **app-scoped** (shared only by the app's own machines) | $3.60/month per IPv4 + Fly compute (compute price UNKNOWN, not verified) | Migration of the backend (Dockerfile reusable); one IP per region; D-1 needs a Fly-specific design; streaming limits not verified |
| Render default outbound ranges | regional ranges | plan price | **Shared across all services in the region** (VERIFIED docs) — weak |
| Render dedicated outbound IPs | dedicated | price not stated in docs | Migration; UNKNOWN cost |
| Static-IP egress proxy (QuotaGuard, Fixie, …) | provider's IPs | UNKNOWN | Code change to route Google calls through a proxy; third party in the path; not evaluated |

Current hosting cannot meet A4 and no paid upgrade is authorised, so **the
deployment is blocked**. Decision needed: (a) authorise Railway Pro
($20/month) and accept shared static IPs, or (b) authorise a Fly.io
migration (~$3.60/month for the IP plus compute) with a dedicated egress IP,
or (c) wait. Recommendation: (b) gives the strongest restriction at the
lowest IP cost but is a migration; (a) is the smallest change. Either way
the IP must be verified (shown in the provider dashboard/CLI) before the
key restriction is set, and the key is created only after approval.

---

## 7. D-1 proposal — client identity on Railway (NOT IMPLEMENTED)

Applies if the backend stays on Railway. A Fly.io move needs a different
design (Fly's own client-IP header and ingress), to be proposed separately.

### What Railway documents
- The edge adds `X-Real-IP` "for identifying client's remote IP", plus
  `X-Forwarded-Proto` (always `https`), `X-Forwarded-Host`,
  `X-Railway-Edge`, `X-Railway-Request-Id`, `X-Request-Start`.
- The edge terminates TLS, adds headers and forwards over Railway's internal
  network.
- A TCP proxy can expose a service's port directly; when configured Railway
  injects `RAILWAY_TCP_PROXY_DOMAIN`/`_PORT`.
- Private networking lets other services in the same project/environment
  reach the service over `*.railway.internal`.

### Not documented
That client-supplied `X-Real-IP` is overwritten; anything about
`X-Forwarded-For`; that a service is reachable only via the edge; which
source addresses the container sees. Staff forum answers (2026-05) say
`X-Real-IP` is always overwritten and apps cannot be reached directly; a
2024 thread shows clients could set it until Railway fixed a bug.

### Trust boundary
```
internet client ──TLS──► Railway HTTP edge (writes X-Real-IP) ──internal──► backend
   TCP proxy on the backend (if ever created)  ─────────────────────────────┘ bypasses edge
   other services in the same project (private network) ───────────────────┘ bypasses edge
```
Trusted: only the `X-Real-IP` value written by the HTTP edge. Not trusted:
any client header, `X-Forwarded-For`, any connection that did not come
through the edge.

**How trusted ingress is identified.** The app cannot authenticate the edge
per request. It relies on (1) deployment facts checked at startup — running
on Railway (`RAILWAY_ENVIRONMENT_ID` present) and **no TCP proxy**
(`RAILWAY_TCP_PROXY_DOMAIN` absent, else refuse to start) — and (2)
per-request consistency: the TCP peer is a non-public address (edge traffic
arrives from Railway's internal network) and Railway's edge headers are
present.

**Can clients bypass it?** Only via a TCP proxy (refused at startup) or
from another service in the project (the project holds only the backend —
Redis is external under §5). No client-reachable path remains if those hold.

**Forged headers.** Prevention depends on Railway overwriting `X-Real-IP`
(staff statement). Mitigations: accept the header only under the conditions
above; ignore `X-Forwarded-For`; fall back to the peer (one shared, stricter
bucket) on any anomaly; count the source per request in metrics; re-test
forged headers after every deploy; global provider budget as the cost
backstop. `TRUSTED_PROXY_IPS` is **not** broadened.

### Implementation (after approval)
1. `CLIENT_IP_SOURCE` = `peer` (default) | `railway`; exclusive with
   `TRUSTED_PROXY_IPS`.
2. Startup: `railway` requires `RAILWAY_ENVIRONMENT_ID`, refuses when
   `RAILWAY_TCP_PROXY_DOMAIN` is set; read via `settings`.
3. Per request: exactly one `X-Real-IP` holding one parseable global address
   (IPv4-mapped normalised), edge markers present and peer not global →
   use it; otherwise the peer.
4. Metric `client_ip_source` = `header` | `fallback_missing` |
   `fallback_invalid` | `fallback_peer_public` (no addresses).
5. Tests for forged/duplicate/list/private/IPv6 headers, missing markers,
   public peer, startup refusals, real-limiter buckets.
6. Sub-decision: IPv6 identities by /64 (changes grouping, not limits) —
   excluded unless approved.

Until D-1 is implemented, every visitor shares one rate-limit identity
(safe for cost, unusable for public traffic).

---

## 8. Production Map ID (D-5, investigation only)

- Advanced Markers require a map ID; Google allows `DEMO_MAP_ID` (VERIFIED
  docs) but does not describe it as a production setting.
- Creating a map ID is free (VERIFIED docs). Map loads are billed as
  **Dynamic Maps** (Essentials, 10,000 free/month) whether or not a map ID
  is used; the billing pages checked do not state any extra charge for map
  IDs, Advanced Markers or the TransitLayer either way — confirm in the
  billing report.
- Setup (after approval; not done): Cloud Console → Google Maps Platform →
  Map Management → Create map ID → type **JavaScript**, **Raster** (matches
  the current default map) → Save. Create it in the project that owns the
  browser key (a same-project requirement is not stated in the docs;
  keeping them together avoids doubt). No cloud styling needed.
- Set `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID=<id>` in Vercel; rebuild.

---

## 9. Ephemeral cache — remaining storage considerations (A1)

No volume means no volume backups or snapshots, but storage security is
**not** eliminated:
- The SQLite file (place ID + coordinates, ≤ 30 days) sits on the hosting
  provider's container disk while the container runs; encryption at rest of
  that disk is not documented (UNKNOWN). File mode 0600, directory 0700,
  non-root user.
- Anyone with shell/exec access to the service can read it.
- It is cleared on every redeploy/restart — that is the disposal mechanism,
  together with the 30-day purge while running.
- The **old Railway service** may have a volume or image holding the legacy
  rich cache (names, types, hours) — UNKNOWN; inspect and delete during
  decommissioning (§11 step 9).

---

## 10. Logs and retention (A5)

| Log | Content | Retention | Status |
|-----|---------|-----------|--------|
| App metrics (stdout JSON) | operation, transport, outcome, failure category, elapsed, stop count, provider call counts | Railway: Hobby 7 d, Pro 30 d (VERIFIED docs); Fly/other: UNKNOWN | Actual plan UNKNOWN |
| App security log | request ID, elapsed ms, exception type | same | — |
| **Platform HTTP logs (Railway)** | per request: `@srcIp` (client IP), path, method, status, user agent, timings, edge region | same plan retention | Outside app control; documented in SECURITY.md; privacy notice must cover it |
| Vercel runtime logs | middleware/functions (app writes none) | Hobby 1 h (VERIFIED docs) | — |
| Excluded from app logs | place names/IDs, coordinates, dates, IPs (redacted from library logs), plans, secrets, raw provider text, comparison savings | — | Tested |

No separate archive or export.

---

## 11. Deployment order (after approvals)

Each step lists its stop condition. "0 calls" = no Google calls.

**0. Approvals and prerequisites**
- Owner approves: D-4 option, Redis provider, D-1 (if Railway), D-5, D-6,
  domain ownership confirmed, live-test allowance (§12).
- Google Cloud: record this month's usage **per SKU across the whole
  billing account** (Billing → Reports, grouped by SKU and project); set
  budget alerts (they do not cap spend); set temporary low daily quotas on
  Places API (New) and Routes API (e.g. 100/day each) for the test window.
- Check the **existing live browser key's** restrictions now (it is public
  in the live bundle).
- Stop if any SKU in §12 is near its monthly free cap.

**1. Local pre-flight** (commands in §15), then `git push origin main`
(only with D-6 approval) and wait for all four CI jobs to pass.

**2. Redis (Upstash, proposed)** — create one database in `eu-west-1`;
copy the `rediss://` URL into the backend secret only. 0 calls.

**3. Backend hosting (depends on D-4)**
- Railway Pro: enable Static Outbound IPs on the backend service, redeploy,
  read the IPs in Settings → Networking.
- Fly.io: create the app in a European region, `fly ips allocate-egress
  --app <app> -r <region>`, read the IPs from `fly ips list`.
- No volume, `RAILWAY_RUN_UID` unset (Railway), 1 instance, healthcheck path
  `/healthz`, no TCP proxy, no other services in the project.

**4. Server key** — create a new key: API restriction Places API (New) +
Routes API; IP restriction = the verified egress IP(s) from step 3. Never
reuse the browser key.

**5. Backend variables and deploy** (secrets in the dashboard):
`GOOGLE_MAPS_API_KEY`, `RATE_LIMIT_STORAGE_URI=rediss://…`,
`APP_ENV=production`, `ALLOWED_ORIGINS=https://routewright.vercel.app`,
`LOG_LEVEL=INFO`, `HSTS_ENABLED=false`, `TRUSTED_PROXY_IPS` empty,
`CLIENT_IP_SOURCE` per D-1 (once implemented). Deploy (`railway up
--detach` / `fly deploy`). Stop on any startup validation error — fix the
variable, not the code. 0 calls.

**6. Frontend** — Vercel env: `NEXT_PUBLIC_API_URL=<BACKEND>`,
`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` (browser key, restricted per §4),
`NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`; confirm no `GOOGLE_MAPS_API_KEY`;
`vercel --prod`. 0 calls except map loads.

**7. Zero-call verification** — PRODUCTION_VERIFICATION.md items marked
"0 calls" (health, headers, CORS, retired routes 404, rate limit via
rejected plans, Redis outage behaviour, logs without IPs, forged headers).

**8. Live test** (§12) with the owner present and low quotas.

**9. Afterwards** — `HSTS_ENABLED=true`; restore normal quotas (still no
free-tier guarantee); if the backend moved, decommission the old Railway
service (remove domain, delete service and any volume after confirming its
contents); record results.

**Streaming:** 60 s operations fit Railway's limits (15 min while data
flows; 5 min idle) (VERIFIED docs); Fly limits not verified; absence of
proxy buffering is checked live.

---

## 12. Minimal live test (unauthorised until approved)

Dublin, transit, departure a few days ahead, one operator. Upper estimates:

| # | Test | Autocomplete | PD Essentials | PD Pro | PD Enterprise | Compute Routes | Dynamic Maps |
|---|------|-------------:|--------------:|-------:|--------------:|---------------:|-------------:|
| L1 | Load page; map under CSP | – | – | – | – | – | 1 |
| L2 | Select city + 4 stops | 10–20 | 4 | 1 | – | – | – |
| L3 | Plan 3 stops; stream visibly incremental | – | – | 1 | 3 | 2 | 1 |
| L4 | Refresh from the second leg | – | – | 1 | 2 | 1 | – |
| L5 | Plan 4 stops (inefficient order), Compare | – | – | 2 | 8 | ≤9 | – |
| L6 | Compare again, Cancel after first progress | – | – | ≤1 | ≤4 | ≤6 | – |
| L7 | Final walking: arrivals vs Google Maps; no `arrival_unknown` | – | – | – | – | – | – |
| | **Total (upper)** | **≤20** | **4** | **≤6** | **≤17** | **≤18** | **≤2** |

≈ 65 billable events. The application budget (2,000/day) and limits are
not a cost guarantee; existing usage on the **billing account** (other
projects and apps share the per-SKU monthly caps) is UNKNOWN. Abandoned
autocomplete sessions bill per request. No zero-charge claim.

L7 is indirect: raw Routes responses are not logged by design.

---

## 13. Rollback and emergency stop

| Situation | Action |
|-----------|--------|
| Bad backend deploy | Railway: previous deployment → Rollback (restores image and variables, within retention). Fly: redeploy the previous image (`fly releases`, `fly deploy --image <previous>`) |
| Bad frontend deploy | `vercel rollback` (Hobby: previous production deployment only); `vercel promote <deployment>` to undo. **Note:** the previous production frontend is the old v1 build, which calls retired routes — rolling the frontend back alone does not restore a working site |
| First v2 deploy fails | keep the new backend unreachable (remove public domain / stop it); frontend rollback restores the old (already broken) build |
| Unexpected Google usage / key exposure | set Places API (New) and Routes API daily quotas to 0 (immediate stop), then restrict/rotate (rotation needs approval); budget alerts do not stop spend |
| Redis outage or quota exhausted | app fails closed (503, no provider calls); restore or upgrade (needs approval) |
| Abuse while D-1 is unimplemented | lower quotas; temporary platform IP blocks |

Vercel rollback keeps current env vars; Railway rollback restores them.

---

## 14. Approval package (what needs a yes)

1. **Hosting for A4**: Railway Pro ($20/month, shared static IPs) **or**
   Fly.io migration (~$3.60/month IP + compute, dedicated egress IP).
2. **Redis**: Upstash free plan, `eu-west-1`.
3. **Client IP**: D-1 as in §7 if on Railway (Fly needs a new proposal).
4. **Domains**: confirm `routewright.vercel.app` and the Railway project are
   ours; final backend origin follows item 1.
5. **Map ID**: create one raster JavaScript map ID.
6. **Push**: all local commits to `origin/main`; CI must pass.
7. **Deploy** in the §11 order, including decommissioning the old Railway
   service if the backend moves.
8. **Live test**: ≤ 65 billable events (§12), low quotas during the test.
9. **Keys**: create the server key (and Map ID) only after 1 and 4.

Deferred / release blockers regardless: monthly free-tier enforcement (A6),
D36 selection limits (interim), D46 comparison-outcome permitted use,
`braces` exception expiry 2026-11-04.

---

## 15. Commands

```bash
# Pre-flight (local, no Google calls)
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy app
cd ../frontend
npm run type-check && npm run lint && npm run test:unit
PATH="../backend/.venv/bin:$PATH" npm run check:types-drift
npm run security:audit
GOOGLE_MAPS_API_KEY=AIzaPROBEserverKEYmustNOTbeBUNDLED12345678 npm run build
SECURITY_BUNDLE_PROBE=AIzaPROBEserverKEYmustNOTbeBUNDLED12345678 npm run security:bundle
npm run test:e2e

# Railway (if chosen)
railway login && cd backend && railway link
railway up --detach && railway logs -n 100

# Vercel
cd frontend && vercel link
vercel env add NEXT_PUBLIC_API_URL production
vercel env add NEXT_PUBLIC_GOOGLE_MAPS_API_KEY production
vercel env add NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID production
vercel --prod
```

---

## Sources (checked 2026-10-06)

- Railway: [Specs & limits](https://docs.railway.com/networking/public-networking/specs-and-limits),
  [Edge networking](https://docs.railway.com/networking/edge-networking),
  [TCP proxy](https://docs.railway.com/networking/tcp-proxy),
  [Variables](https://docs.railway.com/reference/variables),
  [Private networking](https://docs.railway.com/networking/private-networking/how-it-works),
  [Healthchecks](https://docs.railway.com/reference/healthchecks),
  [Volumes](https://docs.railway.com/reference/volumes),
  [Static outbound IPs](https://docs.railway.com/reference/static-outbound-ips),
  [Logging](https://docs.railway.com/reference/logging),
  [Deployment actions](https://docs.railway.com/guides/deployment-actions),
  [CLI](https://docs.railway.com/reference/cli-api),
  [Pricing](https://railway.com/pricing);
  staff forum: [Redis SSL](https://station.railway.com/questions/redis-ssl-support-0deb1f16),
  [client IP 2026-05](https://station.railway.com/questions/need-authoritative-railway-client-ip-p-b7a7b4bd),
  [client IP 2024-08](https://station.railway.com/questions/edge-proxy-x-forwarded-for-and-x-real-ip-c5a50049).
- Vercel: [Encryption/HSTS](https://vercel.com/docs/cdn-security/encryption),
  [Instant Rollback](https://vercel.com/docs/instant-rollback),
  [vercel rollback](https://vercel.com/docs/cli/rollback),
  [Hobby plan](https://vercel.com/docs/plans/hobby).
- Redis providers: [Upstash pricing](https://upstash.com/pricing/redis),
  [Upstash security](https://upstash.com/docs/redis/features/security),
  [Upstash regions (API docs)](https://upstash.com/docs/devops/developer-api/redis/create_database_global),
  [Redis Cloud pricing](https://redis.io/pricing/),
  [Aiven pricing](https://aiven.io/pricing?product=valkey).
- Egress IPs: [Fly.io egress IPs](https://docs.fly.io/networking/egress-ips),
  [Render outbound IPs](https://render.com/docs/outbound-ip-addresses).
- Google: [API security best practices](https://developers.google.com/maps/api-security-best-practices),
  [Places session pricing](https://developers.google.com/maps/documentation/places/web-service/session-pricing),
  [Pricing](https://developers.google.com/maps/billing-and-pricing/pricing),
  [Routes usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing),
  [Get a map ID](https://developers.google.com/maps/documentation/javascript/map-ids/get-map-id),
  [Advanced Markers](https://developers.google.com/maps/documentation/javascript/advanced-markers/overview),
  [Maps JS usage and billing](https://developers.google.com/maps/documentation/javascript/usage-and-billing).
