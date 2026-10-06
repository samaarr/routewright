"""Central outbound provider-call accounting seam.

Every request the backend sends to Google is recorded here with the billing
kind it is expected to incur, AFTER it has been admitted by the shared daily
provider budget (provider_semaphore.consume_provider_budget). Already-sent
calls are never refunded, including failed or cancelled ones.

This is deliberately only a seam. Per-SKU monthly free-allowance enforcement
is deferred by the product manager (TODO.md, 2026-10-06): no new limits are
applied here. A later stage can replace ``InMemoryProviderAccounting`` with a
persistent, atomic, month-aware implementation behind the same interface.

Kinds map to the SKU each request bills at, by its highest-tier field
(verified against the Places/Routes docs, 2026-10-06):

- ``routes_compute``           Routes: Compute Routes (transit/walk/drive)
- ``text_search_enterprise``   v1 Text Search with regularOpeningHours
- ``place_details_enterprise`` v2 stop verification (opening hours)
- ``place_details_pro``        v2 city verification / city selection (displayName)
- ``place_details_essentials`` stop selection (id, location, formattedAddress)
- ``autocomplete``             Autocomplete (New) request

Browser Google Maps JavaScript map loads are a separate SKU that the backend
never sees; they are identified as ``BROWSER_MAP_LOAD_KIND`` for the future
enforcement design but are not counted here.
"""

import logging
from collections import Counter
from threading import Lock
from typing import Literal, Protocol

ProviderCallKind = Literal[
    "routes_compute",
    "text_search_enterprise",
    "place_details_enterprise",
    "place_details_pro",
    "place_details_essentials",
    "autocomplete",
    "unclassified",
]

BROWSER_MAP_LOAD_KIND = "maps_js_dynamic_map_load"

log = logging.getLogger("routewright.provider_accounting")


class ProviderAccounting(Protocol):
    def record(self, kind: ProviderCallKind) -> None: ...

    def snapshot(self) -> dict[str, int]: ...


class InMemoryProviderAccounting:
    """Process-local counters for measurement only. Not an enforcement mechanism."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def record(self, kind: ProviderCallKind) -> None:
        with self._lock:
            self._counts[kind] += 1
        log.debug("provider_call kind=%s", kind)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


accounting: ProviderAccounting = InMemoryProviderAccounting()
