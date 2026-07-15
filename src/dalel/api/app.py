"""FastAPI application factory for the DÁLEL Eco demo website.

Read-only, offline, no database, no LLM calls. Serves normalized pillar
artifacts to the frontend. Errors return clean JSON (``{error, detail}``) —
never a Python traceback, never a filesystem path.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dalel.api import API_VERSION
from dalel.api.config import get_settings
from dalel.api.errors import ApiError
from dalel.api.routes import findings, health, projects, reports, system

logger = logging.getLogger("dalel.api")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DÁLEL Eco — Demo API",
        version=API_VERSION,
        description=(
            "Read-only API over accepted P1/P2/P3 analysis artifacts."
            " Expert-support tool: no legal or administrative conclusions."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def _api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "detail": exc.detail},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Запрос не может быть обработан."
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "detail": detail},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_request", "detail": "Некорректные параметры запроса."},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        # Log server-side with detail; return a generic message (no leak).
        logger.exception("unhandled API error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "Внутренняя ошибка сервера. Повторите попытку позже.",
            },
        )

    app.include_router(health.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(findings.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(system.router, prefix="/api")
    return app


app = create_app()
