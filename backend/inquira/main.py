"""Inquira API application factory."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from inquira import __version__
from inquira.api import ask, auth, workspace
from inquira.core.config import get_settings
from inquira.core.errors import ApiError
from inquira.core.logging import configure_logging, request_id_var
from inquira.db import engine, init_db

log = logging.getLogger("inquira")
API_PREFIX = "/api/v1"
CSRF_HEADER = "x-inquira-client"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_PROBE_PATHS = {f"{API_PREFIX}/health", f"{API_PREFIX}/livez", f"{API_PREFIX}/readyz"}


def _dependency_checks() -> dict[str, str]:
    """Readiness: the metadata DB (and Redis when configured). The warehouse and LLM are deliberately
    excluded, since an outage there shouldn't pull every replica out of the load balancer."""
    checks: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
    if get_settings().redis_url:
        try:
            import redis

            redis.Redis.from_url(get_settings().redis_url, socket_timeout=2).ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {type(e).__name__}"
    return checks


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.is_production)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db()
        log.info("Inquira %s started (env=%s)", __version__, settings.env)
        yield

    app = FastAPI(
        title="Inquira API",
        version=__version__,
        description="Ask your data anything. Natural language to validated, read-only SQL.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        # CSRF: browsers cannot send custom headers cross-site without a CORS preflight,
        # which our CORS policy only allows for configured origins.
        if (request.method not in _SAFE_METHODS and request.url.path.startswith(API_PREFIX)
                and request.headers.get(CSRF_HEADER) != "web"):
            return _error(403, "csrf", "Missing X-Inquira-Client header.")
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path not in _PROBE_PATHS:
            log.info("%s %s %s %.0fms", request.method, request.url.path, response.status_code,
                     (time.perf_counter() - started) * 1000)
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Inquira-Client", "X-Request-ID"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        message = f"{field}: {first.get('msg')}" if field else str(first.get("msg", "Invalid request"))
        return _error(422, "validation_error", message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return _error(500, "internal", "An unexpected error occurred.")

    # Probes are `async def` so they run on the event loop and never queue behind the threadpool
    # that serves long-running questions (a sync probe times out under load and gets pods restarted).
    @app.get(f"{API_PREFIX}/health", tags=["health"])
    @app.get(f"{API_PREFIX}/livez", tags=["health"])
    async def livez() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get(f"{API_PREFIX}/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        checks = await run_in_threadpool(_dependency_checks)
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks},
                            status_code=200 if ok else 503)

    for module in (auth, workspace, ask):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
