"""Bounded process admission plus a shared, fail-closed provider-call budget."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TypeVar

from fastapi import HTTPException
from limits import RateLimitItemPerDay

from app.core.config import settings
from app.core.limiter import limiter
from app.core.provider_accounting import ProviderCallKind, accounting

_T = TypeVar("_T")

CAPACITY_BUSY_DETAIL = "Provider capacity is busy"
USAGE_CONTROL_UNAVAILABLE_DETAIL = "Usage control unavailable"
BUDGET_EXHAUSTED_DETAIL = "Daily provider budget exhausted"

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
        raise HTTPException(503, CAPACITY_BUSY_DETAIL, headers={"Retry-After": "2"}) from exc
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


async def consume_provider_budget(kind: ProviderCallKind = "unclassified") -> None:
    """Count each outbound call, including failed calls, before sending it.

    ``kind`` labels the call for the central accounting seam (separate counts
    for routing, details and suggestions). Every production call site passes
    a kind; the default exists only for legacy tests.
    """
    limit = RateLimitItemPerDay(settings.provider_calls_per_day)
    try:
        admitted = await asyncio.to_thread(limiter.limiter.hit, limit, "provider-global")
    except Exception as exc:
        raise HTTPException(
            503, USAGE_CONTROL_UNAVAILABLE_DETAIL, headers={"Retry-After": "60"}
        ) from exc
    if not admitted:
        # Conservatively wait a day; the provider budget cannot become a fabricated leg.
        raise HTTPException(429, BUDGET_EXHAUSTED_DETAIL, headers={"Retry-After": "86400"})
    accounting.record(kind)


async def run_in_solver_slot(fn: Callable[[], _T], *, wait_seconds: float) -> _T:
    """Run blocking local solver work in a thread under the solver semaphore.

    The slot is released when the worker THREAD finishes, not when the awaiting
    task is cancelled: a cancelled comparison stops waiting immediately, but
    the slot stays held until the (time-limited) solver actually returns, so
    capacity accounting reflects real work. Callers must bound ``fn`` with a
    solver time limit no longer than the remaining operation deadline.
    """
    global _solver
    if _solver is None:
        _solver = asyncio.Semaphore(2)
    sem = _solver
    try:
        await asyncio.wait_for(sem.acquire(), timeout=max(0.0, wait_seconds))
    except TimeoutError as exc:
        raise HTTPException(
            503, "Optimisation capacity is busy", headers={"Retry-After": "2"}
        ) from exc
    try:
        future = asyncio.get_running_loop().run_in_executor(None, fn)
    except BaseException:
        sem.release()
        raise
    future.add_done_callback(lambda _f: sem.release())
    return await asyncio.shield(future)


def solver_slots_free() -> int:
    """Free solver slots (tests/diagnostics)."""
    return _solver._value if _solver is not None else 2
