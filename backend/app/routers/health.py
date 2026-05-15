"""Health probe used by CI smoke tests and platform probes."""

from fastapi import APIRouter

from app.core.config import settings
from app.models.response import HealthResponse

router = APIRouter(tags=["health"])

# Bumped manually on each release. Read by `GET /healthz`.
APP_VERSION = "0.1.0"


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Return service health metadata.

    Always returns 200 OK if the process is alive. We don't probe downstream
    APIs here — that would couple liveness to third parties.
    """
    return HealthResponse(status="ok", version=APP_VERSION, env=settings.app_env)
