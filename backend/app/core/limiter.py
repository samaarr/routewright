"""Client identity is derived only through explicitly trusted proxy networks."""

import logging
from ipaddress import ip_address, ip_network
from typing import Any, cast

from fastapi import Request
from slowapi import Limiter

from app.core.config import settings
from app.core.logredact import redact_addresses


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    try:
        networks = [
            ip_network(v.strip()) for v in settings.trusted_proxy_ips.split(",") if v.strip()
        ]
        address = ip_address(peer)
        if not any(address in network for network in networks):
            return str(address)
        values = request.headers.get("x-forwarded-for", "").split(",")
        if len(values) > 16:
            return peer
        chain = [ip_address(value.strip()) for value in values] + [address]
        for hop in reversed(chain):
            if not any(hop in network for network in networks):
                return str(hop)
    except ValueError:
        pass
    return peer


def request_cost(request: Request) -> int:
    """Stable exempt identity; no fresh UUID counters per request."""
    whitelist = {v.strip() for v in settings.rate_limit_whitelist_ips.split(",") if v.strip()}
    return 0 if _client_ip(request) in whitelist else 1


_EXCEEDED = "ratelimit %s (%s) exceeded at endpoint: %s"


class _ClientKeyFilter(logging.Filter):
    """Keep client identities out of slowapi's log records (D-9).

    slowapi logs the limiter key (the client IP) when a limit is exceeded;
    that argument is dropped. Any other slowapi record is rendered and has
    IP-address tokens redacted, in case a future version logs the key elsewhere.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == _EXCEEDED and isinstance(record.args, tuple) and len(record.args) == 3:
            record.msg = "ratelimit %s exceeded at endpoint: %s"
            record.args = (record.args[0], record.args[2])
        else:
            record.msg = redact_addresses(record.getMessage())
            record.args = None
        return True


logging.getLogger("slowapi").addFilter(_ClientKeyFilter())

limiter = Limiter(
    key_func=_client_ip,
    storage_uri=settings.rate_limit_storage_uri,
    storage_options=cast(
        Any,
        (
            {"socket_connect_timeout": 2, "socket_timeout": 2}
            if settings.rate_limit_storage_uri.startswith(("redis://", "rediss://"))
            else {}
        ),
    ),
)
PLAN_LIMITS = (
    f"{settings.max_requests_per_ip_per_day}/day;{settings.max_requests_per_ip_per_minute}/minute"
)
REFRESH_LIMITS = PLAN_LIMITS
# D36: one combined per-IP allowance for city and place suggestion searches,
# including manual Search. Selection lookups use the same bucket until their
# own limits are specified (open decision, see IMPLEMENTATION_PROGRESS.md).
SELECTION_SEARCH_LIMITS = "30/minute;100/day"
SELECTION_SEARCH_SCOPE = "selection-search"
OPTIMISE_LIMITS = PLAN_LIMITS
