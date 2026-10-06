# Deployment plan — RouteWright v2

> **PROPOSAL — NOT APPROVED.** Decisions D-1 to D-9 (§5) are unresolved.
> Do not execute any step until the owner approves this plan and those
> decisions. Nothing in this document has been deployed or verified live.

Prepared 2026-10-06 for approval. **Nothing here has been executed.** No
hosting setting was changed, nothing was pushed or deployed, no key was
created or rotated and no live Google call was made. Monthly free-tier
enforcement remains deferred and existing application limits are unchanged.
Companion checklist: [PRODUCTION_VERIFICATION.md](PRODUCTION_VERIFICATION.md).

Status labels used below:

- **VERIFIED (repo)** — read in the current code/config at HEAD `46faeac`.
- **VERIFIED (docs)** — checked against official provider documentation on
  2026-10-06 (sources at the end). Staff forum answers are marked as such.
- **MISSING** — configuration that does not exist yet and must be created.
- **DEPLOY-ONLY** — can only be checked against the real deployment.
- **UNKNOWN** — could not be inspected from here.

---

## 1. What was inspected

| Item | Finding | Status |
|------|---------|--------|
| `backend/Dockerfile` | python:3.11-slim, hash-locked deps, `USER app` (uid 1000), uvicorn `--no-proxy-headers --no-access-log --workers 1 --limit-concurrency 40`, listens on `${PORT:-8000}` | VERIFIED (repo); local run verified 2026-10-06 |
| `backend/.dockerignore` | excludes `.env*`, tests, caches, local SQLite | VERIFIED (repo) |
| Railway config-as-code (`railway.toml`/`railway.json`) | none — service settings (root dir, healthcheck, region) live only in the dashboard | MISSING (dashboard settings UNKNOWN) |
| `frontend/vercel.json` | `framework: nextjs`, `regions: ["dub1"]` | VERIFIED (repo) |
| `frontend/next.config.js` | `/api/*` rewrite to localhost **only when `NEXT_PUBLIC_API_URL` is empty**; static security headers | VERIFIED (repo) |
| `frontend/middleware.ts` + `lib/security.ts` | per-request nonce CSP; production build throws unless `NEXT_PUBLIC_API_URL` is an HTTPS origin; `connect-src` allows only Google and that origin; HSTS only when `SECURITY_HSTS_ENABLED=true` | VERIFIED (repo) |
| Browser → backend path | the browser calls the Railway origin **directly** (CORS); Vercel functions are not in the streaming path, so Vercel function timeouts do not apply to streams | VERIFIED (repo) |
| `.github/workflows/ci.yml` | backend (ruff, mypy, pytest **with a Redis service**, pip-audit), frontend (type-check, lint, unit, drift, npm audit, build with a probe server key, bundle check, smoke, e2e), gitleaks, container (non-root + `/healthz`) | VERIFIED (repo) |
| CI on GitHub for current code | last pushed commit `49a77e8`; **27 local commits are unpushed**, so CI has not run on the code to be deployed | UNKNOWN until push |
| Railway / Vercel / gh CLIs, project links | not installed; no `.railway`/`.vercel` link on this machine | Hosting settings UNKNOWN (not inspectable read-only from here) |
| Google Cloud project (keys, restrictions, quotas, budgets, current monthly usage) | no access from here | UNKNOWN |
| Railway plan (Hobby vs Pro) | CLAUDE.md says Hobby; not confirmed | UNKNOWN |

---

## 2. Environment variables

Secret values must be entered in the provider dashboards (or `vercel env add`,
which prompts) — never on a command line, in a file in the repo, or in chat.

### Backend (Railway service)

| Variable | Kind | Production value | Notes |
|----------|------|------------------|-------|
| `GOOGLE_MAPS_API_KEY` | **SECRET** | server key (Places API (New) + Routes API) | startup fails if empty in production |
| `RATE_LIMIT_STORAGE_URI` | **SECRET** (contains Redis password) | Railway reference to the Redis service's private URL, e.g. `${{Redis.REDIS_URL}}` (confirm the variable name in the Redis service) | must start `redis://` or `rediss://`; startup checks connectivity |
| `APP_ENV` | public | `production` | enables startup validation; disables `.env` reading |
| `ALLOWED_ORIGINS` | public | `https://<frontend production domain>` (exact, comma-separated if several) | HTTPS only, no wildcard/path; preview URLs deliberately excluded |
| `LOG_LEVEL` | public | `INFO` | |
| `TRUSTED_PROXY_IPS` | public | **empty** until decision D-1 below | `/0` rejected at startup |
| `HSTS_ENABLED` | public | `false` at first; `true` after HTTPS verified | |
| `PORT` | injected by Railway | — | do not set |
| `CACHE_DB_PATH` | public | leave default (`./cache/places_cache.db` → `/app/cache`, owned by `app`) | see D-2 |
| Limits (`MAX_REQUESTS_PER_IP_PER_*`, `PROVIDER_CALLS_PER_DAY`, `MAX_CONCURRENT_*`, `PROVIDER_WAIT_SECONDS`, `MAX_REQUEST_BYTES`, `MAX_STOPS_PER_REQUEST`, `CACHE_TTL_DAYS`, `CACHE_CLEANUP_SECONDS`) | public | **do not set** — code defaults apply, keeping existing limits unchanged | |
| `TRUSTED_PROXY_COUNT` | — | **must be unset** | any non-zero value aborts startup |
| `RATE_LIMIT_WHITELIST_IPS` | public | empty | |
| `ANTHROPIC_API_KEY` | secret | **do not set** (unused in v1/v2) | |

### Frontend (Vercel project, root directory `frontend`)

| Variable | Kind | Production value | Notes |
|----------|------|------------------|-------|
| `NEXT_PUBLIC_API_URL` | public (inlined at build) | `https://<railway backend domain>` | build-time: changing it requires a redeploy |
| `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` | public by design, **restricted** | browser key (Maps JavaScript API, website-restricted) | visible to every visitor; safety comes from restrictions |
| `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` | public | `DEMO_MAP_ID` or a real Map ID (D-5) | |
| `SECURITY_HSTS_ENABLED` | public | leave `false` (Vercel already sends HSTS — see §3) | |
| `GOOGLE_MAPS_API_KEY` | — | **must not exist in Vercel** | CI bundle check guards the build |

---

## 3. Platform checks

| Area | Current state | Status / action |
|------|---------------|-----------------|
| **Shared Redis** | code requires `redis://`/`rediss://` in production, fails closed (503 `usage_control_unavailable`) if unreachable; CI runs the shared-store tests | VERIFIED (repo/CI). Railway Redis over private networking (`*.railway.internal`) is Wireguard-encrypted (VERIFIED docs), so `redis://` is acceptable there — SECURITY.md's `rediss://` wording needs updating if approved (D-3). Eviction policy, persistence and that no other service shares the DB: DEPLOY-ONLY |
| **Trusted proxy / client IP** | backend uses the TCP peer unless it is in `TRUSTED_PROXY_IPS`, then walks `X-Forwarded-For`. Railway documents `X-Real-IP` as the client-IP header; Railway does **not** publish its proxy address range (VERIFIED docs; staff forum: X-Real-IP is always overwritten and apps cannot be reached except through the edge) | **BLOCKER D-1.** With `TRUSTED_PROXY_IPS` empty every visitor shares one identity — per-IP limits (plan 10/min, 50/day) become site-wide. Safe for cost, unusable beyond a test window |
| **Allowed origins / CORS** | exact HTTPS origins, `GET/POST`, `Content-Type` only, no credentials; startup rejects bad values | VERIFIED (repo). Needs the final frontend domain before the backend's first production start |
| **HTTPS** | Railway: HTTP GET → HTTPS redirect, plain HTTP POST converted to GET, TLS 1.2/1.3 (VERIFIED docs). Vercel: 308 redirect, HSTS `max-age=63072000` sent by default on `.vercel.app` and custom domains (VERIFIED docs) | Backend HSTS not documented by Railway → set `HSTS_ENABLED=true` after verifying HTTPS. Frontend: keep `SECURITY_HSTS_ENABLED=false` (would replace Vercel's 2-year value with 1 year); confirm Vercel's header is present (DEPLOY-ONLY) |
| **CSP** | nonce-based, no `unsafe-inline` scripts in production, Google domains + API origin in `connect-src`; smoke-tested without a Maps key | Live map under CSP: DEPLOY-ONLY |
| **Health checks** | `GET /healthz` returns 200 without touching providers. Railway only probes at deploy time from `healthcheck.railway.app`, default timeout 300 s (VERIFIED docs); the app has no host allow-list, so the probe host is accepted | MISSING: set Healthcheck Path `/healthz` in the Railway service settings. Not continuous monitoring — see §8 |
| **Streaming timeouts** | operation deadline 60 s; NDJSON events throughout. Railway: requests up to 15 min while data flows, closed after 5 min idle; HTTP/1.1 idle keep-alive 60 s between requests (VERIFIED docs) | 60 s fits the documented limits. Absence of response buffering at Railway's edge is **not documented** → DEPLOY-ONLY. Vercel not in the path |
| **Disconnect propagation** | tested locally (cancel releases capacity, stops calls) | Through Railway's edge: DEPLOY-ONLY |
| **Log retention** | metrics as single-line JSON (Railway parses it); Railway retention Free 3 d, Trial/Hobby 7 d, Pro 30 d, Enterprise up to 90 d; 500 lines/s/replica; Railway HTTP logs include `@srcIp` (VERIFIED docs) | Actual plan UNKNOWN → retention 7 d if Hobby. Vercel runtime logs: Hobby 1 h, Pro 1 d (VERIFIED docs) |
| **Storage** | SQLite cache (place ID + coordinates only), purged after 30 days | **D-2:** Railway volumes mount with root ownership — a non-root image needs `RAILWAY_RUN_UID=0` (i.e. run as root), volumes block replicas and add redeploy downtime; Railway docs don't state volume encryption (VERIFIED docs) |
| **Replicas** | in-process gates (`--workers 1`) and the design assume one replica; Redis already shares limits | Keep **1 replica** |
| **Vercel plan** | Hobby is non-commercial/personal only; rollback limited to the previous deployment (VERIFIED docs) | Product decision if RouteWright ever earns money |

---

## 4. Google Maps Platform keys and prerequisites

Recommended per Google's API security best practices (VERIFIED docs):

**Server key** (Railway `GOOGLE_MAPS_API_KEY`)
- API restrictions: **Places API (New)** (covers Autocomplete (New) and Place
  Details (New)) and **Routes API** only.
- Application restriction: **IP addresses** requires Railway's static outbound
  IPs, which are **Pro-plan only**, IPv4 only and possibly shared with other
  customers (VERIFIED docs). On Hobby no IP restriction is possible; the key
  then relies on API restrictions, staying server-side, quotas and the
  app's provider budget (D-4).
- Separate key per app; never reuse the browser key.

**Browser key** (Vercel `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`)
- Application restriction: **Websites** — `https://<production domain>/*`
  (add the custom domain and/or `https://<project>.vercel.app/*`; previews
  intentionally excluded, so maps do not load on preview URLs).
- API restriction: **Maps JavaScript API** only. The frontend loads only the
  JS map, Advanced Markers and the TransitLayer — no browser-side Places or
  Routes calls (VERIFIED repo).
- Map ID: Advanced Markers need a map ID; Google offers `DEMO_MAP_ID` but the
  docs do not say it is intended for production (D-5).

**Project prerequisites (all MISSING/UNKNOWN until the operator confirms)**
1. Billing account attached; budget with alerts at 50/90/100 % (alerts do
   not cap spend).
2. Daily quotas: Places API (New) and Routes API. During the live test,
   temporarily set them low (e.g. 100/day each) so a mistake cannot run
   long. These are console settings for the operator, not app limits.
3. **Current month's usage per SKU** (Cloud Console → Billing → Reports,
   group by SKU): unknown. Free caps are per SKU per month: Dynamic Maps
   10,000; Autocomplete Requests 10,000; Place Details Essentials 10,000,
   Pro 5,000, **Enterprise 1,000**; Compute Routes Essentials 10,000 / Pro
   5,000 / Enterprise 1,000 (VERIFIED docs). Which Compute Routes tier
   TRANSIT/WALK without traffic awareness bills under is not stated on the
   usage page checked — confirm from the SKU names in the billing report
   after the test.
4. Old/exposed keys: restrict first; rotate only if exposure is suspected
   (Google advises care when rotating).

---

## 5. Decisions required before deployment

| ID | Decision | Options | Recommendation |
|----|----------|---------|----------------|
| D-1 | **Client identity on Railway** (blocker for public use) | (a) small code change: when a setting such as `CLIENT_IP_HEADER=x-real-ip` is set, use Railway's `X-Real-IP` (documented header; overwrite guarantee is from Railway staff, not a formal contract); (b) set `TRUSTED_PROXY_IPS` to an observed proxy range (unpublished, can change — fragile); (c) leave empty and accept one shared bucket during a closed test | (c) for the live test only; (a) before any public announcement, as a separate approved change with tests |
| D-2 | Cache storage | (a) **no volume**: ephemeral cache inside the container (lost on redeploy; keeps non-root, no backups/encryption question); (b) volume + `RAILWAY_RUN_UID=0` (runs as root) | (a); update SECURITY.md "encrypted volume" wording accordingly |
| D-3 | Redis transport | `redis://` over Railway private networking (Wireguard) vs requiring `rediss://` | accept `redis://` on the private network; never expose Redis publicly |
| D-4 | Server-key application restriction | Railway Pro static IPs vs Hobby with API restriction + quotas only | owner's cost/risk call; document the choice |
| D-5 | Map ID | `DEMO_MAP_ID` vs a project Map ID (same project as the browser key) | create a project Map ID |
| D-6 | Push and CI | push the 27 local commits and require green CI before deploy | required; needs explicit push approval |
| D-7 | Legacy endpoints (`/api/plan`, `/api/optimise`, `/api/refresh-leg`) | still served; the frontend no longer calls them; they share the limits and budget | retirement still awaits approval; either approve retirement or accept exposure for the test |
| D-9 | **Client IP in 429 log line** (found 2026-10-06) | slowapi logs `WARNING:slowapi:ratelimit 10 per 1 minute (<client key>) exceeded at endpoint: plan-v2` — the key is the client IP in production. Fix: raise the `slowapi` logger level / filter in the app (small change + test) vs accept (Railway HTTP logs already hold `@srcIp`) | **FIXED** (separate commit): a filter on the `slowapi` logger drops the key from that message and redacts IP tokens in any other slowapi record; `tests/test_ratelimit_logging.py` drives the real limiter with IPv4/IPv6 clients |
| D-8 | Frontend domain | `<project>.vercel.app` vs custom domain | decide first — needed for `ALLOWED_ORIGINS` and the browser-key referrer |

Monthly free-tier enforcement stays deferred: **the deployment may be used for
a closed live test only; a public launch claiming free-tier safety is
blocked** until enforcement exists.

---

## 6. Deployment order

Do not skip or reorder. Each step lists its stop condition.

### Step 0 — approvals and prerequisites
- Owner approves this plan, D-1…D-8, and the live-test budget in §7.
- Google: keys created and restricted (§4), temporary low quotas, budget
  alerts, current SKU usage recorded in PRODUCTION_VERIFICATION.md.
- Stop if current-month usage of any SKU in §7 is near its free cap.

### Step 1 — local pre-flight (no network beyond package registries)
```bash
cd backend
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy app
cd ../frontend
npm run type-check && npm run lint && npm run test:unit
npm run check:types-drift && npm run security:audit
GOOGLE_MAPS_API_KEY=AIzaPROBEserverKEYmustNOTbeBUNDLED12345678 npm run build
SECURITY_BUNDLE_PROBE=AIzaPROBEserverKEYmustNOTbeBUNDLED12345678 npm run security:bundle
npm run test:e2e
```
Then (approval D-6) `git push origin main` and wait for all four CI jobs to
pass. Stop on any failure.

### Step 2 — Railway: Redis and backend (dashboard for secrets)
1. Create project (EU region, closest to Vercel `dub1`); add the Redis
   service from Railway's template; keep it private (no public TCP proxy).
2. Add the backend service: source = this repo, **root directory
   `backend`** (Dockerfile build), 1 replica, no volume (D-2).
3. Set variables from §2 in the dashboard (`GOOGLE_MAPS_API_KEY`,
   `RATE_LIMIT_STORAGE_URI` as a reference to the Redis service,
   `APP_ENV=production`, `ALLOWED_ORIGINS=https://<frontend domain>`,
   `LOG_LEVEL=INFO`, `HSTS_ENABLED=false`, `TRUSTED_PROXY_IPS` empty).
4. Settings → Healthcheck Path `/healthz`.
5. Deploy (dashboard deploy from the pushed commit, or CLI):
   ```bash
   railway login
   cd backend && railway link        # choose the project/service
   railway up --detach
   railway logs -n 100               # expect "Application startup complete"
   railway domain                    # generate the public HTTPS domain
   ```
6. Stop if startup logs show a validation error (missing key, non-Redis
   storage, bad origins, proxy settings) — fix the variable, not the code.

### Step 3 — Vercel frontend
```bash
cd frontend
vercel link
vercel env add NEXT_PUBLIC_API_URL production              # https://<railway domain>
vercel env add NEXT_PUBLIC_GOOGLE_MAPS_API_KEY production  # browser key (prompted, not echoed to history)
vercel env add NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID production
vercel --prod
```
Confirm the Vercel project has **no** `GOOGLE_MAPS_API_KEY`. If the final
domain differs from the one used in `ALLOWED_ORIGINS`, update that backend
variable (Railway redeploys).

### Step 4 — zero-Google-call verification (§8 items marked "0 calls")
### Step 5 — live test (§7), with the owner present and quotas low
### Step 6 — after verification
- `HSTS_ENABLED=true` on Railway; restore normal Google quotas (still not a
  free-tier guarantee); record results in PRODUCTION_VERIFICATION.md.
- Public announcement remains blocked by D-1 (if not done) and deferred
  free-tier enforcement.

---

## 7. Minimal live test plan

One operator, one browser, Dublin, transit, a departure a few days ahead.
Counts are upper estimates from the code paths (city lookup: Place Details
Pro; stop verification: Place Details Enterprise per stop; routing: one
Compute Routes per leg; selections: Autocomplete + Place Details
Essentials/Pro). Autocomplete counts depend on typing and debounce.

| # | Test | Autocomplete | PD Essentials | PD Pro | PD Enterprise | Compute Routes | Dynamic Maps |
|---|------|-------------:|--------------:|-------:|--------------:|---------------:|-------------:|
| L1 | Load page, map renders under CSP, no console violations | – | – | – | – | – | 1 |
| L2 | Select city + 4 stops via suggestions | 10–20 | 4 | 1 | – | – | – |
| L3 | Plan with the first 3 stops; watch progress stream incrementally (DevTools) | – | – | 1 | 3 | 2 | (reload) 1 |
| L4 | "Refresh from here" on the second leg | – | – | 1 | 2 | 1 | – |
| L5 | Plan all 4 stops in a deliberately inefficient order, then Compare | – | – | 2 | 8 | 3 + ≤6 | – |
| L6 | Compare again and press Cancel after the first progress event; check metrics shows `cancelled` and no further calls | – | – | ≤1 | ≤4 | ≤6 | – |
| L7 | Final walking times: for L3/L5 legs compare the shown arrival with Google Maps for the same departure; check metrics for `arrival_unknown` | – | – | – | – | – | – |
| | **Total (upper)** | **≤20** | **4** | **≤6** | **≤17** | **≤18** | **≤3** |

About 65 billable events in total, all well below the app's own daily
provider budget (2,000) and the per-scope request limits. **This does not
mean zero charges**: the project's existing usage this month is unknown,
other apps on the same billing account count toward the same per-SKU caps,
and abandoned autocomplete sessions bill per request. Check the billing
report before and 24–48 h after the test.

Optional (adds calls; run only if L6 is inconclusive): close the tab mid
comparison instead of Cancel (≤1 Pro, ≤4 Enterprise, ≤6 Routes).

L7 has a limit: the app does not log raw Routes responses (by design), so
the walking-step `staticDuration` is checked indirectly (arrival present,
plausible against Google Maps, no `arrival_unknown`). A raw-response check
would need a staging-only debug tool, which does not exist and is not
proposed.

---

## 8. Production verification checklist (execution order)

"0 calls" items make no Google calls.

**After Step 2 (backend)**
- [ ] (0 calls) `curl -s https://<backend>/healthz` → `{"status":"ok","version":"0.1.0"}`
- [ ] (0 calls) `curl -sI http://<backend>/healthz` → redirect to HTTPS
- [ ] (0 calls) headers on `/healthz` and on a rejected v2 plan (past
      departure): `cache-control: no-store`, `nosniff`, `DENY`, CSP
      `default-src 'none'`
- [ ] (0 calls) CORS preflight: allowed origin echoed; another origin not
- [ ] (0 calls) Railway logs: startup line present; a rejected plan logs one
      metrics JSON line with `"calls": {}`; no uvicorn access lines; no IPs
- [ ] (0 calls) Redis: limits survive a backend redeploy (same window);
      `maxmemory-policy` noeviction or volatile-*; then briefly stop Redis →
      v2 endpoints return 503 `usage_control_unavailable`, restart Redis
- [ ] (0 calls) rate limit: 11 rejected plan requests within one minute →
      11th is 429 (verified locally; note: with D-1 unresolved this blocks
      everyone for that minute). Check the 429 log line contains no IP (D-9)
- [ ] (0 calls) spoofed `X-Forwarded-For` / `X-Real-IP` from a client does
      not create a separate bucket

**After Step 3 (frontend)**
- [ ] (0 calls) HTTP → HTTPS 308; HSTS present (Vercel default); CSP nonce
      differs per response; no `unsafe-eval` in production
- [ ] (0 calls) `curl` the built JS for the server key prefix → absent
      (CI already checks the build)
- [ ] Map loads on the production domain; blocked on another origin
      (referrer restriction) — 1 map load each

**Live test (§7)** — streaming incremental, terminal event on every run,
refresh/compare semantics, cancellation, final walk.

**Afterwards**
- [ ] Billing report: SKUs and counts match §7's estimate (identifies the
      Compute Routes tier)
- [ ] Record Railway plan and log retention; Vercel runtime log retention
- [ ] Mark items in PRODUCTION_VERIFICATION.md with date and evidence

Ongoing health: Railway's healthcheck runs only at deploy time. An external
uptime monitor on `/healthz` (zero Google calls) is recommended but not
selected here.

---

## 9. Rollback and emergency stop

| Situation | Action |
|-----------|--------|
| Bad backend deploy (not the first) | Railway → Deployments → previous deployment → ⋮ → Rollback (restores image **and** variables; only within the plan's deployment retention) |
| Bad frontend deploy | `vercel rollback` (Hobby: previous production deployment only), later `vercel promote <deployment>` to restore auto-assignment |
| First deployment is bad (nothing to roll back to) | remove the public Railway domain or `railway down` (removes latest deployment); Vercel: remove the production domain assignment or `vercel rollback` is unavailable — delete the deployment |
| Unexpected Google usage / key exposure | Google Cloud: set Places API (New) and Routes API daily quotas to 0 (immediate stop), then restrict or rotate the server key; budget alerts do **not** stop spend |
| Redis outage | app fails closed (503) — no provider calls; restore Redis, no data migration needed |
| Abuse with D-1 unresolved | lower quotas; Vercel/Railway WAF/IP blocks are limited on Hobby |

Variable changes on Vercel are **not** rolled back by Instant Rollback; on
Railway they are. Record every variable change with date.

---

## 10. Summary: verified, missing, deploy-only

**Verified (repo/local):** Dockerfile non-root + health (CI and locally),
no access log, production startup validation (key, Redis, HTTPS origins,
proxy settings), CORS shape, security headers on JSON and stream endpoints,
nonce CSP, server key not bundled (CI), Redis fail-closed and shared limits
(CI Redis service), 60 s deadline, metrics without personal data.

**Verified (provider docs):** Railway streaming/request limits, X-Real-IP
header, HTTPS redirect, healthcheck behaviour, log retention per plan,
volume ownership/replica limits, static IPs Pro-only, private network
encryption; Vercel HTTPS/HSTS defaults, rollback limits, Hobby
non-commercial; Google key restriction guidance, Autocomplete session
billing, free caps per SKU.

**Missing configuration:** Railway project/services/variables/healthcheck
path; Vercel project/env vars; both Google keys and their restrictions;
quotas and budget alerts; Map ID (if D-5); railway config-as-code (optional).

**Deployment-only:** no buffering at Railway's edge, disconnect propagation,
live CSP map, actual HTTPS/HSTS headers, client identity behaviour, Redis
eviction/persistence, live walking-step durations, billing SKU mapping,
actual log retention.

**Defect found and fixed locally:** 429 log line contained the client key/IP (D-9).

**Deferred:** monthly free-tier enforcement (blocks a free-tier-safe public
release); legacy endpoint retirement; D36 selection limits; D46 permitted use
of comparison outcomes; `braces` exception (expires 2026-11-04).

---

## Sources (checked 2026-10-06)

- Railway: [Specs & limits](https://docs.railway.com/networking/public-networking/specs-and-limits),
  [Healthchecks](https://docs.railway.com/reference/healthchecks),
  [Volumes](https://docs.railway.com/reference/volumes),
  [Static outbound IPs](https://docs.railway.com/reference/static-outbound-ips),
  [Private networking](https://docs.railway.com/networking/private-networking/how-it-works),
  [Logging](https://docs.railway.com/reference/logging),
  [Deployment actions](https://docs.railway.com/guides/deployment-actions),
  [CLI](https://docs.railway.com/reference/cli-api);
  staff answers on client-IP headers:
  [2026-05](https://station.railway.com/questions/need-authoritative-railway-client-ip-p-b7a7b4bd),
  [2024-08](https://station.railway.com/questions/edge-proxy-x-forwarded-for-and-x-real-ip-c5a50049).
- Vercel: [Encryption/HSTS](https://vercel.com/docs/cdn-security/encryption),
  [Instant Rollback](https://vercel.com/docs/instant-rollback),
  [vercel rollback](https://vercel.com/docs/cli/rollback),
  [Hobby plan](https://vercel.com/docs/plans/hobby).
- Google: [API security best practices](https://developers.google.com/maps/api-security-best-practices),
  [Places session pricing](https://developers.google.com/maps/documentation/places/web-service/session-pricing),
  [Pricing](https://developers.google.com/maps/billing-and-pricing/pricing),
  [Routes usage and billing](https://developers.google.com/maps/documentation/routes/usage-and-billing),
  [Map IDs](https://developers.google.com/maps/documentation/javascript/map-ids/mapid-over).
