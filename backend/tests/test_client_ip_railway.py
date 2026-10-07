"""Railway client identity (D-1) and HMAC-keyed rate-limit storage.

Railway's HTTP edge writes X-Real-IP; it is trusted only when every condition
that holds for edge traffic holds, otherwise the TCP peer (one shared, stricter
bucket) is used. X-Forwarded-For is ignored in this mode. Limiter keys are
HMACs, so storage never holds raw client IPs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import settings
from app.core.limiter import _client_ip, client_ip_source, limiter, limiter_key
from app.main import app, validate_production

EDGE = [(b"x-railway-edge", b"railway/europe-west4"), (b"x-railway-request-id", b"abc123")]
INTERNAL_PEER = "10.250.0.7"
CLIENT_A = "93.184.216.34"
CLIENT_B = "1.1.1.1"


@pytest.fixture
def railway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "client_ip_source", "railway")
    monkeypatch.setattr(settings, "railway_environment_id", "env-123")
    monkeypatch.setattr(settings, "railway_tcp_proxy_domain", "")
    monkeypatch.setattr(settings, "trusted_proxy_ips", "")


def _request(headers: list[tuple[bytes, bytes]], peer: str = INTERNAL_PEER) -> Request:
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def _identity(headers: list[tuple[bytes, bytes]], peer: str = INTERNAL_PEER) -> tuple[str, Any]:
    ip = _client_ip(_request(headers, peer))
    return ip, client_ip_source.get()


# --- per-request checks ---------------------------------------------------------------


def test_edge_header_is_used(railway: None) -> None:
    assert _identity([(b"x-real-ip", CLIENT_A.encode()), *EDGE]) == (CLIENT_A, "header")


def test_global_ipv6_and_mapped_ipv4(railway: None) -> None:
    assert _identity([(b"x-real-ip", b"2a00:1450:4009::1"), *EDGE]) == (
        "2a00:1450:4009::1",
        "header",
    )
    assert _identity([(b"x-real-ip", b"::ffff:93.184.216.34"), *EDGE]) == (CLIENT_A, "header")


def test_forwarded_for_is_ignored(railway: None) -> None:
    ip, source = _identity([(b"x-forwarded-for", CLIENT_A.encode()), *EDGE])
    assert (ip, source) == (INTERNAL_PEER, "fallback_missing")


def test_missing_edge_markers_fall_back(railway: None) -> None:
    assert _identity([(b"x-real-ip", CLIENT_A.encode())]) == (INTERNAL_PEER, "fallback_missing")


@pytest.mark.parametrize(
    "headers",
    [
        [(b"x-real-ip", CLIENT_A.encode()), (b"x-real-ip", CLIENT_B.encode())],  # duplicate
        [(b"x-real-ip", f"{CLIENT_A}, {CLIENT_B}".encode())],  # list
        [(b"x-real-ip", f"{CLIENT_A}:443".encode())],  # port
        [(b"x-real-ip", f" {CLIENT_A}".encode())],  # padding
        [(b"x-real-ip", b"not-an-ip")],
        [(b"x-real-ip", b"10.1.2.3")],  # private
        [(b"x-real-ip", b"100.64.1.1")],  # CGNAT
        [(b"x-real-ip", b"127.0.0.1")],  # loopback
        [(b"x-real-ip", b"203.0.113.9")],  # documentation range, not global
        [(b"x-real-ip", b"fd00::1")],  # unique local
    ],
)
def test_invalid_header_values_fall_back(railway: None, headers: list[Any]) -> None:
    assert _identity([*headers, *EDGE]) == (INTERNAL_PEER, "fallback_invalid")


def test_public_peer_means_edge_was_bypassed(railway: None) -> None:
    ip, source = _identity([(b"x-real-ip", CLIENT_A.encode()), *EDGE], peer="8.8.4.4")
    assert (ip, source) == ("8.8.4.4", "fallback_peer_public")


def test_peer_mode_ignores_x_real_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "client_ip_source", "peer")
    monkeypatch.setattr(settings, "trusted_proxy_ips", "")
    assert _identity([(b"x-real-ip", CLIENT_A.encode()), *EDGE]) == (INTERNAL_PEER, "peer")


# --- startup validation ---------------------------------------------------------------


def test_railway_mode_requires_railway_environment(
    railway: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "railway_environment_id", "")
    with pytest.raises(RuntimeError, match="requires a Railway environment"):
        validate_production()


def test_railway_mode_refused_with_tcp_proxy(
    railway: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "railway_tcp_proxy_domain", "roundhouse.proxy.rlwy.net")
    with pytest.raises(RuntimeError, match="TCP proxy"):
        validate_production()


def test_railway_mode_excludes_trusted_proxies(
    railway: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_ips", "10.0.0.0/8")
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_IPS"):
        validate_production()


def test_production_requires_limiter_key_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "google_maps_api_key", "placeholder")
    monkeypatch.setattr(settings, "allowed_origins", "https://app.example")
    monkeypatch.setattr(settings, "rate_limit_storage_uri", "rediss://default:pw@r.example:6379")
    monkeypatch.setattr(settings, "limiter_key_secret", "short")
    with pytest.raises(RuntimeError, match="LIMITER_KEY_SECRET"):
        validate_production()


# --- keys and real-limiter buckets ----------------------------------------------------


def test_limiter_key_is_an_hmac_not_the_ip(railway: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "limiter_key_secret", "s" * 32)
    request = _request([(b"x-real-ip", CLIENT_A.encode()), *EDGE])
    key = limiter_key(request)
    assert CLIENT_A not in key and len(key) == 32
    monkeypatch.setattr(settings, "limiter_key_secret", "t" * 32)
    assert limiter_key(request) != key  # secret-dependent


_BODY: dict[str, Any] = {
    "operation_id": "op-d1",
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


def _post(client: TestClient, real_ip: str | None, extra: list[tuple[str, str]] = ()) -> int:  # type: ignore[assignment]
    headers = {"x-railway-edge": "railway/europe-west4", "x-railway-request-id": "abc"}
    if real_ip:
        headers["x-real-ip"] = real_ip
    headers.update(dict(extra))
    return client.post("/api/v2/plan", json=_BODY, headers=headers).status_code


def test_real_limiter_buckets_and_stored_keys(
    railway: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Rejected plans (no provider calls) through the real limiter."""
    caplog.set_level(logging.INFO)
    client = TestClient(app, client=(INTERNAL_PEER, 5555))
    per_minute = settings.max_requests_per_ip_per_minute
    # Forged X-Forwarded-For values do not create new buckets for client A.
    statuses = [
        _post(client, CLIENT_A, [("x-forwarded-for", f"8.8.{i}.1")]) for i in range(per_minute)
    ]
    assert statuses == [422] * per_minute
    assert _post(client, CLIENT_A) == 429
    assert _post(client, CLIENT_B) == 422  # a different edge-reported client has its own bucket

    stored = " ".join(str(k) for k in limiter._storage.storage)  # type: ignore[attr-defined]
    assert "plan-v2" in stored  # limit keys really were written
    expected = limiter_key(_request([(b"x-real-ip", CLIENT_A.encode()), *EDGE]))
    assert expected in stored  # keyed by the HMAC
    assert CLIENT_A not in stored and CLIENT_B not in stored and INTERNAL_PEER not in stored

    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "routewright.metrics"]
    assert lines and all(line["client_ip_source"] == "header" for line in lines)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert CLIENT_A not in text and CLIENT_B not in text


def test_requests_without_edge_markers_share_one_bucket(railway: None) -> None:
    client = TestClient(app, client=(INTERNAL_PEER, 5555))
    per_minute = settings.max_requests_per_ip_per_minute
    for i in range(per_minute):
        status = client.post(
            "/api/v2/plan", json=_BODY, headers={"x-real-ip": f"1.0.0.{i + 1}"}
        ).status_code
        assert status == 422
    # A forged X-Real-IP without edge markers cannot escape the shared peer bucket.
    assert (
        client.post("/api/v2/plan", json=_BODY, headers={"x-real-ip": "9.9.9.9"}).status_code == 429
    )
