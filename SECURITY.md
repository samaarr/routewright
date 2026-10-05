# Security implementation and deployment

Updated 2026-10-05. These controls protect the current anonymous itinerary planner. It has no accounts, passwords, session cookies, uploads, or private saved itineraries. Account authentication, password hashing, ownership checks, database public keys, and row-level security become required when those features are introduced; SQLite is a server-only place cache today.

## Implemented controls

- Server keys stay in ignored environment files or platform secret storage. Browser code receives only a separate public Maps JavaScript key. Never place a server key in any `NEXT_PUBLIC_*` variable.
- Strict request schemas reject unknown fields, invalid coordinates, blank/oversized strings, dates outside supported bounds, and excessive visit durations. Requests are limited to 12 stops and 16 KiB; chunked requests are counted too. Body reading has a ten-second total deadline and compressed bodies are rejected.
- Default limits are 10 requests/minute and 50/day per endpoint and verified client IP. Forwarded IPs are trusted only when the connection peer and intervening proxy hops are explicitly trusted. Whitelist exemptions cannot be spoofed using an untrusted forwarded header.
- Every actual outbound Places/Routes call consumes a shared daily budget (2,000 by default), including unsuccessful calls. Cached Places hits do not consume this budget. Storage failures block calls. This limits anonymous automation and provider spending; it is not proof of a human user or a dollar-denominated billing cap. Provider console quotas are also required.
- Request admission (20/process), provider concurrency (20/process), provider queue deadlines, and solver concurrency (2/process) bound resource use. Solver work runs off the event loop. Multiple replicas require capacity planning as these concurrency caps are per process.
- SQL uses parameters. Cache query keys are SHA-256 digests; raw search text is no longer a cache key. Legacy plaintext keys and expired rows are deleted at startup and hourly. Cache files use mode 0600. Hashing is not encryption: place names and coordinates remain public-place data and require encrypted platform storage if your privacy policy treats them as sensitive. SQLite deletion is not guaranteed forensic erasure; remove old volumes/backups according to retention policy.
- React renders user content as text. Browser scripts use a fresh CSP nonce per response; production script policy has no unsafe-inline or unsafe-eval. Inline styles remain enabled for Google Maps. Security headers prevent framing and MIME sniffing, restrict referrers, and disable response caching. API docs and schema endpoints are disabled; developers may generate the schema offline with `app.openapi()`.
- API validation responses omit submitted values and unknown field names. Provider bodies/exception text and request payloads are excluded from application logs. Health checks omit environment details. Reverse-proxy/platform logs must follow the same privacy policy.
- Dependencies are updated and locked. Python installs verify package hashes. CI blocks Python vulnerability findings, runtime npm vulnerabilities, and new high/critical frontend development findings. Weekly CI repeats scans. Secret scanning covers full Git history and source files, with findings redacted.

## Required production configuration

1. Provision a private Redis instance; set `RATE_LIMIT_STORAGE_URI` on every backend replica to the same database. Use `rediss://` for remote connections and restrict network access. The backend refuses production startup with memory storage or an unavailable store. Do not evict/flush rate-limit keys during normal operations. Redis connect/read operations have two-second timeouts; add infrastructure health alerts.
2. Set `APP_ENV=production`, `GOOGLE_MAPS_API_KEY`, and `ALLOWED_ORIGINS=https://your-frontend-domain`. Configure only the real HTTPS frontend origins. CORS does not authenticate callers: this API is intentionally public.
3. Configure `TRUSTED_PROXY_IPS` with the actual ingress connection peers/CIDRs. The ingress must replace or safely append `X-Forwarded-For`; block direct access bypassing it. Uvicorn runs with `--no-proxy-headers` so the application sees the actual peer. Leave trust empty until the provider's topology is verified. `TRUSTED_PROXY_COUNT` is obsolete and rejected.
4. Set frontend `NEXT_PUBLIC_API_URL=https://your-backend-domain`. Enforce HTTP-to-HTTPS redirects at the ingress for both domains. After verification enable backend `HSTS_ENABLED=true` and frontend `SECURITY_HSTS_ENABLED=true`. TLS termination belongs to the ingress; the application cannot prove it is enabled from local code.
5. Create separate Google keys. Restrict the browser key by website referrer and Maps JavaScript API; restrict the server key to Places API (New) and Routes API, and server egress IP where supported. Set Google quotas, billing alerts, and a provider budget appropriate to your traffic. Never share keys in chat. Rotate any previously exposed key before rewriting Git history; history cleanup requires coordination with collaborators.
6. Store SQLite on a private encrypted volume; restrict backups and retention. Start the backend with a restrictive umask (Docker does this). Monitor generic failure/capacity metrics without recording locations or submitted queries.

Local checks cannot verify these platform settings or live key restrictions. The browser smoke test uses no Maps key, so live Google Maps loading under CSP remains a deployment check. Docker build and live Redis integration must pass in the deployment environment before release.

## Temporary development dependency exception

`braces@3.0.3` has an unpatched stack-exhaustion advisory [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), inherited by Tailwind/ESLint build tools. It is absent from production runtime dependencies. Repository-controlled glob patterns are the only accepted input to these tools; never pass user patterns to builds. `frontend/scripts/security-audit.mjs` permits only this exact advisory/version on dev-only dependency paths, expires on **2026-11-04**, and fails for new high/critical findings or any runtime finding. Update to a patched dependency when available; do not extend the exception without reassessing exposure.

## Verification commands

From `backend`: install `requirements-dev.lock` with `pip install --require-hashes -r requirements-dev.lock`, then run `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app`, and `python -m pytest -q`.

From `frontend` on Node 22.13+ (22.x) or Node 24+: run `npm ci`, `npm run type-check`, `npm run lint`, `npm run security:audit`, and `NEXT_PUBLIC_API_URL=https://api.routewright.invalid npm run build`. Install Playwright Chromium, then run `npm run security:smoke`. The smoke test checks production CSP/header behavior and hydration without spending Google quota.
