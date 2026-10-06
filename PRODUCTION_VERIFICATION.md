# Production verification checklist

Prepared 2026-10-06 (Step 9); revised after the owner's approvals the same
day. Execution order, commands and the live test plan:
[DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md).

**Nothing below is verified in production.** Every item needs the real
deployment or live Google calls, and neither has been authorised. Local
tests use mocked providers; they do not establish Railway (or other host)
proxy behaviour, production key restrictions or the completeness of real
Google responses. Record the date, operator and evidence (screenshot, log
excerpt or command output) for each item.

Status key: `[ ]` not verified · `[x]` verified (with evidence) · `[!]` failed.
"0 calls" marks checks that make no Google calls.

## 0. Preconditions

- [ ] Deployment, push, hosting changes, key creation and the live test are
      approved (DEPLOYMENT_PLAN.md §14) — this checklist authorises nothing.
- [ ] A4 satisfied: the backend has a verified static egress IP (§4 below);
      otherwise stop.
- [ ] This month's Google usage recorded **per SKU across the billing
      account**; temporary low daily quotas set on Places API (New) and
      Routes API; budget alerts set. Quotas and alerts do not guarantee zero
      charges; monthly free-tier enforcement is deferred.

## 1. Existing deployment (found 2026-10-06 by public probe)

- [ ] Ownership of `routewright.vercel.app` and the Railway project
      `routewright-production.up.railway.app` confirmed in the dashboards.
- [ ] The browser key embedded in the live bundle: restrictions checked
      (Websites + Maps JavaScript API only). Status today: UNKNOWN.
- [ ] Old Railway service: cause of the current `502 Application failed to
      respond` noted; if replaced, its domain removed and the service and any
      volume deleted after checking contents (may hold the legacy rich
      cache). Not to be restarted with the old v1 code.

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

- [ ] Egress IP(s) read from the host (Railway Settings → Networking, or
      `fly ips list`) and recorded; note whether shared with other customers.
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
- [ ] If D-1 implemented: `RAILWAY_TCP_PROXY_DOMAIN` absent (startup would
      refuse); project contains only the backend; forged `X-Real-IP` and
      `X-Forwarded-For` from a client do not create a new bucket; two networks
      get separate buckets; metrics `client_ip_source` mostly `header`.
- [ ] If D-1 not implemented: all visitors share one bucket — acceptable only
      for the closed live test.
- [ ] (0 calls) 11 rejected plans within a minute → 11th is 429 with
      `Retry-After`; the 429 log line contains no IP.

## 7. Redis (A2)

- [ ] `RATE_LIMIT_STORAGE_URI` is `rediss://` (provider per approval), used
      only by RouteWright; certificate and hostname verified (startup passes
      without weakening options).
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
- Earlier the same day: container check on a locally built image (non-root
  uid 1000, `/healthz` 200, request reached the intended container, no client
  IPs for health/rejected-plan requests). The image has not been rebuilt with
  `--ws none`; CI's container job will.
