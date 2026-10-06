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


# --- other library log paths (uvicorn) -----------------------------------------


@pytest.mark.parametrize(
    ("message", "args", "address"),
    [
        ('%s - "WebSocket %s" %s', ("203.0.113.77:4321", "/api/v2/plan", 403), "203.0.113.77"),
        ('%s - "WebSocket %s" %s', ("2001:db8::77:4321", "/api/v2/plan", 403), "2001:db8::77"),
        ("%sConnection made", ("[2001:db8::77]:4321 - ",), "2001:db8::77"),
    ],
)
def test_uvicorn_error_records_are_redacted(
    caplog: pytest.LogCaptureFixture, message: str, args: tuple[Any, ...], address: str
) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger("uvicorn.error").info(message, *args)
    text = _rendered(caplog)
    assert address not in text
    assert "[redacted]" in text


def test_real_uvicorn_websocket_rejection_logs_no_client_ip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A WebSocket handshake to a real uvicorn server (WebSocket support left on,
    unlike the container's --ws none) must not log the client address."""
    import socket
    import threading
    import time

    import uvicorn

    caplog.set_level(logging.DEBUG)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, ws="auto"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.01)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(
                b"GET /api/v2/plan HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\n"
                b"Upgrade: websocket\r\nSec-WebSocket-Version: 13\r\n"
                b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
            )
            assert b"403" in client.recv(1024)
        for _ in range(100):
            if any("WebSocket" in r.getMessage() for r in caplog.records):
                break
            time.sleep(0.01)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
    assert any("WebSocket" in r.getMessage() for r in caplog.records), "uvicorn did not log"
    assert "127.0.0.1" not in _rendered(caplog)


def test_container_disables_websockets_and_access_log() -> None:
    from pathlib import Path

    cmd = next(
        line
        for line in (Path(__file__).parents[1] / "Dockerfile").read_text().splitlines()
        if line.startswith("CMD")
    )
    assert "--ws none" in cmd and "--no-access-log" in cmd and "--no-proxy-headers" in cmd
