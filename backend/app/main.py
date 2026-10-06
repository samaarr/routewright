"""FastAPI entry point with fail-closed production configuration."""

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from ipaddress import ip_network
from urllib.parse import parse_qsl, urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core import logredact
from app.core.config import settings
from app.core.limiter import limiter
from app.core.provider_semaphore import reset_gates
from app.core.security import SecurityMiddleware
from app.routers import health, plan_v2, selection
from app.services.geocache import purge_expired

logging.basicConfig(level=settings.log_level)
logging.getLogger("httpx").setLevel(logging.WARNING)
# uvicorn logs WebSocket handshakes with the client address on uvicorn.error
# (not the access log); the container also runs with --ws none.
logredact.install("uvicorn", "uvicorn.error")
log = logging.getLogger("routewright")


# Query options redis-py accepts that would weaken certificate verification.
_WEAK_TLS_OPTIONS = {
    "ssl_cert_reqs": {"none", "optional", "cert_none", "cert_optional", "0", "1"},
    "ssl_check_hostname": {"false", "0", "no", "off"},
}


def _require_verified_tls(uri: str) -> None:
    """Production Redis must use TLS with certificate and hostname checks (approved
    2026-10-06; no plaintext exception). Messages never include the URI, which
    carries the Redis password."""
    parsed = urlsplit(uri)
    if parsed.scheme != "rediss":
        raise RuntimeError("Production Redis must use TLS (rediss://)")
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if value.strip().lower() in _WEAK_TLS_OPTIONS.get(key.lower(), set()):
            raise RuntimeError("Production Redis TLS must verify the certificate and hostname")


def validate_production() -> None:
    for value in settings.trusted_proxy_ips.split(","):
        if value.strip():
            network = ip_network(value.strip())
            if network.prefixlen == 0:
                raise RuntimeError("Trusting all proxy addresses is prohibited")
    if settings.trusted_proxy_count:
        raise RuntimeError("TRUSTED_PROXY_COUNT is obsolete; configure TRUSTED_PROXY_IPS")
    if settings.app_env != "production":
        return
    if not settings.google_maps_api_key.strip():
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required")
    if not settings.rate_limit_storage_uri.startswith(("redis://", "rediss://")):
        raise RuntimeError("Production requires shared Redis usage controls")
    _require_verified_tls(settings.rate_limit_storage_uri)
    for origin in settings.cors_origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or "*" in parsed.hostname
            or parsed.query
            or parsed.fragment
            or parsed.hostname in {"localhost", "127.0.0.1"}
            or parsed.path not in {"", "/"}
            or parsed.username
            or parsed.password
        ):
            raise RuntimeError("Production ALLOWED_ORIGINS must contain HTTPS origins")
    if not settings.cors_origins:
        raise RuntimeError("Production ALLOWED_ORIGINS is required")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_production()
    reset_gates()
    if settings.app_env == "production" and not await asyncio.to_thread(limiter._storage.check):
        raise RuntimeError("Usage-control storage unavailable")

    async def cleanup() -> None:
        while True:
            await purge_expired(settings.cache_db_path, settings.cache_ttl_days)
            await asyncio.sleep(settings.cache_cleanup_seconds)

    await purge_expired(settings.cache_db_path, settings.cache_ttl_days)
    task = asyncio.create_task(cleanup())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="RouteWright API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After", "X-Request-ID"],
    allow_credentials=False,
)
app.add_middleware(SecurityMiddleware)
for router in (
    health.router,
    plan_v2.router,
    selection.router,
):
    app.include_router(router)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry = int(exc.limit.limit.get_expiry()) if exc.limit else 60
    current = getattr(request.state, "view_rate_limit", None)
    if current:
        window = limiter.limiter.get_window_stats(current[0], *current[1])
        retry = max(1, math.ceil(window.reset_time - time.time()))
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry)},
        content={"error": "rate_limit_exceeded", "detail": "Too many requests"},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Controlled messages and locations; unknown JSON keys may themselves be sensitive.
    errors = []
    for error in exc.errors():
        loc = list(error.get("loc", []))
        if error.get("type") == "extra_forbidden" and loc:
            loc[-1] = "extra_field"
        errors.append(
            {
                "loc": loc,
                "msg": "Invalid or missing field",
                "type": error.get("type", "validation_error"),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "detail": "Check the indicated fields",
            "errors": errors,
        },
    )
