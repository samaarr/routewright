"""429 responses must not log the client identity (D-9, found 2026-10-06).

slowapi's own warning, "ratelimit <limit> (<key>) exceeded at endpoint: <scope>",
included the limiter key — the client IP in production. These tests drive the
real limiter (no mocks) until it rejects and inspect every emitted record.
Rejected plans (past departure) make no provider calls.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

_BODY: dict[str, Any] = {
    "operation_id": "op-ratelimit-log",
    "input_revision": 1,
    "city": {"place_id": "c", "name": "C", "lat": 53.3, "lng": -6.2},
    "stops": [
        {"instance_id": "a", "selection": {"place_id": "a", "name": "A", "lat": 53.3, "lng": -6.2}},
        {
            "instance_id": "b",
            "selection": {"place_id": "b", "name": "B", "lat": 53.31, "lng": -6.21},
        },
    ],
    "departure": {"local_date": "2020-01-01", "local_time": "10:00", "timezone": "Europe/Dublin"},
}


def _rendered(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.getMessage()} {r.exc_text or ''}" for r in caplog.records)


@pytest.mark.parametrize("client_ip", ["203.0.113.77", "2001:db8::77"])
def test_rate_limited_request_logs_no_client_ip(
    client_ip: str, caplog: pytest.LogCaptureFixture
) -> None:
    client = TestClient(app, client=(client_ip, 4321))
    caplog.set_level(logging.DEBUG)
    statuses = [
        client.post("/api/v2/plan", json=_BODY).status_code
        for _ in range(settings.max_requests_per_ip_per_minute + 1)
    ]
    assert statuses[:-1] == [422] * settings.max_requests_per_ip_per_minute
    assert statuses[-1] == 429

    # The real limiter rejected the request and said so.
    exceeded = [r for r in caplog.records if r.name == "slowapi" and "exceeded" in r.getMessage()]
    assert exceeded, "expected slowapi's rate-limit warning"
    assert "plan-v2" in exceeded[-1].getMessage()

    assert client_ip not in _rendered(caplog)


def test_slowapi_records_with_an_ip_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    """Defence in depth: any other slowapi message carrying an address is redacted."""
    caplog.set_level(logging.DEBUG)
    logging.getLogger("slowapi").warning("unexpected %s at %s", "198.51.100.9", "2001:db8::9")
    text = _rendered(caplog)
    assert "198.51.100.9" not in text
    assert "2001:db8::9" not in text
    assert "[redacted]" in text
