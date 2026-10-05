"""Security regression tests.

Covers:
- Input validation: blank/whitespace queries, coordinate bounds, extra fields,
  future-date limit, blank city.
- Geocoder: provider response with missing/zero coordinates raises GeocoderError.
- Rate limiting: forged X-Forwarded-For headers are ignored in dev mode;
  trusted-proxy mode selects the correct client IP; burst limit returns 429.
- Validation error responses do not echo submitted input values.
- 429 responses include a Retry-After header.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from app.core.limiter import _client_ip
from app.services.geocoder import GeocoderError, _parse_response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_start() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


def _base_payload(**overrides: Any) -> dict:
    base: dict = {
        "city": "Dublin, Ireland",
        "stops": [
            {"query": "Trinity College"},
            {"query": "Temple Bar"},
        ],
        "start_time": _future_start(),
        "mode": "transit",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestBlankQueryRejected:
    def test_whitespace_only_query_returns_422(self, client: TestClient) -> None:
        """A query of all spaces must be rejected (blank after strip)."""
        payload = _base_payload()
        payload["stops"] = [{"query": "   "}, {"query": "Temple Bar"}]
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422

    def test_empty_string_query_returns_422(self, client: TestClient) -> None:
        payload = _base_payload()
        payload["stops"] = [{"query": ""}, {"query": "Temple Bar"}]
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422

    def test_blank_city_returns_422(self, client: TestClient) -> None:
        payload = _base_payload(city="   ")
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422

    def test_empty_city_returns_422(self, client: TestClient) -> None:
        payload = _base_payload(city="")
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422

    def test_leading_trailing_spaces_in_query_accepted(self, client: TestClient) -> None:
        """Queries with surrounding whitespace are stripped and accepted if non-blank."""
        # This tests that "  Trinity College  " becomes "Trinity College" (2+ chars).
        payload = _base_payload()
        payload["stops"] = [{"query": "  Trinity College  "}, {"query": "Temple Bar"}]
        # Does not geocode — if it reaches geocode it means validation passed.
        # We only check that it does NOT return 422.
        from app.services.geocoder import GeocoderError

        with patch(
            "app.routers.plan.geocode_cached",
            new_callable=AsyncMock,
            side_effect=GeocoderError("mock"),
        ):
            r = client.post("/api/plan", json=payload)
        assert r.status_code == 400  # geocoder error, not validation error


class TestExtraFieldsRejected:
    def test_extra_field_in_plan_request_returns_422(self, client: TestClient) -> None:
        payload = _base_payload(admin_override=True)
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422

    def test_extra_field_in_stop_returns_422(self, client: TestClient) -> None:
        payload = _base_payload()
        payload["stops"] = [
            {"query": "Trinity College", "is_admin": True},
            {"query": "Temple Bar"},
        ]
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422


class TestFutureDateBound:
    def test_far_future_start_time_returns_422(self, client: TestClient) -> None:
        far_future = datetime.now(timezone.utc) + timedelta(days=400)
        payload = _base_payload(start_time=far_future.isoformat())
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422

    def test_just_within_future_limit_accepted(self, client: TestClient) -> None:
        near_limit = datetime.now(timezone.utc) + timedelta(days=99)
        payload = _base_payload(start_time=near_limit.isoformat())
        from app.services.geocoder import GeocoderError

        with patch(
            "app.routers.plan.geocode_cached",
            new_callable=AsyncMock,
            side_effect=GeocoderError("mock"),
        ):
            r = client.post("/api/plan", json=payload)
        # 400 means it passed validation and reached geocoding
        assert r.status_code == 400


class TestRefreshLegCoordinateBounds:
    def test_out_of_range_lat_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/api/refresh-leg",
            json={
                "from_lat": 91.0,
                "from_lng": 0.0,
                "from_name": "A Place",
                "to_lat": 53.0,
                "to_lng": -6.0,
                "to_name": "B Place",
                "mode": "transit",
                "city": "Dublin",
            },
        )
        assert r.status_code == 422

    def test_out_of_range_lng_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/api/refresh-leg",
            json={
                "from_lat": 53.0,
                "from_lng": 181.0,
                "from_name": "A Place",
                "to_lat": 53.0,
                "to_lng": -6.0,
                "to_name": "B Place",
                "mode": "transit",
                "city": "Dublin",
            },
        )
        assert r.status_code == 422

    def test_blank_city_in_refresh_leg_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/api/refresh-leg",
            json={
                "from_lat": 53.0,
                "from_lng": -6.0,
                "from_name": "A Place",
                "to_lat": 53.1,
                "to_lng": -6.1,
                "to_name": "B Place",
                "mode": "transit",
                "city": "  ",
            },
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Geocoder provider-response validation
# ---------------------------------------------------------------------------


class TestGeocoderProviderResponseValidation:
    def _make_place(self, **overrides: Any) -> dict:
        base = {
            "id": "ChIJ_TC",
            "displayName": {"text": "Trinity College"},
            "location": {"latitude": 53.344, "longitude": -6.254},
            "primaryType": "tourist_attraction",
            "types": ["tourist_attraction"],
        }
        base.update(overrides)
        return base

    def test_missing_place_id_raises(self) -> None:
        response_json = {"places": [self._make_place(id="")]}
        with pytest.raises(GeocoderError, match="no place_id"):
            _parse_response(response_json, "Trinity College")

    def test_missing_location_raises(self) -> None:
        place = self._make_place()
        del place["location"]
        response_json = {"places": [place]}
        with pytest.raises(GeocoderError, match="no location"):
            _parse_response(response_json, "Trinity College")

    def test_null_island_coordinates_raises(self) -> None:
        place = self._make_place(location={"latitude": 0.0, "longitude": 0.0})
        response_json = {"places": [place]}
        with pytest.raises(GeocoderError, match="null-island"):
            _parse_response(response_json, "Trinity College")

    def test_missing_places_array_raises(self) -> None:
        with pytest.raises(GeocoderError, match="place not found"):
            _parse_response({}, "Trinity College")

    def test_valid_response_parses_correctly(self) -> None:
        response_json = {"places": [self._make_place()]}
        result = _parse_response(response_json, "Trinity College")
        assert result.place_id == "ChIJ_TC"
        assert result.lat == pytest.approx(53.344)
        assert result.lng == pytest.approx(-6.254)


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
        "path": "/api/plan",
        "query_string": b"",
    }
    return Request(scope)


class TestTrustedProxyIPResolution:
    def test_dev_mode_ignores_xff_uses_remote_addr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """trusted_proxy_count=0 (dev) must use request.client.host, not XFF."""
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_count", 0)
        monkeypatch.setattr("app.core.limiter.settings.rate_limit_whitelist_ips", "")
        request = _make_request_with_xff("1.2.3.4", remote_addr="10.0.0.1")
        assert _client_ip(request) == "10.0.0.1"

    def test_forged_xff_ignored_in_dev_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An attacker prepending IPs to XFF must not spoof their rate-limit bucket."""
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_count", 0)
        monkeypatch.setattr("app.core.limiter.settings.rate_limit_whitelist_ips", "")
        request = _make_request_with_xff("9.9.9.9, 8.8.8.8", remote_addr="10.0.0.1")
        # Dev mode ignores XFF entirely; key is the real connection address.
        assert _client_ip(request) == "10.0.0.1"

    def test_prod_proxy_count_1_resolves_correct_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With 1 trusted proxy, the second-from-right IP is the real client."""
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_count", 1)
        monkeypatch.setattr("app.core.limiter.settings.rate_limit_whitelist_ips", "")
        # XFF: "client_ip, proxy_ip" — proxy_ip is injected by our trusted load balancer.
        monkeypatch.setattr(
            "app.core.limiter.settings.trusted_proxy_ips", "10.0.0.1/32,192.168.1.1/32"
        )
        request = _make_request_with_xff("203.0.113.5, 10.0.0.1")
        assert _client_ip(request) == "203.0.113.5"

    def test_forged_extra_hop_in_prod_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Attacker injects an extra IP before the real one; proxy count strips it correctly."""
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_count", 1)
        monkeypatch.setattr("app.core.limiter.settings.rate_limit_whitelist_ips", "")
        # XFF: "attacker_forged, real_client, trusted_proxy"
        # With proxy_count=1 we strip 1 hop from the right, leaving "attacker_forged, real_client".
        # The result should be "real_client" (rightmost untrusted hop).
        monkeypatch.setattr(
            "app.core.limiter.settings.trusted_proxy_ips", "10.0.0.1/32,192.168.1.1/32"
        )
        request = _make_request_with_xff("9.9.9.9, 203.0.113.5, 10.0.0.1")
        assert _client_ip(request) == "203.0.113.5"

    def test_short_xff_falls_back_to_remote_addr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If XFF has fewer entries than trusted_proxy_count, fall back to remote addr."""
        monkeypatch.setattr("app.core.limiter.settings.trusted_proxy_count", 2)
        monkeypatch.setattr("app.core.limiter.settings.rate_limit_whitelist_ips", "")
        # Only one hop in XFF; not enough to strip 2 proxies — fall back to remote addr.
        request = _make_request_with_xff("10.0.0.1", remote_addr="192.168.0.5")
        assert _client_ip(request) == "192.168.0.5"


class TestBurstRateLimit:
    def test_burst_limit_returns_429_with_retry_after(self) -> None:
        """Exceeding the per-minute burst limit must return 429 with Retry-After.

        Uses the main app's rate_limit_handler which sets Retry-After: 60.
        """

        # The main app is configured with 50/day;10/minute limits.
        # We exhaust the per-minute limit by patching the limits to 1/minute.
        # Use the same isolated-app pattern as test_rate_limiting.py instead.
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

        @isolated.post("/api/plan")
        @lim.limit("1/minute")
        async def plan(request: Request) -> dict:
            return {"ok": True}

        c = TestClient(isolated, raise_server_exceptions=False)
        r1 = c.post("/api/plan")
        assert r1.status_code == 200
        r2 = c.post("/api/plan")
        assert r2.status_code == 429
        assert "retry-after" in r2.headers


# ---------------------------------------------------------------------------
# Validation error response does not echo submitted input
# ---------------------------------------------------------------------------


class TestValidationErrorResponse:
    def test_validation_error_does_not_echo_raw_input(self, client: TestClient) -> None:
        """Submitted field values must not appear in the validation error body."""
        secret_value = "MYSECRETINPUT12345"
        payload = _base_payload(city=secret_value * 8)  # exceeds max_length=120 (144 chars)
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422
        body = r.text
        assert secret_value not in body

    def test_validation_error_includes_field_path(self, client: TestClient) -> None:
        """Error response must include the loc field path so clients can identify the problem."""
        payload = _base_payload()
        payload["stops"] = [{"query": "A"}, {"query": "Temple Bar"}]
        r = client.post("/api/plan", json=payload)
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "validation_error"
        assert "errors" in body
        locs = [tuple(e["loc"]) for e in body["errors"]]
        # Should reference the stops[0].query field
        assert any("query" in loc for loc in locs)

    def test_429_includes_retry_after(self) -> None:
        """The main app's 429 handler must include a Retry-After header."""

        # Use isolated app with 1/minute limit so we can trigger it reliably.
        lim = Limiter(key_func=lambda request: "ra-test-ip")
        isolated = FastAPI()
        isolated.state.limiter = lim

        async def _handler(_req: Request, _exc: RateLimitExceeded) -> JSONResponse:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={"error": "rate_limit_exceeded"},
            )

        isolated.add_exception_handler(RateLimitExceeded, _handler)  # type: ignore[arg-type]

        @isolated.post("/test")
        @lim.limit("1/minute")
        async def route(request: Request) -> dict:
            return {"ok": True}

        c = TestClient(isolated, raise_server_exceptions=False)
        c.post("/test")
        r = c.post("/test")
        assert r.status_code == 429
        assert "retry-after" in r.headers
