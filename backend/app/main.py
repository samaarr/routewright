"""FastAPI application entrypoint.

v1 has two routers: health and plan. Everything else (parser, optimiser)
is deferred to v1.5+ based on real user feedback.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.limiter import limiter
from app.models.response import ErrorResponse
from app.routers import health, plan, refresh_leg

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("routewright")

app = FastAPI(
    title="RouteWright API",
    description="Multi-stop transit itinerary planning.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(health.router)
app.include_router(plan.router)
app.include_router(refresh_leg.router)

async def _rate_limit_handler(_request: Request, _exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate_limit_exceeded", "detail": "Daily limit reached — try again tomorrow."},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error="validation_error", detail=str(exc.errors())).model_dump(),
    )
