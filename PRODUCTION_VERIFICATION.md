# Production verification checklist

Prepared 2026-10-06 (Step 9); revised after the owner's approvals the same
day. Hosting is fixed to Railway (backend) and Vercel (frontend). Execution order, commands and the live test plan:
[DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md).

**Nothing below is verified in production.** Every item needs the real
deployment or live Google calls, and neither has been authorised. Local
tests use mocked providers; they do not establish Railway (or other host)
proxy behaviour, production key restrictions or the completeness of real
Google responses. Record the date, operator and evidence (screenshot, log
excerpt or command output) for each item.

Status key: `[ ]` not verified · `[x]` verified (with evidence) · `[!]` failed.
"0 calls" marks checks that make no Google calls.

## Live results — release R1 (2026-10-07)

Release pair in DEPLOYMENT_PLAN.md §0. One live pass (headless Chromium
against production, Dublin, Fri 2026-10-09 10:00, transit, 4 stops), plus
zero-call checks with curl.

### Verified in production [x]
- [x] **Connected app:** `https://routewright.vercel.app` → backend
      `https://routewright-production.up.railway.app` (CSP `connect-src` and
      bundle name exactly that origin). `/healthz` 200 `{"status":"ok"}`.
- [x] **Selection:** city "Dublin, Ireland" → "Times use Dublin local time
      (Europe/Dublin)"; four explicit selections (Trinity College, Kilmainham
      Gaol, National Gallery of Ireland, Guinness Storehouse).
- [x] **Planning stream:** progress arrived incrementally ("Checking your
      places…" 33 ms → "Planned 0/1/2 of 3 journeys…" at 0.8/1.1/1.3 s);
      sequential times 10:00 → 10:34 → leave 12:04 → 12:42 → leave 13:57 →
      14:32; legs show journey time including waiting and Google travel time
      (e.g. "35 min including waiting (Google travel time: 31 min)").
- [x] **Final walking steps:** every leg produced an arrival; no
      `arrival_unknown` in metrics (indirect evidence — raw Routes responses
      are not logged).
- [x] **Opening hours shown:** "Open until 17:15 · hours for this date" etc.;
      Trinity College "Opening hours unavailable" (Google returned none).
- [x] **Refresh:** from the last leg, request `leg_index 2`,
      `planned_departure 2026-10-09T12:57:47Z` (= 13:57 Dublin, the planned
      departure, not "now"); earlier legs unchanged; metrics `complete`,
      1 route call.
- [x] **Comparison:** one alternative checked plus the original recalculated
      (6 route calls = 2(N−1)); outcome "Estimated journey-time saving:
      40 min."; **Use this order** applied the new order (Trinity → National
      Gallery → Kilmainham → Guinness, consistent times) with **0 API requests**.
- [x] **Cancel:** notice "Planning cancelled…"; backend metrics
      `outcome=cancelled`, 0 provider calls; previous plan unchanged 3 s later.
- [x] **Map under production CSP:** Maps JS 200, 13 tiles, `.gm-style` present,
      transit layer visible; no `securitypolicyviolation`, no console errors,
      no Google Maps key/referrer errors on `routewright.vercel.app`.
- [x] **Layouts:** desktop (1280 px, map/plan tabs) and mobile (390 px; no
      horizontal overflow) screenshots reviewed.
- [x] **HTTPS/headers:** backend `http://` → 301 HTTPS; API responses
      `no-store`, CSP `default-src 'none'; frame-ancestors 'none'`, `nosniff`,
      `DENY`; frontend HSTS `max-age=63072000; includeSubDomains; preload`,
      nonce CSP, `nosniff`, `DENY`, referrer and permissions policies.
- [x] **CORS:** allowed only for `https://routewright.vercel.app`; other origin
      → 400 without allow-origin.
- [x] **Retired routes:** `/api/plan`, `/api/optimise`, `/api/refresh-leg` → 404
      (GET and JSON POST).
- [x] **Trusted ingress / forged headers:** 11 rejected plans with different
      forged `X-Real-IP`, `X-Forwarded-For` and `X-Railway-Edge` → one bucket,
      11th = 429 with `Retry-After`; all metrics `client_ip_source="header"`.
- [x] **Shared rate limits in TLS Redis:** read-only check over verified TLS
      (`SSLConnection`, cert required): limit keys are
      `LIMITS:LIMITER/<hmac32>/…` plus `provider-global`; **no key contains an
      IP**.
- [x] **Safe logs:** application log for the deployment contains no client IP
      (only uvicorn's `0.0.0.0` bind address), no access lines.
- [x] **Server key** absent from Vercel env and from all 7 production JS chunks
      (compared in-process, value never printed); one key-shaped string in the
      bundle = the browser key.
- [x] **Volume removed; region EU West** (`europe-west4-drams3a`), next to
      Upstash eu-west-1.

### Live provider calls (from backend metrics; browser map loads separate)
| Category | Calls |
|----------|------:|
| Autocomplete | 5 |
| Place Details Essentials | 4 |
| Place Details Pro | 4 |
| Place Details Enterprise | 10 |
| Compute Routes | 10 |
| **Backend total** | **33** |
| Dynamic Maps (browser loads) | 2 |

No quota errors. Google billing reports lag; no zero-charge claim.

### Not verified live [ ]
- [ ] Opening-hours **warnings** and **partial failures** (none occurred on
      this trip; covered by mocked tests only).
- [ ] Cancellation **during** provider calls and late-event rejection after a
      cancel (this cancel landed before the first call); mocked tests only.
- [ ] Redis-outage fail-closed in production (not induced; verified locally).
- [ ] Runtime `id` inside the Railway container (`railway ssh` needs an
      account SSH key); non-root rests on the Dockerfile build.
- [ ] Production Map ID: the configured value is a sensitive Vercel variable
      and was not read; the map works with it.
- [ ] Actual log retention (Railway Hobby documents 7 days; plan not
      re-confirmed) and Upstash command usage (no console access).
- [ ] Billing-report confirmation of SKU mapping for the 35 events above.

## 0. Preconditions

- [ ] Deployment, push, hosting changes, key creation and the live test are
      approved (DEPLOYMENT_PLAN.md §14) — this checklist authorises nothing.
- [ ] A4 satisfied: Railway Pro active and Static Outbound IPs enabled on the
      backend service (§4 below); otherwise stop — deployment is blocked.
- [ ] This month's Google usage recorded **per SKU across the billing
      account**; temporary low daily quotas set on Places API (New) and
      Routes API; budget alerts set. Quotas and alerts do not guarantee zero
      charges; monthly free-tier enforcement is deferred.

## 1. Existing deployment (found 2026-10-06 by public probe)

- [ ] Ownership of `routewright.vercel.app` and the Railway project
      `routewright-production.up.railway.app` confirmed in the dashboards.
- [ ] The browser key embedded in the live bundle: restrictions checked
      (Websites + Maps JavaScript API only). Status today: UNKNOWN.
- [ ] Railway service: cause of the current `502 Application failed to
      respond` identified from deploy logs/status (DEPLOYMENT_PLAN.md §3);
      any volume checked and deleted (may hold the legacy rich cache); never
      rolled back or restarted with the old v1 code.

## 2. Backend basics (0 calls)

- [ ] `GET /healthz` → `{"status":"ok","version":"0.1.0"}` via the public URL.
- [ ] Startup log shows no validation error; production refused to start with
      a plaintext or unverified Redis URL during setup (if tried).
- [ ] Retired routes: `POST`/`GET` `/api/plan`, `/api/optimise`,
      `/api/refresh-leg` → 404 on the live backend.
- [ ] Headers on `/healthz` and a rejected v2 plan: `cache-control: no-store`,
      `nosniff`, `DENY`, CSP `default-src 'none'; frame-ancestors 'none'`.
- [ ] CORS: preflight from `https://routewright.vercel.app` allowed; from any
      other origin not allowed.
- [ ] Container user is non-root (image `USER app`; `RAILWAY_RUN_UID` unset
      on Railway); uvicorn runs with `--ws none` (an Upgrade request gets 405).

- [ ] Release pair recorded: Railway deployment ID, Vercel deployment URL, git
      SHA, variable names and non-secret values (rollback needs it;
      DEPLOYMENT_PLAN.md §13).

## 3. Streaming and disconnects

- [ ] **No buffering:** progress events arrive incrementally for plan,
      refresh and compare streams (DevTools or `curl -N`).
- [ ] **60 s supported:** no proxy/edge timeout below 60 s; record the host's
      actual limits. Do not change the deadline to fit infrastructure.
- [ ] Every run ends with exactly one `terminal` event; a closed stream shows
      "didn't finish" (never a silent success).
- [ ] Stream headers: `application/x-ndjson`, `no-store`,
      `x-accel-buffering: no`, CSP/nosniff/DENY.
- [ ] Cancel and tab-close during a comparison: metrics show
      `"outcome": "cancelled"`, no later `routes_compute` calls; capacity freed.

## 4. Keys and egress (A4)

- [ ] Static outbound IPv4 address(es) read from Railway (Settings →
      Networking or `railway outbound-network static-ip status`) after the
      redeploy and recorded; Railway states they may be shared with other
      customers.
- [ ] First live server call succeeds from those IPs (no IPv6 egress
      mismatch).
- [ ] Server key: API restrictions Places API (New) + Routes API only;
      application restriction = exactly those IPs.
- [ ] Browser key: Websites `https://routewright.vercel.app/*` only; Maps
      JavaScript API only.
- [ ] Server key absent from Vercel env vars and from the deployed bundle
      (`curl` the JS chunks for the server key's prefix).
- [ ] A request from a non-allowed IP with the server key is rejected by
      Google (only if approved as part of the live test; costs nothing if
      rejected, but is a live call).

## 5. Map under the production CSP

- [ ] Map, markers and transit layer render; no `securitypolicyviolation`
      events; nonce differs per response; no `unsafe-eval` in production.
- [ ] Map ID in use is the approved production ID (or `DEMO_MAP_ID` if D-5 is
      declined).
- [ ] Map does not load on another origin (referrer restriction).

## 6. HTTPS, HSTS and client identity

- [ ] HTTP → HTTPS redirect on both origins (Railway 301 and Vercel 308
      observed today for the existing names — re-check after deploy).
- [ ] Frontend HSTS: Vercel default `max-age=63072000` present;
      `SECURITY_HSTS_ENABLED` left false.
- [ ] Backend: after verification set `HSTS_ENABLED=true`; header
      `strict-transport-security: max-age=31536000` present.
- [ ] `TRUSTED_PROXY_IPS` empty, `TRUSTED_PROXY_COUNT` unset.
- [ ] If D-1 implemented: no TCP proxy (startup would refuse); the
      environment contains only the backend; forged `X-Real-IP` and
      `X-Forwarded-For` from a client do not create a new bucket; two networks
      get separate buckets; metrics `client_ip_source` mostly `header`;
      Redis keys contain no raw IP (hashed keys). Re-check after any
      networking change.
- [ ] If D-1 not implemented: all visitors share one bucket — acceptable only
      for the closed live test.
- [ ] (0 calls) 11 rejected plans within a minute → 11th is 429 with
      `Retry-After`; the 429 log line contains no IP.

## 7. Redis (A2)

- [ ] `RATE_LIMIT_STORAGE_URI` is `rediss://` to the approved Upstash
      database (`eu-west-1`), used only by RouteWright; startup passes without
      weakening options; no payment method on the Upstash account (no
      automatic paid upgrade); eviction disabled.
- [ ] Eviction policy does not drop limit keys; limits survive a backend
      redeploy within the same window.
- [ ] (0 calls) Redis unavailable → v2 endpoints return 503
      `usage_control_unavailable`, metrics show no provider calls.
- [ ] Shared-store tests run against a **disposable** database, never
      production (they flush it).
- [ ] Provider usage (commands/month) recorded against its free allowance.

## 8. Google response completeness (live test only)

- [ ] Walking steps after the last transit step carry `staticDuration`
      (indirect: arrivals present and plausible against Google Maps; no
      `arrival_unknown` in metrics). Raw responses are not logged.
- [ ] Billing report after 24–48 h: SKUs and counts match DEPLOYMENT_PLAN.md
      §12; identifies the Compute Routes tier actually billed.

## 9. Logs and retention (A5)

- [ ] Hosting plan and its log retention recorded (Railway docs: Hobby 7 d,
      Pro 30 d; other hosts UNKNOWN).
- [ ] Metrics lines parsed as JSON; none contains names, coordinates, dates,
      IPs, operation IDs or comparison savings.
- [ ] No uvicorn access lines; WebSocket/429 lines contain no IP.
- [ ] Platform HTTP logs (Railway `@srcIp`, path, user agent): who has access
      recorded; privacy notice covers them. No separate archive exists.

## 10. Storage (A1)

- [ ] No volume attached; `RAILWAY_RUN_UID` unset; `CACHE_DB_PATH` default.
- [ ] Place selection works right after a redeploy (empty cache → provider).
- [ ] Host disk encryption at rest for container storage: recorded as
      documented / UNKNOWN (ephemeral storage does not remove this question).

## Locally verified (reference only, not production evidence)

As of 2026-10-06 at HEAD (v1 retired):

- Backend: 403 passed, 4 skipped without Redis; the 4 shared-store tests
  passed against a disposable local `redis:7.4-alpine` (db 15, no
  persistence). ruff, format and mypy clean.
- Retired routes return 404 for GET/POST/PUT/OPTIONS and trailing slashes;
  OpenAPI lists only `/healthz` and `/api/v2/*`.
- Production startup refuses `redis://` and `rediss://` with weakened
  verification, without echoing the password.
- Logging: a real-limiter 429 (IPv4 and IPv6 clients) and a real uvicorn
  WebSocket handshake leave no client IP in any log record; `--ws none`
  checked on a local server (Upgrade → 405, "Unsupported upgrade request.").
- Cache: planning ignores a planted wrong cache entry; selection falls back to
  the provider after the cache is deleted, unreadable or failing.
- Frontend: type-check, lint, unit 88, types drift clean (types regenerated
  without v1 models). Browser e2e (31) last run before the v1 retirement; no
  frontend runtime code changed since.
- Final container (rebuilt from HEAD with `--ws none`) in production mode
  against a TLS-only local Redis: non-root uid 1000, `/healthz` 200, 429 after
  10 rejected plans, Upgrade → 405, retired routes 404, no client/forged/peer
  IPs anywhere in the application log; `redis://` refused at startup.
  Redis over verified TLS: shared-store tests 4/4; plaintext, wrong CA,
  wrong hostname refused. Finding: rate-limit keys in Redis contain raw
  client IPs (proposal: hashed keys, DEPLOYMENT_PLAN.md §8).
