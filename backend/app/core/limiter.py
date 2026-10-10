"""Client identity for rate limiting (trusted proxies, Railway edge) and keying.

Identities are never stored raw: the limiter key is an HMAC of the identity
under LIMITER_KEY_SECRET, so the shared Redis holds no client IPs.
"""

import hashlib
import hmac
import logging
from contextvars import ContextVar
from ipaddress import IPv6Address, ip_address, ip_network
from typing import Any, Literal, cast

from fastapi import Request
from slowapi import Limiter

from app.core.config import settings
from app.core.logredact import redact_addresses

ClientIpSource = Literal[
    "peer", "header", "fallback_missing", "fallback_invalid", "fallback_peer_public"
]
# Aggregate metric only (no address): how the current request's identity was derived.
client_ip_source: ContextVar[ClientIpSource | None] = ContextVar(
    "routewright_client_ip_source", default=None
)

# Non-production fallback so tests/dev never key on raw IPs; production
# requires a real secret (main.validate_production).
_DEV_KEY_SECRET = "routewright-development-only-limiter-key"
_RAILWAY_EDGE_MARKERS = ("x-railway-edge", "x-railway-request-id")


def _trusted_chain_ip(request: Request) -> str:
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


def _railway_ip(request: Request) -> tuple[str, ClientIpSource]:
    """Railway edge identity (DEPLOYMENT_PLAN.md D-1).

    X-Real-IP is written by Railway's HTTP edge. It is used only when every
    condition that holds for edge traffic holds; otherwise the TCP peer is used,
    which puts the request in one shared, stricter bucket. X-Forwarded-For is
    ignored entirely.
    """
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ip_address(peer)
    except ValueError:
        return peer, "fallback_invalid"
    if peer_address.is_global:
        # Edge traffic arrives from Railway's internal network; a public peer
        # means a path that did not come through the edge.
        return peer, "fallback_peer_public"
    values = request.headers.getlist("x-real-ip")
    if not values or not all(request.headers.get(m) for m in _RAILWAY_EDGE_MARKERS):
        return peer, "fallback_missing"
    if len(values) != 1 or values[0] != values[0].strip() or "," in values[0]:
        return peer, "fallback_invalid"
    try:
        client = ip_address(values[0])
    except ValueError:
        return peer, "fallback_invalid"
    if isinstance(client, IPv6Address) and client.ipv4_mapped is not None:
        client = client.ipv4_mapped
    if not client.is_global:
        return peer, "fallback_invalid"
    return str(client), "header"


def _client_ip(request: Request) -> str:
    """Raw client identity (never stored or logged; see limiter_key)."""
    if settings.client_ip_source == "railway":
        identity, source = _railway_ip(request)
    else:
        identity, source = _trusted_chain_ip(request), "peer"
    client_ip_source.set(source)
    return identity


def limiter_key(request: Request) -> str:
    """Rate-limit storage key: HMAC-SHA256 of the identity, never the raw IP."""
    secret = settings.limiter_key_secret or _DEV_KEY_SECRET
    digest = hmac.new(secret.encode(), _client_ip(request).encode(), hashlib.sha256)
    return digest.hexdigest()[:32]


def _tester_addresses() -> set[str]:
    """The configured tester allowlist (RATE_LIMIT_WHITELIST_IPS), normalised.

    Entries that are not single IP addresses are ignored, never widened.
    """
    addresses: set[str] = set()
    for value in settings.rate_limit_whitelist_ips.split(","):
        try:
            addresses.add(str(ip_address(value.strip())))
        except ValueError:
            continue
    return addresses


def is_tester(request: Request) -> bool:
    """Experimental features are limited to the configured tester allowlist.

    Uses the verified client identity (_client_ip: TCP peer, trusted proxy
    chains or the checked Railway edge header — never raw forwarded headers).
    Fails closed: with no tester configured, nobody qualifies.
    """
    testers = _tester_addresses()
    if not testers:
        return False
    try:
        identity = str(ip_address(_client_ip(request)))
    except ValueError:
        return False
    return identity in testers


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
    key_func=limiter_key,
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
