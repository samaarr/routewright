"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI test client. Stateless, no setup needed in week 1."""
    with TestClient(app) as c:
        yield c
