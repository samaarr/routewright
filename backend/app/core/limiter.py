"""Per-IP rate limiter shared across routers.

Trusts X-Forwarded-For from Railway's proxy layer. The first IP in the
chain is the real client; subsequent hops are infra-controlled.

KNOWN LIMITATION: state is in-memory. A multi-replica deployment would
need Redis as the storage backend (slowapi supports it via limits[redis]).
"""

from fastapi import Request
from slowapi import Limiter


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_ip)
