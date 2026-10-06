"""Security regression tests (ported to the v2 API when v1 was retired, 2026-10-06).

Covers:
- Input validation on /api/v2/plan: unknown fields, coordinate bounds.
- Rate limiting: forged X-Forwarded-For headers are ignored unless the peer is
  a trusted proxy; trusted-proxy chains select the correct client IP; burst
  limit returns 429 with Retry-After.
- Validation error responses do not echo submitted input values.

Legacy-only checks (free-text query blanks, start_time bounds, Text Search
response parsing) were removed with the v1 endpoints; v2 equivalents live in
test_selection.py (query validation) and test_departure*/test_plan_v2_* (departure range).
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core.limiter import _client_ip
from tests.test_plan_v2_verified import _payload, _stop


def _plan_body(**overrides: Any) -> dict[str, Any]:
    body = _payload([_stop("a", "trinity"), _stop("b", "pub")])
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Input validation on the v2 plan endpoint (no provider calls on rejection)
# ---------------------------------------------------------------------------


class TestExtraFieldsRejected:
    def test_extra_field_in_plan_request_returns_422(self, client: TestClient) -> None:
        r = client.post("/api/v2/plan", json=_plan_body(unexpected="x"))
        assert r.status_code == 422

    def test_extra_field_in_stop_returns_422(self, client: TestClient) -> None:
        body = _plan_body()
        body["stops"][0]["unexpected"] = "x"
        r = client.post("/api/v2/plan", json=body)
        assert r.status_code == 422


class TestCoordinateBounds:
    @pytest.mark.parametrize(("lat", "lng"), [(91.0, -6.2), (53.3, 181.0)])
    def test_out_of_range_selection_coordinates_return_422(
        self, client: TestClient, lat: float, lng: float
    ) -> None:
        body = _plan_body()
        body["stops"][0]["selection"].update({"lat": lat, "lng": lng})
        r = client.post("/api/v2/plan", json=body)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Rate limiting: trusted proxy and forged X-Forwarded-For
# ---------------------------------------------------------------------------


def _make_request_with_xff(xff: str | None, remote_addr: str = "192.168.1.1") -> Request:
    """Build a minimal Starlette Request with a given X-Forwarded-For header."""
    scope = {
        "type": "http",
        "headers": ([(b"x-forwarded-for", xff.encode())] if xff else []),
        "client": (remote_addr, 1234),
        "method": "POST",
        "path": "/api/v2/plan",
        "query_string": b"",
    }
    return Request(scope)


class TestTrustedProxyIPResolution:
    def test_no_trusted_proxies_ignores_xff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_ips", "")
        request = _make_request_with_xff("1.2.3.4", remote_addr="10.0.0.1")
        assert _client_ip(request) == "10.0.0.1"

    def test_forged_xff_ignored_without_trusted_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An attacker prepending IPs to XFF must not spoof their rate-limit bucket."""
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_ips", "")
        request = _make_request_with_xff("9.9.9.9, 8.8.8.8", remote_addr="10.0.0.1")
        assert _client_ip(request) == "10.0.0.1"

    def test_trusted_peer_resolves_client_from_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.core.limiter.settings.trusted_proxy_ips", "10.0.0.1/32,192.168.1.1/32"
        )
        request = _make_request_with_xff("203.0.113.5, 10.0.0.1")
        assert _client_ip(request) == "203.0.113.5"

    def test_forged_extra_hop_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The first untrusted hop from the right wins; a prepended forgery is ignored."""
        monkeypatch.setattr(
            "app.core.limiter.settings.trusted_proxy_ips", "10.0.0.1/32,192.168.1.1/32"
        )
        request = _make_request_with_xff("9.9.9.9, 203.0.113.5, 10.0.0.1")
        assert _client_ip(request) == "203.0.113.5"

    def test_untrusted_peer_uses_remote_addr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_ips", "10.0.0.0/8")
        request = _make_request_with_xff("10.0.0.1", remote_addr="192.168.0.5")
        assert _client_ip(request) == "192.168.0.5"


class TestBurstRateLimit:
    def test_burst_limit_returns_429_with_retry_after(self) -> None:
        """Isolated limiter (1/minute) — the real v2 limits are exercised in
        test_security_controls.py and test_ratelimit_logging.py."""
        lim = Limiter(key_func=lambda request: "burst-test-ip")
        isolated = FastAPI()
        isolated.state.limiter = lim

        async def _handler(_req: Request, _exc: RateLimitExceeded) -> JSONResponse:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={"error": "rate_limit_exceeded"},
            )

        isolated.add_exception_handler(RateLimitExceeded, _handler)  # type: ignore[arg-type]

        @isolated.post("/limited")
        @lim.limit("1/minute")
        async def limited(request: Request) -> dict:
            return {"ok": True}

        c = TestClient(isolated, raise_server_exceptions=False)
        assert c.post("/limited").status_code == 200
        r2 = c.post("/limited")
        assert r2.status_code == 429
        assert "retry-after" in r2.headers


# ---------------------------------------------------------------------------
# Validation error response does not echo submitted input
# ---------------------------------------------------------------------------


class TestValidationErrorResponse:
    def test_validation_error_does_not_echo_raw_input(self, client: TestClient) -> None:
        secret_value = "MYSECRETINPUT12345"
        body = _plan_body()
        body["stops"][0]["selection"]["name"] = secret_value * 50  # exceeds max length
        r = client.post("/api/v2/plan", json=body)
        assert r.status_code == 422
        assert secret_value not in r.text

    def test_validation_error_includes_field_path(self, client: TestClient) -> None:
        body = _plan_body()
        body["stops"][0]["selection"]["lat"] = 91.0
        r = client.post("/api/v2/plan", json=body)
        assert r.status_code == 422
        payload = r.json()
        assert payload["error"] == "validation_error"
        locs = [tuple(e["loc"]) for e in payload["errors"]]
        assert any("lat" in loc for loc in locs)
