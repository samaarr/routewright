"""Tests for POST /api/v2/plan/stream and outside-area warnings (D6-D7, D22-D23, D44).

Provider adapters are deterministic fakes (shared with test_plan_v2_verified).
Disconnect behaviour is tested by driving PlanStream directly with a fake ASGI
``receive`` so the cancellation path is exercised deterministically.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import provider_semaphore
from app.core.deadline import DeadlineScope
from app.main import app
from app.models.request import ItineraryRequest
from app.routers import plan_v2
from app.services import adapter as adapter_module
from app.services.adapter import GoogleRoutesAdapter
from app.services.area import Viewport
from app.services.engine import OperationContext
from app.services.place_details import PlaceDetails
from tests.test_plan_v2_verified import (
    _NOW,
    PLACES,
    FakePlaces,
    FakeRoutes,
    _payload,
    _stop,
)

DUBLIN_VP = Viewport(53.22, -6.45, 53.42, -6.05)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> tuple[FakePlaces, FakeRoutes]:
    places, routes = FakePlaces(), FakeRoutes()
    monkeypatch.setattr(plan_v2, "places_adapter", lambda: places)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    monkeypatch.setattr(plan_v2, "_now", lambda: _NOW)
    return places, routes


def _stream(body: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    resp = TestClient(app).post("/api/v2/plan/stream", json=body)
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    return resp, lines


def _three() -> dict[str, Any]:
    return _payload([_stop("a", "trinity"), _stop("b", "guinness"), _stop("c", "pub")])


def test_stream_event_sequence_and_headers(fakes: Any) -> None:
    resp, events = _stream(_three())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert "no-store" in resp.headers["cache-control"]
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.headers["x-content-type-options"] == "nosniff"
    types = [e["type"] for e in events]
    assert types[:3] == ["operation_start", "phase_start", "phase_complete"]
    assert events[0]["phases"] == ["verification", "routing"]
    assert events[1]["phase"] == "verification" and events[3]["phase"] == "routing"
    assert types[-2:] == ["phase_complete", "terminal"]
    assert types.count("terminal") == 1
    ready = [(e["completed_legs"], e["total_legs"]) for e in events if e["type"] == "leg_ready"]
    assert ready == [(1, 2), (2, 2)]
    assert all(e["operation_id"] == "op-1" and e["input_revision"] == 3 for e in events)
    outcome = events[-1]["outcome"]
    assert outcome["outcome_type"] == "plan"
    assert outcome["result"]["result_type"] == "complete"


def test_stream_partial_failure_keeps_prefix(fakes: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    routes = FakeRoutes(fail_at=1)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    _, events = _stream(_three())
    result = events[-1]["outcome"]["result"]
    assert result["result_type"] == "partial"
    assert [i["item_type"] for i in result["timeline"]] == [
        "stop",
        "leg",
        "stop",
        "failed_leg",
        "unknown_stop",
    ]
    failed = [e for e in events if e["type"] == "leg_ready"][-1]
    assert (failed["leg"]["item_type"], failed["completed_legs"]) == ("failed_leg", 1)


def test_stream_verification_failure_is_terminal_error_with_zero_routing(fakes: Any) -> None:
    from app.services.errors import PlaceVerificationError

    places, routes = fakes
    places.overrides["pub"] = PlaceVerificationError("pub", reason="not_found")
    resp, events = _stream(_three())
    assert resp.status_code == 200  # headers were already sent
    outcome = events[-1]["outcome"]
    assert outcome["outcome_type"] == "error"
    assert outcome["code"] == "place_invalid"
    assert outcome["details"]["instance_ids"] == ["c"]
    assert routes.calls == []
    assert "routing" not in [e.get("phase") for e in events]


def test_stream_invalid_departure_is_http_error_before_stream(fakes: Any) -> None:
    places, routes = fakes
    body = _payload([_stop("a", "trinity"), _stop("b", "pub")], date="2026-02-30")
    resp = TestClient(app).post("/api/v2/plan/stream", json=body)
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"]["error"] == "departure_invalid_date"
    assert places.calls == [] and routes.calls == []


def _short_deadline(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    monkeypatch.setattr(plan_v2, "DeadlineScope", lambda: DeadlineScope(deadline_seconds=seconds))


def test_stream_timeout_during_verification(fakes: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    places, routes = fakes
    places.hang = True
    _short_deadline(monkeypatch, 0.2)
    _, events = _stream(_three())
    outcome = events[-1]["outcome"]
    assert (outcome["outcome_type"], outcome["phase"], outcome["partial"]) == (
        "timeout",
        "verification",
        None,
    )
    assert routes.calls == []


def test_stream_timeout_during_routing_carries_prefix(
    fakes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = FakeRoutes(hang_at=1)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    _short_deadline(monkeypatch, 0.3)
    _, events = _stream(_three())
    outcome = events[-1]["outcome"]
    assert (outcome["outcome_type"], outcome["phase"]) == ("timeout", "routing")
    assert outcome["partial"]["failure_reason"] == "deadline_exceeded"
    assert len(routes.calls) == 2


def test_unexpected_error_is_generic_terminal(fakes: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    class Boom:
        async def fetch_leg(self, **kw: Any) -> Any:
            raise RuntimeError("secret provider text sk-123")

    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: Boom())
    _, events = _stream(_three())
    outcome = events[-1]["outcome"]
    assert outcome == {
        "outcome_type": "error",
        "code": "internal_error",
        "message": "Planning failed unexpectedly. Try again.",
        "details": None,
    }
    assert "sk-123" not in json.dumps(events)


def test_stream_and_json_share_plan_rate_limit(fakes: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    body = _payload([_stop("a", "trinity"), _stop("b", "pub")])
    statuses = []
    for i in range(11):
        path = "/api/v2/plan" if i % 2 else "/api/v2/plan/stream"
        body["operation_id"] = f"op-{i}"
        statuses.append(client.post(path, json=body).status_code)
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429  # existing 10/minute plan limit, shared across both


# --- disconnect / cancellation -------------------------------------------------------


def _request(stops: list[str]) -> ItineraryRequest:
    return ItineraryRequest.model_validate(
        _payload([_stop(f"s{i}", pid) for i, pid in enumerate(stops)])
    )


@pytest.mark.asyncio
async def test_disconnect_cancels_inflight_routing_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client leaves while leg 2 is in flight at the provider: the call is
    cancelled, the provider slot released, no further legs requested, and the
    budget already consumed for sent calls is not refunded."""
    provider_semaphore.reset_gates()
    sem = provider_semaphore._provider
    assert sem is not None
    free_before = sem._value
    sent: list[int] = []
    leg_started = asyncio.Event()

    async def budget(kind: str = "unclassified") -> None:
        sent.append(1)

    async def fake_fetch_leg(**kw: Any) -> Any:
        if len(sent) == 2:  # second leg hangs at the provider
            leg_started.set()
            await asyncio.Event().wait()
        from app.services.directions import LegResult

        return LegResult(1200, 1000, kw["depart_at"], kw["depart_at"], "Bus", None)

    async def consuming_fetch_leg(**kw: Any) -> Any:
        await budget()
        return await fake_fetch_leg(**kw)

    monkeypatch.setattr(adapter_module.directions, "fetch_leg", consuming_fetch_leg)

    disconnect = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await disconnect.wait()
        return {"type": "http.disconnect"}

    stream = plan_v2.PlanStream(
        _request(["trinity", "guinness", "pub", "trinity"]),
        departure_utc=_NOW,
        places=FakePlaces(),
        routes=GoogleRoutesAdapter(),
        ctx=OperationContext(operation_id="op-x", input_revision=1),
        deadline=DeadlineScope(),
        receive=receive,
    )
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for chunk in stream.events():
            received.append(json.loads(chunk))

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(leg_started.wait(), 2)

    # Let the consumer drain everything queued so far: it is now blocked on an
    # empty queue while the provider call hangs — the case that must still
    # react to the disconnect immediately.
    def waiting_on_leg_two() -> bool:
        return (
            bool(received)
            and received[-1]["type"] == "leg_progress"
            and (received[-1]["leg_index"] == 1)
        )

    while not waiting_on_leg_two():
        await asyncio.sleep(0)
    assert stream.queue.empty()
    assert sem._value == free_before - 1  # slot held by the in-flight call
    disconnect.set()
    await asyncio.wait_for(consumer, 1)

    assert stream.disconnected
    assert sem._value == free_before  # released by cancellation
    assert len(sent) == 2  # no third leg requested; the two sent stay counted
    assert all(e["type"] != "terminal" for e in received)  # nothing sent after leaving


@pytest.mark.asyncio
async def test_closing_the_body_iterator_cancels_producer() -> None:
    """If the server stops iterating (e.g. a send fails), the finally block
    cancels the producer rather than abandoning it."""
    places = FakePlaces(hang=True)
    stream = plan_v2.PlanStream(
        _request(["trinity", "pub"]),
        departure_utc=_NOW,
        places=places,
        routes=FakeRoutes(),
        ctx=OperationContext(),
        deadline=DeadlineScope(),
        receive=None,
    )
    gen = stream.events()
    first = json.loads(await gen.__anext__())
    assert first["type"] == "operation_start"
    await gen.aclose()
    assert all(t.done() for t in asyncio.all_tasks() if t is not asyncio.current_task())


def test_event_queue_is_bounded() -> None:
    stream = plan_v2.PlanStream(
        _request(["trinity", "pub"]),
        departure_utc=_NOW,
        places=FakePlaces(),
        routes=FakeRoutes(),
        ctx=OperationContext(),
        deadline=DeadlineScope(),
        receive=None,
    )
    assert stream.queue.maxsize == plan_v2.MAX_QUEUED_EVENTS > 0


# --- outside-area warnings (D44) ------------------------------------------------------


def _with_viewport(monkeypatch: pytest.MonkeyPatch, vp: Viewport | None) -> None:
    city = PLACES["city_dublin"]
    monkeypatch.setitem(
        PLACES,
        "city_dublin",
        PlaceDetails(city.place_id, city.name, city.lat, city.lng, fetched_at=_NOW, viewport=vp),
    )
    monkeypatch.setitem(
        PLACES,
        "glendalough",
        PlaceDetails(
            "glendalough", "Glendalough", 53.0107, -6.3290, primary_type="park", fetched_at=_NOW
        ),
    )


def test_outside_area_stop_allowed_with_warning(
    fakes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_viewport(monkeypatch, DUBLIN_VP)
    body = _payload([_stop("a", "trinity"), _stop("b", "glendalough"), _stop("c", "pub")])
    resp = TestClient(app).post("/api/v2/plan", json=body)
    assert resp.status_code == 200, resp.json()
    area = [w for w in resp.json()["warnings"] if w["code"] == "outside_city_area"]
    assert [(w["affects_instance_id"], w["message"]) for w in area] == [
        ("b", "Outside the selected city's suggested area.")
    ]


def test_outside_area_warning_kept_for_unknown_downstream_stop(
    fakes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_viewport(monkeypatch, DUBLIN_VP)
    routes = FakeRoutes(fail_at=0)
    monkeypatch.setattr(plan_v2, "routes_adapter", lambda: routes)
    body = _payload([_stop("a", "trinity"), _stop("b", "glendalough")])
    result = TestClient(app).post("/api/v2/plan", json=body).json()
    assert result["result_type"] == "partial"
    assert any(
        w["code"] == "outside_city_area" and w["affects_instance_id"] == "b"
        for w in result["warnings"]
    )


def test_missing_viewport_reports_area_check_unavailable(
    fakes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_viewport(monkeypatch, None)
    body = _payload([_stop("a", "trinity"), _stop("b", "glendalough")])
    warnings = TestClient(app).post("/api/v2/plan", json=body).json()["warnings"]
    assert [w["code"] for w in warnings if w["code"].startswith(("area", "outside"))] == [
        "area_unavailable"
    ]
