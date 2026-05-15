"""FastAPI application entrypoint.

v1 has two routers: health and plan. Everything else (parser, optimiser)
is deferred to v1.5+ based on real user feedback.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.models.response import ErrorResponse
from app.routers import health, plan

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("routewright")

app = FastAPI(
    title="RouteWright API",
    description="Multi-stop transit itinerary planning.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(health.router)
app.include_router(plan.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error="validation_error", detail=str(exc.errors())).model_dump(),
    )
