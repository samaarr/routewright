"""CI-only shared-store check against a dedicated disposable Redis database."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis


def test_budget_atomic_across_processes():
    uri = os.getenv("SECURITY_TEST_REDIS_URL")
    if not uri:
        pytest.skip("Dedicated SECURITY_TEST_REDIS_URL not supplied")
    store = redis.Redis.from_url(uri)
    # This URI must identify a disposable test database; never production storage.
    store.flushdb()
    env = {
        **os.environ,
        "APP_ENV": "test",
        "RATE_LIMIT_STORAGE_URI": uri,
        "PROVIDER_CALLS_PER_DAY": "1",
    }
    code = """import asyncio
from fastapi import HTTPException
from app.core.provider_semaphore import consume_provider_budget
async def main():
    try:
        await consume_provider_budget()
        print("admitted")
    except HTTPException as error:
        print(error.status_code)
asyncio.run(main())
"""

    def worker(_):
        return subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(worker, range(2))) == ["429", "admitted"]
    finally:
        store.flushdb()


# ---------------------------------------------------------------------------
# Shared-store behaviour of the v2 controls (same disposable database rules)
# ---------------------------------------------------------------------------

_SUGGEST_WORKER = """
import json, sys
from fastapi.testclient import TestClient
from app.main import app
from app.routers import selection
from app.services.autocomplete import Suggestion

class Fake:
    async def suggest(self, query, **kw):
        return [Suggestion("ChIJx", "X", None)]

selection.suggestion_adapter = lambda: Fake()
client = TestClient(app)
codes = [client.post("/api/v2/suggest/cities", json={"query": "du"}).status_code
         for _ in range(int(sys.argv[1]))]
print(json.dumps(codes))
"""


def _redis_env(uri: str, **extra: str) -> dict[str, str]:
    return {**os.environ, "APP_ENV": "test", "RATE_LIMIT_STORAGE_URI": uri, **extra}


def _uri_or_skip() -> str:
    uri = os.getenv("SECURITY_TEST_REDIS_URL")
    if not uri:
        pytest.skip("Dedicated SECURITY_TEST_REDIS_URL not supplied")
    return uri


def test_selection_limit_is_shared_across_processes() -> None:
    """Two backend processes share one 30/minute per-IP suggestion allowance."""
    import json

    uri = _uri_or_skip()
    store = redis.Redis.from_url(uri)
    store.flushdb()
    try:

        def run(n: str) -> list[int]:
            out = subprocess.check_output(
                [sys.executable, "-c", _SUGGEST_WORKER, n], env=_redis_env(uri), text=True
            )
            # stdout also carries the per-request metrics lines; the result is last.
            codes: list[int] = json.loads(out.strip().splitlines()[-1])
            return codes

        first = run("20")
        second = run("11")
        assert first == [200] * 20
        assert second[:10] == [200] * 10
        assert second[10] == 429  # 31st request across both processes
    finally:
        store.flushdb()


def test_failed_provider_calls_stay_counted_in_shared_budget() -> None:
    """Budget is consumed before sending; a failing call still counts, across processes."""
    uri = _uri_or_skip()
    store = redis.Redis.from_url(uri)
    store.flushdb()
    code = """import asyncio, httpx
from app.services import directions
from datetime import datetime, timezone
async def main():
    def boom(request):
        raise httpx.ConnectError("down", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
        try:
            await directions.fetch_leg(origin_lat=53.3, origin_lng=-6.2, destination_lat=53.4,
                destination_lng=-6.3, depart_at=datetime(2026, 10, 21, 9, tzinfo=timezone.utc),
                mode="walking", client=c)
        except Exception as e:
            print(type(e).__name__, getattr(e, "status_code", ""))
asyncio.run(main())
"""
    env = _redis_env(uri, PROVIDER_CALLS_PER_DAY="2")
    try:
        outputs = [
            subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
            for _ in range(3)
        ]
        # Two failed calls were admitted (and counted); the third is refused by the budget.
        assert outputs[:2] == ["DirectionsError", "DirectionsError"]
        assert outputs[2] == "HTTPException 429"
    finally:
        store.flushdb()


def test_unreachable_store_fails_closed_and_releases_capacity() -> None:
    """With the shared store down, no provider call is made, the error is the
    usage-control category, and the provider slot is released."""
    _uri_or_skip()
    code = """import asyncio
from app.core import provider_semaphore
from app.services import adapter as adapter_module
from app.services.errors import UsageControlUnavailableError
sent = []
async def never(*a, **k):
    sent.append(1)
async def main():
    provider_semaphore.reset_gates()
    free = provider_semaphore._provider._value
    adapter_module.fetch_place_details = never
    try:
        await adapter_module.GooglePlacesAdapter().fetch_details("ChIJx", role="stop")
    except UsageControlUnavailableError:
        print("usage_control", provider_semaphore._provider._value == free, len(sent))
asyncio.run(main())
"""
    env = _redis_env("redis://127.0.0.1:1/0")  # nothing listens on port 1
    out = subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
    assert out == "usage_control True 0"
