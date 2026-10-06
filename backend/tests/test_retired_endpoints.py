"""The v1 endpoints were retired on 2026-10-06 (approved decision).

/api/plan, /api/optimise and /api/refresh-leg must not be served in any
form, must not appear in the OpenAPI schema, and must not make provider
calls. The v2 routes and the local optimiser used by comparison remain.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import optimise

RETIRED = ["/api/plan", "/api/optimise", "/api/refresh-leg"]


@pytest.mark.parametrize("path", RETIRED)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "OPTIONS"])
def test_retired_route_is_not_served(client: TestClient, path: str, method: str) -> None:
    response = client.request(method, path, json={"city": "Dublin", "stops": []})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("path", RETIRED)
def test_retired_route_with_trailing_slash_is_not_served(client: TestClient, path: str) -> None:
    assert client.post(path + "/", json={}).status_code == 404


def test_openapi_lists_only_v2_and_health() -> None:
    paths = set(app.openapi()["paths"])
    assert not paths & set(RETIRED)
    assert all(p == "/healthz" or p.startswith("/api/v2/") for p in paths), paths
    assert {"/api/v2/plan", "/api/v2/refresh", "/api/v2/compare"} <= paths


def test_local_optimiser_is_preserved() -> None:
    """Comparison (Step 8) depends on the haversine OR-Tools optimiser."""
    assert callable(optimise.optimise_order)
