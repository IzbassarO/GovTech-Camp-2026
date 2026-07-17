"""FastAPI application factory for prepared replay and isolated live analysis.

Prepared artifacts remain read-only. New uploads are confined to authenticated,
TTL-bound temporary workspaces. Errors return clean JSON (``{error, detail}``)
without a traceback or filesystem path.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dalel.api import API_VERSION
from dalel.api.body_limit import RequestBodyLimitMiddleware, RequestBodyTooLarge
from dalel.api.config import get_settings
from dalel.api.errors import ApiError
from dalel.api.live import MAX_TOTAL_BYTES, get_live_job_manager
from dalel.api.routes import demo, findings, health, live, projects, reports, system

logger = logging.getLogger("dalel.api")


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    manager = get_live_job_manager()
    manager.start()
    try:
        yield
    finally:
        manager.stop_sweeper()
        manager.reset()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DÁLEL Eco — Demo API",
        version=API_VERSION,
        description=(
            "Immutable prepared replay plus isolated live project analysis."
            " Expert-support tool: no legal or administrative conclusions."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )

    # Enforce the aggregate byte ceiling before Starlette's multipart parser
    # can spool an oversized request. The allowance covers multipart headers
    # and the small JSON request field.
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_TOTAL_BYTES + 2 * 1024 * 1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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

    @app.exception_handler(RequestBodyTooLarge)
    async def _body_limit_handler(_: Request, __: RequestBodyTooLarge) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error": "request_body_too_large",
                "detail": "Размер запроса превышает допустимый лимит.",
            },
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
    app.include_router(demo.router, prefix="/api")
    app.include_router(live.router, prefix="/api")
    return app


app = create_app()
