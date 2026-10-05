"""Bounded process admission plus a shared, fail-closed provider-call budget."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException
from limits import RateLimitItemPerDay

from app.core.config import settings
from app.core.limiter import limiter

_provider: asyncio.Semaphore | None = None
_solver: asyncio.Semaphore | None = None


def reset_gates() -> None:
    global _provider, _solver
    _provider = asyncio.Semaphore(settings.max_concurrent_provider_calls)
    _solver = asyncio.Semaphore(2)


@asynccontextmanager
async def get_provider_semaphore() -> AsyncIterator[None]:
    global _provider
    if _provider is None:
        _provider = asyncio.Semaphore(settings.max_concurrent_provider_calls)
    try:
        await asyncio.wait_for(_provider.acquire(), timeout=settings.provider_wait_seconds)
    except TimeoutError as exc:
        raise HTTPException(503, "Provider capacity is busy", headers={"Retry-After": "2"}) from exc
    try:
        yield
    finally:
        _provider.release()


@asynccontextmanager
async def solver_slot() -> AsyncIterator[None]:
    global _solver
    if _solver is None:
        _solver = asyncio.Semaphore(2)
    try:
        await asyncio.wait_for(_solver.acquire(), timeout=settings.provider_wait_seconds)
    except TimeoutError as exc:
        raise HTTPException(
            503, "Optimisation capacity is busy", headers={"Retry-After": "2"}
        ) from exc
    try:
        yield
    finally:
        _solver.release()


async def consume_provider_budget() -> None:
    """Count each outbound call, including failed calls, before sending it."""
    limit = RateLimitItemPerDay(settings.provider_calls_per_day)
    try:
        admitted = await asyncio.to_thread(limiter.limiter.hit, limit, "provider-global")
    except Exception as exc:
        raise HTTPException(
            503, "Usage control unavailable", headers={"Retry-After": "60"}
        ) from exc
    if not admitted:
        # Conservatively wait a day; the provider budget cannot become a fabricated leg.
        raise HTTPException(
            429, "Daily provider budget exhausted", headers={"Retry-After": "86400"}
        )
