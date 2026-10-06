# Production verification checklist

Prepared 2026-10-06 (Step 9). Execution order, commands and the live test
plan: [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md). Nothing in this file has been verified: every
item needs the real deployment (Railway backend, Vercel frontend) or live
Google calls, and neither was authorised during development. Local tests use
mocked providers and cannot prove these settings. Record the date, operator
and evidence (screenshot, log excerpt or command output) for each item.

Status key: `[ ]` not verified · `[x]` verified (with evidence) · `[!]` failed.

## 0. Preconditions

- [ ] Deploy only after product approval (D49) — this checklist does not
      authorise a deployment.
- [ ] Use a separate, low-quota Google project or the production project with
      tight quotas; live checks below cost a small number of billed calls.
- [ ] Monthly free-tier enforcement is still deferred: confirm Google Cloud
      quotas and budget alerts are in place before any live call.

## 1. Streaming (planning, refresh, comparison)

Each operation streams NDJSON for up to 60 s.

- [ ] **No buffering:** `curl -N -X POST https://<backend>/api/v2/plan/stream
      -H 'content-type: application/json' -d @plan.json` prints
      `operation_start` immediately and later events incrementally (not all at
      the end). Repeat for `/api/v2/refresh/stream` and `/api/v2/compare/stream`.
- [ ] **60 s supported:** with a 12-stop comparison (or an artificially slow
      provider in staging), the connection stays open until the terminal
      event; no proxy/edge timeout below 60 s (Railway, Vercel rewrites if
      used, any CDN). Record the actual idle/request timeouts.
- [ ] **Terminal events arrive:** every run ends with exactly one `terminal`
      event; a proxy-closed stream shows "didn't finish" in the UI (never a
      silent success).
- [ ] **Headers on streams:** `content-type: application/x-ndjson`,
      `cache-control: no-store`, `x-accel-buffering: no`, CSP/nosniff/DENY.
- [ ] Do not change the 60 s deadline to fit infrastructure; report any
      incompatibility.

## 2. Disconnect propagation

- [ ] Start a comparison, then Cancel in the browser (or kill `curl` mid
      stream). Backend metrics line shows `"outcome": "cancelled"` and no
      further `routes_compute` calls are counted after the cancel.
- [ ] Repeat by closing the browser tab; confirm the same.
- [ ] Confirm the admission slot is released (subsequent requests are not
      refused with `capacity_exceeded`).

## 3. Google walking-step durations (final walk)

Arrival = last ride's scheduled arrival + `staticDuration` of later steps;
if missing the leg fails as `arrival_unknown` (no invented time).

- [ ] With live keys, plan several real transit journeys (city centre and
      suburban). Inspect raw Routes responses in a staging-only debug session
      (never in production logs): WALK steps after the last TRANSIT step carry
      `staticDuration`.
- [ ] Count `arrival_unknown` failures in metrics over a sample; if
      non-trivial, report before release (do not add invented durations).
- [ ] Check that arrival times shown match Google Maps' arrival for the same
      departure within a minute or two.

## 4. API-key restrictions

- [ ] Two keys exist. Browser key: HTTP-referrer restricted to the production
      frontend origin(s); API-restricted to Maps JavaScript API.
- [ ] Server key: API-restricted to Places API (New) (covers Autocomplete and
      Place Details) and Routes API; application-restricted to Railway's
      static egress IPs where available.
- [ ] Server key absent from the frontend bundle (CI `security:bundle`) and
      from Vercel environment variables.
- [ ] Old/exposed keys rotated and deleted.
- [ ] Quotas: Places API (New) and Routes API daily caps set; budget alerts at
      50/90/100%.

## 5. Live map under the production CSP

- [ ] Load the production frontend with the real browser key: map tiles,
      markers and transit layer render; no CSP violations in the console
      (`securitypolicyviolation` events) and no blocked Google resources.
- [ ] Script policy has no `unsafe-inline`/`unsafe-eval`; nonce differs per
      response.

## 6. HTTPS and proxy configuration

- [ ] HTTP → HTTPS redirect on both domains.
- [ ] After verification, `HSTS_ENABLED=true` (backend) and
      `SECURITY_HSTS_ENABLED=true` (frontend); response carries
      `strict-transport-security: max-age=31536000`.
- [ ] `TRUSTED_PROXY_IPS` set to the verified Railway ingress peers/CIDRs
      (not empty, not `/0`); `TRUSTED_PROXY_COUNT` unset. From two different
      client IPs, confirm separate rate-limit counters; a spoofed
      `X-Forwarded-For` from outside does not change the identity.
- [ ] Direct access bypassing the ingress is blocked.
- [ ] `ALLOWED_ORIGINS` lists only the HTTPS frontend origin(s).
- [ ] `APP_ENV=production`; startup refuses memory storage.

## 7. Shared Redis

- [ ] `RATE_LIMIT_STORAGE_URI` uses `rediss://` to a private instance shared
      by every replica; no eviction/flush of limit keys.
- [ ] Run the shared-store tests against a disposable database in the
      deployment network (they flush their database — never production):
      `SECURITY_TEST_REDIS_URL=... python -m pytest tests/test_security_redis.py`.
- [ ] Redis outage → API responds 503 `usage_control_unavailable`, no Google
      calls are made (check metrics `calls`).

## 8. Logs and retention

- [ ] Confirm the Railway plan and its log retention (docs: Hobby 7 days,
      Pro 30, Enterprise up to 90) and record the actual value here.
- [ ] Metrics lines appear as parsed JSON attributes; spot-check that none
      contains place names, coordinates, dates, IPs or operation IDs.
- [ ] Railway HTTP logs include client IPs (`@srcIp`): confirm who can access
      project logs and that the privacy policy covers this.
- [ ] Application logs contain no uvicorn access lines (`--no-access-log`).

## 9. Container and storage

- [ ] On Railway: container runs as non-root; `/healthz` returns
      `{"status":"ok",...}` through the public URL. (Verified locally only —
      see below.)
- [ ] SQLite cache on a private encrypted volume; backups restricted; legacy
      rich cache migration ran (no `geocache` table remains).

## Locally verified (for reference, not production evidence)

Backend tests with mocked providers (427 passed with a disposable local
Redis, including the 4 shared-store tests), frontend unit (88) and browser (31)
tests, security smoke (CSP/headers/hydration without a Maps key), bundle
key-exposure check, dependency audits. See IMPLEMENTATION_PROGRESS.md.

Local container check (2026-10-06, image built from HEAD — app code
hashes matched the repo; run on an unused port 127.0.0.1:18765 because
8000–8002/8080 are used by local processes): runs as `uid=1000(app)`,
uvicorn is PID 1 with `--no-access-log`; `/healthz` → 200
`{"status":"ok","version":"0.1.0"}`; a rejected v2 plan (past departure,
zero provider calls) produced its metrics line in that container's log and
the port refused connections once the container was removed; application
logs contained no client IP (the spoofed `X-Forwarded-For` and the Docker
peer `172.17.0.1` were absent; only uvicorn's `0.0.0.0` bind address).
Scope: health and rejected-plan requests only. A rate-limited request
(429) logs slowapi's warning with the client key — the client IP in
production (found 2026-10-06; DEPLOYMENT_PLAN.md D-9). Fixed: the slowapi
logger filter removes it; regression test `tests/test_ratelimit_logging.py`.
Re-check the 429 log line on Railway.
