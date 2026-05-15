"""Health endpoint smoke tests.

These are the cheapest tests in the suite — if they fail, the app didn't
even import. CI runs them first.
"""

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "env" in body


def test_healthz_no_auth_required(client: TestClient) -> None:
    """Health probe must be reachable without any headers."""
    response = client.get("/healthz")
    assert response.status_code == 200
