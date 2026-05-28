"""Per-IP rate limiter shared across routers.

Trusts X-Forwarded-For from Railway's proxy layer. The first IP in the
chain is the real client; subsequent hops are infra-controlled.

Whitelisted IPs (RATE_LIMIT_WHITELIST_IPS env var) bypass the limit via
a UUID bucket key — each request gets a fresh bucket so the counter never
accumulates. slowapi 0.1.9 has no exempt_when hook; this is the workaround.

KNOWN LIMITATION: state is in-memory. A multi-replica deployment would
need Redis as the storage backend (slowapi supports it via limits[redis]).
"""

from uuid import uuid4

from fastapi import Request
from slowapi import Limiter

from app.core.config import settings


def _whitelist() -> frozenset[str]:
    raw = settings.rate_limit_whitelist_ips
    return frozenset(ip.strip() for ip in raw.split(",") if ip.strip())


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    ip = (
        forwarded_for.split(",")[0].strip()
        if forwarded_for
        else (request.client.host if request.client else "unknown")
    )
    if ip in _whitelist():
        return f"__exempt__{uuid4()}"
    return ip


limiter = Limiter(key_func=_client_ip)
