"""Deadline / cancellation context for planning operations.

A single 60-second monotonic clock covers the whole operation (plan,
comparison or refresh). It does not reset on incremental progress.
Cancel-on-disconnect is signalled through the same scope.
"""

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TypeVar

_T = TypeVar("_T")

OPERATION_DEADLINE_SECONDS: float = 60.0


class DeadlineExceededError(Exception):
    """Raised when the operation wall-clock deadline has passed."""


@dataclass
class DeadlineScope:
    """Tracks deadline and cancellation for a single planning operation.

    Typical use::

        scope = DeadlineScope()
        scope.check()  # raises DeadlineExceededError if time is up
        scope.cancel() # call on HTTP disconnect
    """

    deadline_seconds: float = OPERATION_DEADLINE_SECONDS
    _start: float = field(default_factory=time.monotonic, init=False)
    _cancelled: bool = field(default=False, init=False)

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_seconds - (time.monotonic() - self._start))

    def expired(self) -> bool:
        return time.monotonic() - self._start >= self.deadline_seconds

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> None:
        """Raise DeadlineExceededError if cancelled or deadline exceeded."""
        if self._cancelled:
            raise DeadlineExceededError("Operation was cancelled")
        if self.expired():
            raise DeadlineExceededError(f"Operation exceeded the {self.deadline_seconds}s deadline")

    async def bound(self, awaitable: Awaitable[_T]) -> _T:
        """Await ``awaitable`` for at most the remaining deadline.

        Checking only between calls is not enough: a hanging provider call
        would otherwise outlive the operation. On expiry the inner task is
        cancelled, so ``async with`` blocks inside it (provider semaphore,
        httpx client) release their resources before this raises.
        """
        try:
            self.check()
        except DeadlineExceededError:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()  # never started; avoid "never awaited" warnings
            raise
        try:
            return await asyncio.wait_for(awaitable, timeout=self.remaining_seconds())
        except TimeoutError as exc:
            raise DeadlineExceededError(
                f"Operation exceeded the {self.deadline_seconds}s deadline"
            ) from exc
