"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> Iterator[None]:
    """Reset in-memory rate-limit counters before each test.

    Without this, tests that hit rate-limited endpoints in the same test
    session accumulate counts and trigger 429 responses from the shared app
    instance, causing false failures unrelated to the test under scrutiny.
    The rate_limiting tests use isolated apps and are unaffected.
    """
    from app.core.limiter import limiter

    limiter._storage.reset()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI test client. Stateless, no setup needed in week 1."""
    with TestClient(app) as c:
        yield c
