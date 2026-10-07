"""Aggregate operational metrics lines (Step 9, D46).

Captures the JSON lines emitted on the ``routewright.metrics`` logger and
checks bounded fields, call counts by category and excluded content.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import opmetrics
from app.core.deadline import DeadlineScope
from app.main import app
from app.models.request import ItineraryRequest
from app.routers import plan_v2, selection
from app.services.autocomplete import Suggestion
from app.services.engine import OperationContext
from tests.test_final_walk import MockGoogleRoutes, google  # noqa: F401  (fixture)
from tests.test_plan_v2_verified import _NOW, FakePlaces, FakeRoutes, _payload, _stop

KEYS = {
    "client_ip_source",
    "event",
    "operation",
    "transport",
    "outcome",
    "failure",
    "elapsed_ms",
    "stop_count",
    "calls",
    "level",
}
FORBIDDEN = [
    "Place ",
    "Trinity",
    "Guinness",
    "53.",
    "-6.",
    "2026-10",
    "op-1",
    "testclient",
    "127.0.0.1",
    "ChIJ",
    "trinity",
]


@pytest.fixture
def capture() -> Iterator[list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []
    raw: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raw.append(record.getMessage())
            captured.append(json.loads(record.getMessage()))

    handler = Capture()
    opmetrics.log.addHandler(handler)
    yield captured
    opmetrics.log.removeHandler(handler)
    for line in raw:
        for word in FORBIDDEN:
            assert word not in line, f"{word!r} leaked into a metrics line: {line}"


def _only(capture: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(capture) == 1, capture
    line = capture[0]
    assert set(line) == KEYS
    assert line["outcome"] in opmetrics.OUTCOMES
    assert line["failure"] is None or line["failure"] in opmetrics.FAILURES
    assert set(line["calls"]) <= opmetrics.CALL_KINDS
    assert isinstance(line["elapsed_ms"], int) and line["elapsed_ms"] >= 0
    return line


def test_plan_line_counts_routing_calls_and_excludes_trip_details(
    google: dict[str, Any],  # noqa: F811
    capture: list[dict[str, Any]],
) -> None:
    body = _payload(
        [_stop("a", "A"), _stop("b", "B"), _stop("c", "C")], date="2026-10-21", time_="09:00"
    )
    assert TestClient(app).post("/api/v2/plan", json=body).status_code == 200
    line = _only(capture)
    assert (line["operation"], line["transport"], line["outcome"]) == ("plan", "json", "complete")
    assert line["calls"] == {"routes_compute": 2}
    assert line["stop_count"] == 3


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: FakePlaces())
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: FakeRoutes(fail_at=1))
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)


def _three() -> dict[str, Any]:
    return _payload([_stop("a", "trinity"), _stop("b", "guinness"), _stop("c", "pub")])


def test_partial_and_stream_outcomes(fakes: None, capture: list[dict[str, Any]]) -> None:
    TestClient(app).post("/api/v2/plan/stream", json=_three())
    line = _only(capture)
    assert (line["transport"], line["outcome"], line["failure"]) == (
        "stream",
        "partial",
        "no_route",
    )


def test_rejected_before_provider_calls(fakes: None, capture: list[dict[str, Any]]) -> None:
    body = _payload([_stop("a", "trinity"), _stop("b", "pub")], date="2026-02-30")
    assert TestClient(app).post("/api/v2/plan/stream", json=body).status_code == 422
    line = _only(capture)
    assert (line["outcome"], line["failure"], line["calls"]) == (
        "rejected",
        "departure_invalid_date",
        {},
    )


def test_comparison_outcome_is_not_split_into_recommendation_categories(
    google: dict[str, Any],  # noqa: F811
    capture: list[dict[str, Any]],
) -> None:
    from tests.test_final_walk import _RIDES

    google["mock"] = MockGoogleRoutes(_RIDES)
    body = _payload([_stop(p.lower(), p, 0) for p in "ABCD"], date="2026-10-21", time_="09:00")
    body.update({"fixed_first": True, "fixed_last": True})
    res = TestClient(app).post("/api/v2/compare", json=body).json()
    assert res["status"] == "recommended"
    line = _only(capture)
    assert (line["operation"], line["outcome"]) == ("compare", "compared")
    assert line["calls"] == {"routes_compute": 6}
    assert "saving" not in json.dumps(line) and "300" not in json.dumps(line)


@pytest.mark.asyncio
async def test_disconnect_is_recorded_as_cancelled(capture: list[dict[str, Any]]) -> None:
    disconnect = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    req = ItineraryRequest.model_validate(_three())
    metrics = opmetrics.OperationMetrics("plan", "stream", 3)
    stream = plan_v2.PlanStream(
        req,
        departure_utc=_NOW + timedelta(days=1),
        places=FakePlaces(hang=True),
        routes=FakeRoutes(),
        ctx=OperationContext(operation_id="op-1", input_revision=3),
        deadline=DeadlineScope(),
        receive=receive,
        metrics=metrics,
    )

    async def consume() -> None:
        async for _ in stream.events():
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    disconnect.set()
    await asyncio.wait_for(task, 1)
    assert _only(capture)["outcome"] == "cancelled"


def test_selection_lines_hold_no_query_text(
    monkeypatch: pytest.MonkeyPatch, capture: list[dict[str, Any]]
) -> None:
    class Fake:
        def __init__(self, result: list[Suggestion]) -> None:
            self.result = result

        async def suggest(self, query: str, **kw: Any) -> list[Suggestion]:
            return self.result

    monkeypatch.setattr(selection, "suggestion_adapter", lambda: Fake([]))
    TestClient(app).post("/api/v2/suggest/places", json={"query": "trinity college"})
    line = _only(capture)
    assert (line["operation"], line["outcome"], line["stop_count"]) == (
        "suggest_place",
        "no_matches",
        None,
    )


def test_unknown_categories_are_bounded() -> None:
    captured: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    handler = Capture()
    opmetrics.log.addHandler(handler)
    try:
        m = opmetrics.OperationMetrics("plan", "json", 99)
        m.calls["made_up_kind"] += 1
        m.finish("brand_new_outcome", "free text from somewhere 53.34,-6.26")
        m.finish("complete")  # ignored: one line per operation
    finally:
        opmetrics.log.removeHandler(handler)
    assert len(captured) == 1
    line = json.loads(captured[0])
    assert (line["outcome"], line["failure"], line["stop_count"], line["calls"]) == (
        "error",
        "other",
        None,
        {},
    )
