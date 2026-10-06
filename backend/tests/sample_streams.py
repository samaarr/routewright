"""Emit real /api/v2/plan/stream bodies (fake Google adapters) as one JSON object.

Used by the frontend contract test (frontend/tests/unit/contract.test.ts) to
check that what this backend actually streams passes the frontend's runtime
validators and NDJSON reader. Not collected by pytest (no test_ prefix).

Run from backend/: python -m tests.sample_streams
"""

import json
import sys
from typing import Any

from fastapi.testclient import TestClient

from app.core.deadline import DeadlineScope
from app.core.limiter import limiter
from app.main import app
from app.routers import plan_v2
from app.services.area import Viewport
from app.services.errors import PlaceVerificationError
from app.services.place_details import PlaceDetails
from tests.test_plan_v2_verified import _NOW, PLACES, FakePlaces, FakeRoutes, _payload, _stop


def _run(name: str, places: FakePlaces, routes: FakeRoutes, deadline: float = 60.0) -> str:
    limiter._storage.reset()
    plan_v2.places_adapter = lambda: places  # type: ignore[assignment]
    plan_v2.routes_adapter = lambda: routes  # type: ignore[assignment]
    plan_v2._now = lambda: _NOW  # type: ignore[assignment]
    plan_v2.DeadlineScope = lambda: DeadlineScope(deadline_seconds=deadline)  # type: ignore[assignment,misc]
    body = _payload(
        [_stop("a", "trinity"), _stop("b", "guinness", stay=45), _stop("c", "glendalough")]
    )
    body["operation_id"] = f"op-{name}"
    resp = TestClient(app).post("/api/v2/plan/stream", json=body)
    assert resp.status_code == 200, resp.text
    return resp.text


def _selection_samples() -> dict[str, Any]:
    import tempfile

    from app.core.config import settings
    from app.routers import selection
    from app.services.autocomplete import Suggestion
    from tests.test_selection import FakePlaces as SelPlaces
    from tests.test_selection import FakeSuggest

    limiter._storage.reset()
    settings.cache_db_path = tempfile.mkdtemp() + "/places.db"
    suggest, places = FakeSuggest(), SelPlaces()
    suggest.result = [Suggestion("ChIJdublin", "Dublin", "Ireland")]
    selection.suggestion_adapter = lambda: suggest  # type: ignore[assignment]
    selection.places_adapter = lambda: places  # type: ignore[assignment]
    client = TestClient(app)
    return {
        "suggestions": client.post("/api/v2/suggest/cities", json={"query": "dub"}).json(),
        "select_city": client.post("/api/v2/select/city", json={"place_id": "ChIJdublin"}).json(),
        "select_place": client.post("/api/v2/select/place", json={"place_id": "ChIJx"}).json(),
    }


def main() -> None:
    city = PLACES["city_dublin"]
    PLACES["city_dublin"] = PlaceDetails(
        city.place_id,
        city.name,
        city.lat,
        city.lng,
        fetched_at=_NOW,
        viewport=Viewport(53.22, -6.45, 53.42, -6.05),
    )
    PLACES["glendalough"] = PlaceDetails(
        "glendalough", "Glendalough", 53.0107, -6.3290, primary_type="park", fetched_at=_NOW
    )
    out: dict[str, Any] = {
        "complete": _run("complete", FakePlaces(), FakeRoutes()),
        "partial": _run("partial", FakePlaces(), FakeRoutes(fail_at=1)),
        "error": _run(
            "error",
            FakePlaces(
                {
                    "guinness": PlaceVerificationError(
                        "guinness", reason="moved", moved_place_id="ChIJnew"
                    )
                }
            ),
            FakeRoutes(),
        ),
        "timeout": _run("timeout", FakePlaces(), FakeRoutes(hang_at=1), deadline=0.3),
    }
    out.update(_selection_samples())
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
