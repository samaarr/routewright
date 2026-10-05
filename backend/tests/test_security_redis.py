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
