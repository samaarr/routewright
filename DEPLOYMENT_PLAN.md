# Deployment plan — RouteWright v2 (Railway + Vercel)

> **PROPOSAL — NOT APPROVED FOR EXECUTION. DEPLOYMENT BLOCKED** pending a
> cost decision on Railway Pro (§6). Approved design decisions are recorded
> in §1; the push, hosting changes, upgrades, key creation, deployment and
> live Google calls all still require explicit approval (§15). Nothing in
> this document has been deployed or verified in production.

Revised 2026-10-06 after the owner fixed the hosting to **Railway (backend)
and Vercel (frontend)**. Other hosts are out of scope. Companion checklist:
[PRODUCTION_VERIFICATION.md](PRODUCTION_VERIFICATION.md).

Labels: **VERIFIED (repo)** current code; **VERIFIED (local)** observed in a
local run, 2026-10-06; **VERIFIED (public probe)** read-only requests from
outside (no Google calls); **VERIFIED (docs)** official provider docs,
2026-10-06 (staff forum answers labelled separately); **UNKNOWN** needs
dashboard/account access; **PROPOSED** awaiting approval.

---

## 1. Decision record

### Approved (2026-10-06)

| ID | Decision | Status |
|----|----------|--------|
| H | **Hosting fixed: Railway + Vercel.** No migration | Recorded |
| A1 | **Ephemeral cache**: container filesystem, no volume, non-root, `RAILWAY_RUN_UID` unset; planning independent of the cache; failures fall back | Done (`7365dee`); storage considerations remain (§10) |
| A2 | **Redis requires verified TLS (`rediss://`)**, no plaintext exception | Done (`5ef006d`); VERIFIED (local) over real TLS (§7); provider needs approval |
| A3 | **v1 endpoints retired** (`/api/plan`, `/api/optimise`, `/api/refresh-leg`) | Done (`3c9f7ec`); VERIFIED (local) 404 in the production-mode container |
| A4 | **Server key: verified outbound-IP restriction** + Places API (New) + Routes API restriction, before deployment | **BLOCKED** — needs Railway Pro (§6); not relaxed |
| A5 | **Metrics**: aggregate app logs on the platform only, no archive, no sensitive content or comparison savings; platform HTTP logs documented separately; retention to verify | Code done; retention UNKNOWN (§11) |
| A6 | **Monthly free-tier enforcement deferred**; limits unchanged; no zero-charge claim from quotas or alerts | Unchanged |

### Completed fixes
| ID | Item | Status |
|----|------|--------|
| D-9 | Client IP in 429 log line | Fixed `8123f47` |
| D-9b | Client IP in uvicorn WebSocket log lines | Fixed `f3901c9` (`--ws none` + redaction) |
| — | Final container (`--ws none`) | VERIFIED (local): rebuilt from HEAD, production mode, TLS Redis — §16 |

### Open proposals
| ID | Proposal | Section |
|----|----------|---------|
| C1 | Railway Pro upgrade for Static Outbound IPs ($20/month) | §6 |
| C2 | Upstash Redis free plan, `eu-west-1`, no payment method | §7 |
| D-1 | Railway client-IP integration + hashed limiter keys | §8 |
| D-5 | Production Map ID | §9 |
| D-6 | Push local commits; green CI | §12 |
| D-8 | Confirm ownership of the existing Vercel/Railway names | §4 |

### Findings needing attention
- The existing backend returns 502 (§3); the live frontend is broken.
- Rate-limit **keys in Redis contain the raw client IP** (e.g.
  `LIMITS:LIMITER/<ip>/plan-v2/10/1/minute`, TTL up to one day) — VERIFIED
  (local). With Upstash, a third party would hold them. Proposal in §8.
- The browser key embedded in the live bundle has UNKNOWN restrictions.

---

## 2. Costs (VERIFIED docs, 2026-10-06; usage figures are estimates)

| Item | Plan | Price | Notes |
|------|------|-------|-------|
| Railway | Hobby (current per CLAUDE.md; UNKNOWN) | $5/month incl. $5 usage | **No static outbound IPs** |
| Railway | **Pro (required for A4)** | **$20/month per workspace incl. $20 usage**; usage beyond: CPU $20/vCPU-month, memory $10/GB-month, egress $0.05/GB | Static Outbound IPs: no extra charge stated. Pro also gives 30-day logs, 120 h image retention |
| Upgrade delta | Hobby → Pro | **+$15/month** if usage stays within the $20 credit | Upgrades take effect immediately; proration not stated in the docs |
| Estimated backend usage | 1 replica, light traffic | ≈ $2–8/month (estimate, not measured) | Within the Pro credit at test volumes |
| Vercel | Hobby | $0 | Non-commercial use only |
| Upstash Redis | Free | $0 | 500K commands/month, 256 MB; no card → requests rejected at the limit, no charge |
| Google Maps Platform | — | **UNKNOWN** | Existing billing-account usage unknown; no zero-charge claim |

---

## 3. Existing deployment and the Railway 502 (VERIFIED public probe)

| Item | Observation |
|------|-------------|
| `https://routewright.vercel.app` | Live (200), older build; CSP `connect-src` names `https://routewright-production.up.railway.app`; Vercel HSTS `max-age=63072000; includeSubDomains; preload` |
| Browser key in the live bundle | present (expected); restrictions UNKNOWN |
| `https://routewright-production.up.railway.app` | Every request (`/healthz`, `/`) waits ~15 s, then **`502 Application failed to respond`** with `x-railway-fallback: true`, edge `lhr1` (request IDs `sNfIG52JS6aJj1JSezItjw`, `4O7Wduv1Q6KNubfZAax-fw`, `v4UijRJpSpqv617ZO8poTA`). `http://` → 301 to HTTPS |
| `routewright.com` | registered, Cloudflare, owner UNKNOWN — not used |

**Interpretation (not verified):** the domain is still routed to a service
but nothing accepts the connection on the target port. Possible causes: no
active deployment (crashed/removed, or stopped because trial/usage credits
ran out), the app listening on a different port or interface than Railway
targets, or the app failing at startup (e.g. the old code's production
checks failing on missing/changed variables, or Redis unreachable).

**Not investigated further:** no Railway CLI, credentials or dashboard
access here. Nothing was changed or restarted. Information needed (read-only;
the owner can collect it):
1. Plan and billing state (Trial/Free/Hobby/Pro; credits exhausted or
   services paused?) — Workspace → Usage/Billing.
2. Service list and the backend service's **deployment history**: status of
   the latest deployments (Active/Crashed/Failed/Removed), commit SHA, time.
3. **Deploy logs** of the latest deployment (last ~200 lines) and its build
   log: `railway logs -n 200`, `railway logs --build -n 200`.
4. HTTP logs for the request IDs above (upstream error detail).
5. Service settings: networking (generated domain, target port), custom
   start command, healthcheck path/timeout, App Sleeping/serverless toggle,
   region, replicas, **volumes** (and whether a volume holds the legacy
   cache), TCP proxy, static IPs.
6. Variable **names only** (no values): e.g. `railway variables --json |
   jq 'keys'` (check flags with `railway variables --help`), especially
   `PORT`, `APP_ENV`, `RATE_LIMIT_STORAGE_URI` (scheme only),
   `TRUSTED_PROXY_COUNT`, `ALLOWED_ORIGINS`.
7. Other services in the project/environment (e.g. a Railway Redis).

---

## 4. Domains, origins, keys, CSP (D-8)

Ownership is UNKNOWN from here; confirm in the dashboards.

| Role | Value |
|------|-------|
| Frontend origin | `https://routewright.vercel.app` |
| Backend origin | `https://routewright-production.up.railway.app` (existing service; stable across deployments) |

- Backend `ALLOWED_ORIGINS=https://routewright.vercel.app`.
- Frontend `NEXT_PUBLIC_API_URL=https://routewright-production.up.railway.app`
  (inlined at build time — VERIFIED docs).
- **Browser key:** Websites `https://routewright.vercel.app/*`; API
  restriction Maps JavaScript API only. Previews get no map.
- **Server key:** API restriction Places API (New) + Routes API; IP
  restriction = the Railway static outbound IPv4 address(es) (§6).
- **Frontend CSP** (generated by `lib/security.ts`):
  ```
  default-src 'none'; script-src 'self' 'nonce-<per request>' https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://maps.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com; connect-src 'self' https://*.googleapis.com https://*.gstatic.com https://*.google.com https://*.googleusercontent.com https://*.ggpht.com https://routewright-production.up.railway.app; worker-src 'self' blob:; frame-src https://www.google.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'
  ```
- Backend API CSP: `default-src 'none'; frame-ancestors 'none'`.

---

## 5. Repository configuration (VERIFIED repo)

- Dockerfile: `USER app` (uid 1000); uvicorn `--no-proxy-headers
  --no-access-log --ws none --workers 1 --limit-concurrency 40`, port
  `${PORT:-8000}`, `umask 077`.
- Production startup requires `GOOGLE_MAPS_API_KEY`, verified-TLS
  `rediss://`, HTTPS `ALLOWED_ORIGINS`; rejects `TRUSTED_PROXY_COUNT`, `/0`
  trust; pings Redis.
- Routes: `/healthz` and `/api/v2/*` only.
- No Railway config-as-code; `frontend/vercel.json` region `dub1`.
- CI: backend (with Redis service), frontend (incl. bundle key check, e2e),
  gitleaks, container (non-root + `/healthz`).
- Local commits not pushed since `49a77e8`; CI has not run on them.

---

## 6. Server-key outbound-IP restriction on Railway (A4) — BLOCKED

**Railway options (VERIFIED docs):** Static Outbound IPs are available only
on **Pro**, for any service, IPv4 only, enabled per service (Settings →
Networking → Enable Static IPs, or `railway outbound-network static-ip
enable`), effective after a **redeploy**. The addresses "may be shared with
other customers", change if the service moves region, and cannot receive
inbound traffic. No extra charge beyond Pro is stated. Hobby has no static
egress IP, so **A4 cannot be met on the current plan → deployment blocked
pending the cost decision (C1: +$15/month net).** The requirement is not
relaxed.

**What a (shared) outbound-IP restriction protects against**
- A leaked server key (from a log, a `.env`, a screenshot, a compromised
  laptop or CI) being used from **anywhere else on the internet**: Google
  rejects requests that do not come from the listed IP(s).
- Casual or automated abuse of a scraped key, which is the common case.

**What it does not protect against**
- **Co-tenants:** anyone whose traffic leaves Railway through the same shared
  IPv4 can use a leaked key. Exposure is narrowed to that pool, not removed.
- **Compromise of our own service** (code execution, SSRF): requests come
  from the allowed IP.
- **Spend:** the restriction is not a cost limit — quotas, the app budget and
  rate limits are the controls, and none guarantees zero charges.
- **Abuse through our public API:** that uses our IP by design; rate limits
  and the provider budget handle it.
- **Operational risks:** region change or migration changes the IPs; the
  backend must reach Google over IPv4 from those addresses (if it egresses
  over IPv6, calls fail closed with an authorisation error — first live
  call verifies this); all assigned IPs must be listed.

---

## 7. Redis with TLS (A2) — proposal C2: Upstash

| Requirement | Upstash (VERIFIED docs unless noted) |
|-------------|--------------------------------------|
| TLS | "enabled by default for all Upstash Redis databases. It's not possible to disable it." Public CA — the image's `/etc/ssl/certs/ca-certificates.crt` is present (VERIFIED local) |
| Client compatibility | Redis protocol over TCP; Scripting (EVAL/EVALSHA/SCRIPT LOAD), INCRBY, EXPIRE, GET, TTL, PING supported. The `limits` fixed-window strategy used here needs exactly EVALSHA (incr+expire script, with SCRIPT LOAD/EVAL fallback), GET, TTL, PING (VERIFIED repo). Not yet tested against Upstash itself |
| Region | `eu-west-1` (Ireland) is an allowed primary region (API docs). Railway region to match: EU West |
| Command limit (free) | 500K commands/month, 256 MB data, 10 GB bandwidth, 10 MB request, 1 free database |
| At the limit | `ERR max requests limit exceeded` — requests rejected. The app fails closed (503, no provider calls) |
| Eviction | Disabled by default; writes rejected when the data limit is reached (no silent loss of limit keys). Do not enable it (its policy can evict keys) |
| Paid overflow | Free plan without a payment method: no charges, requests rejected. **Adding a card upgrades the database automatically** to a paid plan. Pay-as-you-go supports a monthly budget cap (rate-limited at the cap). Proposal: no payment method |
| Data held | rate-limit and budget keys only; today the keys include client IPs (see D-1 hashing) |

**Railway Redis is not an option:** the template URL is `redis://` with no
TLS option (Railway staff answer); A2 forbids plaintext.

**Local verification (VERIFIED local, no Upstash resource created):** a
TLS-only, password-protected `redis:7.4-alpine` with a throwaway CA:
- shared-store tests 4/4 passed over `rediss://…?ssl_ca_certs=…`;
- refused: plaintext to the TLS port, wrong CA, hostname not in the
  certificate, and system CAs only (self-signed) — verification is enforced;
- the production-mode backend container started against it (startup TLS
  validation + PING), enforced limits through it (keys created over TLS),
  and **refused to start** with `redis://` (exit 3, password not printed).

Usage estimate: ≈ 10–15 commands per 3–4-stop plan → the free allowance
covers on the order of 30,000 operations/month. Not a guarantee.

---

## 8. D-1 — Railway client identity (final proposal, NOT IMPLEMENTED)

### Railway facts
Documented: the edge adds `X-Real-IP` ("client's remote IP"),
`X-Forwarded-Proto: https`, `X-Forwarded-Host`, `X-Railway-Edge`,
`X-Railway-Request-Id`, `X-Request-Start`; the edge terminates TLS and
forwards internally; a TCP proxy exposes a port directly and sets
`RAILWAY_TCP_PROXY_DOMAIN`; services in the same environment reach each
other over the private network. **Not documented:** that a client's
`X-Real-IP` is overwritten, `X-Forwarded-For` handling, the source address
range, or that the edge is the only path. Staff (2026-05): `X-Real-IP` is
always overwritten; apps behind the HTTP proxy cannot be accessed directly.
A 2024 thread shows clients could set it until a fix.

### Trust boundary
```
client ──TLS──► Railway HTTP edge ──(X-Real-IP written)──► backend container
TCP proxy (if created)          ──────────────────────────► bypasses edge
other services, same environment ──private network───────► bypasses edge
```
Trusted: the `X-Real-IP` value written by the edge, only. Railway staff and
project members are inside the boundary (they control deployment).

### Direct access handling
| Path | Handling |
|------|----------|
| Public HTTP via the generated domain | Always through the edge (staff statement); per-request checks below |
| TCP proxy on the backend | **Forbidden.** Startup refuses `CLIENT_IP_SOURCE=railway` when `RAILWAY_TCP_PROXY_DOMAIN` is set. Residual: a proxy added without a redeploy is not seen by the running process — the deployment checklist re-verifies networking after any settings change |
| Private network | The environment contains **only the backend** (Redis is Upstash, outside Railway). Any future service in the environment is a trust decision |
| Static outbound IPs | outbound only; "cannot be used to receive inbound traffic" (docs) |
| Custom domain / CDN in front | Not used. A CDN would make `X-Real-IP` the CDN's address → would require a new design |

### Forged-header prevention
1. `X-Forwarded-For` is ignored entirely in `railway` mode; `TRUSTED_PROXY_IPS`
   stays empty and is **not broadened**.
2. `X-Real-IP` is used only if **all** hold, else the TCP peer is used (all
   such requests share one stricter bucket):
   - exactly one `X-Real-IP` header, holding exactly one parseable address
     (no list, port, whitespace tricks; IPv4-mapped IPv6 normalised);
   - the address is globally routable (not private, loopback, link-local,
     CGNAT, reserved, multicast, unspecified);
   - `X-Railway-Edge` and `X-Railway-Request-Id` are present (consistency
     check; forgeable, so never sufficient alone);
   - the TCP peer is **not** a globally routable address (edge traffic arrives
     from Railway's internal network; a public peer means a non-edge path).
3. Startup: `CLIENT_IP_SOURCE=railway` requires `RAILWAY_ENVIRONMENT_ID` and
   no `RAILWAY_TCP_PROXY_DOMAIN`; exclusive with `TRUSTED_PROXY_IPS`; read via
   `settings`.
4. Aggregate metric `client_ip_source` = `header` | `fallback_missing` |
   `fallback_invalid` | `fallback_peer_public` (no addresses) so a change at
   Railway shows up.
5. After every deploy and networking change: forged `X-Real-IP` /
   `X-Forwarded-For` from a client do not create a new bucket; two networks
   get separate buckets.
6. If any check fails in production: set `CLIENT_IP_SOURCE=peer` (one shared
   bucket — safe for cost) and redeploy.

### Hashed limiter keys (new, same change)
Redis keys currently contain raw client IPs (VERIFIED local). Proposal: the
limiter key becomes `HMAC-SHA256(LIMITER_KEY_SECRET, identity)` (truncated,
hex), with the secret as a new backend secret. Whitelist comparison happens
on the raw address before hashing. Upstash then stores no client IPs. Secret
rotation resets counters (acceptable; document it).

### Tests (with the implementation)
Forged/duplicate/list/private/IPv6/mapped headers, missing edge markers,
public peer, TCP-proxy and missing-environment startup refusal, exclusivity
with `TRUSTED_PROXY_IPS`, unchanged `peer` mode, real-limiter buckets per
identity, keys contain no raw IP.

**Sub-decision (not included unless approved):** group IPv6 identities by
/64 (changes grouping, not limit values).

Until D-1 ships, all visitors share one identity: acceptable only for the
closed live test.

---

## 9. Production Map ID (D-5, investigation only)

Advanced Markers need a map ID; `DEMO_MAP_ID` is allowed but not described as
a production setting. Creating a map ID is free; map loads bill as Dynamic
Maps (Essentials, 10,000 free/month) either way; no extra charge for map IDs
or Advanced Markers is stated (confirm in the billing report). Setup after
approval: Cloud Console → Google Maps Platform → Map Management → Create map
ID → JavaScript, Raster → Save, in the browser key's project; set
`NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` in Vercel and rebuild (inlined at build).

---

## 10. Ephemeral cache — remaining considerations (A1)

No volume → no volume backups/snapshots. Not eliminated: the SQLite file
(place ID + coordinates, ≤ 30 days) is on Railway's container disk while the
container runs (encryption at rest not documented); readable by anyone with
shell access to the service; cleared on each redeploy/restart and by the
30-day purge. The existing service may have a volume with the legacy rich
cache (UNKNOWN; §3 item 5) — inspect and delete it before reusing the
service.

---

## 11. Logs and retention (A5)

| Log | Content | Retention |
|-----|---------|-----------|
| App metrics (JSON) | operation, transport, outcome, failure, elapsed, stop count, call counts | Railway Pro 30 days (Hobby 7) — VERIFIED docs; actual plan UNKNOWN |
| App security log | request ID, elapsed, exception type | same |
| Railway HTTP logs (platform) | `@srcIp` client IP, path, method, status, user agent, timings, edge | same; outside app control; privacy notice must cover it |
| Vercel runtime logs | middleware/functions (app writes none) | Hobby 1 hour (VERIFIED docs) |

Excluded from app logs (tested, incl. the final container): names/IDs,
coordinates, dates, IPs, plans, secrets, raw provider text, comparison
savings. No archive.

---

## 12. Deployment order (after approvals)

0. **Approvals and prerequisites:** C1, C2, D-1 (+ hashed keys), D-5, D-6,
   D-8, live-test allowance. Owner collects the §3 information; resolve the
   502 cause. Google: record this month's usage per SKU **across the billing
   account**; check the live browser key's restrictions; budget alerts (not
   a cap); temporary low daily quotas on Places API (New) and Routes API
   (e.g. 100/day). Stop if any SKU is near its free cap.
1. **Implement D-1** (after approval), local checks, then push (D-6) and wait
   for green CI.
2. **Upstash:** create one free database in `eu-west-1`, no payment method,
   eviction off. 0 calls.
3. **Railway:** upgrade to Pro (C1); on the existing backend service: no
   volume (delete any legacy volume after checking it), no TCP proxy,
   `RAILWAY_RUN_UID` unset, 1 replica, region EU West, healthcheck path
   `/healthz`; enable Static Outbound IPs; record the IPv4 address(es).
4. **Server key:** create (approval) with API restriction Places API (New) +
   Routes API and IP restriction = the recorded IPs.
5. **Backend variables** (secrets in the dashboard): `GOOGLE_MAPS_API_KEY`,
   `RATE_LIMIT_STORAGE_URI=rediss://…`, `LIMITER_KEY_SECRET` (with D-1),
   `APP_ENV=production`, `ALLOWED_ORIGINS=https://routewright.vercel.app`,
   `LOG_LEVEL=INFO`, `HSTS_ENABLED=false`, `CLIENT_IP_SOURCE=railway`,
   `TRUSTED_PROXY_IPS` empty. **Snapshot** the variable names and non-secret
   values. Deploy the pushed commit (`railway up --detach` or dashboard);
   the redeploy also activates the static IPs. Stop on any startup error.
6. **Zero-call checks** (PRODUCTION_VERIFICATION.md §2, §6, §7, §9).
7. **Vercel:** set `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`,
   `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`; confirm no `GOOGLE_MAPS_API_KEY`;
   `vercel --prod`. Record the deployment URL with the backend deployment ID
   as **release pair R1**.
8. **Live test** (§14) with the owner present and low quotas.
9. **Afterwards:** `HSTS_ENABLED=true` (redeploy → new backend deployment,
   same pair R1 for the frontend); restore normal quotas; record results.

Streaming: 60 s operations fit Railway's limits (15 min while data flows,
5 min idle; VERIFIED docs); buffering checked live.

---

## 13. Rollback (corrected)

### Platform behaviour (VERIFIED docs)
- **Railway Rollback** restores "both the Docker image and the custom
  variables from that deployment"; it is available only within the plan's
  image retention (Hobby 72 h, **Pro 120 h**). **Redeploy** reuses "identical
  code and build/deploy configuration" — variable behaviour is not stated, so
  do **not** use Redeploy as a rollback. Variables are not assumed correct
  after any rollback: compare against the recorded snapshot, and re-enter
  secrets that were rotated since (a restored old key may have been deleted).
- **Vercel Instant Rollback** points the domain at a previous build; Hobby
  can only return to the **immediately previous** production deployment; it
  does not change the project's environment variables, and the restored
  build keeps the `NEXT_PUBLIC_*` values inlined when it was built (VERIFIED
  docs). It disables auto-assignment until `vercel promote` is used.

### Release pairs
A release pair = (Railway deployment ID, Vercel deployment URL, git SHA,
variable snapshot). A frontend and backend are compatible only when built
from the same SHA, or when `frontend/schema.json` and the v2 API are
unchanged between them (`git diff <a>..<b> -- frontend/schema.json
backend/app/models` is empty). The backend origin is the same Railway
domain for all pairs, so inlined `NEXT_PUBLIC_API_URL` stays valid.

| Situation | Rollback |
|-----------|----------|
| Release R(n) bad, R(n−1) is a v2 pair within retention | Railway: Rollback to R(n−1)'s deployment; check variables vs snapshot. Vercel: `vercel rollback` if R(n−1)'s frontend is the immediately previous production deployment (the only Hobby rollback target); otherwise redeploy R(n−1)'s SHA. Order: backend first if the API changed, otherwise only the side that changed |
| Only one side changed and the contract is unchanged | roll back that side alone |
| **First v2 release (R1) bad** | **No compatible previous pair exists**: the previous frontend is the v1 build (calls retired routes) and the previous backend deployments are v1 code (legacy routes; currently failing) — **never roll back to them**. Instead "safe off": set Google quotas to 0 or remove the backend's public domain / stop the deployment (`railway down`), then fix forward. The site is already non-functional today, so this is no regression |
| Older than retention | redeploy the recorded SHA with the recorded variables (new deployment) |
| Key exposure / unexpected usage | Places API (New) and Routes API daily quotas to 0 (immediate), then restrict/rotate with approval; alerts do not stop spend |
| Redis limit/outage | app fails closed (503, no provider calls); fix or upgrade with approval |

---

## 14. Smallest useful live test (unauthorised until approved)

Dublin, transit, departure a few days ahead, one operator, owner present,
low quotas. Four stops are needed so that comparison has a different order
to evaluate with first/last pins on (three pinned stops leave nothing to
reorder and make no routing calls). Upper estimates:

| # | Step | Checks | AC | PD Ess | PD Pro | PD Ent | Routes | Maps |
|---|------|--------|---:|------:|------:|------:|------:|----:|
| T0 | Zero-call checks | health, headers, CORS, 404s, 429, Redis TLS, logs | – | – | – | – | – | – |
| T1 | Load page | map + CSP + referrer key | – | – | – | – | – | 1 |
| T2 | Select city + 4 stops | selection, area warnings | ≤20 | 4 | 1 | – | – | – |
| T3 | Plan, middle stops deliberately swapped | streaming incremental, final walking times, metrics | – | – | 1 | 4 | 3 | – |
| T4 | Refresh from the last leg | planned departure, prefix kept | – | – | 1 | 2 | 1 | – |
| T5 | Compare | candidate + fresh original, saving threshold | – | – | 1 | 4 | ≤6 | – |
| T6 | Plan again, Cancel after first progress | disconnect propagation, capacity freed | – | – | ≤1 | ≤4 | ≤3 | ≤1 |
| | **Total (upper)** | | **≤20** | **4** | **≤5** | **≤14** | **≤13** | **≤2** |

≈ 58 billable events. Final walking durations are checked indirectly
(arrivals vs Google Maps; no `arrival_unknown`). Unknown existing usage on
the billing account; abandoned autocomplete sessions bill per request; no
zero-charge claim. Upstash commands: < 1,000.

---

## 15. Blockers and approval package

**Blockers**
1. **A4 egress IP → Railway Pro cost decision (C1, +$15/month net).**
2. Approvals: push (D-6), Upstash (C2), D-1 implementation, Map ID (D-5),
   domain ownership (D-8), deployment, server-key creation, live test.
3. The 502 cause on the existing service (information in §3).
4. Client identity (D-1) before any public traffic.
5. Monthly free-tier enforcement deferred → no free-tier-safe public claim.

**Deferred regardless:** D36 selection limits (interim combined
30/min + 100/day), D46 comparison-outcome permitted use, `braces` exception
expiring 2026-11-04 (not extended).

---

## 16. Final container verification (VERIFIED local, 2026-10-06)

Image rebuilt from HEAD (app code hashes = repo, 37 files), run on an unused
port in **production mode** against the TLS-only test Redis:
- `uid=1000(app)`; PID 1 = uvicorn with `--no-proxy-headers --no-access-log
  --ws none`; `/healthz` → 200 `{"status":"ok","version":"0.1.0"}`.
- 11 rejected plans (zero provider calls) with forged `X-Forwarded-For` and
  `X-Real-IP` → 10 × 422, then 429 with `Retry-After: 60`; log line
  `ratelimit 10 per 1 minute exceeded at endpoint: plan-v2` (no key).
- Upgrade request → 405; log `Unsupported upgrade request.` (no address).
- Retired routes → 404 (JSON POST and GET; a POST without a JSON content type
  gets 415 from the security middleware before routing).
- Whole application log scanned: no client, forged or Docker-peer address.
- 10 metrics lines, `"calls": {}`.
- `redis://` in production → startup refused (exit 3), password not printed.
Test containers, network, image and certificates were removed afterwards.

---

## 17. Commands

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

# Railway (after approvals)
railway login && cd backend && railway link
railway outbound-network static-ip status
railway up --detach && railway logs -n 100

# Vercel (after approvals)
cd frontend && vercel link
vercel env add NEXT_PUBLIC_API_URL production
vercel env add NEXT_PUBLIC_GOOGLE_MAPS_API_KEY production
vercel env add NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID production
vercel --prod
```

---

## Sources (checked 2026-10-06)

- Railway: [Static outbound IPs](https://docs.railway.com/reference/static-outbound-ips),
  [Plans and pricing](https://docs.railway.com/pricing/plans),
  [Pricing page](https://railway.com/pricing),
  [Deployment actions](https://docs.railway.com/guides/deployment-actions),
  [Roll back a bad deploy](https://docs.railway.com/guides/roll-back-bad-deploy),
  [Deployments reference](https://docs.railway.com/deployments/reference),
  [Specs & limits](https://docs.railway.com/networking/public-networking/specs-and-limits),
  [Edge networking](https://docs.railway.com/networking/edge-networking),
  [TCP proxy](https://docs.railway.com/networking/tcp-proxy),
  [Variables](https://docs.railway.com/reference/variables),
  [Private networking](https://docs.railway.com/networking/private-networking/how-it-works),
  [Healthchecks](https://docs.railway.com/reference/healthchecks),
  [Volumes](https://docs.railway.com/reference/volumes),
  [Logging](https://docs.railway.com/reference/logging),
  [CLI](https://docs.railway.com/reference/cli-api);
  staff forum: [Redis SSL](https://station.railway.com/questions/redis-ssl-support-0deb1f16),
  [client IP 2026-05](https://station.railway.com/questions/need-authoritative-railway-client-ip-p-b7a7b4bd),
  [client IP 2024-08](https://station.railway.com/questions/edge-proxy-x-forwarded-for-and-x-real-ip-c5a50049).
- Vercel / Next.js: [Instant Rollback](https://vercel.com/docs/instant-rollback),
  [vercel rollback](https://vercel.com/docs/cli/rollback),
  [Encryption/HSTS](https://vercel.com/docs/cdn-security/encryption),
  [Hobby plan](https://vercel.com/docs/plans/hobby),
  [Next.js environment variables](https://nextjs.org/docs/app/guides/environment-variables).
- Upstash: [Pricing](https://upstash.com/pricing/redis),
  [Pricing & limits docs](https://upstash.com/docs/redis/overall/pricing),
  [Billing/budget](https://upstash.com/docs/redis/overall/billing),
  [Security (TLS)](https://upstash.com/docs/redis/features/security),
  [Connect a client](https://upstash.com/docs/redis/howto/connectclient),
  [Redis compatibility](https://upstash.com/docs/redis/overall/rediscompatibility),
  [Eviction](https://upstash.com/docs/redis/features/eviction),
  [Max requests limit](https://upstash.com/docs/redis/troubleshooting/max_requests_limit),
  [Regions (API)](https://upstash.com/docs/devops/developer-api/redis/create_database_global);
  Redis Cloud [pricing](https://redis.io/pricing/).
- Google: [API security best practices](https://developers.google.com/maps/api-security-best-practices),
  [Pricing](https://developers.google.com/maps/billing-and-pricing/pricing),
  [Places session pricing](https://developers.google.com/maps/documentation/places/web-service/session-pricing),
  [Get a map ID](https://developers.google.com/maps/documentation/javascript/map-ids/get-map-id),
  [Advanced Markers](https://developers.google.com/maps/documentation/javascript/advanced-markers/overview).
