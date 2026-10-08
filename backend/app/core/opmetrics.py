"""Aggregate operational metrics as structured log lines (Step 9, D46).

One JSON line per v2 operation on stdout, which the hosting platform
(Railway) parses into queryable attributes and keeps for its plan's log
retention (Hobby 7 days, Pro 30 days, Enterprise up to 90 days — per
docs.railway.com/reference/logging, checked 2026-10-06). No metrics
database, separate service or archive is used.

Fields (all bounded / low-cardinality):
    event        "operation"
    operation    plan | refresh | compare | compare_exhaustive | suggest_city |
                 suggest_place |
                 select_city | select_place
    transport    json | stream
    outcome      a fixed category (see OUTCOMES)
    failure      a fixed failure category or null (unknown values -> "other")
    elapsed_ms   integer milliseconds
    stop_count   number of stops (2-12) or null
    calls        {provider call kind: count} for calls this operation issued
    client_ip_source  how the rate-limit identity was derived (peer | header |
                 fallback_*), never the address itself; null if not limited

Deliberately excluded: place names/IDs, coordinates, travel dates/times,
IP addresses, operation IDs or any per-trip identifier, plans, request or
response bodies, secrets, raw provider text. Comparison savings/totals are
not logged, and completed comparisons are not split into recommended /
not-faster / hours-ineligible: D46 requires permitted-use confirmation
before collecting how often alternatives meet the saving threshold.
"""

import json
import logging
import sys
import time
from collections import Counter
from contextvars import ContextVar
from typing import Literal

OperationType = Literal[
    "plan",
    "refresh",
    "compare",
    "compare_exhaustive",
    "suggest_city",
    "suggest_place",
    "select_city",
    "select_place",
]
Transport = Literal["json", "stream"]

OUTCOMES = frozenset(
    {
        "complete",
        "partial",
        "timeout",
        "error",
        "rejected",  # failed before any provider call (validation/departure)
        "cancelled",  # client disconnected/cancelled
        "no_different_order",
        "compared",  # comparison finished; result category intentionally not split
        "incomplete",  # comparison could not be completed
        "ok",
        "no_matches",
    }
)
FAILURES = frozenset(
    {
        # leg failure reasons
        "no_route",
        "arrival_unknown",
        "provider_temporary",
        "quota_exceeded",
        "provider_capacity",
        "deadline_exceeded",
        "cancelled",
        # error categories
        "place_invalid",
        "place_temporary",
        "usage_control_unavailable",
        "timezone_unresolved",
        "timezone_conflict",
        "duplicate_instance_id",
        "departure_invalid",
        "departure_invalid_date",
        "departure_nonexistent",
        "departure_ambiguous",
        "departure_occurrence_not_applicable",
        "departure_out_of_range",
        "departure_timezone_mismatch",
        "planned_departure_unsupported",
        "invalid_query",
        "provider_unavailable",
        "internal_error",
        "other",
    }
)
CALL_KINDS = frozenset(
    {
        "routes_compute",
        "place_details_enterprise",
        "place_details_pro",
        "place_details_essentials",
        "autocomplete",
        "unclassified",
    }
)

_current: ContextVar["OperationMetrics | None"] = ContextVar("routewright_operation", default=None)

log = logging.getLogger("routewright.metrics")
log.propagate = False
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
log.setLevel(logging.INFO)


class OperationMetrics:
    """Collects one operation's aggregate measurements and logs them once."""

    def __init__(
        self, operation: OperationType, transport: Transport, stop_count: int | None = None
    ) -> None:
        self.operation = operation
        self.transport = transport
        self.stop_count = stop_count if stop_count is not None and 0 < stop_count <= 12 else None
        self.calls: Counter[str] = Counter()
        self._start = time.monotonic()
        self._done = False

    def activate(self) -> None:
        """Make this the current operation for provider-call counting."""
        _current.set(self)

    def finish(self, outcome: str, failure: str | None = None) -> None:
        if self._done:
            return
        self._done = True
        record = {
            "event": "operation",
            "operation": self.operation,
            "transport": self.transport,
            "outcome": outcome if outcome in OUTCOMES else "error",
            "failure": None if failure is None else (failure if failure in FAILURES else "other"),
            "elapsed_ms": int((time.monotonic() - self._start) * 1000),
            "stop_count": self.stop_count,
            "calls": {k: v for k, v in sorted(self.calls.items()) if k in CALL_KINDS},
            "client_ip_source": _ip_source(),
            "level": "info",
        }
        log.info(json.dumps(record, sort_keys=True))


CLIENT_IP_SOURCES = frozenset(
    {"peer", "header", "fallback_missing", "fallback_invalid", "fallback_peer_public"}
)


def _ip_source() -> str | None:
    from app.core.limiter import client_ip_source  # late import: limiter imports settings only

    value = client_ip_source.get()
    return value if value in CLIENT_IP_SOURCES else None


def record_call(kind: str) -> None:
    """Count an admitted outbound provider call against the current operation."""
    current = _current.get()
    if current is not None:
        current.calls[kind] += 1
